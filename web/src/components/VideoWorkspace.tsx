/*
  Mesa de trabajo: el video de la intersección ocupando la pantalla, con
  zoom y desplazamiento, sus controles flotando encima, y una capa de
  dibujo que pone quien la usa (el calibrador).

  Cómo se reproduce. Al darle reproducir, si el archivo lo admite (el video
  con detecciones siempre; el original si es .mp4/.mov/.webm), con un
  <video> de verdad que el navegador transmite por partes: pedirlo cuadro
  por cuadro por internet tardaba 2.6 s por cuadro de 2560x1440 (medido el
  1-oct-2026). En pausa se vuelve al cuadro exacto del servidor, que es lo
  que hace falta para calibrar y para avanzar de uno en uno. Los .mkv,
  .avi o .wmv, que el navegador no reproduce, van cuadro por cuadro.

  Zoom. Calibrar un video de 2560 px en un recuadro de 1000 obligaba a
  poner la línea a ojo (8-oct-2026, el dueño). La rueda del mouse acerca en
  el punto del cursor, como en un mapa; con zoom, arrastrar el fondo
  desplaza la imagen. El zoom es una transformación CSS del marco, así que
  la imagen, el video y la capa de dibujo se mueven juntos y la capa sigue
  recibiendo los clics en coordenadas del video.
*/

