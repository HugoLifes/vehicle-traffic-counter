/*
  Cliente de la API.

  Un solo lugar donde se decide qué es un error y con qué texto se cuenta,
  porque antes cada página inventaba el suyo: unas mostraban `HTTP 409`,
  otras `Error: undefined`. Aquí se saca el `detail` que manda FastAPI, que
  es el que sí explica qué pasó.
*/

import type {
  EngineState,
  GeoResult,
  Lane,
  LaneCount,
  Point,
  Project,
  ProjectCreate,
  ProjectMetrics,
  VideoJob,
  VideoSegment,
  Zone,
  FrameDetection,
  RagDocumento,
  RagRespuesta,
  RagConversacion,
  RagMensaje,
} from './types';
import type {
  AforoDireccional,
  DiagnosticoGuardado,
  EventoProyecto,
  FichaCamara,
  FuenteVideo,
  Tramo,
} from './types';

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    // Distinguir "no hay red" de "el servidor dijo que no" importa: la
    // primera se resuelve reintentando, la segunda no.
    throw new ApiError(
      'No se pudo contactar al servidor. Revisa que la plataforma siga encendida.',
      0,
    );
  }

  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail =
      body && typeof body === 'object' && 'detail' in body
        ? textoDelDetalle((body as { detail: unknown }).detail, res.status)
        : `El servidor respondió ${res.status}.`;
    throw new ApiError(detail, res.status);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

/* El `detail` de FastAPI puede ser texto, un objeto con `mensaje` o la lista
   de errores de validación. `String()` de un objeto da "[object Object]", que
   es lo que vieron en Juárez al fallar una subida (2-oct-2026). */
function textoDelDetalle(detail: unknown, status: number): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    const partes = detail
      .map((d) => (d && typeof d === 'object' && 'msg' in d ? String((d as { msg: unknown }).msg) : ''))
      .filter(Boolean);
    if (partes.length) return `Datos no válidos: ${partes.join('; ')}.`;
  }
  if (detail && typeof detail === 'object' && 'mensaje' in detail) {
    return String((detail as { mensaje: unknown }).mensaje);
  }
  return `El servidor respondió ${status}.`;
}

const json = (body: unknown): RequestInit => ({
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body),
});

/* --- Proyectos --------------------------------------------------------- */

export const listProjects = () => request<Project[]>('/api/projects');
export const getProject = (id: number) => request<Project>(`/api/projects/${id}`);
export const createProject = (data: ProjectCreate) =>
  request<Project>('/api/projects', json(data));
export const copyCalibration = (id: number, fromProjectId: number) =>
  request<{ lanes: number; zones: number }>(
    `/api/projects/${id}/copy-calibration`,
    json({ from_project_id: fromProjectId }),
  );

export const getCalibrationStatus = (id: number) =>
  request<{ calibrated_at: string | null; stale: number; awaiting: number }>(
    `/api/projects/${id}/calibration-status`,
  );

export const recount = (id: number) =>
  request<{ requeued: number }>(`/api/projects/${id}/recount`, { method: 'POST' });
/* Velocidad de lo ya contado sin recontar (remedir_velocidad.py). */
export const medirVelocidad = (id: number) =>
  request<{ en_cola: number }>(`/api/projects/${id}/medir-velocidad`, { method: 'POST' });
export const detenerVelocidad = (id: number) =>
  request<{ detenidos: number }>(`/api/projects/${id}/medir-velocidad/detener`, {
    method: 'POST',
  });

export const updateProject = (id: number, data: Partial<ProjectCreate>) =>
  request<Project>(`/api/projects/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });

export const deleteProject = (id: number) =>
  request<{ deleted: number }>(`/api/projects/${id}`, { method: 'DELETE' });

export const getCameraCard = (id: number) =>
  request<FichaCamara>(`/api/projects/${id}/camara`);

export const listEvents = (id: number) =>
  request<EventoProyecto[]>(`/api/projects/${id}/eventos`);

export const startCounting = (id: number) =>
  request<{ started: number }>(`/api/projects/${id}/start-counting`, { method: 'POST' });

/* --- Carriles ---------------------------------------------------------- */

export const listLanes = (projectId: number) =>
  request<Lane[]>(`/api/lanes?project_id=${projectId}`);

export const createLane = (data: { project_id: number; name: string; points: [Point, Point] }) =>
  request<Lane>('/api/lanes', json(data));

export const renameLane = (laneId: number, name: string) =>
  request<Lane>(`/api/lanes/${laneId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });

