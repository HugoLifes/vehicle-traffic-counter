/*
  Mesa de trabajo: el video de la intersección con controles de
  reproducción, y encima el lienzo donde se dibujan las líneas de conteo.

  Sirve para las dos cosas que se hacen mirando el video:

   · CALIBRAR — recorrer la grabación original, pausar donde el tránsito
     se ve claro y dibujar ahí las líneas. Antes se calibraba sobre un
     cuadro fijo del centro, lo que obliga a adivinar: si en ese instante
     no pasa nadie, no hay forma de saber por dónde circulan.

   · REVISAR — recorrer la versión que dibujó la IA para comprobar si
     contó bien. Es el mismo reproductor con los mismos controles, así
     que se puede parar en el cuadro exacto de un cruce y comparar.

  Cómo se reproduce, y por qué no es un <video>: los aforos llegan en
  .mkv, .avi o .wmv, que los navegadores no reproducen de forma fiable, y
  un video todavía sin procesar no tiene versión en H.264 — ese
  transcodificado ocurre después de contar, y calibrar va antes. Así que
  los cuadros los sirve el backend uno a uno. Medido de punta a punta:
  2.7 ms por cuadro consecutivo (369 por segundo) y 15 ms al saltar con la
  barra de tiempo. El video original va a 15 cuadros por segundo, así que
  sobra para verlo a velocidad real.

  Usar el mismo motor para las dos fuentes tiene una ventaja que un
  <video> nativo no da: avanzar de cuadro en cuadro sobre el video
  anotado, que es justo lo que hace falta para verificar un conteo.

  El cuadro va en un <img> y las líneas en un <canvas> transparente
  encima. Separarlos evita redibujar la imagen completa quince veces por
  segundo solo porque cambió un punto de una línea.
*/

import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, IconButton, SelectField } from './ui';
import {
  IconPause,
  IconPlay,
  IconReplay,
  IconRepeat,
  IconStepBack,
  IconStepForward,
  IconJumpBack,
  IconJumpForward,
} from './Icons';
import { frameUrl, getFrameDetections } from '../lib/api';
import type { FrameDetection, FuenteVideo, Lane, Point, VideoSegment, Zone } from '../lib/types';

/* Colores de carril: se dibujan sobre el video, no sobre la interfaz, así
   que no salen de los tokens de tema. Son tonos saturados que destacan
   contra el asfalto con cualquier iluminación. */
export const LANE_COLORS = ['#ff5470', '#2dd4ff', '#ffd23f', '#7cff6b', '#c77dff', '#ff9f45'];
export const laneColor = (i: number) => LANE_COLORS[i % LANE_COLORS.length];

/* Las zonas usan una paleta aparte de la de los carriles a propósito: son
   cosas distintas (un área contra una línea) y compartir colores haría
   creer que la zona 1 y el carril 1 tienen algo que ver. */
export const ZONE_COLORS = ['#ffbe46', '#82eb82', '#eb8ceb', '#5ac8ff'];
export const zoneColor = (i: number, kind?: string) =>
  kind === 'excluir' ? '#c85050' : ZONE_COLORS[i % ZONE_COLORS.length];

const SPEEDS = [0.25, 0.5, 1, 2, 4];
const JUMP_SECONDS = 5;

/** Vector unitario hacia el lado que el backend clasifica como "Entrada".
    Misma fórmula (producto cruzado) que usa counter.py, para que no haya
    sorpresas entre lo que se ve aquí y lo que de verdad cuenta el motor. */
function entradaDirection(p1: Point, p2: Point): [number, number] {
  const lx = p2[0] - p1[0];
  const ly = p2[1] - p1[1];
  const len = Math.hypot(lx, ly) || 1;
  const perp: [number, number] = [-ly / len, lx / len];
  return perp[0] * ly - perp[1] * lx > 0 ? perp : [-perp[0], -perp[1]];
}

function mmss(seconds: number): string {
  const s = Math.max(0, seconds);
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
}

