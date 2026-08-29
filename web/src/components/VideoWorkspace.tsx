/*
  Mesa de trabajo: el video de la intersección con controles de
  reproducción, y encima el lienzo donde se dibujan las líneas de conteo.

  Antes se calibraba sobre un cuadro fijo del centro del video. Eso obliga
  a adivinar: si en ese instante no pasa nadie, no hay forma de saber por
  dónde circulan realmente los vehículos. Aquí se recorre la grabación,
  se pausa donde el tránsito se ve claro y se dibuja ahí.

  Cómo se reproduce, y por qué no es un <video>: los aforos llegan en
  .mkv, .avi o .wmv, que los navegadores no reproducen de forma fiable, y
  un video todavía sin procesar no tiene versión en H.264 — ese
  transcodificado ocurre después de contar, y calibrar va antes. Así que
  los cuadros los sirve el backend uno a uno. Medido de punta a punta:
  2.7 ms por cuadro consecutivo (369 por segundo) y 15 ms al saltar con la
  barra de tiempo. El video original va a 15 cuadros por segundo, así que
  sobra para verlo a velocidad real.

  El cuadro va en un <img> y las líneas en un <canvas> transparente
  encima. Separarlos evita redibujar la imagen completa quince veces por
  segundo solo porque cambió un punto de una línea.
*/

import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, IconButton, SelectField } from './ui';
import {
  IconPause,
  IconPlay,
  IconStepBack,
  IconStepForward,
  IconJumpBack,
  IconJumpForward,
} from './Icons';
import { frameUrl } from '../lib/api';
import type { Lane, Point, VideoSegment } from '../lib/types';

/* Colores de carril: se dibujan sobre el video, no sobre la interfaz, así
   que no salen de los tokens de tema. Son tonos saturados que destacan
   contra el asfalto con cualquier iluminación. */
export const LANE_COLORS = ['#ff5470', '#2dd4ff', '#ffd23f', '#7cff6b', '#c77dff', '#ff9f45'];
export const laneColor = (i: number) => LANE_COLORS[i % LANE_COLORS.length];

const SPEEDS = [0.5, 1, 2, 4];
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
  /** Puntos de la línea que se está dibujando ahora mismo. */
  drawing: Point[];
  /** Si está activo, un clic en el lienzo agrega un punto. */
  drawMode: boolean;
  onCanvasPoint: (p: Point) => void;
  /** Rastro de movimiento acumulado, si está disponible y encendido. */
  heatmap: HTMLImageElement | null;
  showHeatmap: boolean;
}