/* null quita el tramo: la línea vuelve a solo contar. */
export const setLaneTramo = (laneId: number, tramo: Tramo | null) =>
  request<Lane>(`/api/lanes/${laneId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(tramo ? { tramo } : { quitar_tramo: true }),
  });

export const deleteLane = (laneId: number) =>
  request<void>(`/api/lanes/${laneId}`, { method: 'DELETE' });

/* --- Zonas de calzada -------------------------------------------------- */

export const listZones = (projectId: number) =>
  request<Zone[]>(`/api/zones?project_id=${projectId}`);

export const createZone = (data: {
  project_id: number;
  name: string;
  points: Point[];
  kind?: string;
}) => request<Zone>('/api/zones', json(data));

export const renameZone = (zoneId: number, name: string) =>
  request<Zone>(`/api/zones/${zoneId}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });

export const deleteZone = (zoneId: number) =>
  request<void>(`/api/zones/${zoneId}`, { method: 'DELETE' });

/* --- RAG: documentos y preguntas --------------------------------------- */

export const listRagDocs = (projectId?: number) =>
  request<RagDocumento[]>(
    projectId ? `/api/rag/documentos?project_id=${projectId}` : '/api/rag/documentos',
  );

export const uploadRagDoc = (form: FormData) =>
  request<{ doc_id: number; nombre: string; fragmentos: number }>('/api/rag/documentos', {
    method: 'POST',
    body: form,
  });

export const deleteRagDoc = (docId: number) =>
  request<void>(`/api/rag/documentos/${docId}`, { method: 'DELETE' });

export const askRag = (pregunta: string, projectId?: number) =>
  request<RagRespuesta>('/api/rag/preguntar', json({ pregunta, project_id: projectId ?? null }));

export const listRagChats = (projectId?: number) =>
  request<RagConversacion[]>(
    projectId ? `/api/rag/conversaciones?project_id=${projectId}` : '/api/rag/conversaciones',
  );

export const createRagChat = (projectId?: number) =>
  request<{ id: number }>('/api/rag/conversaciones', json({ project_id: projectId ?? null }));

export const readRagChat = (id: number) =>
  request<{ mensajes: RagMensaje[] }>(`/api/rag/conversaciones/${id}`);

export const deleteRagChat = (id: number) =>
  request<void>(`/api/rag/conversaciones/${id}`, { method: 'DELETE' });

export const sendRagMessage = (conversacionId: number, pregunta: string) =>
  request<RagRespuesta>('/api/rag/chat', json({ conversacion_id: conversacionId, pregunta }));

/* --- Videos ------------------------------------------------------------ */

export const listVideos = (projectId?: number) =>
  request<VideoJob[]>(projectId ? `/api/videos?project_id=${projectId}` : '/api/videos');

export const deleteVideo = (jobId: number) =>
  request<void>(`/api/videos/${jobId}`, { method: 'DELETE' });

/* El servidor devuelve `accepted`, no `jobs`. El tipo decía lo segundo
   desde el principio y nadie lo notó porque la interfaz solo leía
   `rejected`; al empezar a avisar de cuántos videos entraron, salió. */
export const uploadVideos = (form: FormData) =>
  request<{ accepted: VideoJob[]; rejected: { filename: string; reason: string }[] }>(
    '/api/videos/upload',
    { method: 'POST', body: form },
  );

