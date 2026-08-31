/*
  Formas de datos que devuelve la API de FastAPI.

  Están escritas a mano contra src/api/routes_*.py y src/storage/*.py.
  Los nombres de campo son los del backend (snake_case) a propósito: una
  capa de traducción a camelCase solo agregaría un lugar más donde un
  cambio del backend puede pasar desapercibido.
*/

export type JobStatus =
  | 'awaiting_calibration'
  | 'queued'
  | 'processing'
  | 'done'
  | 'error';

export type EngineStatus = 'running' | 'starting' | 'stopped' | 'error';

export interface Project {
  id: number;
  name: string;
  description: string | null;
  latitude: number | null;
  longitude: number | null;
  address: string | null;
  interval_minutes: number;
  created_at: string;
  updated_at: string;
  /* Estadísticas acumuladas que agrega el endpoint de listado. */
  video_count: number;
  lane_count: number;
  crossing_count: number;
  awaiting_count: number;
}

export interface ProjectCreate {
  name: string;
  description?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  address?: string | null;
  interval_minutes?: number;
}

export interface Lane {
  id: number;
  project_id: number;
  name: string;
  /* Exactamente dos puntos: [[x1, y1], [x2, y2]] en píxeles del frame. */
  points: [Point, Point];
}

export type Point = [number, number];

/**
 * Área dibujada sobre el video que delimita una calzada.
 *
 * Complementa a Lane, no la reemplaza: la línea dice DÓNDE se cuenta y la
 * zona dice CUÁL calzada es. En perspectiva las dos calzadas quedan una
 * encima de la otra, así que una sola línea cruza ambas y sin la zona no
 * hay forma de separar los sentidos.
 */
/** Detección calculada al vuelo sobre un cuadro del video original. */
export interface FrameDetection {
  bbox: [number, number, number, number];
  confidence: number;
  class_name: string;
  /** false = la descartó el filtro de zonas. Se muestra igual, en gris. */
  en_zona: boolean;
  zona_id: number | null;
}

export interface Zone {
  id: number;
  project_id: number;
  name: string;
  /** 'calzada' cuenta y atribuye; 'excluir' descarta lo que caiga dentro. */
  kind: 'calzada' | 'excluir';
  /** Tres o más vértices, en píxeles del frame. */
  points: Point[];
}

export interface VideoJob {
  id: number;
  original_name: string;
  source_label: string;
  status: JobStatus;
  size_bytes: number;
  total_frames: number | null;
  processed_frames: number;
  video_start_time: string | null;
  error: string | null;
}

export interface VehicleCounts {
  in: number;
  out: number;
}

export interface LaneCount {
  lane_id: number;
  lane_name: string;
  in: number;
  out: number;
  total: number;
  by_vehicle_type: Record<string, VehicleCounts>;
}

export interface EngineState {
  status: EngineStatus;
  camera_source: string;
  frame_width: number;
  frame_height: number;
  fps_estimate: number;
  last_error: string | null;
}

export interface Interval {
  start: string;
  end: string;
  in: number;
  out: number;
  total: number;
  by_vehicle_type?: Record<string, VehicleCounts>;
}

export interface PeakHour {
  start: string;
  end: string;
  volume: number;
  fhp: number | null;
  subperiodos: number;
  peak_interval_start: string;
  peak_interval_volume: number;
  flujo_irregular: boolean;
}

export interface LaneMetrics {
  lane_id: number;
  lane_name: string;
  total: number;
  in: number;
  out: number;
  composition: Record<string, number>;
  peak_hour: PeakHour | null;
  intervals: Interval[];
}

export interface ProjectMetrics {
  interval_minutes: number;
  totals: { in: number; out: number; total: number };
  composition: Record<string, number>;
  composition_pct: Record<string, number>;
  peak_hour: PeakHour | null;
  combined_intervals: Interval[];
  lanes: LaneMetrics[];
}

export interface GeoResult {
  display_name: string;
  latitude: number | null;
  longitude: number | null;
}

/*
  Un video de la intersección tal como lo describe /api/frames/videos.
  Las claves vienen en español porque así las manda ese router; traducirlas
  aquí solo añadiría un sitio más donde un cambio del backend pasa
  desapercibido.
*/
export interface VideoSegment {
  job_id: number;
  nombre: string;
  estado: JobStatus;
  fps: number;
  total_frames: number;
  duracion_s: number;
  /* Pueden venir sin saberse: el listado no abre los archivos para
     averiguarlas — el cliente las toma del primer cuadro que carga, que
     es exacto y no cuesta una apertura por video. */
  ancho: number | null;
  alto: number | null;
  hora_inicio: string | null;
  /** Si ya existe la versión que dibujó la IA sobre este video. */
  tiene_procesado: boolean;
}

/** Qué video se está viendo: la grabación tal cual, o la anotada por la IA. */
export type FuenteVideo = 'original' | 'procesado';
