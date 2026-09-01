/*
  Consultas a la API.

  Todo el sondeo periódico vive aquí, declarado con `refetchInterval`.
  Antes cada página armaba su propio `setInterval` y luego comparaba a
  mano el estado nuevo contra el anterior para no volver a pintar el DOM
  (había un `Map` de nodos por cada lista). Eso es exactamente el trabajo
  que hace React por su cuenta, así que ese código desapareció.

  `refetchInterval` se apaga solo cuando la pestaña está en segundo plano,
  así que la plataforma deja de pedirle datos al Jetson mientras nadie la
  está mirando.
*/

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import * as api from './api';
import { avisar } from './avisos';
import { navegarA } from './navegar';
import { errorMessage } from './api';
import { plural } from './format';
import type { Point, ProjectCreate } from './types';

/** La cola y la cámara se miran en vivo; 3 s es el ritmo del backend. */
const LIVE_MS = 3000;

export const keys = {
  projects: ['projects'] as const,
  lanes: (projectId: number) => ['lanes', projectId] as const,
  zones: (projectId: number) => ['zones', projectId] as const,
  videos: (projectId?: number) => ['videos', projectId ?? 'all'] as const,
  metrics: (projectId: number, minutes: number) => ['metrics', projectId, minutes] as const,
  engine: ['engine'] as const,
  counts: ['counts'] as const,
};

export function useProjects() {
  return useQuery({ queryKey: keys.projects, queryFn: api.listProjects });
}

export function useLanes(projectId: number | null) {
  return useQuery({
    queryKey: keys.lanes(projectId ?? 0),
    queryFn: () => api.listLanes(projectId as number),
    enabled: projectId !== null,
  });
}

export function useVideos(projectId?: number, live = false) {
  return useQuery({
    queryKey: keys.videos(projectId),
    queryFn: () => api.listVideos(projectId),
    refetchInterval: live ? LIVE_MS : false,
  });
}

export function useMetrics(projectId: number | null, minutes: number) {
  return useQuery({
    queryKey: keys.metrics(projectId ?? 0, minutes),
    queryFn: () => api.getMetrics(projectId as number, minutes),
    enabled: projectId !== null,
  });
}

export function useEngineState() {
  return useQuery({
    queryKey: keys.engine,
    queryFn: api.getEngineState,
    refetchInterval: LIVE_MS,
  });
}

export function useCounts() {
  return useQuery({ queryKey: keys.counts, queryFn: api.getCounts, refetchInterval: LIVE_MS });
}

/* --- Mutaciones ----------------------------------------------------------

   Cada una avisa de su desenlace. Antes ninguna lo hacía: el resultado se
   deducía de que la lista cambiara —o no cambiara— y un fallo solo se
   veía si la pantalla que lo provocó seguía abierta. Al cambiar de
   pestaña el error desaparecía sin haberse leído.

   El aviso de fallo dice qué se intentaba, no solo que algo salió mal:
   "No se pudo borrar el carril" con la causa del servidor debajo. */

/** Envuelve una mutación para que avise siempre de cómo terminó. */
function conAviso<TDatos, TVars>(
  opciones: {
    mutationFn: (v: TVars) => Promise<TDatos>;
    exito?: (
      d: TDatos,
      v: TVars,
    ) => {
      titulo: string;
      detalle?: string;
      /** A dónde lleva el aviso. Sustituye al enlace que traían los
          avisos en línea: encolar el conteo y no decir dónde se ve el
          avance obliga a buscarlo a mano. */
      ir?: { etiqueta: string; a: string };
    } | null;
    fallo: string;
    alTerminar?: () => void;
  },
) {
  return {
    mutationFn: opciones.mutationFn,
    onSuccess: (d: TDatos, v: TVars) => {
      const msg = opciones.exito?.(d, v);
      if (msg) {
        avisar.ok(msg.titulo, {
          detalle: msg.detalle,
          accion: msg.ir
            ? { etiqueta: msg.ir.etiqueta, alPulsar: () => navegarA(msg.ir!.a) }
            : undefined,
        });
      }
      opciones.alTerminar?.();
    },
    onError: (e: unknown) => avisar.error(opciones.fallo, { detalle: errorMessage(e) }),
  };
}

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    ...conAviso({
      mutationFn: (data: ProjectCreate) => api.createProject(data),
      exito: (p) => ({ titulo: 'Intersección creada', detalle: p.name }),
      fallo: 'No se pudo crear la intersección',
      alTerminar: () => qc.invalidateQueries({ queryKey: keys.projects }),
    }),
  });
}