interface Props {
  segments: VideoSegment[];
  jobId: number | null;
  onJobChange: (id: number) => void;
  lanes: Lane[];
  /** Áreas de calzada ya guardadas. */
  zones?: Zone[];
  /** Puntos de la línea o del polígono que se está dibujando ahora mismo. */
  drawing: Point[];
  /** Si está activo, un clic en el lienzo agrega un punto. */
  drawMode: boolean;
  /** 'linea' marca 2 puntos; 'zona' acumula vértices hasta cerrar. */
  drawKind?: 'linea' | 'zona';
  onCanvasPoint: (p: Point) => void;
  /** Pide y dibuja las cajas del detector sobre el video original. */
  showDetections?: boolean;
  /** Rastro de movimiento acumulado, si está disponible y encendido. */
  heatmap: HTMLImageElement | null;
  showHeatmap: boolean;
  /* La fuente vive fuera del componente para que un enlace pueda
     aterrizar directamente en "este segmento, con detecciones" — que es
     como se llega desde la cola de procesamiento. */
  fuente: FuenteVideo;
  onFuenteChange: (f: FuenteVideo) => void;
  /** Ancho real del video, en cuanto se conoce por el primer cuadro. */
  onTamano?: (ancho: number, alto: number) => void;
}

export function VideoWorkspace({
  segments,
  jobId,
  onJobChange,
  lanes,
  zones = [],
  drawing,
  drawMode,
  drawKind = 'linea',
  onCanvasPoint,
  showDetections = false,
  heatmap,
  showHeatmap,
  fuente,
  onFuenteChange,
  onTamano,
}: Props) {
  const segment = segments.find((s) => s.job_id === jobId) ?? null;

  /* Dimensiones reales del video. Arrancan con lo que diga el listado (que
     puede no saberlas) y se corrigen con el primer cuadro que llega: la
     imagen cargada es la fuente exacta, y evita que el servidor tenga que
     abrir cada archivo solo para medirlo. */
  const [tamano, setTamano] = useState<{ ancho: number; alto: number } | null>(null);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [repetir, setRepetir] = useState(false);
  const [terminado, setTerminado] = useState(false);
  const [loadError, setLoadError] = useState(false);

  const imgRef = useRef<HTMLImageElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);

  /* Detecciones del cuadro que se está viendo. Cada una cuesta una
     inferencia de GPU (~50 ms), así que solo se piden con el video en
     pausa: hacerlo durante la reproducción pondría al servidor a detectar
     15 cuadros por segundo para nada, compitiendo con la cola de conteo
     que probablemente esté corriendo al mismo tiempo. */
  const [detections, setDetections] = useState<FrameDetection[]>([]);
  const [cargandoDet, setCargandoDet] = useState(false);
  const stageRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef(0);
  frameRef.current = frame;

  const ancho = tamano?.ancho ?? segment?.ancho ?? null;
  const alto = tamano?.alto ?? segment?.alto ?? null;
  const total = segment?.total_frames ?? 0;
  const fps = segment?.fps ?? 15;
  const hayProcesado = segment?.tiene_procesado ?? false;

  // Al cambiar de segmento se vuelve al principio y se detiene: seguir
  // reproduciendo en un punto arbitrario de otro video desorienta.
  useEffect(() => {
    setFrame(0);
    setPlaying(false);
    setTerminado(false);
    setLoadError(false);
    setTamano(null);
  }, [jobId]);

  // Si el segmento elegido no tiene versión con detecciones, se vuelve al
  // original en vez de dejar la pestaña marcada sobre un video que no está.
  //
  // La condición exige que el segmento YA se conozca. Sin eso, al abrir un
  // enlace del tipo `?ver=procesado` la salvaguarda se disparaba en el
  // primer render —cuando los metadatos todavía no habían llegado y por
  // tanto `hayProcesado` era falso— y devolvía a "Original" el enlace que
  // pedía justo lo contrario.
  useEffect(() => {
    if (!segment) return;
    if (fuente === 'procesado' && !hayProcesado) onFuenteChange('original');
  }, [segment, fuente, hayProcesado, onFuenteChange]);

  // Cambiar de fuente conserva la posición: la gracia de comparar es ver
  // el MISMO instante con y sin las cajas de la IA.
  useEffect(() => {
    setPlaying(false);
    setTerminado(false);
  }, [fuente]);

  /* --- Carga de un cuadro ---------------------------------------------
     Se precarga en un Image suelto y solo se cambia el src visible cuando
     ya está decodificado. Asignarlo directamente dejaba el hueco en
     blanco un instante en cada cuadro, y a quince por segundo eso es un
     parpadeo constante. */
  const loadFrame = useCallback(
    (n: number) =>
      new Promise<boolean>((resolve) => {
        if (jobId === null) return resolve(false);
        const url = frameUrl(jobId, n, fuente);
        const pre = new Image();
        pre.onload = () => {
          if (imgRef.current) imgRef.current.src = url;
          if (pre.naturalWidth && pre.naturalHeight) {
            setTamano((prev) =>
              prev && prev.ancho === pre.naturalWidth && prev.alto === pre.naturalHeight
                ? prev
                : { ancho: pre.naturalWidth, alto: pre.naturalHeight },
            );
          }
          setLoadError(false);
          resolve(true);
        };
        pre.onerror = () => {
          setLoadError(true);
          resolve(false);
        };
        pre.src = url;
      }),
    [jobId, fuente],
  );

  useEffect(() => {
    void loadFrame(frame);
  }, [frame, loadFrame]);

  useEffect(() => {
    if (tamano) onTamano?.(tamano.ancho, tamano.alto);
  }, [tamano, onTamano]);

  /* --- Bucle de reproducción ------------------------------------------
     Encadenado, no por intervalo: cada cuadro espera a que el anterior
     haya llegado. Con un setInterval, un tirón de red encolaría
     peticiones y el video se aceleraría de golpe al recuperarse. */
  useEffect(() => {
    if (!playing || jobId === null || !total) return;
    let cancelled = false;
    let timer = 0;

    const periodo = 1000 / (fps * speed);

    const paso = async () => {
      if (cancelled) return;
      let siguiente = frameRef.current + 1;

      if (siguiente >= total) {
        if (!repetir) {
          // Al terminar no se deja el botón en "Reproducir" sin más: se
          // marca que se acabó, y el botón pasa a decir "Repetir". Sin
          // eso, pulsar reproducir al final no hacía nada visible.
          setPlaying(false);
          setTerminado(true);
          return;
        }
        siguiente = 0;
      }

      const t0 = performance.now();
      const ok = await loadFrame(siguiente);
      if (cancelled) return;
      if (!ok) {
        setPlaying(false);
        return;
      }
      frameRef.current = siguiente;
      setFrame(siguiente);
      // Se descuenta lo que tardó en llegar, para que la velocidad
      // elegida sea la que se ve y no dependa de la latencia.
      const espera = Math.max(0, periodo - (performance.now() - t0));
      timer = window.setTimeout(() => void paso(), espera);
    };

    timer = window.setTimeout(() => void paso(), periodo);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [playing, jobId, total, fps, speed, repetir, loadFrame]);

  // Dibujar exige una imagen quieta: al empezar a marcar puntos se pausa.
  useEffect(() => {
    if (drawMode) setPlaying(false);
  }, [drawMode]);

  useEffect(() => {
    if (!showDetections || !segment || playing || fuente === 'procesado') {
      setDetections([]);
      return;
    }
    let cancelado = false;
    setCargandoDet(true);
    // Pequeña espera: al avanzar cuadro a cuadro con las flechas se
    // dispararía una inferencia por pulsación.
    const t = setTimeout(() => {
      getFrameDetections(segment.job_id, frame)
        .then((r) => !cancelado && setDetections(r.detections))
        .catch(() => !cancelado && setDetections([]))
        .finally(() => !cancelado && setCargandoDet(false));
    }, 220);
    return () => {
      cancelado = true;
      clearTimeout(t);
      window.clearTimeout(t);
    };
  }, [showDetections, segment, frame, playing, fuente]);

  /* --- Lienzo de líneas ------------------------------------------------ */

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx || !segment || ancho === null || alto === null) return;

    canvas.width = ancho;
    canvas.height = alto;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // Sobre el video procesado la IA ya dibujó sus propias líneas y cajas.
    // Repintar las nuestras encima duplicaría cada línea con un desfase de
    // un píxel y haría imposible saber cuál es cuál.
    if (fuente === 'procesado') return;

    // El rastro va debajo de las líneas: sirve para juzgar si la línea
    // cruza el tránsito o corre a lo largo de él.
    if (showHeatmap && heatmap) {
      ctx.globalAlpha = 0.55;
      ctx.drawImage(heatmap, 0, 0, canvas.width, canvas.height);
      ctx.globalAlpha = 1;
    }

    /* Las zonas van DEBAJO de las líneas: delimitan el área y las líneas
       son lo que hay que poder ver con precisión para colocarlas bien. */
    const poligono = (pts: Point[], color: string, label: string | null, cerrado: boolean) => {
      if (pts.length < 2) return;
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (const p of pts.slice(1)) ctx.lineTo(p[0], p[1]);
      if (cerrado) ctx.closePath();

      if (cerrado) {
        ctx.fillStyle = color;
        ctx.globalAlpha = 0.2;
        ctx.fill();
        ctx.globalAlpha = 1;
      }
      ctx.strokeStyle = 'rgba(0,0,0,0.5)';
      ctx.lineWidth = 4;
      ctx.stroke();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.stroke();

      for (const p of pts) {
        ctx.fillStyle = 'rgba(0,0,0,0.55)';
        ctx.beginPath();
        ctx.arc(p[0], p[1], 5.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(p[0], p[1], 4, 0, Math.PI * 2);
        ctx.fill();
      }

      if (label) {
        const cx = pts.reduce((a, p) => a + p[0], 0) / pts.length;
        const top = Math.min(...pts.map((p) => p[1]));
        ctx.font = 'bold 13px sans-serif';
        const w = ctx.measureText(label).width;
        ctx.fillStyle = 'rgba(0,0,0,0.8)';
        ctx.fillRect(cx - w / 2 - 5, top - 20, w + 10, 18);
        ctx.fillStyle = color;
        ctx.fillText(label, cx - w / 2, top - 7);
      }
    };

    zones.forEach((z, i) => poligono(z.points, zoneColor(i, z.kind), z.name, true));

    const flecha = (from: Point, dir: [number, number], color: string) => {
      const to: Point = [from[0] + dir[0] * 26, from[1] + dir[1] * 26];
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(from[0], from[1]);
      ctx.lineTo(to[0], to[1]);
      ctx.stroke();
      const a = Math.atan2(dir[1], dir[0]);
      ctx.beginPath();
      ctx.moveTo(to[0], to[1]);
      ctx.lineTo(to[0] - 8 * Math.cos(a - 0.4), to[1] - 8 * Math.sin(a - 0.4));
      ctx.lineTo(to[0] - 8 * Math.cos(a + 0.4), to[1] - 8 * Math.sin(a + 0.4));
      ctx.closePath();
      ctx.fill();
    };

    const linea = (p1: Point, p2: Point, color: string, label: string | null) => {
      // Contorno oscuro bajo la línea: sobre asfalto claro o faros una
      // línea de color plano se pierde.
      ctx.strokeStyle = 'rgba(0,0,0,0.55)';
      ctx.lineWidth = 6;
      ctx.beginPath();
      ctx.moveTo(p1[0], p1[1]);
      ctx.lineTo(p2[0], p2[1]);
      ctx.stroke();

      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(p1[0], p1[1]);
      ctx.lineTo(p2[0], p2[1]);
      ctx.stroke();

      for (const p of [p1, p2]) {
        ctx.fillStyle = 'rgba(0,0,0,0.55)';
        ctx.beginPath();
        ctx.arc(p[0], p[1], 6.5, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(p[0], p[1], 5, 0, Math.PI * 2);
        ctx.fill();
      }

      const mid: Point = [(p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2];
      flecha(mid, entradaDirection(p1, p2), color);

      if (label) {
        ctx.font = 'bold 14px sans-serif';
        const w = ctx.measureText(label).width;
        ctx.fillStyle = 'rgba(0,0,0,0.8)';
        ctx.fillRect(mid[0] + 6, mid[1] - 18, w + 10, 20);
        ctx.fillStyle = color;
        ctx.fillText(label, mid[0] + 11, mid[1] - 3);
      }
    };

    /* Cajas del detector calculadas para ESTE cuadro. A diferencia de las
       del video procesado, están al día con la calibración actual: se
       pueden ver mientras se mueven las líneas. */
    for (const d of detections) {
      const [x1, y1, x2, y2] = d.bbox;
      // Gris para lo que el filtro de zonas descartó: verlo es lo que
      // delata una zona mal dibujada antes de gastar una hora contando.
      const color = !d.en_zona ? '#8a8f98' : d.confidence >= 0.4 ? '#4ade80' : '#fb923c';
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.5;
      ctx.setLineDash(d.en_zona ? [] : [3, 3]);
      ctx.strokeRect(x1, y1, x2 - x1, y2 - y1);
      ctx.setLineDash([]);
      ctx.font = '10px sans-serif';
      ctx.fillStyle = color;
      ctx.fillText(d.confidence.toFixed(2), x1, Math.max(9, y1 - 2));
    }

    lanes.forEach((lane, i) => linea(lane.points[0], lane.points[1], laneColor(i), lane.name));

    if (drawKind === 'zona') {
      // Abierto mientras se dibuja: el área no está definida hasta cerrarla,
      // y mostrarla rellena antes daría una idea equivocada de su forma.
      poligono(drawing, '#ffffff', null, false);
    } else if (drawing.length === 1) {
      ctx.fillStyle = 'rgba(0,0,0,0.55)';
      ctx.beginPath();
      ctx.arc(drawing[0][0], drawing[0][1], 6.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.arc(drawing[0][0], drawing[0][1], 5, 0, Math.PI * 2);
      ctx.fill();
    } else if (drawing.length === 2) {
      linea(drawing[0], drawing[1], '#ffffff', null);
    }
  }, [segment, lanes, zones, drawing, drawKind, detections, heatmap, showHeatmap, fuente]);

  /* --- Transporte ------------------------------------------------------ */

  const irA = useCallback(
    (n: number) => {
      if (!total) return;
      setTerminado(false);
      setFrame(Math.max(0, Math.min(total - 1, n)));
    },
    [total],
  );

  const saltar = useCallback(
    (segundos: number) => irA(frameRef.current + Math.round(segundos * fps)),
    [irA, fps],
  );

  /** Reproducir, pausar, o volver a empezar si ya terminó. */
  const alternarReproduccion = useCallback(() => {
    if (terminado) {
      setTerminado(false);
      setFrame(0);
      setPlaying(true);
      return;
    }
    setPlaying((v) => !v);
  }, [terminado]);

  // Atajos de teclado dentro de la mesa. Espacio no se intercepta cuando
  // el foco está en un botón: ahí ya significa "activar este botón".
  const onKeyDown = (e: React.KeyboardEvent) => {
    const target = e.target as HTMLElement;
    const esControl = ['BUTTON', 'INPUT', 'SELECT', 'A'].includes(target.tagName);

    if (e.key === ' ' && !esControl) {
      e.preventDefault();
      alternarReproduccion();
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      setPlaying(false);
      if (e.shiftKey) saltar(-JUMP_SECONDS);
      else irA(frameRef.current - 1);
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      setPlaying(false);
      if (e.shiftKey) saltar(JUMP_SECONDS);
      else irA(frameRef.current + 1);
    }
  };

  const onStageClick = (e: React.MouseEvent) => {
    if (!segment) return;
    // Fuera del modo dibujo, un clic en el video reproduce o pausa, que es
    // lo que hace cualquier reproductor.
    if (!drawMode) {
      alternarReproduccion();
      return;
    }
    const stage = stageRef.current;
    if (!stage || ancho === null || alto === null) return;
    const r = stage.getBoundingClientRect();
    onCanvasPoint([
      ((e.clientX - r.left) * ancho) / r.width,
      ((e.clientY - r.top) * alto) / r.height,
    ]);
  };

  if (!segment) {
    return (
      <div className="workspace">
        <div className="ws-stage ws-stage-empty">
          <p>Elige una intersección con videos para empezar a calibrar.</p>
        </div>
      </div>
    );
  }

  const tiempo = frame / fps;
  const etiquetaTiempo = `${mmss(tiempo)} / ${mmss(segment.duracion_s)}`;
  const etiquetaPlay = terminado ? 'Repetir' : playing ? 'Pausa' : 'Reproducir';

  return (
    <div className="workspace" onKeyDown={onKeyDown}>
      <div className="ws-head">
        {segments.length > 1 && (
          <SelectField
            label="Segmento"
            value={jobId ?? ''}
            onChange={(e) => onJobChange(Number(e.target.value))}
          >
            {segments.map((s) => (
              <option key={s.job_id} value={s.job_id}>
                {s.nombre}
                {s.hora_inicio ? ` — inicia ${s.hora_inicio.slice(11, 19)}` : ''}
              </option>
            ))}
          </SelectField>
        )}

        {/*
          Grupo de radios, no dos botones: son opciones excluyentes de una
          misma pregunta ("¿qué video estoy viendo?"), y con radios las
          flechas del teclado se mueven entre ellas y el lector de pantalla
          anuncia "1 de 2".
        */}
        <fieldset className="ws-source">
          <legend>Ver</legend>
          <div className="ws-source-options">
            <label className={fuente === 'original' ? 'is-on' : undefined}>
              <input
                type="radio"
                name="fuente-video"
                checked={fuente === 'original'}
                onChange={() => onFuenteChange('original')}
              />
              <span>Original</span>
            </label>
            <label
              className={`${fuente === 'procesado' ? 'is-on' : ''}${hayProcesado ? '' : ' is-off'}`}
            >
              <input
                type="radio"
                name="fuente-video"
                checked={fuente === 'procesado'}
                disabled={!hayProcesado}
                onChange={() => onFuenteChange('procesado')}
              />
              <span>Con detecciones</span>
            </label>
          </div>
          <p className="ws-source-hint">
            {!hayProcesado
              ? 'La versión con detecciones aparece cuando termina el conteo de este segmento.'
              : fuente === 'procesado'
                ? // Se aclara de QUÉ calibración son esas líneas: están quemadas
                  // en la imagen desde que se procesó el video, así que si
                  // después se movieron no coinciden con las de Original —
                  // que es exactamente la confusión que provoca si no se dice.
                  'Lo que vio la IA cuando se procesó. Sus líneas están quemadas en la imagen: si las editaste después, aquí siguen las anteriores.'
                : 'La grabación tal como se subió. Es sobre esta donde se dibujan los carriles.'}
          </p>
        </fieldset>
      </div>

      <div
        className={`ws-stage${drawMode ? ' is-drawing' : ''}`}
        ref={stageRef}
        onClick={onStageClick}
        /* Hasta que llega el primer cuadro se reserva 16:9, para que la
           tarjeta no salte de alto y mueva los controles bajo el cursor. */
        style={{ aspectRatio: ancho && alto ? `${ancho} / ${alto}` : '16 / 9' }}
      >
        <img ref={imgRef} alt={`Cuadro ${frame + 1} de ${segment.nombre}`} />
        {/* El lienzo solo pinta; los clics los recoge el contenedor, que
            es quien conoce la escala entre píxeles del video y de pantalla. */}
        <canvas ref={canvasRef} aria-hidden="true" />

        {/* Distintivo permanente de qué se está mirando: sin él, el video
            anotado y el original se confunden en cuadros sin tránsito. */}
        {fuente === 'procesado' && <span className="ws-badge">Con detecciones</span>}
        {/* Detectar cuesta una inferencia: sin este aviso, el medio segundo
            entre pausar y ver las cajas parece que no pasó nada. */}
        {cargandoDet && <span className="ws-badge">Detectando…</span>}

        {drawMode && (
          <span className="ws-badge ws-badge-draw">
            {drawing.length === 0 ? 'Marca el primer punto' : 'Marca el segundo punto'}
          </span>
        )}

        {loadError && (
          <p className="ws-error" role="alert">
            No se pudo cargar este cuadro del video.
          </p>
        )}
      </div>

      <div className="ws-transport">
        <div className="ws-buttons">
          <IconButton
            label={`Retroceder ${JUMP_SECONDS} segundos`}
            onClick={() => { setPlaying(false); saltar(-JUMP_SECONDS); }}
          >
            <IconJumpBack />
          </IconButton>
          <IconButton label="Cuadro anterior" onClick={() => { setPlaying(false); irA(frame - 1); }}>
            <IconStepBack />
          </IconButton>

          <Button variant="primary" className="ws-play" onClick={alternarReproduccion}>
            {/* El estado va en el icono Y en la palabra: quien no distinga
                los glifos lo lee igual. */}
            {terminado ? <IconReplay size={15} /> : playing ? <IconPause size={15} /> : <IconPlay size={15} />}
            {etiquetaPlay}
          </Button>

          <IconButton label="Cuadro siguiente" onClick={() => { setPlaying(false); irA(frame + 1); }}>
            <IconStepForward />
          </IconButton>
          <IconButton
            label={`Avanzar ${JUMP_SECONDS} segundos`}
            onClick={() => { setPlaying(false); saltar(JUMP_SECONDS); }}
          >
            <IconJumpForward />
          </IconButton>
        </div>

        {/* <input type="range"> nativo: trae el manejo de teclado, el
            arrastre y el anuncio en lector de pantalla sin reconstruir nada. */}
        <input
          className="ws-scrub"
          type="range"
          min={0}
          max={Math.max(0, total - 1)}
          value={frame}
          aria-label="Posición en el video"
          aria-valuetext={etiquetaTiempo}
          onChange={(e) => { setPlaying(false); irA(Number(e.target.value)); }}
        />

        <output className="ws-time mono" aria-live="off">
          {etiquetaTiempo}
        </output>

        <IconButton
          label={repetir ? 'Desactivar repetición continua' : 'Repetir en bucle al terminar'}
          aria-pressed={repetir}
          className={repetir ? 'is-accent' : undefined}
          onClick={() => setRepetir((v) => !v)}
        >
          <IconRepeat />
        </IconButton>

        <label className="ws-speed">
          <span>Velocidad</span>
          <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
            {SPEEDS.map((v) => (
              <option key={v} value={v}>
                {v}×
              </option>
            ))}
          </select>
        </label>
      </div>

      <p className="ws-hint">
        Cuadro <span className="mono">{frame + 1}</span> de{' '}
        <span className="mono">{total}</span>
        {' · '}
        {segment.fps} cuadros por segundo
        {repetir ? ' · repetición continua activada' : ''}. Con el lienzo enfocado:{' '}
        <kbd>espacio</kbd> reproduce, <kbd>←</kbd> <kbd>→</kbd> avanzan un cuadro y con{' '}
        <kbd>Shift</kbd> saltan {JUMP_SECONDS} segundos.
      </p>
    </div>
  );
}
