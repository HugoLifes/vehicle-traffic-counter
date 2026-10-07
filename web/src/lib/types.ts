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
  /* Aforo direccional: movimientos contados y accesos dibujados. */
  movement_count?: number;
  access_count?: number;
  /* Cruces con la clase de pesado revisada sobre su recorte; recontar la borra. */
  revisados_count?: number;
  /* Videos con la velocidad pendiente de medir sin recontar. */
  velocidad_pendiente?: number;
  /* Si el vehículo se ve grande (cámara de frente o cercana) o chico
     (lejana o de lado). Lo decide el servidor a partir de lo guardado. */
  tipo_camara?: TipoCamara;
  video_anotado?: number | boolean;
}

export type TipoCamara = 'grandes' | 'chicos';

/** Un aforo solo direccional cuenta movimientos, no cruces de línea. */
export function esDireccional(p: Pick<Project, 'crossing_count' | 'movement_count'>): boolean {
  return p.crossing_count === 0 && (p.movement_count ?? 0) > 0;
}

/** Lo contado en la intersección: cruces de línea o movimientos. */
export function contados(p: Pick<Project, 'crossing_count' | 'movement_count'>): number {
  return esDireccional(p) ? (p.movement_count ?? 0) : p.crossing_count;
}

export interface ProjectCreate {
  name: string;
  description?: string | null;
  latitude?: number | null;
  longitude?: number | null;
  address?: string | null;
  interval_minutes?: number;
  tipo_camara?: TipoCamara;
  video_anotado?: boolean;
}

export interface Lane {
  id: number;
  project_id: number;
  name: string;
  /* Exactamente dos puntos: [[x1, y1], [x2, y2]] en píxeles del frame. */
  points: [Point, Point];
  /* Tramo de velocidad: null si la línea solo cuenta. */
  tramo?: Tramo | null;
}

/**
 * Segunda línea del tramo de velocidad y la distancia en el pavimento hasta
 * la línea de conteo. Es el equivalente a las dos mangueras del contador de
 * ejes: la velocidad sale de cuánto tarda cada vehículo en pasar de una a
 * otra.
 */
export interface Tramo {
  linea: [Point, Point];
  distancia_m: number;
}