import { useCallback, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { IconButton } from './ui';
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
import { frameUrl, getFrameDetections, originalUrl, videoUrl } from '../lib/api';
import type { FrameDetection, FuenteVideo, VideoSegment } from '../lib/types';

/* Colores de calzada: se dibujan sobre el video, no sobre la interfaz, así
   que no salen de los tokens de tema. Saturados para destacar contra el
   asfalto con cualquier luz. La zona y su línea comparten color: son la
   misma calzada. */
export const CALZADA_COLORS = ['#ff5470', '#2dd4ff', '#ffd23f', '#7cff6b', '#c77dff', '#ff9f45'];
export const calzadaColor = (i: number) => CALZADA_COLORS[i % CALZADA_COLORS.length];
export const ACCESO_COLORS = ['#ffbe46', '#82eb82', '#eb8ceb', '#5ac8ff'];

const SPEEDS = [0.25, 0.5, 1, 2, 4];
const JUMP_SECONDS = 5;
const ZOOM_MAX = 10;

function mmss(seconds: number): string {
  const s = Math.max(0, seconds);
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(Math.floor(s % 60)).padStart(2, '0')}`;
}

export interface CapaContexto {
  ancho: number;
  alto: number;
  /** Píxeles de video por píxel de pantalla, con el zoom aplicado. */
  unidad: number;
  detecciones: FrameDetection[];
  /** Para que la capa pida desplazar la imagen al arrastrar el fondo. */
  onFondoPointerDown: (e: React.PointerEvent) => void;
}

interface Props {
  segments: VideoSegment[];
  jobId: number | null;
  onJobChange: (id: number) => void;
  fuente: FuenteVideo;
  onFuenteChange: (f: FuenteVideo) => void;
  showDetections?: boolean;
  /** Mientras se dibuja, el video no se reproduce. */
  pausar?: boolean;
  onTamano?: (ancho: number, alto: number) => void;
  /** La capa de dibujo, dentro del marco que se acerca y se desplaza. */
  children?: (c: CapaContexto) => ReactNode;
  /** Espacio que tapan los paneles flotantes, en píxeles de pantalla: la
      imagen se ajusta al hueco libre para que al abrir no quede debajo. */
  margenes?: { izquierda?: number; arriba?: number; derecha?: number; abajo?: number };
}

export function VideoWorkspace({
  segments,
  jobId,
  onJobChange,
  fuente,
  onFuenteChange,
  showDetections = false,
  pausar = false,
  onTamano,
  children,
  margenes,
}: Props) {
  const segment = segments.find((s) => s.job_id === jobId) ?? null;

  const [tamano, setTamano] = useState<{ ancho: number; alto: number } | null>(null);
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [repetir, setRepetir] = useState(false);
  const [terminado, setTerminado] = useState(false);
  const [loadError, setLoadError] = useState(false);

  const imgRef = useRef<HTMLImageElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const escenaRef = useRef<HTMLDivElement>(null);
  const [modoVideo, setModoVideo] = useState(false);
  const modoVideoRef = useRef(false);
  modoVideoRef.current = modoVideo;
  const [videoFallo, setVideoFallo] = useState(false);
  const [bufferizando, setBufferizando] = useState(false);

  const [detections, setDetections] = useState<FrameDetection[]>([]);
  const [cargandoDet, setCargandoDet] = useState(false);
  const frameRef = useRef(0);
  frameRef.current = frame;

  const ancho = tamano?.ancho ?? segment?.ancho ?? null;
  const alto = tamano?.alto ?? segment?.alto ?? null;
  const total = segment?.total_frames ?? 0;
  const fps = segment?.fps ?? 15;
  const hayProcesado = segment?.tiene_procesado ?? false;
  const fuenteVideo =
    jobId === null || videoFallo
      ? null
      : fuente === 'procesado'
        ? hayProcesado
          ? videoUrl(jobId)
          : null
        : segment?.original_reproducible
          ? originalUrl(jobId)
          : null;

  /* --- Encaje y zoom --------------------------------------------------- */
  const [escena, setEscena] = useState<{ w: number; h: number }>({ w: 0, h: 0 });
  const [vista, setVista] = useState({ z: 1, tx: 0, ty: 0 });
  const vistaRef = useRef(vista);
  vistaRef.current = vista;
  useLayoutEffect(() => {
    const el = escenaRef.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setEscena({ w: el.clientWidth, h: el.clientHeight }));
    ro.observe(el);
    setEscena({ w: el.clientWidth, h: el.clientHeight });
    return () => ro.disconnect();
  }, [segment !== null]);

  const ra = ancho && alto ? ancho / alto : 16 / 9;
  const mi = margenes?.izquierda ?? 0;
  const ma = margenes?.arriba ?? 0;
  const libreW = Math.max(escena.w * 0.4, escena.w - mi - (margenes?.derecha ?? 0));
  const libreH = Math.max(escena.h * 0.4, escena.h - ma - (margenes?.abajo ?? 0));
  const ajuste = escena.w && escena.h ? Math.min(libreW, libreH * ra) : 0;
  const fw = ajuste;
  const fh = ajuste / ra;
  const ox = Math.min(mi, escena.w - libreW) + (libreW - fw) / 2;
  const oy = Math.min(ma, escena.h - libreH) + (libreH - fh) / 2;
  const unidad = ancho && fw ? ancho / (fw * vista.z) : 1;

  const zoomEn = useCallback(
    (factor: number, cx?: number, cy?: number) => {
      setVista((v) => {
        const z2 = Math.max(1, Math.min(ZOOM_MAX, v.z * factor));
        if (z2 === 1) return { z: 1, tx: 0, ty: 0 };
        const px = cx ?? escena.w / 2;
        const py = cy ?? escena.h / 2;
        // El punto bajo el cursor se queda en su sitio.
        const wx = (px - ox - v.tx) / v.z;
        const wy = (py - oy - v.ty) / v.z;
        return { z: z2, tx: px - ox - wx * z2, ty: py - oy - wy * z2 };
      });
    },
    [escena.w, escena.h, ox, oy],
  );

  useEffect(() => {
    const el = escenaRef.current;
    if (!el) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const r = el.getBoundingClientRect();
      // Proporcional al giro: una muesca de ratón (~100) acerca 1.17×, y el
      // panel táctil, que manda muchos eventos chicos, no salta a lo loco.
      const d = e.deltaMode === 1 ? e.deltaY * 33 : e.deltaY;
      zoomEn(Math.exp(-Math.max(-300, Math.min(300, d)) * 0.0016), e.clientX - r.left, e.clientY - r.top);
    };
    el.addEventListener('wheel', onWheel, { passive: false });
    return () => el.removeEventListener('wheel', onWheel);
  }, [zoomEn]);

  const desplazar = useCallback((e: React.PointerEvent | PointerEvent) => {
    const x0 = e.clientX;
    const y0 = e.clientY;
    const b = { tx: vistaRef.current.tx, ty: vistaRef.current.ty };
    const mover = (ev: PointerEvent) => {
      setVista((v) => (v.z === 1 ? v : { ...v, tx: b.tx + ev.clientX - x0, ty: b.ty + ev.clientY - y0 }));
    };
    const soltar = () => {
      window.removeEventListener('pointermove', mover);
      window.removeEventListener('pointerup', soltar);
    };
    window.addEventListener('pointermove', mover);
    window.addEventListener('pointerup', soltar);
  }, []);

  const onFondoPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (vista.z > 1) desplazar(e);
    },
    [vista.z, desplazar],
  );

  /* --- Segmento y fuente ---------------------------------------------- */
  useEffect(() => {
    setFrame(0);
    setPlaying(false);
    setTerminado(false);
    setLoadError(false);
    setTamano(null);
    setVideoFallo(false);
  }, [jobId]);

  useEffect(() => {
    if (!segment) return;
    if (fuente === 'procesado' && !hayProcesado) onFuenteChange('original');
  }, [segment, fuente, hayProcesado, onFuenteChange]);

  useEffect(() => {
    setPlaying(false);
    setTerminado(false);
  }, [fuente]);

  useEffect(() => {
    if (pausar) setPlaying(false);
  }, [pausar]);

  /* --- Carga de un cuadro: precargado, sin parpadeo ------------------- */
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
    if (modoVideoRef.current) return;
    void loadFrame(frame);
  }, [frame, loadFrame]);

  useEffect(() => {
    if (tamano) onTamano?.(tamano.ancho, tamano.alto);
  }, [tamano, onTamano]);

  /* --- Reproducción con <video> -------------------------------------- */
  useEffect(() => {
    const v = videoRef.current;
    if (!playing || !fuenteVideo || !v || !total) return;
    let cancelado = false;
    setModoVideo(true);
    modoVideoRef.current = true;
    v.playbackRate = speed;
    const inicio = frameRef.current / fps;
    const fijarInicio = () => {
      if (Math.abs(v.currentTime - inicio) > 0.5 / fps) v.currentTime = inicio;
    };
    if (v.readyState >= 1) fijarInicio();
    else v.addEventListener('loadedmetadata', fijarInicio, { once: true });
    v.play().catch((e: unknown) => {
      if (cancelado || (e instanceof DOMException && e.name === 'AbortError')) return;
      setVideoFallo(true);
    });
    let raf = 0;
    const seguir = () => {
      if (cancelado) return;
      const n = Math.min(total - 1, Math.floor(v.currentTime * fps));
      if (n !== frameRef.current) {
        frameRef.current = n;
        setFrame(n);
      }
      raf = requestAnimationFrame(seguir);
    };
    raf = requestAnimationFrame(seguir);
    const alTerminar = () => {
      setPlaying(false);
      setTerminado(true);
    };
    v.addEventListener('ended', alTerminar);
    return () => {
      cancelado = true;
      cancelAnimationFrame(raf);
      v.removeEventListener('ended', alTerminar);
      v.pause();
      const n = Math.max(0, Math.min(total - 1, Math.round(v.currentTime * fps)));
      frameRef.current = n;
      setFrame(n);
      void loadFrame(n).then(() => {
        modoVideoRef.current = false;
        setModoVideo(false);
      });
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, fuenteVideo, fps, total, loadFrame]);

  useEffect(() => {
    if (videoRef.current) videoRef.current.playbackRate = speed;
  }, [speed]);
  useEffect(() => {
    if (videoRef.current) videoRef.current.loop = repetir;
  }, [repetir]);

  /* --- Reproducción cuadro por cuadro (formatos que el navegador no lee) */
  useEffect(() => {
    if (!playing || fuenteVideo || jobId === null || !total) return;
    let cancelled = false;
    let timer = 0;
    const periodo = 1000 / (fps * speed);
    const paso = async () => {
      if (cancelled) return;
      let siguiente = frameRef.current + 1;
      if (siguiente >= total) {
        if (!repetir) {
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
      timer = window.setTimeout(() => void paso(), Math.max(0, periodo - (performance.now() - t0)));
    };
    timer = window.setTimeout(() => void paso(), periodo);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [playing, fuenteVideo, jobId, total, fps, speed, repetir, loadFrame]);

  /* --- Detecciones del cuadro en pausa ------------------------------- */
  useEffect(() => {
    if (!showDetections || !segment || playing || fuente === 'procesado') {
      setDetections((d) => (d.length ? [] : d));
      return;
    }
    let cancelado = false;
    setCargandoDet(true);
    const t = setTimeout(() => {
      getFrameDetections(segment.job_id, frame)
        .then((r) => !cancelado && setDetections(r.detections))
        .catch(() => !cancelado && setDetections([]))
        .finally(() => !cancelado && setCargandoDet(false));
    }, 220);
    return () => {
      cancelado = true;
      clearTimeout(t);
    };
  }, [showDetections, segment, frame, playing, fuente]);

  /* --- Transporte ----------------------------------------------------- */
  const irA = useCallback(
    (n: number) => {
      if (!total) return;
      setTerminado(false);
      setFrame(Math.max(0, Math.min(total - 1, n)));
    },
    [total],
  );
  const saltar = useCallback((s: number) => irA(frameRef.current + Math.round(s * fps)), [irA, fps]);
  const alternarReproduccion = useCallback(() => {
    if (terminado) {
      setTerminado(false);
      setFrame(0);
      setPlaying(true);
      return;
    }
    setPlaying((v) => !v);
  }, [terminado]);

  const onKeyDown = (e: React.KeyboardEvent) => {
    const t = e.target as HTMLElement;
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(t.tagName)) return;
    const esBoton = ['BUTTON', 'A'].includes(t.tagName);
    if (e.key === ' ' && !esBoton) {
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
    } else if (e.key === '+' || e.key === '=') {
      zoomEn(1.4);
    } else if (e.key === '-') {
      zoomEn(1 / 1.4);
    } else if (e.key === '0') {
      setVista({ z: 1, tx: 0, ty: 0 });
    }
  };

  if (!segment) {
    return (
      <div className="workspace">
        <div className="ws-escena ws-vacia">
          <p>Cargando los videos de esta intersección…</p>
        </div>
      </div>
    );
  }

  const tiempo = frame / fps;
  const etiquetaTiempo = `${mmss(tiempo)} / ${mmss(segment.duracion_s)}`;
  const horaReal = segment.hora_inicio
    ? new Date(new Date(segment.hora_inicio.replace(' ', 'T')).getTime() + tiempo * 1000)
        .toTimeString()
        .slice(0, 8)
    : null;

  return (
    <div className="workspace" onKeyDown={onKeyDown} tabIndex={-1}>
      <div
        className="ws-escena"
        ref={escenaRef}
        onPointerDown={(e) => {
          // Botón central: desplazar con cualquier herramienta.
          if (e.button === 1) {
            e.preventDefault();
            desplazar(e);
          }
        }}
      >
        <div
          className="ws-marco"
          style={{
            width: fw,
            height: fh,
            transform: `translate(${ox + vista.tx}px, ${oy + vista.ty}px) scale(${vista.z})`,
          }}
        >
          <img ref={imgRef} alt={`Cuadro ${frame + 1} de ${segment.nombre}`} className={modoVideo ? 'is-oculto' : undefined} draggable={false} />
          {fuenteVideo && (
            <video
              ref={videoRef}
              key={fuenteVideo}
              src={fuenteVideo}
              className={modoVideo ? undefined : 'is-oculto'}
              muted
              playsInline
              preload="metadata"
              loop={repetir}
              aria-hidden="true"
              onWaiting={() => setBufferizando(true)}
              onPlaying={() => setBufferizando(false)}
              onPause={() => setBufferizando(false)}
              onError={() => {
                setVideoFallo(true);
                setModoVideo(false);
              }}
            />
          )}
          {ancho && alto && children?.({ ancho, alto, unidad, detecciones: detections, onFondoPointerDown })}
        </div>

        <div className="ws-insignias">
          {fuente === 'procesado' && <span className="ws-badge">Con detecciones</span>}
          {cargandoDet && <span className="ws-badge">Detectando…</span>}
          {modoVideo && bufferizando && <span className="ws-badge">Cargando video…</span>}
          {loadError && <span className="ws-badge is-error">No se pudo cargar este cuadro</span>}
        </div>

        <div className="ws-zoom" role="group" aria-label="Zoom">
          <button type="button" onClick={() => zoomEn(1 / 1.4)} aria-label="Alejar" disabled={vista.z <= 1}>
            −
          </button>
          <button type="button" className="mono" onClick={() => setVista({ z: 1, tx: 0, ty: 0 })} title="Ajustar a la pantalla (0)">
            {Math.round(vista.z * 100)}%
          </button>
          <button type="button" onClick={() => zoomEn(1.4)} aria-label="Acercar" disabled={vista.z >= ZOOM_MAX}>
            +
          </button>
        </div>
      </div>

      <div className="ws-barra">
        <div className="ws-barra-fila">
          <IconButton label={`Retroceder ${JUMP_SECONDS} segundos`} onClick={() => { setPlaying(false); saltar(-JUMP_SECONDS); }}>
            <IconJumpBack />
          </IconButton>
          <IconButton label="Cuadro anterior" onClick={() => { setPlaying(false); irA(frame - 1); }}>
            <IconStepBack />
          </IconButton>
          <button type="button" className="ws-play" onClick={alternarReproduccion} aria-label={terminado ? 'Repetir' : playing ? 'Pausa' : 'Reproducir'}>
            {terminado ? <IconReplay size={16} /> : playing ? <IconPause size={16} /> : <IconPlay size={16} />}
          </button>
          <IconButton label="Cuadro siguiente" onClick={() => { setPlaying(false); irA(frame + 1); }}>
            <IconStepForward />
          </IconButton>
          <IconButton label={`Avanzar ${JUMP_SECONDS} segundos`} onClick={() => { setPlaying(false); saltar(JUMP_SECONDS); }}>
            <IconJumpForward />
          </IconButton>

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
          <output className="ws-time mono" aria-live="off" title={`Cuadro ${frame + 1} de ${total}`}>
            {horaReal ?? etiquetaTiempo}
          </output>

          <IconButton
            label={repetir ? 'Desactivar repetición continua' : 'Repetir en bucle'}
            aria-pressed={repetir}
            className={repetir ? 'is-accent' : undefined}
            onClick={() => setRepetir((v) => !v)}
          >
            <IconRepeat />
          </IconButton>
          <select className="ws-mini-select" value={speed} onChange={(e) => setSpeed(Number(e.target.value))} aria-label="Velocidad">
            {SPEEDS.map((v) => (
              <option key={v} value={v}>
                {v}×
              </option>
            ))}
          </select>
        </div>

        <div className="ws-barra-fila ws-barra-info">
          {segments.length > 1 ? (
            <select
              className="ws-mini-select ws-segmento"
              value={jobId ?? ''}
              onChange={(e) => onJobChange(Number(e.target.value))}
              aria-label="Video"
            >
              {segments.map((s) => (
                <option key={s.job_id} value={s.job_id}>
                  {s.nombre}
                  {s.hora_inicio ? ` — ${s.hora_inicio.slice(0, 16)}` : ''}
                </option>
              ))}
            </select>
          ) : (
            <span className="ws-segmento-solo">{segment.nombre}</span>
          )}
          <div className="ws-fuente" role="radiogroup" aria-label="Qué video ver">
            <button type="button" role="radio" aria-checked={fuente === 'original'} className={fuente === 'original' ? 'is-on' : undefined} onClick={() => onFuenteChange('original')}>
              Original
            </button>
            <button
              type="button"
              role="radio"
              aria-checked={fuente === 'procesado'}
              disabled={!hayProcesado}
              title={hayProcesado ? 'Lo que vio la IA al contar; sus líneas son las de ese momento' : 'Aparece cuando termina el conteo de este video'}
              className={fuente === 'procesado' ? 'is-on' : undefined}
              onClick={() => onFuenteChange('procesado')}
            >
              Con detecciones
            </button>
          </div>
          <span className="ws-atajos">
            <kbd>espacio</kbd> reproduce · <kbd>←</kbd><kbd>→</kbd> cuadro · rueda: zoom
          </span>
        </div>
      </div>
    </div>
  );
}