/*
  Subida de UN video, con su avance. Con fetch no hay forma de saber cuánto
  lleva una subida, y la pantalla mandaba todos los videos en una sola
  petición: por internet, con la subida de una oficina (0.3–1 MB/s medido),
  un lote de varios cientos de megas pasaba minutos en "Subiendo…" sin
  moverse, y un corte a la mitad perdía el lote entero sin que el servidor
  llegara a ver nada (1-oct-2026, primer día de la beta).
*/
export function uploadVideoConProgreso(
  form: FormData,
  onProgress: (cargado: number, total: number) => void,
): Promise<{ accepted: VideoJob[]; rejected: { filename: string; reason: string }[] }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/videos/upload');
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded, e.total);
    };
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* respuesta sin JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as { accepted: VideoJob[]; rejected: { filename: string; reason: string }[] });
        return;
      }
      const detail =
        body && typeof body === 'object' && 'detail' in body
          ? textoDelDetalle((body as { detail: unknown }).detail, xhr.status)
          : `El servidor respondió ${xhr.status}.`;
      reject(new ApiError(detail, xhr.status));
    };
    xhr.onerror = () =>
      reject(
        new ApiError(
          'Se cortó la conexión a media subida. Los videos que ya subieron se quedan; vuelve a intentar con los que faltan.',
          0,
        ),
      );
    xhr.send(form);
  });
}

/*
  Subida por pedazos de 16 MB. Un video de campo pesa 3.3 GB y por internet
  sube a ~1 MB/s: casi una hora en una sola petición, y cualquier corte (un
  reinicio de la plataforma, un tropiezo de la red) la tiraba entera con un
  502 sin que nada llegara al servidor (1-oct-2026). Así un corte cuesta un
  pedazo: se reintenta solo ese, con espera creciente, y si el servidor ya lo
  tenía responde 409 con lo que tiene y se sigue desde ahí. Volver a elegir
  el mismo archivo después de cerrar la página continúa donde se quedó.
*/
/* 4 MB: desde Juárez, por el relevo de internet, se midieron ~25 KB/s. Un
   pedazo de 16 MB tardaba 11 min y un corte a la mitad lo tiraba entero; uno
   de 4 MB son menos de 3 min. En la red de la casa el costo es nulo. */
const PEDAZO = 4 * 1024 * 1024;
const REINTENTOS = 6;

function subirPedazo(
  url: string,
  pedazo: Blob,
  onProgress: (cargado: number) => void,
): Promise<{ status: number; body: unknown }> {
  return new Promise((resolve) => {
    const xhr = new XMLHttpRequest();
    xhr.open('PUT', url);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.upload.onprogress = (e) => onProgress(e.loaded);
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* sin JSON */
      }
      resolve({ status: xhr.status, body });
    };
    // Corte de red: status 0, se reintenta.
    xhr.onerror = () => resolve({ status: 0, body: null });
    xhr.ontimeout = () => resolve({ status: 0, body: null });
    xhr.send(pedazo);
  });
}

const esperar = (ms: number) => new Promise((r) => setTimeout(r, ms));

export async function subirVideoPorPedazos(
  archivo: File,
  projectId: number,
  inicio: string | null,
  onProgress: (cargado: number, total: number, reintentando: boolean) => void,
): Promise<{ accepted: VideoJob[]; rejected: { filename: string; reason: string }[] }> {
  const datos = {
    project_id: projectId,
    nombre: archivo.name,
    tamano: archivo.size,
    modificado: archivo.lastModified,
    inicio,
  };
  const { subida_id, recibido, ya_subido } = await request<{
    subida_id: string;
    recibido: number;
    ya_subido?: number;
  }>('/api/videos/subida/iniciar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(datos),
  });
  // Este mismo archivo ya quedó registrado: terminar devuelve ese video.
  let offset = ya_subido ? archivo.size : recibido;
  onProgress(offset, archivo.size, false);
  let fallos = 0;
  let ocupado = 0;
  while (offset < archivo.size) {
    const pedazo = archivo.slice(offset, Math.min(archivo.size, offset + PEDAZO));
    const r = await subirPedazo(
      `/api/videos/subida/${subida_id}?offset=${offset}`,
      pedazo,
      (cargado) => onProgress(offset + cargado, archivo.size, fallos > 0),
    );
    if (r.status === 200) {
      offset = (r.body as { recibido: number }).recibido;
      fallos = 0;
      onProgress(offset, archivo.size, false);
      continue;
    }
    if (r.status === 409) {
      const det = (r.body as { detail?: { recibido?: number; ocupado?: boolean } } | null)?.detail;
      if (det?.ocupado) {
        // Otra pestaña (o un doble clic) sube este mismo archivo: se espera
        // a que acabe en vez de pelearse por el mismo pedazo.
        ocupado += 1;
        if (ocupado > 120) {
          throw new ApiError(
            `${archivo.name} se está subiendo desde otra pestaña o equipo. Espera a que termine allá.`,
            409,
          );
        }
        onProgress(det.recibido ?? offset, archivo.size, true);
        await esperar(5000);
        offset = det.recibido ?? offset;
        continue;
      }
      // El servidor tiene otra cosa (un reintento de un pedazo que sí llegó).
      if (typeof det?.recibido === 'number') {
        offset = det.recibido;
        continue;
      }
    }
    if (r.status === 401) throw new ApiError('La sesión pide usuario y contraseña de nuevo.', 401);
    fallos += 1;
    if (fallos > REINTENTOS) {
      throw new ApiError(
        `Se cortó la conexión varias veces seguidas. Lo subido se conserva: vuelve a elegir ${archivo.name} y sigue donde se quedó.`,
        r.status,
      );
    }
    onProgress(offset, archivo.size, true);
    await esperar(Math.min(30000, 2000 * 2 ** (fallos - 1)));
  }
  return request<{ accepted: VideoJob[]; rejected: { filename: string; reason: string }[] }>(
    `/api/videos/subida/${subida_id}/terminar`,
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(datos) },
  );
}

