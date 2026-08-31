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
} from './types';
import type { FuenteVideo } from './types';

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
        ? String((body as { detail: unknown }).detail)
        : `El servidor respondió ${res.status}.`;
    throw new ApiError(detail, res.status);
  }

  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
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

/* --- Videos ------------------------------------------------------------ */

export const listVideos = (projectId?: number) =>
  request<VideoJob[]>(projectId ? `/api/videos?project_id=${projectId}` : '/api/videos');

export const deleteVideo = (jobId: number) =>
  request<void>(`/api/videos/${jobId}`, { method: 'DELETE' });

export const uploadVideos = (form: FormData) =>
  request<{ jobs: VideoJob[]; rejected: { filename: string; reason: string }[] }>(
    '/api/videos/upload',
    { method: 'POST', body: form },
  );

export const getMetrics = (projectId: number, minutes: number) =>
  request<ProjectMetrics>(`/api/videos/metrics?project_id=${projectId}&minutes=${minutes}`);

export const videoUrl = (jobId: number) => `/api/videos/${jobId}/video`;

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
        ? String((body as { detail: unknown }).detail)
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
export const heatmapUrl = (projectId: number) => `/api/camera/heatmap?project_id=${projectId}`;

/* --- Mensaje de error legible ------------------------------------------ */

export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return 'Ocurrió un error inesperado.';
}
