/*
  Calibrador: la imagen de la cámara ocupando la pantalla y los controles
  flotando encima, como en un tablero de tránsito.

  Se calibra por CALZADA, no por piezas sueltas. Una calzada es su zona (el
  área de la calle) + su línea de conteo + opcionalmente el tramo de
  velocidad, del mismo color y atadas entre sí. Antes la línea y la zona se
  dibujaban en tarjetas distintas y la pantalla no ofrecía forma de
  atarlas: las líneas de Campos Eliseos quedaron sueltas y cada una contaba
  los vehículos de las dos calles (8-oct-2026).

  Todo lo dibujado se corrige arrastrando: vértices, extremos, la figura
  entera; un vértice nuevo se saca del punto medio de un borde. Los cambios
  de forma quedan en un borrador hasta "Guardar": mover una línea marca
  como desactualizados todos los videos ya contados, y en el proyecto 7 eso
  ofrecía recontar 731 videos y borrar la revisión de 879 pesados. Un
  arrastre accidental no puede costar eso.

  Cada calzada se revisa en vivo (components/calib/geometria.ts): que la
  línea cruce toda la calle, que vaya de través y que no esté pegada a la
  orilla de la imagen. Son los tres errores que ya costaron conteos.
*/

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ConfirmDialog, EmptyState } from '../components/ui';
import { VideoWorkspace, calzadaColor, ACCESO_COLORS } from '../components/VideoWorkspace';
import { Lienzo, type LineaFig, type Seleccion, type ZonaFig } from '../components/calib/Lienzo';
import { revisarCalzada, type Aviso } from '../components/calib/geometria';
import {
  keys,
  useCalibrationStatus,
  useLanes,
  useRecount,
  useStartCounting,
  useVideos,
  useZones,
} from '../lib/queries';
import { useProjectParam } from '../lib/useProjectParam';
import * as api from '../lib/api';
import { errorMessage, fetchImage, heatmapUrl, listVideoSegments } from '../lib/api';
import { plural } from '../lib/format';
import type { FuenteVideo, Lane, Point, Zone } from '../lib/types';

type Herramienta = 'seleccionar' | 'calzada' | 'acceso' | 'linea' | 'tramo';

interface Borrador {
  zonas: Record<number, Point[]>;
  lineas: Record<number, [Point, Point]>;
  tramos: Record<number, [Point, Point]>;
}
const VACIO: Borrador = { zonas: {}, lineas: {}, tramos: {} };
const hayCambios = (b: Borrador) =>
  Object.keys(b.zonas).length + Object.keys(b.lineas).length + Object.keys(b.tramos).length;

/** Lo que falta para terminar de dibujar algo: un nombre o una distancia. */
type Pendiente =
  | { tipo: 'calzada'; zona: Point[]; linea: [Point, Point] | null }
  | { tipo: 'acceso'; zona: Point[] }
  | { tipo: 'linea'; zonaId: number; linea: [Point, Point] }
  | { tipo: 'tramo'; laneId: number; linea: [Point, Point] };

const NEUTRO = '#d0d6de';