export function useCameraCard(projectId: number | null) {
  return useQuery({
    queryKey: ['camara', projectId ?? 0],
    queryFn: () => api.getCameraCard(projectId as number),
    enabled: projectId !== null,
  });
}

export function useEvents(projectId: number | null) {
  return useQuery({
    queryKey: ['eventos', projectId ?? 0],
    queryFn: () => api.listEvents(projectId as number),
    enabled: projectId !== null,
    // El registro cambia cuando el usuario hace algo, y lo que hace suele
    // ocurrir en otra pestaña del mismo proyecto.
    refetchInterval: 10000,
  });
}

export function useUpdateProject(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    ...conAviso({
      mutationFn: (data: Partial<ProjectCreate>) => api.updateProject(projectId, data),
      exito: () => ({ titulo: 'Cambios guardados' }),
      fallo: 'No se pudieron guardar los cambios',
      alTerminar: () => qc.invalidateQueries({ queryKey: keys.projects }),
    }),
  });
}

export function useDeleteProject() {
  const qc = useQueryClient();
  return useMutation({
    ...conAviso({
      mutationFn: (projectId: number) => api.deleteProject(projectId),
      exito: () => ({ titulo: 'Intersección borrada' }),
      fallo: 'No se pudo borrar la intersección',
      alTerminar: () => qc.invalidateQueries(),
    }),
  });
}

export function useCreateLane(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    ...conAviso({
      mutationFn: (data: { name: string; points: [Point, Point] }) =>
        api.createLane({ project_id: projectId, ...data }),
      exito: (_d, v) => ({ titulo: 'Carril guardado', detalle: v.name }),
      fallo: 'No se pudo guardar el carril',
      alTerminar: () => {
        qc.invalidateQueries({ queryKey: keys.lanes(projectId) });
        qc.invalidateQueries({ queryKey: keys.projects });
      },
    }),
  });
}

export function useRenameLane(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    ...conAviso({
      mutationFn: ({ laneId, name }: { laneId: number; name: string }) =>
        api.renameLane(laneId, name),
      exito: (_d, v) => ({ titulo: 'Carril renombrado', detalle: v.name }),
      fallo: 'No se pudo renombrar el carril',
      alTerminar: () => qc.invalidateQueries({ queryKey: keys.lanes(projectId) }),
    }),
  });
}

export function useDeleteLane(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    ...conAviso({
      mutationFn: (laneId: number) => api.deleteLane(laneId),
      exito: () => ({ titulo: 'Carril eliminado' }),
      fallo: 'No se pudo eliminar el carril',
      alTerminar: () => {
        qc.invalidateQueries({ queryKey: keys.lanes(projectId) });
        qc.invalidateQueries({ queryKey: keys.projects });
      },
    }),
  });
}

export function useCalibrationStatus(projectId: number | null) {
  return useQuery({
    queryKey: ['calibration-status', projectId ?? 0],
    queryFn: () => api.getCalibrationStatus(projectId as number),
    enabled: projectId !== null,
    // Se refresca solo: el aviso tiene que aparecer en cuanto el usuario
    // mueve una línea, no cuando recarga la página.
    refetchInterval: 4000,
  });
}

export function useRecount() {
  const qc = useQueryClient();
  return useMutation({
    ...conAviso({
      mutationFn: (projectId: number) => api.recount(projectId),
      exito: (r, projectId) => ({
        titulo: 'Reconteo encolado',
        detalle: `${plural(r.requeued, 'video', 'videos')} con la calibración actual. Te aviso cuando terminen.`,
        ir: { etiqueta: 'Ver la cola', a: `/proyecto/${projectId}/subir` },
      }),
      fallo: 'No se pudo volver a contar',
      alTerminar: () => qc.invalidateQueries(),
    }),
  });
}

