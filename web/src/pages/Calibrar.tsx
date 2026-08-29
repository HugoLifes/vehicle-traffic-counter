/*
  Calibración de carriles.

  La pantalla se organiza alrededor de la mesa de trabajo: el video con
  sus controles ocupa el lugar principal y el panel de carriles va al
  lado. Antes el lienzo era un cuadro fijo colgado bajo la barra de
  pasos, lo que lo hacía parecer un accesorio de la guía en vez de la
  herramienta central de la pantalla — que es lo que realmente es.

  Calibrar va ANTES de contar a propósito: sin líneas definidas el
  sistema tendría que inventarse una, y una línea inventada que no cruza
  la vía produce un aforo de cero sin avisar de nada.
*/

import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
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
import { VideoWorkspace, laneColor } from '../components/VideoWorkspace';
import {
  useCreateLane,
  useDeleteLane,
  useLanes,
  useRenameLane,
  useStartCounting,
  useVideos,
} from '../lib/queries';
import { useProjectParam } from '../lib/useProjectParam';
import { errorMessage, fetchImage, heatmapUrl, listVideoSegments } from '../lib/api';
import { plural } from '../lib/format';
import type { Lane, Point } from '../lib/types';

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
function validarLinea(p1: Point, p2: Point, anchoVideo: number, hayRastro: boolean): string[] {
  const problemas: string[] = [];
  const largo = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]);
  const pctAncho = (largo / anchoVideo) * 100;

  if (pctAncho < 15) {
    problemas.push(
      `La línea mide solo ${Math.round(pctAncho)} % del ancho de la imagen. Si no cubre el carril completo, los vehículos pasan por los lados sin contarse.`,
    );
  }

  if (hayRastro) {
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

  const { data: segments, isLoading: cargandoVideos } = useQuery({
    queryKey: ['segments', projectId],
    queryFn: () => listVideoSegments(projectId as number),
    enabled: projectId !== null,
  });

  const [jobId, setJobId] = useState<number | null>(null);
  const [heatmap, setHeatmap] = useState<HTMLImageElement | null>(null);
  const [showHeatmap, setShowHeatmap] = useState(false);

  const [drawMode, setDrawMode] = useState(false);
  const [points, setPoints] = useState<Point[]>([]);
  const [newName, setNewName] = useState('');
  const [warnings, setWarnings] = useState<string[]>([]);
  const [hint, setHint] = useState<string | null>(null);
  const [toDelete, setToDelete] = useState<Lane | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  const segment = segments?.find((s) => s.job_id === jobId) ?? null;

  // Al llegar la lista de videos se elige el primero; al cambiar de
  // intersección se descarta lo que hubiera a medio dibujar, para no
  // arrastrar puntos de una escena a otra.
  useEffect(() => {
    setJobId(segments && segments.length ? segments[0].job_id : null);
    setPoints([]);
    setDrawMode(false);
    setWarnings([]);
    setHint(null);
  }, [segments]);

  // El rastro de movimiento es opcional: si el proyecto no tiene conteos
  // previos no existe, y calibrar a mano sigue siendo posible.
  useEffect(() => {
    setHeatmap(null);
    setShowHeatmap(false);
    if (projectId === null) return;
    let cancelled = false;
    fetchImage(heatmapUrl(projectId))
      .then((img) => !cancelled && setHeatmap(img))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const onCanvasPoint = useCallback(
    (p: Point) => {
      setPoints((prev) => {
        if (prev.length >= 2) return prev;
        const next = [...prev, p];
        if (next.length === 2 && segment) {
          setDrawMode(false);
          setWarnings(validarLinea(next[0], next[1], segment.ancho, heatmap !== null));
          setNewName(`Carril ${(lanes?.length ?? 0) + 1}`);
          setHint('Ponle nombre al carril y guárdalo.');
          setTimeout(() => {
            nameRef.current?.focus();
            nameRef.current?.select();
          }, 0);
        } else {
          setHint('Ahora marca el segundo punto, al otro lado del carril.');
        }
        return next;
      });
    },
    [segment, heatmap, lanes],
  );

  async function saveLane() {
    if (points.length !== 2 || !newName.trim() || projectId === null) return;
    await createLane.mutateAsync({ name: newName.trim(), points: [points[0], points[1]] });
    setPoints([]);
    setNewName('');
    setWarnings([]);
    setHint('Carril guardado. Puedes agregar otro o editar los que ya existen.');
  }

  function cancelarDibujo() {
    setPoints([]);
    setDrawMode(false);
    setWarnings([]);
    setHint(null);
  }

  const awaiting = (jobs ?? []).filter((j) => j.status === 'awaiting_calibration');
  const laneCount = lanes?.length ?? 0;
  const sinVideos = projectId !== null && !cargandoVideos && (segments?.length ?? 0) === 0;

  return (
    <Page
      title="Calibrar carriles"
      subtitle="Recorre el video y dibuja la línea donde cruzan los vehículos"
      projectScoped
    >
      <div className="page-controls">
        <ProjectPicker projects={projects} value={projectId} onChange={setProjectId} />
      </div>

      {sinVideos && (
        <EmptyState
          title="Esta intersección todavía no tiene videos"
          body="Para calibrar hace falta la grabación: las líneas se dibujan sobre el video real, no sobre un plano."
          action={
            <Link className="btn btn-primary" to={`/subir?project=${projectId}`}>
              Subir videos
            </Link>
          }
        />
      )}

      {projectId === null && (
        <EmptyState
          title="Elige una intersección"
          body="Los carriles se definen por intersección y los comparten todos sus videos."
        />
      )}

      {projectId !== null && !sinVideos && (
        <div className="calib-layout">
          <div className="calib-main">
            <h2 className="section-title">Mesa de trabajo</h2>

            <VideoWorkspace
              segments={segments ?? []}
              jobId={jobId}
              onJobChange={setJobId}
              lanes={lanes ?? []}
              drawing={points}
              drawMode={drawMode}
              onCanvasPoint={onCanvasPoint}
              heatmap={heatmap}
              showHeatmap={showHeatmap}
            />

            <div className="canvas-tools">
              <label className="toggle-heat">
                <input
                  type="checkbox"
                  checked={showHeatmap}
                  disabled={heatmap === null}
                  onChange={(e) => setShowHeatmap(e.target.checked)}
                />
                <span>Ver por dónde pasan los vehículos</span>
              </label>
              <span className="tool-hint">
                {heatmap === null
                  ? 'El rastro aparece cuando la intersección ya tiene conteos.'
                  : 'Dibuja la línea cruzando ese rastro, no a lo largo de él.'}
              </span>
            </div>

            {/* Región educada: el estado del dibujo cambia sin que se pueda
                ver el cursor, así que hay que anunciarlo. */}
            <div role="status" aria-live="polite">
              {hint && <p className="calib-hint">{hint}</p>}
            </div>

            {warnings.length > 0 && (
              <div className="notice-stack" style={{ marginTop: 'var(--space-3)' }}>
                {warnings.map((w, i) => (
                  /* Ámbar y no rojo: es una advertencia sobre la calidad de
                     la medición, no un error que impida guardar. */
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

            {points.length === 2 ? (
              <>
                <div className="new-lane-form rise">
                  <TextField
                    label="Nombre del carril"
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
                {/* Salida del error más probable: marcar mal los dos puntos.
                    Sin esto, la única forma de deshacer un clic torcido era
                    guardar la línea mala y borrarla después. */}
                <Button block onClick={cancelarDibujo} style={{ marginTop: 'var(--space-2)' }}>
                  Volver a marcar la línea
                </Button>
              </>
            ) : drawMode ? (
              <>
                <p className="sc-info">
                  Marca {points.length === 0 ? 'el primer punto' : 'el segundo punto'} sobre el
                  video, a un lado del carril.
                </p>
                <Button block onClick={cancelarDibujo}>
                  Cancelar
                </Button>
              </>
            ) : (
              <Button
                variant="primary"
                block
                disabled={!segment}
                onClick={() => {
                  setDrawMode(true);
                  setPoints([]);
                  setWarnings([]);
                  setHint('Pausa el video donde se vea bien el tránsito y marca el primer punto.');
                }}
              >
                Nuevo carril
              </Button>
            )}

            {createLane.isError && (
              <div style={{ marginTop: 'var(--space-3)' }}>
                <Notice title="No se pudo guardar el carril">
                  {errorMessage(createLane.error)}
                </Notice>
              </div>
            )}

            {/* El botón de arrancar solo aparece cuando hay algo que
                arrancar: carriles definidos Y videos esperando. Así no se
                puede lanzar un conteo sobre una línea que no existe. */}
            {awaiting.length > 0 && laneCount > 0 && (
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
                  <Link to={`/subir?project=${projectId}`}>Subir videos</Link>.
                </Notice>
              </div>
            )}
            {startCounting.isError && (
              <div style={{ marginTop: 'var(--space-3)' }}>
                <Notice title="No se pudo empezar el conteo">
                  {errorMessage(startCounting.error)}
                </Notice>
              </div>
            )}
          </Card>
        </div>
      )}

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
