/*
  Subida de videos (arrastrar y soltar o selector) y cola de procesamiento.

  Los archivos NO se suben al soltarlos: primero se arma una lista local
  donde se elige la intersección y la hora real de inicio de cada
  segmento, y todo se envía junto al confirmar. Esa hora es lo que ubica
  cada cruce en su intervalo (8:00–8:15, 8:15–8:30…), así que el reporte
  sale bien desde el primer momento y no como una corrección posterior.
*/

import { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Page } from '../components/Page';
import { ProjectPicker } from '../components/ProjectPicker';
import { Button, Card, EmptyState, IconButton, Notice, Pill } from '../components/ui';
import { IconClose, IconEye, IconTrash, IconUpload, IconVideo } from '../components/Icons';
import { useDeleteVideo, useStartCounting, useUploadVideos, useVideos } from '../lib/queries';
import { useProjectParam } from '../lib/useProjectParam';
import { errorMessage, frameUrl, videoUrl } from '../lib/api';
import {
  JOB_STATUS_LABEL,
  JOB_STATUS_TONE,
  fileExtension,
  formatSize,
  guessStartTime,
  plural,
  todayISO,
} from '../lib/format';
import type { VideoJob } from '../lib/types';
import { ConfirmDialog } from '../components/ui';

const ALLOWED = ['.mp4', '.avi', '.mov', '.mkv', '.webm', '.flv', '.wmv', '.m4v', '.mpg', '.mpeg'];

interface Pending {
  id: string;
  file: File;
  date: string;
  time: string;
}

interface Rejection {
  filename: string;
  reason: string;
}

/* --- Visor en vivo del procesamiento ------------------------------------
   Muestra el cuadro que la IA está analizando ahora mismo. Va a su propio
   ritmo (dos por segundo) para que se lea como video y no como
   diapositivas. */

function LiveView({ jobs }: { jobs: VideoJob[] }) {
  const [src, setSrc] = useState<string | null>(null);
  const [jobId, setJobId] = useState<number | null>(null);
  const urlRef = useRef<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    let inFlight = false;

    async function tick() {
      if (inFlight || document.hidden) return;
      inFlight = true;
      try {
        const res = await fetch('/api/videos/live-frame', { cache: 'no-store' });
        // 204 no es un error: significa que no hay nada procesándose.
        if (res.status === 204) {
          if (!cancelled) setSrc(null);
          return;
        }
        if (!res.ok) return;
        const url = URL.createObjectURL(await res.blob());
        if (cancelled) {
          URL.revokeObjectURL(url);
          return;
        }
        // Liberar el cuadro anterior; si no, la memoria del navegador crece
        // sin límite a dos imágenes por segundo.
        if (urlRef.current) URL.revokeObjectURL(urlRef.current);
        urlRef.current = url;
        setSrc(url);
        const id = res.headers.get('X-Job-Id');
        setJobId(id ? Number(id) : null);
      } catch {
        // Sin red se deja el último cuadro en pantalla en vez de parpadear.
      } finally {
        inFlight = false;
      }
    }

    void tick();
    const timer = window.setInterval(tick, 500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      if (urlRef.current) URL.revokeObjectURL(urlRef.current);
      urlRef.current = null;
    };
  }, []);

  if (!src) return null;
  const job = jobs.find((j) => j.id === jobId);

  return (
    <Card accent className="live-view rise">
      <div className="live-head">
        <h2 className="section-title" style={{ margin: 0 }}>
          Procesando ahora
        </h2>
        <Pill tone="warning" dot live>
          {job?.original_name ?? 'Procesando…'}
        </Pill>
      </div>
      <div className="live-stage">
        <img src={src} alt="Cuadro actual del video con las detecciones de la IA" />
      </div>
      <p className="live-hint">
        Lo que ves es el cuadro que la IA está analizando en este momento: una caja por vehículo, su
        identificador de seguimiento y las líneas de conteo.
      </p>
    </Card>
  );
}

/* --- Fila de la cola ------------------------------------------------------ */