export function useCopyCalibration(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    ...conAviso({
      mutationFn: (fromProjectId: number) => api.copyCalibration(projectId, fromProjectId),
      exito: (r) => ({
        titulo: 'Calibración copiada',
        detalle: `${plural(r.lanes, 'carril', 'carriles')} y ${plural(r.zones, 'zona', 'zonas')}. Revísala antes de contar.`,
        ir: { etiqueta: 'Revisar los carriles', a: `/proyecto/${projectId}/calibrar` },
      }),
      fallo: 'No se pudo copiar la calibracion',
      alTerminar: () => {
        qc.invalidateQueries({ queryKey: keys.lanes(projectId) });
        qc.invalidateQueries({ queryKey: keys.zones(projectId) });
        qc.invalidateQueries({ queryKey: keys.projects });
      },
    }),
  });
}

export function useZones(projectId: number | null) {
  return useQuery({
    queryKey: keys.zones(projectId ?? 0),
    queryFn: () => api.listZones(projectId as number),
    enabled: projectId !== null,
  });
}

export function useCreateZone(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    ...conAviso({
      mutationFn: (data: { name: string; points: Point[]; kind?: string }) =>
        api.createZone({ project_id: projectId, ...data }),
      exito: (_d, v) => ({ titulo: 'Zona guardada', detalle: v.name }),
      fallo: 'No se pudo guardar la zona',
      alTerminar: () => qc.invalidateQueries({ queryKey: keys.zones(projectId) }),
    }),
  });
}

export function useRenameZone(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    ...conAviso({
      mutationFn: ({ zoneId, name }: { zoneId: number; name: string }) =>
        api.renameZone(zoneId, name),
      exito: (_d, v) => ({ titulo: 'Zona renombrada', detalle: v.name }),
      fallo: 'No se pudo renombrar la zona',
      alTerminar: () => qc.invalidateQueries({ queryKey: keys.zones(projectId) }),
    }),
  });
}

export function useDeleteZone(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    ...conAviso({
      mutationFn: (zoneId: number) => api.deleteZone(zoneId),
      exito: () => ({ titulo: 'Zona eliminada' }),
      fallo: 'No se pudo eliminar la zona',
      alTerminar: () => qc.invalidateQueries({ queryKey: keys.zones(projectId) }),
    }),
  });
}

export function useDeleteVideo() {
  const qc = useQueryClient();
  return useMutation({
    ...conAviso({
      mutationFn: (jobId: number) => api.deleteVideo(jobId),
      exito: () => ({ titulo: 'Video eliminado' }),
      fallo: 'No se pudo eliminar el video',
      alTerminar: () => {
        qc.invalidateQueries({ queryKey: ['videos'] });
        qc.invalidateQueries({ queryKey: keys.projects });
      },
    }),
  });
}

export function useUploadVideos() {
  const qc = useQueryClient();
  return useMutation({
    ...conAviso({
      mutationFn: (form: FormData) => api.uploadVideos(form),
      exito: (r) => {
        const n = r.accepted?.length ?? 0;
        // Una subida parcial no es un exito a secas: lo rechazado va en
        // su propio aviso, porque es lo que hay que revisar.
        if (r.rejected?.length) {
          avisar.aviso(plural(r.rejected.length, 'archivo rechazado', 'archivos rechazados'), {
            detalle: r.rejected.map((x) => `${x.filename}: ${x.reason}`).join(' \u00b7 '),
          });
        }
        return n
          ? {
              titulo: plural(n, 'video subido', 'videos subidos'),
              detalle: 'El siguiente paso es calibrar los carriles.',
            }
          : null;
      },
      fallo: 'No se pudieron subir los videos',
      alTerminar: () => {
        qc.invalidateQueries({ queryKey: ['videos'] });
        qc.invalidateQueries({ queryKey: keys.projects });
      },
    }),
  });
}

export function useStartCounting() {
  const qc = useQueryClient();
  return useMutation({
    ...conAviso({
      mutationFn: (projectId: number) => api.startCounting(projectId),
      exito: (r, projectId) => ({
        titulo: 'Conteo iniciado',
        detalle: `${plural(r.started, 'video en cola', 'videos en cola')}. Te aviso cuando terminen.`,
        ir: { etiqueta: 'Ver la cola', a: `/proyecto/${projectId}/subir` },
      }),
      fallo: 'No se pudo empezar el conteo',
      alTerminar: () => {
        qc.invalidateQueries({ queryKey: ['videos'] });
        qc.invalidateQueries({ queryKey: keys.projects });
      },
    }),
  });
}