export default function Calibrar() {
  const { projectId, projects } = useProjectParam();
  const qc = useQueryClient();
  const { data: lanes } = useLanes(projectId);
  const { data: zones } = useZones(projectId);
  const { data: calibStatus } = useCalibrationStatus(projectId);
  const { data: jobs } = useVideos(projectId ?? undefined);
  const recontar = useRecount();
  const startCounting = useStartCounting();

  const { data: segments, isLoading: cargandoVideos } = useQuery({
    queryKey: ['segments', projectId],
    queryFn: () => listVideoSegments(projectId as number),
    enabled: projectId !== null,
  });

  const [params] = useSearchParams();
  const [jobId, setJobId] = useState<number | null>(null);
  const [fuente, setFuente] = useState<FuenteVideo>(params.get('ver') === 'procesado' ? 'procesado' : 'original');
  const [heatmap, setHeatmap] = useState<HTMLImageElement | null>(null);
  const [verHeatmap, setVerHeatmap] = useState(false);
  const [verDetecciones, setVerDetecciones] = useState(false);
  const [tamano, setTamano] = useState<{ ancho: number; alto: number } | null>(null);

  const [herr, setHerr] = useState<Herramienta>('seleccionar');
  const [puntos, setPuntos] = useState<Point[]>([]);
  /* Calzada a medias: ya se cerró la zona y falta su línea. */
  const [zonaNueva, setZonaNueva] = useState<Point[] | null>(null);
  /* Para 'linea' el id de la zona; para 'tramo' el del carril. */
  const [objetivo, setObjetivo] = useState<number | null>(null);
  const [pendiente, setPendiente] = useState<Pendiente | null>(null);
  const [nombre, setNombre] = useState('');
  const [distancia, setDistancia] = useState('');
  const [seleccion, setSeleccion] = useState<Seleccion>(null);
  const [borrador, setBorrador] = useState<Borrador>(VACIO);
  const historial = useRef<Borrador[]>([]);
  const [guardando, setGuardando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [borrar, setBorrar] = useState<{ tipo: 'calzada' | 'acceso' | 'linea'; id: number; nombre: string } | null>(null);
  const estudioRef = useRef<HTMLDivElement>(null);
  const [altoEstudio, setAltoEstudio] = useState(640);
  /* Bajo 900 px el panel deja de flotar (ver .estudio en pages.css). */
  const [angosto, setAngosto] = useState(() => window.matchMedia('(max-width: 900px)').matches);
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 900px)');
    const cambio = () => setAngosto(mq.matches);
    mq.addEventListener('change', cambio);
    return () => mq.removeEventListener('change', cambio);
  }, []);

  /* El estudio ocupa lo que queda de pantalla bajo el encabezado. */
  useEffect(() => {
    const medir = () => {
      const top = estudioRef.current?.getBoundingClientRect().top ?? 0;
      setAltoEstudio(Math.max(520, window.innerHeight - Math.max(0, top) - 12));
    };
    medir();
    window.addEventListener('resize', medir);
    return () => window.removeEventListener('resize', medir);
  }, [segments]);

  useEffect(() => {
    if (!segments || !segments.length) {
      setJobId(null);
    } else {
      const pedido = Number(params.get('job'));
      // De arranque, un video de día a media mañana si lo hay: calibrar sobre
      // la noche o el amanecer es calibrar a ciegas.
      const deDia = segments.find((s) => {
        const h = Number(s.hora_inicio?.slice(11, 13));
        return h >= 9 && h <= 16;
      });
      setJobId(segments.some((s) => s.job_id === pedido) ? pedido : (deDia ?? segments[0]).job_id);
    }
    cancelar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [segments, params]);

  useEffect(() => {
    setHeatmap(null);
    setVerHeatmap(false);
    if (projectId === null) return;
    let cancelado = false;
    fetchImage(heatmapUrl(projectId))
      .then((img) => !cancelado && setHeatmap(img))
      .catch(() => undefined);
    return () => {
      cancelado = true;
    };
  }, [projectId]);

  /* --- Modelo: calzadas, accesos y líneas sueltas, con el borrador ---- */
  const calzadas = useMemo(
    () => (zones ?? []).filter((z) => z.kind === 'calzada' || z.kind === 'excluir'),
    [zones],
  );
  const accesos = useMemo(() => (zones ?? []).filter((z) => z.kind === 'acceso'), [zones]);
  const colorZona = useCallback(
    (z: Zone) =>
      z.kind === 'acceso'
        ? ACCESO_COLORS[accesos.findIndex((a) => a.id === z.id) % ACCESO_COLORS.length]
        : z.kind === 'excluir'
          ? '#c85050'
          : calzadaColor(calzadas.findIndex((c) => c.id === z.id)),
    [accesos, calzadas],
  );
  const lineasDe = (zonaId: number) => (lanes ?? []).filter((l) => l.zone_id === zonaId);
  const sueltas = (lanes ?? []).filter((l) => !l.zone_id || !(zones ?? []).some((z) => z.id === l.zone_id));

  const geoZona = (z: Zone) => borrador.zonas[z.id] ?? z.points;
  const geoLinea = (l: Lane) => borrador.lineas[l.id] ?? l.points;
  const geoTramo = (l: Lane) => (l.tramo ? borrador.tramos[l.id] ?? l.tramo.linea : null);

  /* Sin el tamaño real no se revisa la orilla: suponer 1920×1080 en una
     cámara de 2560 marcaba "pegada a la orilla" a líneas a media imagen. */
  const segActual = segments?.find((s) => s.job_id === jobId);
  const ancho = tamano?.ancho ?? segActual?.ancho ?? null;
  const alto = tamano?.alto ?? segActual?.alto ?? null;

  const avisosDe = (z: Zone): Aviso[] => {
    if (z.kind !== 'calzada') return [];
    const ls = lineasDe(z.id);
    if (!ls.length) return revisarCalzada(geoZona(z), null, ancho, alto);
    return ls.flatMap((l) => revisarCalzada(geoZona(z), geoLinea(l), ancho, alto));
  };

  const zonasFig: ZonaFig[] = (zones ?? []).map((z) => ({
    id: z.id,
    nombre: z.name,
    color: colorZona(z),
    puntos: geoZona(z),
    acceso: z.kind === 'acceso',
  }));
  const lineasFig: LineaFig[] = (lanes ?? []).map((l) => {
    const z = (zones ?? []).find((q) => q.id === l.zone_id);
    const t = geoTramo(l);
    return {
      id: l.id,
      nombre: l.name,
      color: z ? colorZona(z) : NEUTRO,
      puntos: geoLinea(l),
      tramo: t && l.tramo ? { linea: t, distancia_m: l.tramo.distancia_m } : null,
      alerta: z ? avisosDe(z).some((a) => a.nivel === 'error') : true,
    };
  });

  /* --- Edición ------------------------------------------------------- */
  /* Un arrastre entero es un solo paso de "deshacer": se guarda el estado de
     antes de empezar a arrastrar, no cada movimiento del ratón. */
  const borradorRef = useRef(borrador);
  borradorRef.current = borrador;
  const arrastrando = useRef(false);
  const onMover = useCallback((tipo: 'zona' | 'linea' | 'tramo', id: number, p: Point[]) => {
    const b = borradorRef.current;
    if (!arrastrando.current) {
      arrastrando.current = true;
      historial.current = [...historial.current.slice(-49), b];
    }
    const nuevo =
      tipo === 'zona'
        ? { ...b, zonas: { ...b.zonas, [id]: p } }
        : tipo === 'linea'
          ? { ...b, lineas: { ...b.lineas, [id]: [p[0], p[1]] as [Point, Point] } }
          : { ...b, tramos: { ...b.tramos, [id]: [p[0], p[1]] as [Point, Point] } };
    borradorRef.current = nuevo;
    setBorrador(nuevo);
  }, []);
  const onFinMover = useCallback(() => {
    arrastrando.current = false;
  }, []);
  const deshacer = useCallback(() => {
    const prev = historial.current.pop();
    if (prev) setBorrador(prev);
  }, []);

  async function guardarBorrador() {
    setGuardando(true);
    setError(null);
    try {
      for (const [id, p] of Object.entries(borrador.zonas)) await api.updateZone(Number(id), { points: p });
      for (const [id, p] of Object.entries(borrador.lineas)) await api.updateLane(Number(id), { points: p });
      for (const [id, p] of Object.entries(borrador.tramos)) {
        const l = lanes?.find((q) => q.id === Number(id));
        if (l?.tramo) await api.updateLane(l.id, { tramo: { ...l.tramo, linea: p } });
      }
      setBorrador(VACIO);
      historial.current = [];
      await refrescar();
    } catch (e) {
      setError(`No se pudieron guardar los cambios: ${errorMessage(e)}`);
    } finally {
      setGuardando(false);
    }
  }

  async function refrescar() {
    if (projectId === null) return;
    await Promise.all([
      qc.invalidateQueries({ queryKey: keys.lanes(projectId) }),
      qc.invalidateQueries({ queryKey: keys.zones(projectId) }),
      qc.invalidateQueries({ queryKey: keys.projects }),
      qc.invalidateQueries({ queryKey: ['calibration-status', projectId] }),
    ]);
  }

  /* --- Dibujo -------------------------------------------------------- */
  function cancelar() {
    setHerr('seleccionar');
    setPuntos([]);
    setZonaNueva(null);
    setObjetivo(null);
    setPendiente(null);
    setError(null);
  }

  function empezar(h: Herramienta, obj: number | null = null) {
    setHerr(h);
    setPuntos([]);
    setZonaNueva(null);
    setObjetivo(obj);
    setPendiente(null);
    setSeleccion(null);
    setError(null);
  }

  const onPunto = (p: Point) => {
    if (herr === 'calzada' || herr === 'acceso') {
      if (zonaNueva) {
        // Segundo paso de la calzada: la línea.
        const next = [...puntos, p];
        if (next.length === 2) {
          setPendiente({ tipo: 'calzada', zona: zonaNueva, linea: [next[0], next[1]] });
          setNombre(`Calzada ${calzadas.length + 1}`);
          setPuntos([]);
        } else setPuntos(next);
        return;
      }
      setPuntos((prev) => [...prev, p]);
      return;
    }
    if (herr === 'linea' || herr === 'tramo') {
      const next = [...puntos, p];
      if (next.length < 2) {
        setPuntos(next);
        return;
      }
      setPuntos([]);
      if (herr === 'linea' && objetivo !== null) {
        setPendiente({ tipo: 'linea', zonaId: objetivo, linea: [next[0], next[1]] });
      } else if (herr === 'tramo' && objetivo !== null) {
        const l = lanes?.find((q) => q.id === objetivo);
        setDistancia(l?.tramo ? String(l.tramo.distancia_m) : '');
        setPendiente({ tipo: 'tramo', laneId: objetivo, linea: [next[0], next[1]] });
      }
    }
  };

  const cerrarZona = () => {
    if (puntos.length < 3) return;
    if (herr === 'acceso') {
      setPendiente({ tipo: 'acceso', zona: puntos });
      setNombre(`Acceso ${accesos.length + 1}`);
      setPuntos([]);
    } else {
      setZonaNueva(puntos);
      setPuntos([]);
    }
  };

  async function guardarPendiente(sinLinea = false) {
    if (!pendiente || projectId === null) return;
    setError(null);
    try {
      if (pendiente.tipo === 'calzada' || (pendiente.tipo === 'acceso' && !sinLinea)) {
        const z = await api.createZone({
          project_id: projectId,
          name: nombre.trim() || 'Calzada',
          points: pendiente.zona,
          kind: pendiente.tipo === 'acceso' ? 'acceso' : 'calzada',
        });
        if (pendiente.tipo === 'calzada' && pendiente.linea && !sinLinea) {
          await api.createLane({
            project_id: projectId,
            name: nombre.trim() || 'Calzada',
            points: pendiente.linea,
            zone_id: z.id,
          });
        }
      } else if (pendiente.tipo === 'linea') {
        const z = zones?.find((q) => q.id === pendiente.zonaId);
        await api.createLane({
          project_id: projectId,
          name: z?.name ?? 'Calzada',
          points: pendiente.linea,
          zone_id: pendiente.zonaId,
        });
      } else if (pendiente.tipo === 'tramo') {
        const d = Number(distancia.replace(',', '.'));
        if (!(d > 0 && d <= 500)) {
          setError('Escribe la distancia en metros entre las dos líneas (entre 0 y 500).');
          return;
        }
        const l = lanes?.find((q) => q.id === pendiente.laneId);
        await api.updateLane(pendiente.laneId, {
          tramo: { linea: pendiente.linea, distancia_m: d, origen: l?.tramo?.origen ?? null },
        });
      }
      await refrescar();
      cancelar();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function guardarSinLinea() {
    if (!zonaNueva || projectId === null) return;
    try {
      await api.createZone({ project_id: projectId, name: `Calzada ${calzadas.length + 1}`, points: zonaNueva, kind: 'calzada' });
      await refrescar();
      cancelar();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function confirmarBorrado() {
    if (!borrar) return;
    try {
      if (borrar.tipo === 'linea') await api.deleteLane(borrar.id);
      else {
        for (const l of lineasDe(borrar.id)) await api.deleteLane(l.id);
        await api.deleteZone(borrar.id);
      }
      setSeleccion(null);
      await refrescar();
    } catch (e) {
      setError(errorMessage(e));
    }
    setBorrar(null);
  }

  async function atar(laneId: number, zoneId: number) {
    try {
      await api.updateLane(laneId, { zone_id: zoneId });
      await refrescar();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  async function renombrar(tipo: 'zona' | 'linea', id: number, n: string) {
    const v = n.trim();
    if (!v) return;
    try {
      if (tipo === 'zona') {
        await api.updateZone(id, { name: v });
        // La línea de una calzada lleva su nombre: es lo que sale en el Excel.
        for (const l of lineasDe(id)) if (l.name !== v) await api.updateLane(l.id, { name: v });
      } else await api.updateLane(id, { name: v });
      await refrescar();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  /* --- Teclado -------------------------------------------------------- */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(t.tagName)) return;
      if (e.key === 'Escape') cancelar();
      else if ((e.key === 'Backspace' || e.key === 'Delete') && puntos.length) {
        e.preventDefault();
        setPuntos((p) => p.slice(0, -1));
      } else if (e.key === 'Enter' && (herr === 'calzada' || herr === 'acceso') && !zonaNueva) cerrarZona();
      else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault();
        deshacer();
      } else if (e.key.toLowerCase() === 'v' && !pendiente) cancelar();
      else if (e.key.toLowerCase() === 'n' && !pendiente) empezar('calzada');
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [puntos, herr, zonaNueva, pendiente, deshacer]);

  /* --- Estado del conteo ---------------------------------------------- */
  const awaiting = (jobs ?? []).filter((j) => j.status === 'awaiting_calibration');
  const laneCount = lanes?.length ?? 0;
  const calibrado = laneCount > 0 || accesos.length >= 2;
  const sinVideos = projectId !== null && !cargandoVideos && (segments?.length ?? 0) === 0;
  const otros = (projects ?? []).filter((p) => p.id !== projectId);
  const cambios = hayCambios(borrador);

  const dibujando = herr !== 'seleccionar' && !pendiente;
  const colorDibujo =
    herr === 'acceso'
      ? ACCESO_COLORS[accesos.length % ACCESO_COLORS.length]
      : herr === 'calzada'
        ? calzadaColor(calzadas.length)
        : herr === 'linea' && objetivo !== null
          ? colorZona(zones!.find((z) => z.id === objetivo)!)
          : (lineasFig.find((l) => l.id === objetivo)?.color ?? '#ffffff');

  /* Lo recién dibujado sigue a la vista mientras se le pone nombre, y la
     zona mientras se traza su línea: antes desaparecía y había que nombrar
     a ciegas. */
  const zonaPrevia =
    pendiente?.tipo === 'calzada' || pendiente?.tipo === 'acceso' ? pendiente.zona : zonaNueva;
  const lineaPrevia =
    pendiente?.tipo === 'calzada' || pendiente?.tipo === 'linea' ? pendiente.linea : null;
  const zonasLienzo: ZonaFig[] = zonaPrevia
    ? [...zonasFig, { id: -1, nombre: nombre, color: colorDibujo, puntos: zonaPrevia, acceso: herr === 'acceso' }]
    : zonasFig;
  const lineasLienzo: LineaFig[] = lineaPrevia
    ? [...lineasFig, { id: -1, nombre: nombre || 'Nueva', color: colorDibujo, puntos: lineaPrevia }]
    : lineasFig;

  const instruccion = (() => {
    if (herr === 'calzada' && !zonaNueva)
      return puntos.length < 3
        ? 'Rodea la calle: marca las esquinas de la calzada, desde donde aparecen los vehículos hasta donde salen.'
        : 'Sigue marcando, o cierra la zona: clic en el primer punto, doble clic o Enter.';
    if (herr === 'calzada' && zonaNueva)
      return puntos.length === 0
        ? 'Ahora la línea de conteo: un punto en una orilla de la calle…'
        : '…y el otro en la orilla de enfrente, cruzándola de través, donde el vehículo se vea grande.';
    if (herr === 'acceso')
      return 'Rodea el brazo del acceso, con sus carriles de entrada y salida, hasta la orilla de la imagen.';
    if (herr === 'linea') return puntos.length === 0 ? 'Marca un extremo de la línea, en una orilla de la calle.' : 'Ahora el otro extremo, en la orilla de enfrente.';
    if (herr === 'tramo')
      return 'Segunda línea del tramo de velocidad: a unos 8–12 m de la de conteo, sobre una marca que se pueda medir en el pavimento.';
    return null;
  })();

  if (projectId === null) {
    return <EmptyState title="Elige una intersección" body="Las calzadas se calibran por intersección." />;
  }
  if (sinVideos) {
    return (
      <EmptyState
        title="Esta intersección todavía no tiene videos"
        body="Las calzadas se dibujan sobre el video real, no sobre un plano."
        action={
          <Link className="btn btn-primary" to={`/proyecto/${projectId}/subir`}>
            Subir videos
          </Link>
        }
      />
    );
  }

  const segmentosOrdenados = segments ?? [];

  return (
    <div className="estudio" ref={estudioRef} style={{ height: altoEstudio }}>
      <VideoWorkspace
        segments={segmentosOrdenados}
        jobId={jobId}
        onJobChange={setJobId}
        fuente={fuente}
        onFuenteChange={setFuente}
        showDetections={verDetecciones}
        pausar={dibujando}
        onTamano={(a, h) => setTamano({ ancho: a, alto: h })}
        margenes={angosto ? { arriba: 60 } : { izquierda: 336, arriba: 64, derecha: 16, abajo: 12 }}
      >
        {(c) =>
          fuente === 'procesado' ? null : (
            <Lienzo
              ancho={c.ancho}
              alto={c.alto}
              unidad={c.unidad}
              zonas={zonasLienzo}
              lineas={lineasLienzo}
              seleccion={seleccion}
              onSeleccion={setSeleccion}
              editable={herr === 'seleccionar' && !pendiente}
              onMover={onMover}
              onFinMover={onFinMover}
              dibujo={
                dibujando
                  ? {
                      tipo: (herr === 'calzada' || herr === 'acceso') && !zonaNueva ? 'poligono' : 'segmento',
                      puntos,
                      color: colorDibujo,
                    }
                  : null
              }
              onPunto={onPunto}
              onCerrar={cerrarZona}
              detecciones={c.detecciones}
              heatmap={heatmap}
              verHeatmap={verHeatmap}
              onFondoPointerDown={c.onFondoPointerDown}
            />
          )
        }
      </VideoWorkspace>

      {/* --- Barra de herramientas ------------------------------------ */}
      <div className="est-herramientas" role="toolbar" aria-label="Herramientas de calibración">
        <button type="button" className={herr === 'seleccionar' ? 'is-on' : undefined} onClick={cancelar} title="Seleccionar y mover (V)">
          Mover
        </button>
        <button type="button" className={herr === 'calzada' ? 'is-on' : undefined} onClick={() => empezar('calzada')} disabled={fuente === 'procesado'} title="Nueva calzada: zona + línea (N)">
          + Calzada
        </button>
        <button type="button" className={herr === 'acceso' ? 'is-on' : undefined} onClick={() => empezar('acceso')} disabled={fuente === 'procesado'} title="Acceso para el aforo direccional">
          + Acceso
        </button>
        <span className="est-sep" />
        <label className="est-capa" title={heatmap ? 'Por dónde pasan los vehículos (de lo ya contado)' : 'Aparece cuando la intersección ya tiene conteos'}>
          <input type="checkbox" checked={verHeatmap} disabled={!heatmap} onChange={(e) => setVerHeatmap(e.target.checked)} />
          Rastro
        </label>
        <label className="est-capa" title="Lo que detecta la IA en el cuadro en pausa. Gris punteado: fuera de las zonas.">
          <input type="checkbox" checked={verDetecciones} disabled={fuente === 'procesado'} onChange={(e) => setVerDetecciones(e.target.checked)} />
          Detecciones
        </label>
      </div>

      {/* --- Instrucción del paso actual --------------------------------- */}
      {(instruccion || fuente === 'procesado') && !pendiente && (
        <div className="est-instruccion" role="status" aria-live="polite">
          <span>
            {fuente === 'procesado'
              ? 'Se calibra sobre el video Original: el de detecciones trae las líneas de cuando se contó.'
              : instruccion}
          </span>
          {dibujando && (
            <span className="est-instruccion-acciones">
              {puntos.length > 0 && (
                <button type="button" onClick={() => setPuntos((p) => p.slice(0, -1))}>
                  Deshacer punto <kbd>⌫</kbd>
                </button>
              )}
              {(herr === 'calzada' || herr === 'acceso') && !zonaNueva && puntos.length >= 3 && (
                <button type="button" className="is-primario" onClick={cerrarZona}>
                  Cerrar zona <kbd>Enter</kbd>
                </button>
              )}
              {herr === 'calzada' && zonaNueva && puntos.length === 0 && (
                <button type="button" onClick={() => void guardarSinLinea()}>
                  Guardar sin línea
                </button>
              )}
              <button type="button" onClick={cancelar}>
                Cancelar <kbd>Esc</kbd>
              </button>
            </span>
          )}
        </div>
      )}

      {/* --- Formulario para terminar lo dibujado ------------------------- */}
      {pendiente && (
        <form
          className="est-pendiente"
          onSubmit={(e) => {
            e.preventDefault();
            void guardarPendiente();
          }}
        >
          {pendiente.tipo === 'tramo' ? (
            <>
              <label>
                Distancia entre las dos líneas, en metros
                <input autoFocus inputMode="decimal" value={distancia} placeholder="8.5" onChange={(e) => setDistancia(e.target.value)} />
              </label>
              <p className="est-nota">
                Mídela en el pavimento, en el sentido del tránsito: con cinta, o con la regla de un mapa satelital entre dos marcas
                que se vean en el video. Si está mal, todas las velocidades salen mal en la misma proporción.
              </p>
            </>
          ) : pendiente.tipo === 'linea' ? (
            <p className="est-nota">Línea de conteo de «{zones?.find((z) => z.id === pendiente.zonaId)?.name}».</p>
          ) : (
            <label>
              {pendiente.tipo === 'acceso' ? 'Nombre del acceso' : 'Nombre de la calzada (así sale en el reporte y el Excel)'}
              <input autoFocus value={nombre} onChange={(e) => setNombre(e.target.value)} />
            </label>
          )}
          {pendiente.tipo === 'calzada' && pendiente.linea && (
            <ListaAvisos avisos={revisarCalzada(pendiente.zona, pendiente.linea, ancho, alto)} />
          )}
          {pendiente.tipo === 'linea' && (
            <ListaAvisos
              avisos={revisarCalzada(zones?.find((z) => z.id === pendiente.zonaId)?.points ?? null, pendiente.linea, ancho, alto)}
            />
          )}
          {error && <p className="est-error">{error}</p>}
          <div className="est-pendiente-acciones">
            <button type="button" onClick={cancelar}>
              Cancelar
            </button>
            <button type="submit" className="is-primario">
              {pendiente.tipo === 'tramo' ? 'Guardar tramo' : pendiente.tipo === 'linea' ? 'Guardar línea' : 'Guardar'}
            </button>
          </div>
        </form>
      )}

      {/* --- Cambios sin guardar ------------------------------------------- */}
      {cambios > 0 && !pendiente && !dibujando && (
        <div className="est-guardar" role="status">
          <span>
            {plural(cambios, 'cambio sin guardar', 'cambios sin guardar')}
            {(jobs ?? []).some((j) => j.status === 'done') && ' · los videos ya contados quedarán con la calibración anterior hasta recontarlos'}
          </span>
          <button type="button" onClick={deshacer} disabled={!historial.current.length}>
            Deshacer <kbd>Ctrl Z</kbd>
          </button>
          <button
            type="button"
            onClick={() => {
              setBorrador(VACIO);
              historial.current = [];
            }}
          >
            Descartar
          </button>
          <button type="button" className="is-primario" disabled={guardando} onClick={() => void guardarBorrador()}>
            {guardando ? 'Guardando…' : 'Guardar cambios'}
          </button>
        </div>
      )}

      {/* --- Panel de calzadas -------------------------------------------- */}
      <aside className="est-panel" aria-label="Calzadas">
        <header className="est-panel-cab">
          <h2>Calzadas</h2>
          <span className="est-panel-sub">{plural(calzadas.length, 'calzada', 'calzadas')}</span>
        </header>

        <div className="est-panel-cuerpo">
          {calzadas.length === 0 && accesos.length === 0 && sueltas.length === 0 && (
            <div className="est-vacio">
              <p>
                Una <strong>calzada</strong> es una calle con un sentido de circulación: rodéala y crúzala con su línea de conteo.
              </p>
              <button type="button" className="is-primario" onClick={() => empezar('calzada')} disabled={fuente === 'procesado'}>
                Dibujar la primera calzada
              </button>
              {otros.length > 0 && (
                <p className="est-nota">
                  ¿Ya calibraste esta cámara antes?{' '}
                  <Link to={`/proyecto/${projectId}`}>Copia la calibración de otra intersección</Link>.
                </p>
              )}
            </div>
          )}

          {calzadas.map((z) => {
            const ls = lineasDe(z.id);
            const avisos = avisosDe(z);
            const sel = (seleccion?.tipo === 'zona' && seleccion.id === z.id) || ls.some((l) => seleccion?.id === l.id && seleccion.tipo !== 'zona');
            return (
              <section key={z.id} className={`est-calzada${sel ? ' is-sel' : ''}`} style={{ ['--c' as string]: colorZona(z) }}>
                <div className="est-calzada-cab" onClick={() => setSeleccion({ tipo: 'zona', id: z.id })}>
                  <span className="est-punto" />
                  <input
                    className="est-nombre"
                    defaultValue={z.name}
                    key={z.name}
                    aria-label="Nombre de la calzada"
                    onClick={(e) => e.stopPropagation()}
                    onFocus={() => setSeleccion({ tipo: 'zona', id: z.id })}
                    onBlur={(e) => e.target.value.trim() !== z.name && void renombrar('zona', z.id, e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && (e.target as HTMLInputElement).blur()}
                  />
                  <button type="button" className="est-icono" title="Borrar la calzada y su línea" onClick={(e) => { e.stopPropagation(); setBorrar({ tipo: 'calzada', id: z.id, nombre: z.name }); }}>
                    ×
                  </button>
                </div>
                {z.kind === 'excluir' && <p className="est-nota">Zona excluida: lo que cae dentro no se cuenta.</p>}
                {z.kind === 'calzada' && (
                  <div className="est-calzada-cuerpo">
                    {ls.length === 0 ? (
                      <button type="button" className="est-accion" onClick={() => empezar('linea', z.id)} disabled={fuente === 'procesado'}>
                        + Dibujar su línea de conteo
                      </button>
                    ) : (
                      ls.map((l) => (
                        <div key={l.id} className="est-fila">
                          <button type="button" className="est-enlace" onClick={() => setSeleccion({ tipo: 'linea', id: l.id })}>
                            {l.name === z.name ? 'Línea de conteo' : `Línea «${l.name}»`}
                          </button>
                          {l.tramo ? (
                            <span className="est-chip" title="Tramo de velocidad">
                              velocidad · {l.tramo.distancia_m} m
                              <button type="button" onClick={() => empezar('tramo', l.id)} title="Volver a dibujar el tramo o cambiar la distancia">✎</button>
                              <button type="button" onClick={() => void api.setLaneTramo(l.id, null).then(refrescar)} title="Quitar el tramo">×</button>
                            </span>
                          ) : (
                            <button type="button" className="est-enlace est-sec" onClick={() => empezar('tramo', l.id)} disabled={fuente === 'procesado'}>
                              + medir velocidad
                            </button>
                          )}
                        </div>
                      ))
                    )}
                    <ListaAvisos avisos={avisos} compacto />
                  </div>
                )}
              </section>
            );
          })}

          {sueltas.length > 0 && (
            <section className="est-grupo">
              <h3>Líneas sin calzada</h3>
              <p className="est-nota">Cuentan los vehículos de todas las calles. Átalas a su calzada:</p>
              {sueltas.map((l) => (
                <div key={l.id} className="est-suelta">
                  <span className="est-nombre-fijo">{l.name}</span>
                  <select
                    value=""
                    onChange={(e) => e.target.value && void atar(l.id, Number(e.target.value))}
                    aria-label={`Calzada de ${l.name}`}
                  >
                    <option value="">Atar a…</option>
                    {calzadas.map((z) => (
                      <option key={z.id} value={z.id}>
                        {z.name}
                      </option>
                    ))}
                  </select>
                  <button type="button" className="est-icono" title="Borrar la línea" onClick={() => setBorrar({ tipo: 'linea', id: l.id, nombre: l.name })}>
                    ×
                  </button>
                </div>
              ))}
            </section>
          )}

          {accesos.length > 0 && (
            <section className="est-grupo">
              <h3>Accesos (direccional)</h3>
              {accesos.map((z) => (
                <div key={z.id} className="est-suelta" style={{ ['--c' as string]: colorZona(z) }}>
                  <span className="est-punto" />
                  <input
                    className="est-nombre"
                    defaultValue={z.name}
                    key={z.name}
                    onBlur={(e) => e.target.value.trim() !== z.name && void renombrar('zona', z.id, e.target.value)}
                  />
                  <button type="button" className="est-icono" title="Borrar el acceso" onClick={() => setBorrar({ tipo: 'acceso', id: z.id, nombre: z.name })}>
                    ×
                  </button>
                </div>
              ))}
            </section>
          )}

          {error && !pendiente && <p className="est-error">{error}</p>}
        </div>

        {/* --- Conteo ---------------------------------------------------- */}
        <footer className="est-panel-pie">
          {(calibStatus?.stale ?? 0) > 0 && calibrado ? (
            <>
              <p className="est-estado is-aviso">
                {plural(calibStatus?.stale ?? 0, 'video contado', 'videos contados')} con una calibración anterior.
              </p>
              <button type="button" className="est-boton" disabled={recontar.isPending || cambios > 0} onClick={() => recontar.mutate(projectId)}>
                {recontar.isPending ? 'Reencolando…' : 'Volver a contar con estas líneas'}
              </button>
            </>
          ) : awaiting.length > 0 && calibrado ? (
            <>
              <p className="est-estado">{plural(awaiting.length, 'video esperando', 'videos esperando')}.</p>
              <button type="button" className="est-boton is-primario" disabled={startCounting.isPending || cambios > 0} onClick={() => startCounting.mutate(projectId)}>
                {startCounting.isPending ? 'Iniciando…' : 'Empezar conteo'}
              </button>
            </>
          ) : calibrado && (jobs ?? []).some((j) => j.status === 'done') ? (
            <p className="est-estado is-bien">Los conteos están al día con estas calzadas.</p>
          ) : (
            <p className="est-estado">Dibuja al menos una calzada con su línea para poder contar.</p>
          )}
          {cambios > 0 && <p className="est-nota">Guarda los cambios antes de contar.</p>}
        </footer>
      </aside>

      <ConfirmDialog
        open={borrar !== null}
        title={borrar?.tipo === 'linea' ? '¿Borrar esta línea?' : borrar?.tipo === 'acceso' ? '¿Borrar este acceso?' : '¿Borrar esta calzada?'}
        body={
          borrar
            ? borrar.tipo === 'calzada'
              ? `Se borran la zona «${borrar.nombre}» y su línea de conteo. Lo ya contado se conserva en el histórico.`
              : `Se borra «${borrar.nombre}». Lo ya contado se conserva en el histórico.`
            : ''
        }
        confirmLabel="Borrar"
        destructive
        onConfirm={() => void confirmarBorrado()}
        onCancel={() => setBorrar(null)}
      />
    </div>
  );
}

function ListaAvisos({ avisos, compacto = false }: { avisos: Aviso[]; compacto?: boolean }) {
  if (!avisos.length) {
    return compacto ? <p className="est-ok">✓ Línea bien puesta</p> : null;
  }
  return (
    <ul className={`est-avisos${compacto ? ' is-compacto' : ''}`}>
      {avisos.map((a, i) => (
        <li key={i} className={a.nivel === 'error' ? 'is-error' : 'is-aviso'}>
          {a.texto}
        </li>
      ))}
    </ul>
  );
}