function JobRow({
  job,
  projectId,
  onDelete,
}: {
  job: VideoJob;
  projectId: number | null;
  onDelete: (j: VideoJob) => void;
}) {
  const [open, setOpen] = useState(false);
  const [loop, setLoop] = useState(false);

  const pct = job.total_frames
    ? Math.min(100, Math.round((job.processed_frames / job.total_frames) * 100))
    : job.status === 'done'
      ? 100
      : 0;

  const format = fileExtension(job.original_name).replace('.', '').toUpperCase();
  const start = job.video_start_time ? job.video_start_time.slice(11, 19) : 'sin hora';

  return (
    <>
      <div className="job-row">
        <span className="job-icon">
          <IconVideo size={22} strokeWidth={1.6} />
        </span>
        <div className="job-info">
          <div className="job-name" title={job.original_name}>
            {job.original_name}
          </div>
          <div className="job-meta">
            {format} · {formatSize(job.size_bytes)} · inicio {start}
          </div>
        </div>

        <div
          className="job-progress"
          role="progressbar"
          aria-valuenow={pct}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-label={`Avance de ${job.original_name}`}
        >
          <div className="bar" style={{ scale: `${pct / 100} 1` }} />
        </div>

        {/* El estado se lleva en texto además del color de la pill. */}
        <Pill
          tone={JOB_STATUS_TONE[job.status]}
          dot
          live={job.status === 'processing'}
        >
          {job.status === 'error' && job.error
            ? `Error: ${job.error}`
            : JOB_STATUS_LABEL[job.status]}
        </Pill>

        {job.status === 'done' && (
          <IconButton
            label={open ? 'Ocultar el video con detecciones' : 'Ver el video con las detecciones'}
            tone="accent"
            aria-expanded={open}
            onClick={() => setOpen((v) => !v)}
          >
            <IconEye />
          </IconButton>
        )}

        <IconButton
          label={`Eliminar ${job.original_name}`}
          tone="danger"
          disabled={job.status === 'processing'}
          onClick={() => onDelete(job)}
        >
          <IconTrash strokeWidth={2} />
        </IconButton>
      </div>

      {open && (
        /*
          Vista rápida dentro de la cola: sirve para confirmar de un
          vistazo que el conteo hizo algo razonable. Para mirar de verdad
          —parar en el cuadro de un cruce y comprobar si se contó— está la
          mesa de trabajo, y por eso el enlace va aquí mismo.
        */
        <div className="job-player rise">
          <div className="jp-head">
            <span className="jp-title">{job.original_name}</span>
            <Pill tone="accent">Con detecciones</Pill>
          </div>
          {/* Controles nativos: dan pantalla completa, velocidad y volumen
              sin reconstruir nada. `loop` es lo único que el navegador no
              expone en su barra, así que se ofrece aparte.

              La portada sale del servidor de cuadros y no del propio
              video: con `preload="metadata"` el navegador no decodifica
              ninguna imagen, así que sin ella el reproductor se abre en
              negro y no se sabe si cargó o se rompió. Se toma un cuadro
              de la mitad, donde es más probable que haya tránsito que en
              el primer segundo. */}
          <video
            controls
            loop={loop}
            preload="metadata"
            poster={frameUrl(job.id, Math.floor((job.total_frames ?? 2) / 2), 'procesado')}
            src={videoUrl(job.id)}
          />
          <div className="jp-foot">
            <label className="jp-loop">
              <input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} />
              <span>Repetir en bucle</span>
            </label>
            <Link className="jp-link" to={`/calibrar?project=${projectId}&job=${job.id}&ver=procesado`}>
              Revisar cuadro a cuadro
            </Link>
          </div>
        </div>
      )}
    </>
  );
}

/* --- Página --------------------------------------------------------------- */