export const getMetrics = (projectId: number, minutes: number) =>
  request<ProjectMetrics>(`/api/videos/metrics?project_id=${projectId}&minutes=${minutes}`);

export const getDireccional = (projectId: number, minutes: number) =>
  request<AforoDireccional>(`/api/projects/${projectId}/direccional?interval_minutes=${minutes}`);

/* Si el disco de los videos está conectado y cuánto le cabe. */
export interface Almacenamiento {
  exigido: boolean;
  conectado: boolean;
  libre_gb: number;
  total_gb: number;
  usado_videos_gb: number;
  gb_por_hora: number | null;
  horas_que_caben: number | null;
  problema: string | null;
}
export const getAlmacenamiento = () => request<Almacenamiento>('/api/videos/almacenamiento');

/* Carpeta de entrada: videos que llegaron por WinSCP o en un disco
   conectado al Jetson, sin pasar por el navegador. */
export interface ArchivoEntrada {
  ruta: string;
  nombre: string;
  tamano: number;
  modificado: string;
  fecha: string | null;
  hora: string | null;
  importado: number | null;
}
export interface EstadoImportacion {
  activa: boolean;
  total?: number;
  hechos?: number;
  bytes_total?: number;
  bytes_hechos?: number;
  actual?: string | null;
  errores?: { ruta: string; motivo: string }[];
  videos?: number[];
  omitidos?: number;
}
export const getEntrada = (projectId: number) =>
  request<{ disponible: boolean; archivos: ArchivoEntrada[]; importacion: EstadoImportacion }>(
    `/api/entrada?project_id=${projectId}`,
  );
export const getEstadoImportacion = () => request<EstadoImportacion>('/api/entrada/estado');
export const importarEntrada = (projectId: number, archivos: { ruta: string; inicio: string }[]) =>
  request<EstadoImportacion>('/api/entrada/importar', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ project_id: projectId, archivos }),
  });

/* La hora real de inicio de un video ya subido y aún sin contar. */
export const ponerInicio = (jobId: number, inicio: string) =>
  request<VideoJob>(`/api/videos/${jobId}/inicio`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ inicio }),
  });

export const videoUrl = (jobId: number) => `/api/videos/${jobId}/video`;
export const originalUrl = (jobId: number) => `/api/videos/${jobId}/original`;

export const getDiagnostico = (jobId: number) =>
  request<DiagnosticoGuardado>(`/api/videos/${jobId}/diagnostico`);

/* El diagnóstico usa la misma GPU que la cola de conteo, así que el backend
   lo rechaza mientras haya videos contándose. */
/* Video con detecciones de un video ya contado, sin recontarlo. */
export const anotarVideo = (jobId: number) =>
  request<{ job_id: number; anotado_estado: string }>(`/api/videos/${jobId}/anotar`, {
    method: 'POST',
  });

