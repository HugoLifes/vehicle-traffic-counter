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
import { Link, useSearchParams } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
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
import { VideoWorkspace, laneColor, zoneColor } from '../components/VideoWorkspace';
import {
  useCreateLane,
  useDeleteLane,
  useLanes,
  useRenameLane,
  useStartCounting,
  useVideos,
  useCalibrationStatus,
  useRecount,
  useCreateZone,
  useDeleteZone,
  useRenameZone,
  useZones,
} from '../lib/queries';
import { useProjectParam } from '../lib/useProjectParam';
import { errorMessage, fetchImage, heatmapUrl, listVideoSegments } from '../lib/api';
import { plural } from '../lib/format';
import type { FuenteVideo, Lane, Point, Zone } from '../lib/types';

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
  const { projectId, projects } = useProjectParam();

  const { data: lanes } = useLanes(projectId);
  const { data: zones } = useZones(projectId);
  const createZone = useCreateZone(projectId ?? 0);
  const renameZone = useRenameZone(projectId ?? 0);
  const removeZone = useDeleteZone(projectId ?? 0);
  const { data: calibStatus } = useCalibrationStatus(projectId);
  const recontar = useRecount();
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

  /*
    El segmento y la fuente se leen de la URL en la primera carga. Es lo
    que hace que "Revisar cuadro a cuadro" desde la cola aterrice en el
    video correcto y ya con las detecciones puestas, en vez de dejar al
    usuario buscándolo entre los segmentos.
  */
  const [params] = useSearchParams();
  const [jobId, setJobId] = useState<number | null>(null);
  const [fuente, setFuente] = useState<FuenteVideo>(
    params.get('ver') === 'procesado' ? 'procesado' : 'original',
  );
  const [heatmap, setHeatmap] = useState<HTMLImageElement | null>(null);
  const [showHeatmap, setShowHeatmap] = useState(false);
  const [verDetecciones, setVerDetecciones] = useState(false);

  const [drawMode, setDrawMode] = useState(false);
  /* 'linea' dibuja una línea de conteo (2 puntos); 'zona' dibuja el área de
     una calzada (3 o más). Comparten el mismo lienzo y el mismo arreglo de
     puntos porque para el usuario es el mismo gesto: marcar sobre el video. */
  const [drawKind, setDrawKind] = useState<'linea' | 'zona'>('linea');
  const [points, setPoints] = useState<Point[]>([]);
  const [zoneToDelete, setZoneToDelete] = useState<Zone | null>(null);
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
    if (!segments || !segments.length) {
      setJobId(null);
    } else {
      const pedido = Number(params.get('job'));
      const existe = segments.some((s) => s.job_id === pedido);
      setJobId(existe ? pedido : segments[0].job_id);
    }
    setPoints([]);
    setDrawMode(false);
    setWarnings([]);
    setHint(null);
  }, [segments, params]);

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

  /* El ancho real del video lo descubre la mesa al cargar el primer
     cuadro; la validación de la línea lo necesita para saber qué
     proporción de la calzada cubre. */
  const [anchoVideo, setAnchoVideo] = useState<number | null>(null);

  const onCanvasPoint = useCallback(
    (p: Point) => {
      // Una zona acumula vértices sin tope: el usuario decide cuándo la
      // cierra. Solo se le exige que tenga al menos 3 para encerrar un área.
      if (drawKind === 'zona') {
        setPoints((prev) => [...prev, p]);
        setHint(
          points.length + 1 >= 3
            ? 'Sigue marcando el contorno, o cierra la zona cuando ya rodee la calzada.'
            : 'Marca las esquinas de la calzada. Con 3 puntos ya se puede cerrar.',
        );
        return;
      }
      setPoints((prev) => {
        if (prev.length >= 2) return prev;
        const next = [...prev, p];
        if (next.length === 2 && segment) {
          setDrawMode(false);
          setWarnings(validarLinea(next[0], next[1], anchoVideo ?? 640, heatmap !== null));
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
    [segment, heatmap, lanes, drawKind, points.length],
  );

  async function saveLane() {
    if (points.length !== 2 || !newName.trim() || projectId === null) return;
    await createLane.mutateAsync({ name: newName.trim(), points: [points[0], points[1]] });
    setPoints([]);
    setNewName('');
    setWarnings([]);
    setHint('Carril guardado. Puedes agregar otro o editar los que ya existen.');
  }

  async function saveZone() {
    if (points.length < 3 || !newName.trim() || projectId === null) return;
    await createZone.mutateAsync({ name: newName.trim(), points, kind: 'calzada' });
    setPoints([]);
    setNewName('');
    setDrawKind('linea');
    setHint('Zona guardada. Los cruces que ocurran dentro se le atribuyen a ella.');
  }

  function cancelarDibujo() {
    setPoints([]);
    setDrawMode(false);
    setDrawKind('linea');
    setWarnings([]);
    setHint(null);
  }

  const awaiting = (jobs ?? []).filter((j) => j.status === 'awaiting_calibration');
  const otrosProyectos = (projects ?? []).filter((p) => p.id !== projectId);
  const laneCount = lanes?.length ?? 0;
  const sinVideos = projectId !== null && !cargandoVideos && (segments?.length ?? 0) === 0;

  return (
    <>

      {sinVideos && (
        <EmptyState
          title="Esta intersección todavía no tiene videos"
          body="Para calibrar hace falta la grabación: las líneas se dibujan sobre el video real, no sobre un plano."
          action={
            <Link className="btn btn-primary" to={`/proyecto/${projectId}/subir`}>
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
              zones={zones ?? []}
              drawing={points}
              drawMode={drawMode}
              drawKind={drawKind}
              onCanvasPoint={onCanvasPoint}
              showDetections={verDetecciones}
              heatmap={heatmap}
              showHeatmap={showHeatmap}
              fuente={fuente}
              onFuenteChange={setFuente}
              onTamano={(a) => setAnchoVideo(a)}
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
              <label className="toggle-heat">
                <input
                  type="checkbox"
                  checked={verDetecciones}
                  disabled={fuente === 'procesado'}
                  onChange={(e) => setVerDetecciones(e.target.checked)}
                />
                <span>Ver lo que detecta la IA ahora</span>
              </label>
              <span className="tool-hint">
                {verDetecciones
                  ? /* Se explica el gris porque es el dato más útil de todos:
                       una caja descartada sobre la calzada significa que la
                       zona está mal dibujada, y se ve antes de reprocesar. */
                    'Verde: detección firme. Naranja: confianza baja. Gris punteado: descartada por quedar fuera de las zonas. Pausa el video para calcularlas.'
                  : heatmap === null
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
            </div>

            {/* Reutilizar la calibración de otra intersección vive en el
                Resumen del proyecto, no aquí: es una acción sobre el
                proyecto entero y no parte de dibujar líneas. Estaba en los
                dos sitios a la vez, con dos nombres y dos estilos
                distintos; aquí queda el camino, no una segunda copia. */}
            {laneCount === 0 && (zones?.length ?? 0) === 0 && otrosProyectos.length > 0 && (
              <p className="sc-info">
                ¿Ya calibraste esta cámara antes? Puedes{' '}
                <Link to={`/proyecto/${projectId}`}>
                  copiar la calibración de otra intersección
                </Link>{' '}
                en vez de volver a dibujarla.
              </p>
            )}

            <div className="lane-list">
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

            {drawKind === 'zona' ? (
              <>
                <p className="sc-info">
                  {points.length < 3
                    ? `Marca las esquinas de la calzada sobre el video (${points.length}/3 mínimo).`
                    : `${points.length} puntos marcados. Ponle nombre y cierra la zona.`}
                </p>
                {points.length >= 3 && (
                  <div className="new-lane-form rise">
                    <TextField
                      label="Nombre de la zona"
                      ref={nameRef}
                      value={newName}
                      placeholder="Calzada norte"
                      onChange={(e) => setNewName(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                          e.preventDefault();
                          void saveZone();
                        }
                      }}
                    />
                    <Button
                      variant="primary"
                      onClick={() => void saveZone()}
                      disabled={createZone.isPending || !newName.trim()}
                    >
                      Cerrar zona
                    </Button>
                  </div>
                )}
                <Button block onClick={cancelarDibujo} style={{ marginTop: 'var(--space-2)' }}>
                  Cancelar
                </Button>
                {createZone.isError && (
                  <div style={{ marginTop: 'var(--space-3)' }}>
                    <Notice title="No se pudo guardar la zona">
                      {errorMessage(createZone.error)}
                    </Notice>
                  </div>
                )}
              </>
            ) : points.length === 2 ? (
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
              <>
                <Button
                  variant="primary"
                  block
                  disabled={!segment || fuente === 'procesado'}
                  onClick={() => {
                    setDrawMode(true);
                    setPoints([]);
                    setWarnings([]);
                    setHint('Pausa el video donde se vea bien el tránsito y marca el primer punto.');
                  }}
                >
                  Nuevo carril
                </Button>
                {fuente === 'procesado' && (
                  /* Un control deshabilitado sin explicación es una
                     puerta cerrada sin cartel: aquí se dice por qué y
                     cómo abrirla. */
                  <p className="sc-info" style={{ marginTop: 'var(--space-2)' }}>
                    Los carriles se dibujan sobre el video original. La versión con detecciones ya
                    tiene las líneas quemadas en la imagen, así que unas nuevas no coincidirían con
                    lo que se ve. Cambia a <strong>Original</strong> para seguir calibrando.
                  </p>
                )}
              </>
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
            {/* La pregunta que esto contesta es "¿el video ya está contado
                con estas líneas o con las de antes?". Editar la geometría
                no cambia por sí solo ningún conteo ya guardado, y sin este
                aviso no había forma de notarlo. */}
            {(calibStatus?.stale ?? 0) > 0 && laneCount > 0 && (
              <div className="start-counting">
                <Notice tone="warning" title="Los conteos son de una calibración anterior">
                  {plural(
                    calibStatus?.stale ?? 0,
                    'video ya contado se procesó',
                    'videos ya contados se procesaron',
                  )}{' '}
                  antes del último cambio de líneas o zonas, así que sus números y su video
                  anotado siguen siendo los de la geometría vieja.
                </Notice>
                <Button
                  variant="primary"
                  block
                  disabled={recontar.isPending}
                  style={{ marginTop: 'var(--space-3)' }}
                  onClick={() => projectId !== null && recontar.mutate(projectId)}
                >
                  {recontar.isPending ? 'Reencolando…' : 'Volver a contar con estas líneas'}
                </Button>
                {recontar.isError && (
                  <div style={{ marginTop: 'var(--space-2)' }}>
                    <Notice title="No se pudo reencolar">{errorMessage(recontar.error)}</Notice>
                  </div>
                )}
              </div>
            )}

            {(calibStatus?.stale ?? 0) === 0 &&
              (calibStatus?.awaiting ?? 0) === 0 &&
              laneCount > 0 &&
              (jobs?.some((j) => j.status === 'done') ?? false) && (
                <div className="start-counting">
                  <Notice tone="good" title="Los conteos están al día">
                    Todos los videos se contaron con las líneas y zonas que ves ahora.
                  </Notice>
                </div>
              )}

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
                  <Link to={`/proyecto/${projectId}/subir`}>Subir videos</Link>.
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

          {/* Las zonas van en su propia tarjeta y no mezcladas con los
              carriles: son cosas distintas y confundirlas es justo el
              error que llevó a dibujar líneas paralelas a la vía. */}
          <Card className="lane-panel zone-panel">
            <h2>Zonas de calzada</h2>
            <p className="sc-info">
              La línea dice <strong>dónde</strong> se cuenta; la zona dice{' '}
              <strong>cuál calzada</strong> es. En perspectiva las dos calzadas quedan una encima de
              la otra y una sola línea cruza ambas — sin zonas no hay forma de separar los sentidos.
            </p>

            <div className="lane-list">
              {(zones?.length ?? 0) === 0 && (
                <EmptyState
                  title="Sin zonas todavía"
                  body="Rodea cada calzada con un polígono. Lo que quede fuera deja de contarse."
                />
              )}
              {zones?.map((zone, i) => (
                <div className="lane-item" key={zone.id}>
                  <span className="lane-swatch" style={{ background: zoneColor(i, zone.kind) }} />
                  <input
                    className="lane-name-input"
                    defaultValue={zone.name}
                    aria-label={`Nombre de la zona ${zone.name}`}
                    onBlur={(e) => {
                      const name = e.target.value.trim();
                      if (name && name !== zone.name) renameZone.mutate({ zoneId: zone.id, name });
                    }}
                  />
                  <IconButton
                    label={`Eliminar la zona ${zone.name}`}
                    tone="danger"
                    onClick={() => setZoneToDelete(zone)}
                  >
                    <IconClose />
                  </IconButton>
                </div>
              ))}
            </div>

            {drawKind !== 'zona' && points.length === 0 && (
              <Button
                block
                disabled={!segment || fuente === 'procesado'}
                onClick={() => {
                  setDrawKind('zona');
                  setDrawMode(true);
                  setPoints([]);
                  setWarnings([]);
                  setNewName(`Calzada ${(zones?.length ?? 0) + 1}`);
                  setHint('Marca las esquinas de la calzada. Con 3 puntos ya se puede cerrar.');
                }}
              >
                Nueva zona
              </Button>
            )}
          </Card>
        </div>
      )}

      <ConfirmDialog
        open={zoneToDelete !== null}
        title="¿Eliminar esta zona?"
        body={
          zoneToDelete
            ? `Se borra el área "${zoneToDelete.name}". Los cruces que ya se le atribuyeron se conservan en el histórico.`
            : ''
        }
        confirmLabel="Eliminar zona"
        destructive
        onConfirm={() => {
          if (zoneToDelete) removeZone.mutate(zoneToDelete.id);
          setZoneToDelete(null);
        }}
        onCancel={() => setZoneToDelete(null)}
      />

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
    </>
  );
}
