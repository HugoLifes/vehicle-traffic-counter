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
import { Button, Card, EmptyState, IconButton, Notice, Pill } from '../components/ui';
import { IconClose, IconEye, IconTrash, IconUpload, IconVideo } from '../components/Icons';
import {
  useAnotarVideo,
  useDeleteVideo,
  useDiagnosticar,
  useDiagnostico,
  useStartCounting,
  keys,
  useVideos,
} from '../lib/queries';
import { useProjectParam } from '../lib/useProjectParam';
import {
  errorMessage,
  frameUrl,
  getAlmacenamiento,
  ponerInicio,
  subirVideoPorPedazos,
  videoUrl,
} from '../lib/api';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  JOB_STATUS_LABEL,
  JOB_STATUS_TONE,
  fileExtension,
  formatSize,
  guessStartTime,
  minutoDelNombre,
  plural,
  todayISO,
} from '../lib/format';
import type { VideoJob } from '../lib/types';
import { ConfirmDialog } from '../components/ui';
import { Almacenamiento } from '../components/Almacenamiento';
import { ImportarEntrada } from '../components/ImportarEntrada';

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
   Una transmisión continua (MJPEG) de lo que la IA analiza, como la de una
   cámara IP: el navegador la pinta solo, sin pedir foto por foto. Antes se
   pedía un cuadro cada medio segundo y el servidor dibujaba uno por segundo
   de video: con el análisis a ~1.6x del tiempo real se veían diapositivas.
   Aquí solo se pregunta, cada 2 s, si hay algo procesándose. */