export default function Subir() {
  const { projectId, project, projects, setProjectId } = useProjectParam();
  // La cola se acota a la intersección elegida: con varios aforos en curso,
  // ver los videos de todos mezclados no ayuda a nadie.
  const { data: jobs } = useVideos(projectId ?? undefined, true);
  const upload = useUploadVideos();
  const remove = useDeleteVideo();
  const start = useStartCounting();

  const [pending, setPending] = useState<Pending[]>([]);
  const [rejections, setRejections] = useState<Rejection[]>([]);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);
  const [toDelete, setToDelete] = useState<VideoJob | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const selectorRef = useRef<HTMLDivElement>(null);

  const awaiting = (jobs ?? []).filter((j) => j.status === 'awaiting_calibration');

  function addFiles(files: File[]) {
    const rejected: Rejection[] = [];
    const accepted: Pending[] = [];

    for (const file of files) {
      const ext = fileExtension(file.name);
      if (!ALLOWED.includes(ext)) {
        rejected.push({
          filename: file.name,
          // El error dice cómo arreglarlo, no solo qué salió mal.
          reason: `El formato ${ext || 'de este archivo'} no se puede procesar. Usa MP4, AVI, MOV, MKV, WEBM, FLV, WMV, M4V o MPG.`,
        });
        continue;
      }
      accepted.push({
        id: `${file.name}-${file.size}-${Math.random().toString(36).slice(2)}`,
        file,
        date: todayISO(),
        time: guessStartTime(file.name) ?? '',
      });
    }

    if (rejected.length) setRejections((r) => [...r, ...rejected]);
    if (accepted.length) setPending((p) => [...p, ...accepted]);
  }

  async function confirmUpload() {
    if (projectId === null) {
      setProjectError('Elige a qué intersección pertenecen estos videos.');
      selectorRef.current?.querySelector('select')?.focus();
      return;
    }

    const form = new FormData();
    const startTimes: Record<string, string> = {};
    for (const entry of pending) {
      form.append('files', entry.file);
      if (entry.date && entry.time) startTimes[entry.file.name] = `${entry.date} ${entry.time}`;
    }
    form.append('project_id', String(projectId));
    form.append('start_times', JSON.stringify(startTimes));

    try {
      const result = await upload.mutateAsync(form);
      if (result.rejected?.length) setRejections((r) => [...r, ...result.rejected]);
      setMessage(
        `${plural(pending.length, 'video subido', 'videos subidos')}. El siguiente paso es calibrar los carriles.`,
      );
      setPending([]);
    } catch (e) {
      setRejections((r) => [
        ...r,
        ...pending.map((p) => ({
          filename: p.file.name,
          reason: `No se pudo subir. ${errorMessage(e)}`,
        })),
      ]);
    }
  }

  return (
    <Page
      title="Subir videos"
      subtitle="Procesamiento por lote — uno o varios archivos a la vez"
      projectScoped
    >
      {/* --- Zona de arrastrar y soltar ---
          Es un <button> de verdad, no un <div role="button">: así el
          teclado, el foco y el anuncio funcionan sin código extra. */}
      <button
        type="button"
        className={`dropzone${dragging ? ' dragover' : ''}`}
        onClick={() => inputRef.current?.click()}
        onDragEnter={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragOver={(e) => e.preventDefault()}
        onDragLeave={(e) => {
          e.preventDefault();
          setDragging(false);
        }}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          addFiles(Array.from(e.dataTransfer.files ?? []));
        }}
      >
        <IconUpload size={40} strokeWidth={1.6} />
        <div className="dz-title">Arrastra uno o varios videos aquí</div>
        <div className="dz-sub">
          o <u>elige archivos desde tu equipo</u>
        </div>
        <div className="dz-formats">MP4 · AVI · MOV · MKV · WEBM · FLV · WMV · M4V · MPG</div>
      </button>

      <input
        ref={inputRef}
        type="file"
        multiple
        hidden
        accept={ALLOWED.join(',')}
        onChange={(e) => {
          addFiles(Array.from(e.target.files ?? []));
          e.target.value = '';
        }}
      />

      {(rejections.length > 0 || message) && (
        <div className="notice-stack">
          {message && (
            <Notice tone="good" onDismiss={() => setMessage(null)}>
              {message}{' '}
              <Link to={projectId ? `/calibrar?project=${projectId}` : '/calibrar'}>
                Ir a calibrar
              </Link>
            </Notice>
          )}
          {rejections.map((r, i) => (
            <Notice
              key={`${r.filename}-${i}`}
              title={r.filename}
              onDismiss={() => setRejections((list) => list.filter((_, j) => j !== i))}
            >
              {r.reason}
            </Notice>
          ))}
        </div>
      )}

      {/* --- Lista previa a subir --- */}
      {pending.length > 0 && (
        <Card className="staging rise">
          <h2 className="section-title">Antes de subir</h2>

          <div className="staging-shared" ref={selectorRef}>
            <ProjectPicker
              projects={projects}
              value={projectId}
              error={projectError}
              onChange={(id) => {
                setProjectId(id);
                setProjectError(null);
              }}
              hint={
                <>
                  Todos los videos de la misma intersección comparten sus carriles y se unen en un
                  solo reporte por intervalos. ¿Falta la intersección?{' '}
                  <Link to="/">Créala aquí</Link>.
                </>
              }
            />
          </div>

          <div className="staging-files">
            {pending.map((entry) => (
              <div className="staging-file-row" key={entry.id}>
                <span className="sf-name" title={entry.file.name}>
                  {entry.file.name}
                </span>
                <span className="sf-meta">
                  {fileExtension(entry.file.name).replace('.', '').toUpperCase()} ·{' '}
                  {formatSize(entry.file.size)}
                </span>
                <div className="sf-start">
                  <span>Inicio real:</span>
                  <input
                    type="date"
                    value={entry.date}
                    aria-label={`Fecha de inicio de ${entry.file.name}`}
                    onChange={(e) =>
                      setPending((p) =>
                        p.map((x) => (x.id === entry.id ? { ...x, date: e.target.value } : x)),
                      )
                    }
                  />
                  <input
                    type="time"
                    step={1}
                    value={entry.time}
                    aria-label={`Hora de inicio de ${entry.file.name}`}
                    onChange={(e) =>
                      setPending((p) =>
                        p.map((x) => (x.id === entry.id ? { ...x, time: e.target.value } : x)),
                      )
                    }
                  />
                </div>
                <IconButton
                  label={`Quitar ${entry.file.name} de la lista`}
                  onClick={() => setPending((p) => p.filter((x) => x.id !== entry.id))}
                  style={{ marginInlineStart: 'auto' }}
                >
                  <IconClose />
                </IconButton>
              </div>
            ))}
          </div>

          <div className="staging-actions">
            <Button onClick={() => setPending([])}>Cancelar</Button>
            <Button variant="primary" onClick={() => void confirmUpload()} disabled={upload.isPending}>
              {upload.isPending
                ? 'Subiendo…'
                : pending.length === 1
                  ? 'Subir 1 video'
                  : `Subir ${pending.length} videos`}
            </Button>
          </div>
        </Card>
      )}

      <LiveView jobs={jobs ?? []} />

      {/* --- Arrancar el conteo ---
          Solo aparece cuando de verdad hay algo que arrancar: videos
          esperando Y carriles ya definidos. */}
      {awaiting.length > 0 && (project?.lane_count ?? 0) > 0 && (
        <div className="notice-stack">
          <Notice tone="info" title="Listo para contar">
            {plural(awaiting.length, 'video esperando', 'videos esperando')} y{' '}
            {plural(project!.lane_count, 'carril definido', 'carriles definidos')}.{' '}
            <Button
              variant="primary"
              disabled={start.isPending}
              onClick={() => projectId !== null && start.mutate(projectId)}
              style={{ marginInlineStart: 'var(--space-2)' }}
            >
              {start.isPending ? 'Iniciando…' : 'Empezar conteo'}
            </Button>
          </Notice>
        </div>
      )}

      <h2 className="section-title">Cola de procesamiento</h2>
      <div className="job-list">
        {jobs?.length === 0 && (
          <EmptyState
            title={
              projectId === null
                ? 'Elige una intersección para ver su cola'
                : 'Todavía no has subido ningún video'
            }
            body={
              projectId === null
                ? 'Cada intersección tiene su propia cola de procesamiento y su propio histórico.'
                : 'Arrastra los segmentos de la grabación a la zona de arriba. Puedes subir varios a la vez; se procesan uno por uno.'
            }
          />
        )}
        {jobs?.map((job) => (
          <JobRow key={job.id} job={job} projectId={projectId} onDelete={setToDelete} />
        ))}
      </div>

      <ConfirmDialog
        open={toDelete !== null}
        title="¿Eliminar este video?"
        body={
          toDelete
            ? `Se borra "${toDelete.original_name}" y los conteos que produjo. Esta acción no se puede deshacer.`
            : ''
        }
        confirmLabel="Eliminar video"
        destructive
        onConfirm={() => {
          if (toDelete) remove.mutate(toDelete.id);
          setToDelete(null);
        }}
        onCancel={() => setToDelete(null)}
      />
    </Page>
  );
}
