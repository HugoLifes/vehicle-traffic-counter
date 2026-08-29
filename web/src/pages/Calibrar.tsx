/*
  Calibración de carriles.

  Se carga un cuadro real de la grabación, el usuario marca dos puntos
  donde cruzan los vehículos y la línea se guarda con nombre. La flecha de
  "Entrada" se calcula con la MISMA fórmula (producto cruzado) que usa el
  backend en counter.py, para que no haya sorpresas entre lo que se ve
  aquí y lo que de verdad cuenta el motor.

  Calibrar va ANTES de contar a propósito: sin líneas definidas el sistema
  tendría que inventarse una, y una línea inventada que no cruza la vía
  produce un aforo de cero sin avisar de nada.
*/

import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Page } from '../components/Page';
import { ProjectPicker } from '../components/ProjectPicker';
import {
  Button,
  Card,
  ConfirmDialog,
  EmptyState,
  IconButton,
  Notice,
  TextField,
} from '../components/ui';
import { IconClose } from '../components/Icons';
import {
  useCreateLane,
  useDeleteLane,
  useLanes,
  useRenameLane,
  useStartCounting,
  useVideos,
} from '../lib/queries';
import { useProjectParam } from '../lib/useProjectParam';
import { errorMessage, fetchImage, heatmapUrl, snapshotUrl } from '../lib/api';
import { plural } from '../lib/format';
import type { Lane, Point } from '../lib/types';

/* Colores de carril: se dibujan sobre el video, no sobre la interfaz, así
   que no salen de los tokens de tema. Son tonos saturados que destacan
   contra el asfalto en cualquier iluminación. */
const LANE_COLORS = ['#ff5470', '#2dd4ff', '#ffd23f', '#7cff6b', '#c77dff', '#ff9f45'];
const laneColor = (i: number) => LANE_COLORS[i % LANE_COLORS.length];

/** Vector unitario hacia el lado que el backend clasifica como "Entrada". */
function entradaDirection(p1: Point, p2: Point): [number, number] {
  const lx = p2[0] - p1[0];
  const ly = p2[1] - p1[1];
  const len = Math.hypot(lx, ly) || 1;
  const perp: [number, number] = [-ly / len, lx / len];
  const cross = perp[0] * ly - perp[1] * lx;
  return cross > 0 ? perp : [-perp[0], -perp[1]];
}

/**
 * Revisa que la línea recién dibujada sirva para contar.
 *
 * Los dos errores que de verdad arruinan un aforo:
 *  · Línea demasiado corta: los vehículos pasan por los lados sin tocarla.
 *  · Línea paralela al tránsito: el vehículo avanza A LO LARGO de ella en
 *    vez de cruzarla, así que casi nunca dispara un conteo.
 *
 * Se avisa pero no se bloquea: puede haber escenas donde el usuario sepa
 * algo que esta comprobación no.
 */
function validarLinea(p1: Point, p2: Point, canvasWidth: number, hasHeatmap: boolean): string[] {
  const problemas: string[] = [];
  const largo = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]);
  const pctAncho = (largo / canvasWidth) * 100;

  if (pctAncho < 15) {
    problemas.push(
      `La línea mide solo ${Math.round(pctAncho)} % del ancho de la imagen. Si no cubre el carril completo, los vehículos pasan por los lados sin contarse.`,
    );
  }

  if (hasHeatmap) {
    const angulo = Math.abs((Math.atan2(p2[1] - p1[1], p2[0] - p1[0]) * 180) / Math.PI) % 180;
    if (angulo < 25 || angulo > 155) {
      problemas.push(
        'La línea quedó casi horizontal. Si el tránsito también circula en horizontal, los vehículos avanzan a lo largo de ella y no la cruzan. Activa "Ver por dónde pasan los vehículos" y dibújala atravesando ese rastro.',
      );
    }
  }

  return problemas;
}

