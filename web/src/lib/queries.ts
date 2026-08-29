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
import type { Point, ProjectCreate } from './types';

/** La cola y la cámara se miran en vivo; 3 s es el ritmo del backend. */
const LIVE_MS = 3000;

export const keys = {
  projects: ['projects'] as const,
  lanes: (projectId: number) => ['lanes', projectId] as const,
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

/* --- Mutaciones --------------------------------------------------------- */

export function useCreateProject() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: ProjectCreate) => api.createProject(data),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects }),
  });
}

export function useCreateLane(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: { name: string; points: [Point, Point] }) =>
      api.createLane({ project_id: projectId, ...data }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.lanes(projectId) });
      qc.invalidateQueries({ queryKey: keys.projects });
    },
  });
}

export function useRenameLane(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ laneId, name }: { laneId: number; name: string }) =>
      api.renameLane(laneId, name),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.lanes(projectId) }),
  });
}

export function useDeleteLane(projectId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (laneId: number) => api.deleteLane(laneId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.lanes(projectId) });
      qc.invalidateQueries({ queryKey: keys.projects });
    },
  });
}

export function useDeleteVideo() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId: number) => api.deleteVideo(jobId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['videos'] });
      qc.invalidateQueries({ queryKey: keys.projects });
    },
  });
}

export function useUploadVideos() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (form: FormData) => api.uploadVideos(form),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['videos'] });
      qc.invalidateQueries({ queryKey: keys.projects });
    },
  });
}

export function useStartCounting() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (projectId: number) => api.startCounting(projectId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['videos'] });
      qc.invalidateQueries({ queryKey: keys.projects });
    },
  });
}