export function VideoWorkspace({
  segments,
  jobId,
  onJobChange,
  lanes,
  drawing,
  drawMode,
  onCanvasPoint,
  heatmap,
  showHeatmap,
}: Props) {
  const segment = segments.find((s) => s.job_id === jobId) ?? null;

  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [loadError, setLoadError] = useState(false);

  const imgRef = useRef<HTMLImageElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stageRef = useRef<HTMLDivElement>(null);
  const frameRef = useRef(0);
  frameRef.current = frame;

  const total = segment?.total_frames ?? 0;
  const fps = segment?.fps ?? 15;

  // Al cambiar de segmento se vuelve al principio y se detiene: seguir
  // reproduciendo en un punto arbitrario de otro video desorienta.
  useEffect(() => {
    setFrame(0);
    setPlaying(false);
    setLoadError(false);
  }, [jobId]);

  /* --- Carga de un cuadro ---------------------------------------------
     Se precarga en un Image suelto y solo se cambia el src visible cuando
     ya está decodificado. Asignarlo directamente dejaba el hueco en
     blanco un instante en cada cuadro, y a quince por segundo eso es un
     parpadeo constante. */
  const loadFrame = useCallback(
    (n: number) =>
      new Promise<boolean>((resolve) => {
        if (jobId === null) return resolve(false);
        const url = frameUrl(jobId, n);
        const pre = new Image();
        pre.onload = () => {
          if (imgRef.current) imgRef.current.src = url;
          setLoadError(false);
          resolve(true);
        };
        pre.onerror = () => {
          setLoadError(true);
          resolve(false);
        };
        pre.src = url;
      }),
    [jobId],
  );

  useEffect(() => {
    void loadFrame(frame);
    // `frame` cambia también al arrastrar la barra; loadFrame ya está
    // memorizado por jobId, así que no rehace la carga sin motivo.
  }, [frame, loadFrame]);

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
      const siguiente = frameRef.current + 1;
      if (siguiente >= total) {
        setPlaying(false);
        return;
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
  }, [playing, jobId, total, fps, speed, loadFrame]);

  // Dibujar exige una imagen quieta: al empezar a marcar puntos se pausa.
  useEffect(() => {
    if (drawMode) setPlaying(false);
  }, [drawMode]);

  /* --- Lienzo de líneas ------------------------------------------------ */

  useEffect(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx || !segment) return;

    canvas.width = segment.ancho;
    canvas.height = segment.alto;
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    // El rastro va debajo de las líneas: sirve para juzgar si la línea
    // cruza el tránsito o corre a lo largo de él.
    if (showHeatmap && heatmap) {
      ctx.globalAlpha = 0.55;
      ctx.drawImage(heatmap, 0, 0, canvas.width, canvas.height);
      ctx.globalAlpha = 1;
    }

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

    lanes.forEach((lane, i) => linea(lane.points[0], lane.points[1], laneColor(i), lane.name));

    if (drawing.length === 1) {
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
  }, [segment, lanes, drawing, heatmap, showHeatmap]);

  /* --- Transporte ------------------------------------------------------ */

  const irA = useCallback(
    (n: number) => {
      if (!total) return;
      setFrame(Math.max(0, Math.min(total - 1, n)));
    },
    [total],
  );

  const saltar = useCallback(
    (segundos: number) => irA(frameRef.current + Math.round(segundos * fps)),
    [irA, fps],
  );

  // Atajos de teclado dentro de la mesa. Espacio no se intercepta cuando
  // el foco está en un botón: ahí ya significa "activar este botón".
  const onKeyDown = (e: React.KeyboardEvent) => {
    const target = e.target as HTMLElement;
    const esControl = ['BUTTON', 'INPUT', 'SELECT', 'A'].includes(target.tagName);

    if (e.key === ' ' && !esControl) {
      e.preventDefault();
      setPlaying((v) => !v);
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault();
      setPlaying(false);
      e.shiftKey ? saltar(-JUMP_SECONDS) : irA(frameRef.current - 1);
    } else if (e.key === 'ArrowRight') {
      e.preventDefault();
      setPlaying(false);
      e.shiftKey ? saltar(JUMP_SECONDS) : irA(frameRef.current + 1);
    }
  };

  const onStageClick = (e: React.MouseEvent) => {
    if (!drawMode || !segment) return;
    const stage = stageRef.current;
    if (!stage) return;
    const r = stage.getBoundingClientRect();
    onCanvasPoint([
      ((e.clientX - r.left) * segment.ancho) / r.width,
      ((e.clientY - r.top) * segment.alto) / r.height,
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

  return (
    // eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions
    <div className="workspace" onKeyDown={onKeyDown}>
      {segments.length > 1 && (
        <div className="ws-head">
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
        </div>
      )}

      <div
        className={`ws-stage${drawMode ? ' is-drawing' : ''}`}
        ref={stageRef}
        onClick={onStageClick}
        style={{ aspectRatio: `${segment.ancho} / ${segment.alto}` }}
      >
        <img ref={imgRef} alt={`Cuadro ${frame + 1} de ${segment.nombre}`} />
        {/* El lienzo solo pinta; los clics los recoge el contenedor, que
            es quien conoce la escala entre píxeles del video y de pantalla. */}
        <canvas ref={canvasRef} aria-hidden="true" />
        {loadError && (
          <p className="ws-error" role="alert">
            No se pudo cargar este cuadro del video.
          </p>
        )}
      </div>

      <div className="ws-transport">
        <div className="ws-buttons">
          <IconButton label={`Retroceder ${JUMP_SECONDS} segundos`} onClick={() => { setPlaying(false); saltar(-JUMP_SECONDS); }}>
            <IconJumpBack />
          </IconButton>
          <IconButton label="Cuadro anterior" onClick={() => { setPlaying(false); irA(frame - 1); }}>
            <IconStepBack />
          </IconButton>

          <Button
            variant="primary"
            className="ws-play"
            aria-pressed={playing}
            onClick={() => setPlaying((v) => !v)}
          >
            {/* El estado va en el icono Y en la palabra: quien no distinga
                los dos glifos lo lee igual. */}
            {playing ? <IconPause size={15} /> : <IconPlay size={15} />}
            {playing ? 'Pausa' : 'Reproducir'}
          </Button>

          <IconButton label="Cuadro siguiente" onClick={() => { setPlaying(false); irA(frame + 1); }}>
            <IconStepForward />
          </IconButton>
          <IconButton label={`Avanzar ${JUMP_SECONDS} segundos`} onClick={() => { setPlaying(false); saltar(JUMP_SECONDS); }}>
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
        {segment.fps} cuadros por segundo. Con el lienzo enfocado: <kbd>espacio</kbd> reproduce,{' '}
        <kbd>←</kbd> <kbd>→</kbd> avanzan un cuadro y con <kbd>Shift</kbd> saltan {JUMP_SECONDS}{' '}
        segundos.
      </p>
    </div>
  );
}