/* Entra a la cola de la GPU y responde enseguida; el resultado se lee con
   getDiagnostico cuando `diag_estado` del video se vacía. */
export const diagnosticarVideo = (jobId: number, direccional = false) =>
  request<{ job_id: number; diag_estado: string }>(
    `/api/videos/${jobId}/diagnostico?rastreo=true&direccional=${direccional}`,
    { method: 'POST' },
  );

/* --- Exportación --------------------------------------------------------
   Enlaces directos, no fetch: así el navegador maneja la descarga con su
   propia barra de progreso y el nombre de archivo que manda el servidor,
   en vez de tener que armar un blob y un <a download> a mano. */

export const exportIntervalsUrl = (projectId: number, minutes: number) =>
  `/api/export/intervalos.csv?project_id=${projectId}&minutes=${minutes}`;

/* El entregable: mismo formato que los estudios que el cliente ya recibe,
   para que no haya que rehacerlo a mano. No depende del intervalo elegido
   en pantalla porque el formato de la empresa es siempre por hora y por
   cuartos de hora. */
export const exportAforoExcelUrl = (projectId: number) =>
  `/api/export/aforo.xlsx?project_id=${projectId}`;

export const exportSummaryUrl = (projectId: number, minutes: number) =>
  `/api/export/resumen.csv?project_id=${projectId}&minutes=${minutes}`;

/* --- Motor en vivo ----------------------------------------------------- */

export const getEngineState = () => request<EngineState>('/api/status');
export const getCounts = () => request<LaneCount[]>('/api/counts');

/* --- Geocodificación ---------------------------------------------------
   Pasa por nuestro backend, no por Nominatim directo: su política exige
   User-Agent propio, un máximo de 1 petición por segundo y cachear los
   resultados, y eso solo se puede garantizar del lado del servidor. */

export const geoSearch = (q: string) =>
  request<GeoResult[]>(`/api/geo/search?q=${encodeURIComponent(q)}`);

export const geoReverse = (lat: number, lon: number) =>
  request<GeoResult>(`/api/geo/reverse?lat=${lat}&lon=${lon}`);

/* --- Imágenes de calibración ------------------------------------------- */

export async function fetchImage(url: string): Promise<HTMLImageElement> {
  const res = await fetch(url);
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    const detail =
      body && typeof body === 'object' && 'detail' in body
        ? textoDelDetalle((body as { detail: unknown }).detail, res.status)
        : `El servidor respondió ${res.status}.`;
    throw new ApiError(detail, res.status);
  }
  const blobUrl = URL.createObjectURL(await res.blob());
  try {
    const img = new Image();
    await new Promise<void>((resolve, reject) => {
      img.onload = () => resolve();
      img.onerror = () => reject(new Error('La imagen llegó dañada.'));
      img.src = blobUrl;
    });
    return img;
  } finally {
    // El <img> ya decodificó los bytes; el blob puede liberarse enseguida.
    URL.revokeObjectURL(blobUrl);
  }
}

export const snapshotUrl = (projectId: number) => `/api/camera/snapshot?project_id=${projectId}`;

/* --- Recorrido del video ------------------------------------------------
   Los cuadros se piden por índice, no por segundos: calibrar exige avanzar
   de uno en uno para dar con el instante exacto del cruce, y con segundos
   en coma flotante el mismo valor puede caer en un cuadro o en el
   siguiente según cómo redondee. */

export const listVideoSegments = (projectId: number) =>
  request<VideoSegment[]>(`/api/frames/videos?project_id=${projectId}`);

export const frameUrl = (jobId: number, frame: number, fuente: FuenteVideo = 'original') =>
  `/api/frames/frame?job_id=${jobId}&frame=${frame}&fuente=${fuente}`;
export const getFrameDetections = (jobId: number, frame: number) =>
  request<{ frame: number; detections: FrameDetection[] }>(
    `/api/frames/detections?job_id=${jobId}&frame=${frame}`,
  );

export const heatmapUrl = (projectId: number) => `/api/camera/heatmap?project_id=${projectId}`;

/* --- Mensaje de error legible ------------------------------------------ */

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return 'Ocurrió un error inesperado.';
}