/* Velocidad de punto de un grupo de vehículos, en km/h. */
export interface VelocidadResumen {
  n: number;
  media: number | null;
  p15: number | null;
  p50: number | null;
  p85: number | null;
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

/** Documento indexado en el RAG. Sin project_id = aplica a todas las
    intersecciones (normativa general); con él, es de esa intersección. */
export interface RagDocumento {
  id: number;
  project_id: number | null;
  name: string;
  kind: string;
  size_bytes: number;
  chunks: number;
  created_at: string;
}

export interface RagFuente {
  n: number;
  documento: string;
  pagina: number | null;
  extracto: string;
  doc_id: number;
  /** De qué motor de búsqueda vino: sirve para ver si la híbrida aporta. */
  en_vectorial: boolean;
  en_lexica: boolean;
}

export interface RagConversacion {
  id: number;
  project_id: number | null;
  titulo: string;
  mensajes: number;
  updated_at: string;
}

export interface RagMensaje {
  id: number;
  rol: 'user' | 'assistant';
  texto: string;
  fuentes: RagFuente[];
  created_at: string;
}

export interface RagRespuesta {
  respuesta: string;
  fuentes: RagFuente[];
}

/* --- Diagnóstico de encuadre -------------------------------------------- */

/** Qué tan apto es el encuadre para aforar, medido ANTES de contar.
    No promete un porcentaje de exactitud: `razon_esperada` es el rango
    contra conteo manual que corresponde al veredicto, y los avisos dicen
    qué cambiar. */
export interface DiagnosticoEncuadre {
  puntaje: number;
  veredicto: string;
  color: 'verde' | 'ambar' | 'rojo';
  avisos: string[];
  razon_esperada: [number, number] | null;
  etapa: string;
  /** Puntaje de cada etapa cuando se corrieron las dos. `rastreo` viene en
      null cuando esa etapa no fue concluyente (poco tránsito en el minuto
      de prueba), y entonces manda la etapa por imagen. */
  imagen?: number;
  rastreo?: number | null;
}

export interface DiagnosticoGuardado {
  job_id: number;
  puntaje: number;
  veredicto: string;
  color: 'verde' | 'ambar' | 'rojo';
  etapa: string;
  created_at: string;
  datos: {
    medidas: Record<string, unknown>;
    rastreo: Record<string, number> | null;
    diagnostico: DiagnosticoEncuadre;
  };
}

/* --- Aforo direccional (origen-destino) --------------------------------- */

export interface MovimientoOD {
  intervalo: string;
  origen_id: number;
  destino_id: number;
  vehicle_type: string;
  total: number;
}

/** Vehículo del que se vio el origen o el destino, no ambos. */
export interface IncompletoOD {
  intervalo: string;
  origen_id: number | null;
  destino_id: number | null;
  total: number;
}

/** Cuántos vehículos entraron y salieron por un acceso en un intervalo.
    Incluye los movimientos incompletos: uno del que no se vio el destino
    sigue diciendo por dónde entró. */
export interface VolumenAcceso {
  intervalo: string;
  acceso_id: number;
  entradas: number;
  salidas: number;
}

export interface AforoDireccional {
  /** id del acceso → nombre. Las llaves llegan como texto (JSON). */
  accesos: Record<string, string>;
  intervalo_minutos: number;
  /** 'trayectoria': cada vehículo se decidió por la forma de su recorrido;
      'zonas': solo por los accesos que pisó (videos contados antes de
      guardar recorridos). */
  metodo: 'trayectoria' | 'zonas';
  /** Cuántos vehículos se decidieron de cada forma y por qué quedaron los
      demás sin decidir. */
  resumen_metodo: Record<string, number>;
  movimientos: MovimientoOD[];
  incompletos: IncompletoOD[];
  por_acceso: VolumenAcceso[];
}

export interface Zone {
  id: number;
  project_id: number;
  name: string;
  /** 'calzada' cuenta y atribuye; 'excluir' descarta lo que caiga dentro;
      'acceso' es un brazo de la intersección para el aforo direccional. */
  kind: 'calzada' | 'excluir' | 'acceso';
  /** Tres o más vértices, en píxeles del frame. */
  points: Point[];
}

export interface VideoJob {
  id: number;
  /* A qué intersección pertenece. Lo devuelve la API desde siempre; hacía
     falta declararlo para que el vigilante pueda llevar al usuario al
     proyecto correcto cuando avisa de que un video terminó. */
  project_id: number;
  original_name: string;
  source_label: string;
  status: JobStatus;
  size_bytes: number;
  total_frames: number | null;
  processed_frames: number;
  video_start_time: string | null;
  error: string | null;
  /* Avisos del último conteo: zona que descarta casi todo, vehículos que no
     cruzaron ninguna línea, archivo cortado. Null si no hubo nada que avisar. */
  aviso?: string | null;
  /* Cuadros por segundo del archivo y cuándo empezó a contarse (UTC, como lo
     guarda SQLite): con ellos se sabe a qué velocidad va el análisis. */
  fps?: number | null;
  started_at?: string | null;
  /* Ruta del video con detecciones; null si todavía no hay. */
  output_video_path?: string | null;
  /* Video con detecciones pedido para un video ya contado: en cola, generándose
     (con su avance en %) o con error. Null si no hay nada pendiente. */
  anotado_estado?: 'en_cola' | 'generando' | 'error' | null;
  anotado_avance?: number | null;
  /* Revisión del encuadre pedida: en la cola de la GPU, revisándose o con
     error (y su motivo). Null cuando no hay nada pendiente. */
  diag_estado?: 'en_cola' | 'revisando' | 'error' | null;
  /* Resumen de la revisión de encuadre ya hecha (null si no hay): viene en
     la lista para no pedirla video por video. */
  diag_color?: 'verde' | 'ambar' | 'rojo' | null;
  diag_veredicto?: string | null;
  diag_puntaje?: number | null;
  diag_error?: string | null;
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
  velocidad?: VelocidadResumen;
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
  /* Desglose de la A (AUTO, CAMIONETA, PICKUP, SIN_SUBTIPO); suma la A. */
  subtipos_A?: Record<string, number>;
  /* null = en este carril el vehículo se ve demasiado pequeño para separar
     liviano de pesado, así que no se entrega desglose por tipo. */
  umbral_pesado_px: number | null;
  tramo?: Tramo | null;
  /* El automóvil como regla: con la distancia capturada, cuánto medirían
     de alto los automóviles del carril. 'revisar' = la distancia no cuadra. */
  control_tramo?: {
    estado: 'coherente' | 'revisar' | 'no_aplica' | 'sin_datos';
    alto_auto_m: number | null;
  } | null;
  velocidad?: VelocidadResumen | null;
  peak_hour: PeakHour | null;
  intervals: Interval[];
}

export interface ProjectMetrics {
  interval_minutes: number;
  totals: { in: number; out: number; total: number };
  composition: Record<string, number>;
  /* Porcentajes sobre los vehículos que SÍ se clasificaron, no sobre el
     total: los no clasificados van aparte para que no salgan compitiendo
     como si fueran un tipo de vehículo más. */
  composition_pct: Record<string, number>;
  subtipos_A?: Record<string, number>;
  sin_clasificar: number;
  sin_clasificar_pct: number;
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
  /** Si el original se puede reproducir como video en el navegador. */
  original_reproducible?: boolean;
}

/** Qué video se está viendo: la grabación tal cual, o la anotada por la IA. */
export type FuenteVideo = 'original' | 'procesado';


/* --- Ficha de la cámara --------------------------------------------------
   Qué tan buen material está recibiendo el detector. El alto del vehículo
   se mide cruce a cruce; `con_medida` dice sobre cuántos, porque un
   percentil de veinte muestras no vale lo mismo que uno de cuarenta mil. */
export interface AlturaVehiculo {
  con_medida: number;
  mediana: number | null;
  p10: number | null;
  p90: number | null;
}

export interface FichaCamara {
  videos: number;
  videos_muestreados: number;
  resoluciones: { resolucion: string; muestras: number }[];
  fps: number | null;
  bitrate_kbps: number | null;
  altura_vehiculo: AlturaVehiculo;
  alto_necesario_px: number;
  bitrate_minimo_kbps: number;
  avisos: string[];
}

/* --- Registro del proyecto ----------------------------------------------- */

export type TipoEvento = 'proyecto' | 'video' | 'calibracion' | 'conteo';

export interface EventoProyecto {
  id: number;
  kind: TipoEvento;
  summary: string;
  detail: string | null;
  created_at: string;
}