function LiveView({ jobs }: { jobs: VideoJob[] }) {
  const [jobId, setJobId] = useState<number | null>(null);
  // Cambia al reconectar: un <img> con la misma URL no vuelve a pedirla.
  const [conexion, setConexion] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function tick() {
      if (document.hidden) return;
      try {
        const res = await fetch('/api/videos/live-frame?estado=1', { cache: 'no-store' });
        if (cancelled) return;
        if (res.status === 204) {
          setJobId(null);
          return;
        }
        if (!res.ok) return;
        const d = (await res.json()) as { job_id: number | null };
        setJobId(d.job_id ?? null);
      } catch {
        // Sin red se deja lo que está en pantalla.
      }
    }
    void tick();
    const timer = window.setInterval(tick, 2000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const src = jobId != null ? `/api/videos/live-stream?v=${jobId}-${conexion}` : null;
  if (!src) return null;
  const job = jobs.find((j) => j.id === jobId);
  /* A qué velocidad va el análisis respecto al video: es lo que explica por
     qué esta vista avanza más despacio que la grabación. */
  let ritmo: number | null = null;
  if (job?.started_at && job.fps && job.processed_frames > 0) {
    const inicio = Date.parse(`${job.started_at.replace(' ', 'T')}Z`);
    const segundos = (Date.now() - inicio) / 1000;
    if (segundos > 5) ritmo = job.processed_frames / job.fps / segundos;
  }

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
        <img
          src={src}
          alt="Video en vivo con las detecciones de la IA"
          // La transmisión se corta al terminar cada archivo o si cae la red:
          // se vuelve a abrir en 1 s.
          onError={() => window.setTimeout(() => setConexion((c) => c + 1), 1000)}
        />
      </div>
      <p className="live-hint">
        Es el análisis en vivo: la IA revisa uno por uno todos los cuadros del video
        {ritmo ? `, a ${ritmo.toFixed(1)}× del tiempo real` : ''}. Si va por debajo de 1×, la vista
        avanza más despacio que la grabación; con internet lento se saltan cuadros para no
        atrasarse. El video ya contado se ve a velocidad normal con el ojo de cada archivo.
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
  /* Un video sin hora no cae en ningún intervalo del reporte. Mientras no se
     haya contado, la hora se corrige aquí sin volver a subirlo. */
  const corregible = ['awaiting_calibration', 'queued', 'error'].includes(job.status);
  const [editHora, setEditHora] = useState(false);
  const [fechaE, setFechaE] = useState(job.video_start_time?.slice(0, 10) ?? todayISO());
  const [horaE, setHoraE] = useState(job.video_start_time?.slice(11, 19) ?? '');
  const [errHora, setErrHora] = useState<string | null>(null);
  async function guardarHora() {
    try {
      setErrHora(null);
      const h = horaE.length === 5 ? `${horaE}:00` : horaE;
      await ponerInicio(job.id, `${fechaE} ${h}`);
      setEditHora(false);
      void qcFila.invalidateQueries({ queryKey: ['videos'] });
    } catch (e) {
      setErrHora(errorMessage(e));
    }
  }

  /* Diagnóstico del encuadre: dice si vale la pena contar este video antes
     de gastar horas en hacerlo. Corre sobre la misma GPU que la cola, así
     que el backend lo rechaza mientras haya videos contándose. */
  const diagnosticar = useDiagnosticar();
  const qcFila = useQueryClient();
  /* La revisión corre en la cola de la GPU: mientras está pendiente el botón
     lo dice, y en cuanto termina se lee el resultado. */
  const revisando = job.diag_estado === 'en_cola' || job.diag_estado === 'revisando';
  const estabaRevisando = useRef(revisando);
  useEffect(() => {
    if (estabaRevisando.current && !revisando) {
      void qcFila.invalidateQueries({ queryKey: ['diagnostico', job.id] });
    }
    estabaRevisando.current = revisando;
  }, [revisando, job.id, qcFila]);
  const textoRevisar =
    job.diag_estado === 'en_cola'
      ? 'Revisión en cola…'
      : job.diag_estado === 'revisando'
        ? 'Revisando encuadre…'
        : null;
  /* Video con detecciones: lo deja el conteo si el proyecto lo pide, o se
     genera después sobre un video ya contado, sin recontarlo. */
  const anotar = useAnotarVideo();
  const tieneVideo = Boolean(job.output_video_path);
  const anotando = job.anotado_estado === 'en_cola' || job.anotado_estado === 'generando';
  /* Los avisos son lo útil del diagnóstico —dicen qué cambiar de la cámara—,
     así que cuando el encuadre NO sale bueno el detalle se abre solo:
     esconder "esta perspectiva va a costar exactitud" detrás de un clic es
     no avisar. El usuario puede cerrarlo, y entonces manda su elección. */
  const [verDetalle, setVerDetalle] = useState<boolean | null>(null);
  const resumen = job.diag_color
    ? { color: job.diag_color, veredicto: job.diag_veredicto, puntaje: job.diag_puntaje }
    : null;
  const abierto = verDetalle ?? (resumen ? resumen.color !== 'verde' : false);
  /* El detalle (avisos, exactitud esperable) se pide solo si se muestra. */
  const { data: diag } = useDiagnostico(job.id, Boolean(resumen) && abierto);
  const d = diag?.datos?.diagnostico;
  const TONO: Record<string, 'good' | 'warning' | 'critical'> = {
    verde: 'good',
    ambar: 'warning',
    rojo: 'critical',
  };

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
            {format} · {formatSize(job.size_bytes)} · inicio{' '}
            {job.video_start_time ? start : <strong className="sin-hora">sin hora</strong>}
            {corregible && !editHora && (
              <>
                {' · '}
                <button type="button" className="enlace-boton" onClick={() => setEditHora(true)}>
                  {job.video_start_time ? 'cambiar hora' : 'poner hora'}
                </button>
              </>
            )}
          </div>
          {editHora && (
            <div className="sf-start">
              <input
                type="date"
                value={fechaE}
                aria-label={`Fecha de inicio de ${job.original_name}`}
                onChange={(e) => setFechaE(e.target.value)}
              />
              <input
                type="time"
                step={1}
                value={horaE}
                aria-label={`Hora de inicio de ${job.original_name}`}
                onChange={(e) => setHoraE(e.target.value)}
              />
              <Button onClick={() => void guardarHora()} disabled={!fechaE || !horaE}>
                Guardar
              </Button>
              <Button onClick={() => setEditHora(false)}>Cancelar</Button>
              {errHora && <span className="sf-meta">{errHora}</span>}
            </div>
          )}
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

        {resumen ? (
          <button
            type="button"
            className="pill-boton"
            aria-expanded={abierto}
            title={abierto ? 'Ocultar el detalle del encuadre' : 'Ver por qué y qué cambiar'}
            onClick={() => setVerDetalle(!abierto)}
          >
            <Pill tone={TONO[resumen.color]} dot>
              Encuadre {resumen.veredicto} · {resumen.puntaje}/100
            </Pill>
          </button>
        ) : (
          <Button
            onClick={() => diagnosticar.mutate({ jobId: job.id })}
            disabled={diagnosticar.isPending || revisando}
          >
            {textoRevisar ?? (diagnosticar.isPending ? 'Pidiendo…' : 'Revisar encuadre')}
          </Button>
        )}

        {job.status === 'done' && anotando && (
          <Pill tone="accent" dot live>
            {job.anotado_estado === 'en_cola'
              ? 'Video con detecciones en cola'
              : `Generando video · ${job.anotado_avance ?? 0} %`}
          </Pill>
        )}

        {job.status === 'done' && !anotando && !tieneVideo && (
          <Button onClick={() => anotar.mutate({ jobId: job.id })} disabled={anotar.isPending}>
            {job.anotado_estado === 'error' ? 'Reintentar video' : 'Generar video con detecciones'}
          </Button>
        )}

        {job.status === 'done' && tieneVideo && !anotando && (
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

      {job.diag_estado === 'error' && (
        <div className="notice-stack">
          <Notice tone="warning" title="No se pudo revisar el encuadre">
            {job.diag_error || 'La revisión falló.'} Puedes volver a pedirla.
          </Notice>
        </div>
      )}

      {job.anotado_estado === 'error' && (
        <div className="notice-stack">
          <Notice tone="warning" title="No se pudo generar el video con detecciones">
            El conteo de este video no cambió. Vuelve a pedirlo; si se repite, revisa que el
            archivo original siga en el equipo.
          </Notice>
        </div>
      )}

      {job.status === 'done' && job.aviso && (
        /* Lo que el conteo encontró raro en este video (zona que descarta
           casi todo, vehículos que no cruzaron ninguna línea, archivo
           cortado). Va a la pantalla porque el registro del contenedor no
           lo lee nadie, y un aviso que nadie ve es lo mismo que no avisar. */
        <div className="notice-stack">
          <Notice tone="warning" title="Revisa este video antes de entregar">
            {job.aviso}
          </Notice>
        </div>
      )}

      {d && abierto && (
        /*
          Qué le pasa a este encuadre y qué se puede hacer. El veredicto solo
          no sirve de nada: lo accionable es el aviso ("el vehículo mide 22 px",
          "imagen sobreexpuesta", "los rastros mueren a media escena").
        */
        <div className="job-diagnostico rise">
          <div className="jd-head">
            <span className="jd-title">
              Encuadre {d.veredicto} · {d.puntaje}/100
              {d.razon_esperada
                ? ` · exactitud esperable ${d.razon_esperada[0].toFixed(2)}×–${d.razon_esperada[1].toFixed(2)}× del conteo real`
                : ' · con este encuadre no se puede prometer exactitud'}
            </span>
            <Button
              onClick={() => diagnosticar.mutate({ jobId: job.id })}
              disabled={diagnosticar.isPending || revisando}
            >
              {textoRevisar ?? (diagnosticar.isPending ? 'Pidiendo…' : 'Revisar de nuevo')}
            </Button>
          </div>

          {d.avisos.length > 0 ? (
            <div className="notice-stack">
              {d.avisos.map((a, i) => (
                <Notice
                  key={i}
                  tone={d.color === 'rojo' ? 'critical' : 'warning'}
                  title={i === 0 ? 'Esta perspectiva puede afectar el aforo' : undefined}
                >
                  {a}
                </Notice>
              ))}
            </div>
          ) : (
            <Notice tone="good" title="El encuadre no tiene pegas">
              El vehículo se ve bastante grande y los rastros entran y salen por donde deben.
            </Notice>
          )}

          <p className="jd-fuente">
            Medido sobre este mismo video ({d.etapa}), antes de contarlo. No es una predicción del
            modelo: son las señales que en este proyecto se contrastaron contra conteos manuales.
          </p>
        </div>
      )}

      {open && tieneVideo && !anotando && (
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
          {/* `auto`: el reproductor solo existe cuando se abrió, así que se
              empieza a cargar enseguida en vez de esperar al clic de
              reproducir; por internet eso es un segundo de arranque menos. */}
          <video
            controls
            loop={loop}
            preload="auto"
            poster={frameUrl(job.id, Math.floor((job.total_frames ?? 2) / 2), 'procesado')}
            /* El avance cambia al regenerarlo: sin esto el navegador puede
               seguir mostrando el video de antes, que tenía la misma ruta. */
            src={`${videoUrl(job.id)}?v=${job.anotado_avance ?? 0}`}
          />
          <div className="jp-foot">
            <label className="jp-loop">
              <input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} />
              <span>Repetir en bucle</span>
            </label>
            <Button onClick={() => anotar.mutate({ jobId: job.id })} disabled={anotar.isPending}>
              Volver a generar
            </Button>
            <Link className="jp-link" to={`/proyecto/${projectId}/calibrar?job=${job.id}&ver=procesado`}>
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
  const { projectId, project } = useProjectParam();
  // La cola se acota a la intersección elegida: con varios aforos en curso,
  // ver los videos de todos mezclados no ayuda a nadie.
  const { data: jobs } = useVideos(projectId ?? undefined, true);
  const qc = useQueryClient();
  /* Avance de cada video mientras sube, uno por uno. */
  const [progreso, setProgreso] = useState<
    Record<string, { cargado: number; total: number; estado: 'subiendo' | 'reintentando' | 'error' }>
  >({});
  const [subiendo, setSubiendo] = useState(false);
  /* El estado de React tarda un render en verse: un doble clic rápido
     arrancaba dos subidas del mismo archivo (Juárez, 2-oct-2026). */
  const subiendoRef = useRef(false);

  /* Cerrar la página a media subida la pierde: el navegador pregunta antes. */
  useEffect(() => {
    if (!subiendo) return;
    const alSalir = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = '';
    };
    window.addEventListener('beforeunload', alSalir);
    return () => window.removeEventListener('beforeunload', alSalir);
  }, [subiendo]);
  const remove = useDeleteVideo();
  const start = useStartCounting();

  const [pending, setPending] = useState<Pending[]>([]);
  const [rejections, setRejections] = useState<Rejection[]>([]);
  const [dragging, setDragging] = useState(false);
  const [toDelete, setToDelete] = useState<VideoJob | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  /* Sin el disco de los videos el servidor rechaza las subidas: se dice
     antes de que alguien espere media hora a que suba un archivo. */
  const { data: almacen } = useQuery({
    queryKey: ['almacenamiento'],
    queryFn: getAlmacenamiento,
    refetchInterval: 60000,
  });

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
    // La intersección la fija la ruta (/proyecto/:projectId/subir), así que
    // aquí no puede faltar; si faltara, subir sin destino sería peor que
    // no hacer nada.
    if (projectId === null) return;

    if (subiendoRef.current) return;
    const sinHora = pending.filter((p) => !p.date || !p.time);
    if (sinHora.length) {
      setRejections((x) => [
        ...x,
        {
          filename: sinHora.map((p) => p.file.name).join(', '),
          reason:
            'Falta la fecha o la hora real de inicio. Sin ella los vehículos no caen en ningún ' +
            'cuarto de hora del reporte.',
        },
      ]);
      return;
    }
    subiendoRef.current = true;

    /* Uno por uno: cada video que termina ya está a salvo en el servidor
       aunque el siguiente falle, y la barra dice cuánto falta. */
    setSubiendo(true);
    let subidos = 0;
    let fallidos = 0;
    for (const entry of [...pending]) {
      setProgreso((p) => ({
        ...p,
        [entry.id]: { cargado: 0, total: entry.file.size, estado: 'subiendo' },
      }));
      try {
        const r = await subirVideoPorPedazos(
          entry.file,
          projectId,
          entry.date && entry.time ? `${entry.date} ${entry.time}` : null,
          (cargado, total, reintentando) =>
            setProgreso((p) => ({
              ...p,
              [entry.id]: { cargado, total, estado: reintentando ? 'reintentando' : 'subiendo' },
            })),
        );
        if (r.rejected?.length) setRejections((x) => [...x, ...r.rejected]);
        subidos += r.accepted?.length ?? 0;
        setPending((p) => p.filter((x) => x.id !== entry.id));
        setProgreso((p) => {
          const n = { ...p };
          delete n[entry.id];
          return n;
        });
        qc.invalidateQueries({ queryKey: ['videos'] });
      } catch (e) {
        fallidos += 1;
        setProgreso((p) => ({
          ...p,
          [entry.id]: { cargado: 0, total: entry.file.size, estado: 'error' },
        }));
        setRejections((x) => [
          ...x,
          { filename: entry.file.name, reason: `No se pudo subir. ${errorMessage(e)}` },
        ]);
      }
    }
    setSubiendo(false);
    subiendoRef.current = false;
    qc.invalidateQueries({ queryKey: ['videos'] });
    qc.invalidateQueries({ queryKey: keys.projects });
    if (subidos > 0) {
      setMessage(
        `${plural(subidos, 'video subido', 'videos subidos')}.` +
          (fallidos
            ? ` ${plural(fallidos, 'quedó', 'quedaron')} en la lista para volver a intentar.`
            : '') +
          ' El siguiente paso es calibrar los carriles.',
      );
    }
  }

  return (
    <>
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

      <Almacenamiento />

      {projectId !== null && <ImportarEntrada projectId={projectId} />}

      {almacen?.problema && (
        <div className="notice-stack">
          <Notice tone="critical" title="No se pueden subir videos">
            {almacen.problema}
          </Notice>
        </div>
      )}

      {(rejections.length > 0 || message) && (
        <div className="notice-stack">
          {message && (
            <Notice tone="good" onDismiss={() => setMessage(null)}>
              {message}{' '}
              <Link to={`/proyecto/${projectId}/calibrar`}>
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
          <div className="sf-start sf-todos">
            <span>Para todos:</span>
            <input
              type="date"
              aria-label="Fecha de grabación de todos los videos"
              disabled={subiendo}
              onChange={(e) => {
                const v = e.target.value;
                if (v) setPending((p) => p.map((x) => ({ ...x, date: v })));
              }}
            />
            {pending.some((p) => minutoDelNombre(p.file.name) !== null) && (
              <label>
                hora de la carpeta{' '}
                <select
                  aria-label="Hora de la carpeta: los videos se llaman por el minuto"
                  disabled={subiendo}
                  defaultValue=""
                  onChange={(e) => {
                    const hh = e.target.value;
                    if (!hh) return;
                    setPending((p) =>
                      p.map((x) => {
                        const mm = minutoDelNombre(x.file.name);
                        return mm === null
                          ? x
                          : { ...x, time: `${hh}:${String(mm).padStart(2, '0')}:00` };
                      }),
                    );
                  }}
                >
                  <option value="">elegir…</option>
                  {Array.from({ length: 24 }, (_, h) => String(h).padStart(2, '0')).map((h) => (
                    <option key={h} value={h}>
                      {h}:00
                    </option>
                  ))}
                </select>
              </label>
            )}
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
                  disabled={subiendo}
                >
                  <IconClose />
                </IconButton>
                {progreso[entry.id] && (
                  <div className="sf-progreso">
                    {progreso[entry.id].estado === 'error' ? (
                      <span className="sf-meta">No se pudo subir; sigue en la lista para reintentar.</span>
                    ) : (
                      <>
                        <div
                          className="job-progress"
                          role="progressbar"
                          aria-valuenow={Math.round(
                            (100 * progreso[entry.id].cargado) / Math.max(1, progreso[entry.id].total),
                          )}
                          aria-valuemin={0}
                          aria-valuemax={100}
                          aria-label={`Subida de ${entry.file.name}`}
                        >
                          <div
                            className="bar"
                            style={{
                              scale: `${progreso[entry.id].cargado / Math.max(1, progreso[entry.id].total)} 1`,
                            }}
                          />
                        </div>
                        <span className="sf-meta">
                          {Math.round(
                            (100 * progreso[entry.id].cargado) / Math.max(1, progreso[entry.id].total),
                          )}{' '}
                          % · {formatSize(progreso[entry.id].cargado)} de{' '}
                          {formatSize(progreso[entry.id].total)}
                          {progreso[entry.id].estado === 'reintentando' && ' · se cortó, reintentando…'}
                        </span>
                      </>
                    )}
                  </div>
                )}
              </div>
            ))}
          </div>

          {subiendo && (
            <p className="field-hint">
              Subiendo un video a la vez, en pedazos. No cierres esta página hasta que termine: la
              velocidad depende del internet de este equipo, y por internet 1 GB tarda de 15 a 30
              minutos. Si la conexión se corta, el pedazo se reintenta solo; si se cierra la página,
              vuelve a elegir el mismo archivo y sigue donde se quedó.
            </p>
          )}

          <div className="staging-actions">
            <Button onClick={() => setPending([])} disabled={subiendo}>
              Cancelar
            </Button>
            <Button variant="primary" onClick={() => void confirmUpload()} disabled={subiendo}>
              {subiendo
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
    </>
  );
}