export default function Calibrar() {
  const { projectId, projects, setProjectId } = useProjectParam();

  const { data: lanes } = useLanes(projectId);
  const { data: jobs } = useVideos(projectId ?? undefined);
  const createLane = useCreateLane(projectId ?? 0);
  const renameLane = useRenameLane(projectId ?? 0);
  const removeLane = useDeleteLane(projectId ?? 0);
  const startCounting = useStartCounting();

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [frame, setFrame] = useState<HTMLImageElement | null>(null);
  const [heat, setHeat] = useState<HTMLImageElement | null>(null);
  const [showHeat, setShowHeat] = useState(false);
  const [frameError, setFrameError] = useState<string | null>(null);
  const [loadingFrame, setLoadingFrame] = useState(false);

  const [drawing, setDrawing] = useState(false);
  const [points, setPoints] = useState<Point[]>([]);
  const [newName, setNewName] = useState('');
  const [warnings, setWarnings] = useState<string[]>([]);
  const [hint, setHint] = useState('Elige una intersección arriba para cargar un cuadro del video.');
  const [toDelete, setToDelete] = useState<Lane | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  /* --- Carga del cuadro y del rastro de movimiento --------------------- */

  useEffect(() => {
    // Al cambiar de intersección se limpia todo el estado de dibujo: de lo
    // contrario quedaban puntos de la escena anterior sobre el cuadro nuevo.
    setPoints([]);
    setDrawing(false);
    setWarnings([]);
    setHeat(null);
    setShowHeat(false);

    if (projectId === null) {
      setFrame(null);
      setFrameError(null);
      setHint('Elige una intersección arriba para cargar un cuadro del video.');
      return;
    }

    let cancelled = false;
    setLoadingFrame(true);
    setFrameError(null);
    setHint('Cargando un cuadro del video…');

    fetchImage(snapshotUrl(projectId))
      .then((img) => {
        if (cancelled) return;
        setFrame(img);
        setHint('Presiona "Nuevo carril" y marca dos puntos donde cruzan los vehículos.');
        // El rastro es opcional: si no hay conteos previos no existe, y la
        // calibración a mano sigue siendo posible.
        return fetchImage(heatmapUrl(projectId))
          .then((h) => !cancelled && setHeat(h))
          .catch(() => undefined);
      })
      .catch((e) => {
        if (cancelled) return;
        setFrame(null);
        setFrameError(errorMessage(e));
      })
      .finally(() => !cancelled && setLoadingFrame(false));

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  /* --- Dibujo del lienzo ------------------------------------------------ */

  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext('2d');
    if (!canvas || !ctx || !frame) return;

    canvas.width = frame.naturalWidth;
    canvas.height = frame.naturalHeight;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(frame, 0, 0, canvas.width, canvas.height);

    // El rastro va encima del cuadro y debajo de las líneas, para poder
    // juzgar si la línea cruza el tránsito o corre a lo largo de él.
    if (showHeat && heat) {
      ctx.globalAlpha = 0.55;
      ctx.drawImage(heat, 0, 0, canvas.width, canvas.height);
      ctx.globalAlpha = 1;
    }

    const drawArrow = (from: Point, dir: [number, number], color: string) => {
      const len = 26;
      const to: Point = [from[0] + dir[0] * len, from[1] + dir[1] * len];
      ctx.strokeStyle = color;
      ctx.fillStyle = color;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(from[0], from[1]);
      ctx.lineTo(to[0], to[1]);
      ctx.stroke();
      const angle = Math.atan2(dir[1], dir[0]);
      ctx.beginPath();
      ctx.moveTo(to[0], to[1]);
      ctx.lineTo(to[0] - 8 * Math.cos(angle - 0.4), to[1] - 8 * Math.sin(angle - 0.4));
      ctx.lineTo(to[0] - 8 * Math.cos(angle + 0.4), to[1] - 8 * Math.sin(angle + 0.4));
      ctx.closePath();
      ctx.fill();
    };

    const drawLine = (p1: Point, p2: Point, color: string, label: string | null) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.beginPath();
      ctx.moveTo(p1[0], p1[1]);
      ctx.lineTo(p2[0], p2[1]);
      ctx.stroke();

      for (const p of [p1, p2]) {
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(p[0], p[1], 5, 0, Math.PI * 2);
        ctx.fill();
      }

      const mid: Point = [(p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2];
      drawArrow(mid, entradaDirection(p1, p2), color);

      if (label) {
        ctx.font = 'bold 14px sans-serif';
        // Fondo opaco tras el texto: sobre asfalto claro un rótulo sin
        // respaldo se vuelve ilegible.
        ctx.fillStyle = 'rgba(0,0,0,0.8)';
        ctx.fillRect(mid[0] + 6, mid[1] - 18, ctx.measureText(label).width + 10, 20);
        ctx.fillStyle = color;
        ctx.fillText(label, mid[0] + 11, mid[1] - 3);
      }
    };

    (lanes ?? []).forEach((lane, i) =>
      drawLine(lane.points[0], lane.points[1], laneColor(i), lane.name),
    );

    if (points.length === 1) {
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.arc(points[0][0], points[0][1], 5, 0, Math.PI * 2);
      ctx.fill();
    } else if (points.length === 2) {
      drawLine(points[0], points[1], '#ffffff', null);
    }
  }, [frame, heat, showHeat, lanes, points]);

  useEffect(redraw, [redraw]);

  function handleCanvasClick(e: React.MouseEvent<HTMLCanvasElement>) {
    if (!drawing || !frame) return;
    const canvas = canvasRef.current!;
    const rect = canvas.getBoundingClientRect();
    const point: Point = [
      ((e.clientX - rect.left) * canvas.width) / rect.width,
      ((e.clientY - rect.top) * canvas.height) / rect.height,
    ];
    const next = [...points, point];
    setPoints(next);

    if (next.length === 2) {
      setDrawing(false);
      setWarnings(validarLinea(next[0], next[1], canvas.width, heat !== null));
      setNewName(`Carril ${(lanes?.length ?? 0) + 1}`);
      setHint('Ponle nombre al carril y guárdalo.');
      // El foco viaja al campo que sigue, para poder terminar sin el ratón.
      setTimeout(() => {
        nameRef.current?.focus();
        nameRef.current?.select();
      }, 0);
    } else {
      setHint('Ahora marca el segundo punto, al otro lado del carril.');
    }
  }

  async function saveLane() {
    if (points.length !== 2 || !newName.trim() || projectId === null) return;
    await createLane.mutateAsync({
      name: newName.trim(),
      points: [points[0], points[1]],
    });
    setPoints([]);
    setNewName('');
    setWarnings([]);
    setHint('Carril guardado. Puedes agregar otro o editar los que ya existen.');
  }

  const awaiting = (jobs ?? []).filter((j) => j.status === 'awaiting_calibration');
  const laneCount = lanes?.length ?? 0;
  const canStart = awaiting.length > 0 && laneCount > 0;

  return (
    <Page
      title="Calibrar carriles"
      subtitle="Dibuja la línea justo donde cruzan los vehículos"
      projectScoped
    >
      <div className="page-controls">
        <ProjectPicker projects={projects} value={projectId} onChange={setProjectId} />
      </div>

      <div className="calib-layout">
        <div>
          <div className="canvas-wrap">
            <canvas
              ref={canvasRef}
              width={640}
              height={360}
              className={drawing ? 'is-drawing' : undefined}
              onClick={handleCanvasClick}
            />
          </div>

          <div className="canvas-tools">
            <label className="toggle-heat">
              <input
                type="checkbox"
                checked={showHeat}
                disabled={heat === null}
                onChange={(e) => setShowHeat(e.target.checked)}
              />
              <span>Ver por dónde pasan los vehículos</span>
            </label>
            <span className="tool-hint">
              Dibuja la línea <strong>cruzando</strong> ese rastro, no a lo largo de él.
            </span>
          </div>

          {/* Región educada: el estado del lienzo cambia sin que se pueda
              ver el cursor, así que hay que anunciarlo. */}
          <p className="calib-hint" role="status" aria-live="polite">
            {loadingFrame ? 'Cargando un cuadro del video…' : hint}
          </p>

          {frameError && (
            <div className="notice-stack" style={{ marginTop: 'var(--space-3)' }}>
              <Notice title="No se pudo cargar el cuadro del video">
                {frameError} Sube al menos un video a esta intersección antes de calibrar.{' '}
                <Link to={projectId ? `/subir?project=${projectId}` : '/subir'}>Ir a subir</Link>
              </Notice>
            </div>
          )}

          {warnings.length > 0 && (
            <div className="notice-stack" style={{ marginTop: 'var(--space-3)' }}>
              {warnings.map((w, i) => (
                /* Ámbar y no rojo: es una advertencia sobre la calidad de la
                   medición, no un error que impida guardar. */
                <Notice key={i} tone="warning" title="Revisa esta línea">
                  {w}
                </Notice>
              ))}
            </div>
          )}
        </div>

        <Card className="lane-panel">
          <h2>Carriles</h2>

          <div className="lane-list">
            {laneCount === 0 && (
              <EmptyState
                title="Sin carriles todavía"
                body="Un carril es la línea que los vehículos tienen que cruzar para ser contados."
              />
            )}
            {lanes?.map((lane, i) => (
              <div className="lane-item" key={lane.id}>
                <span className="lane-swatch" style={{ background: laneColor(i) }} />
                <input
                  className="lane-name-input"
                  defaultValue={lane.name}
                  aria-label={`Nombre del carril ${lane.name}`}
                  onBlur={(e) => {
                    const name = e.target.value.trim();
                    if (name && name !== lane.name) renameLane.mutate({ laneId: lane.id, name });
                  }}
                />
                <IconButton
                  label={`Eliminar el carril ${lane.name}`}
                  tone="danger"
                  onClick={() => setToDelete(lane)}
                >
                  <IconClose />
                </IconButton>
              </div>
            ))}
          </div>

          <Button
            variant="primary"
            block
            disabled={!frame}
            onClick={() => {
              setDrawing(true);
              setPoints([]);
              setWarnings([]);
              setHint('Marca el primer punto de la línea, a un lado del carril.');
            }}
          >
            Nuevo carril
          </Button>

          {points.length === 2 && (
            <div className="new-lane-form rise">
              <TextField
                label="Nombre"
                ref={nameRef}
                value={newName}
                placeholder="Acceso Norte"
                onChange={(e) => setNewName(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    void saveLane();
                  }
                }}
              />
              <Button
                variant="primary"
                onClick={() => void saveLane()}
                disabled={createLane.isPending || !newName.trim()}
              >
                Guardar
              </Button>
            </div>
          )}

          {createLane.isError && (
            <div style={{ marginTop: 'var(--space-3)' }}>
              <Notice title="No se pudo guardar el carril">{errorMessage(createLane.error)}</Notice>
            </div>
          )}

          {/* El botón de arrancar solo aparece cuando hay algo que arrancar:
              carriles definidos Y videos esperando. Así no se puede lanzar
              un conteo sobre una línea que no existe. */}
          {canStart && (
            <div className="start-counting">
              <p className="sc-info">
                {plural(awaiting.length, 'video esperando', 'videos esperando')} y{' '}
                {plural(laneCount, 'carril definido', 'carriles definidos')}.
              </p>
              <Button
                variant="primary"
                block
                disabled={startCounting.isPending}
                onClick={() => projectId !== null && startCounting.mutate(projectId)}
              >
                {startCounting.isPending ? 'Iniciando…' : 'Empezar conteo'}
              </Button>
            </div>
          )}

          {startCounting.isSuccess && (
            <div style={{ marginTop: 'var(--space-3)' }}>
              <Notice tone="good" title="Conteo iniciado">
                Puedes seguir el avance en{' '}
                <Link to={projectId ? `/subir?project=${projectId}` : '/subir'}>Subir videos</Link>.
              </Notice>
            </div>
          )}
          {startCounting.isError && (
            <div style={{ marginTop: 'var(--space-3)' }}>
              <Notice title="No se pudo empezar el conteo">{errorMessage(startCounting.error)}</Notice>
            </div>
          )}
        </Card>
      </div>

      <ConfirmDialog
        open={toDelete !== null}
        title="¿Eliminar este carril?"
        body={
          toDelete
            ? `Se borra la línea "${toDelete.name}". Los conteos que ya registró se conservan en el histórico.`
            : ''
        }
        confirmLabel="Eliminar carril"
        destructive
        onConfirm={() => {
          if (toDelete) removeLane.mutate(toDelete.id);
          setToDelete(null);
        }}
        onCancel={() => setToDelete(null)}
      />
    </Page>
  );
}
