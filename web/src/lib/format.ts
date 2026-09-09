/*
  Formato y vocabulario en español.

  Todo lo que el usuario lee pasa por aquí. Antes había etiquetas crudas
  del backend filtrándose a la interfaz: la cámara mostraba `running` y
  `starting` en una interfaz enteramente en español, y los tipos de
  vehículo salían como `car` y `truck`.
*/

import type { EngineStatus, JobStatus } from './types';

/* Las categorías son las de la SCT, no las del detector.
   `truck` de COCO mezcla la pickup con el tractocamión, y traducirlo a
   "Camión" hacía que el reporte declarara 1 501 camiones donde el aforo
   manual contó 417. Ahora el backend entrega A / PESADO / SIN_RESOLVER,
   verificado vehículo por vehículo contra el conteo manual.

   Las clases de COCO siguen aquí porque la cámara en vivo todavía las
   emite sin pasar por la traducción. */
export const VEHICLE_LABEL: Record<string, string> = {
  A: 'Liviano (A)',
  PESADO: 'Pesado',
  SIN_RESOLVER: 'Sin clasificar',
  car: 'Automóvil',
  truck: 'Camión o camioneta',
  bus: 'Autobús',
  motorcycle: 'Motocicleta',
};

export const VEHICLE_LABEL_PLURAL: Record<string, string> = {
  A: 'livianos',
  PESADO: 'pesados',
  SIN_RESOLVER: 'sin clasificar',
  car: 'automóviles',
  truck: 'camiones o camionetas',
  bus: 'autobuses',
  motorcycle: 'motocicletas',
};

/* Por qué un carril puede no traer desglose por tipo. Se muestra en vez
   de la gráfica de composición, para que "sin datos" no se confunda con
   "no pasaron vehículos". */
export const SIN_CLASIFICAR_MOTIVO =
  'En esta calzada el vehículo se ve demasiado pequeño para separar liviano ' +
  'de pesado de forma defendible, así que no se entrega el desglose por tipo.';

export const vehicleLabel = (type: string) => VEHICLE_LABEL[type] ?? type;

/* Cada categoría toma su color del tema, para que la gráfica siga siendo
   legible en claro y en oscuro. Los valores viven en tokens.css. */
export const vehicleColorVar = (type: string) =>
  VEHICLE_LABEL[type] ? `var(--veh-${type})` : 'var(--veh-other)';

export const JOB_STATUS_LABEL: Record<JobStatus, string> = {
  awaiting_calibration: 'Falta calibrar',
  queued: 'En cola',
  processing: 'Procesando',
  done: 'Listo',
  error: 'Error',
};

export const ENGINE_STATUS_LABEL: Record<EngineStatus, string> = {
  running: 'En marcha',
  starting: 'Iniciando',
  stopped: 'Detenida',
  error: 'Con error',
};

export type Tone = 'neutral' | 'good' | 'warning' | 'critical' | 'accent';

export const JOB_STATUS_TONE: Record<JobStatus, Tone> = {
  // Esperar calibración no es un aviso ni un error: es un paso normal
  // del flujo, así que va en neutro y no en ámbar.
  awaiting_calibration: 'neutral',
  queued: 'warning',
  processing: 'warning',
  done: 'good',
  error: 'critical',
};

export const ENGINE_STATUS_TONE: Record<EngineStatus, Tone> = {
  running: 'good',
  starting: 'warning',
  stopped: 'neutral',
  error: 'critical',
};

/* --- Números y tamaños -------------------------------------------------- */

const nf = new Intl.NumberFormat('es-MX');
export const formatNumber = (n: number) => nf.format(n);

export function formatSize(bytes: number | null | undefined): string {
  if (!bytes) return '—';
  const units = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  let v = bytes;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i += 1;
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`;
}

/*
  Nunca se arma una frase pegando trozos alrededor de un número: el orden
  de las palabras cambia entre idiomas y el plural no siempre es "+s".
  Estas funciones devuelven la frase entera.
*/
export const plural = (n: number, one: string, many: string) =>
  `${formatNumber(n)} ${n === 1 ? one : many}`;

/* --- Fechas y horas ----------------------------------------------------- */

/** Toma solo HH:MM de un ISO local del backend (sin zona horaria). */
export const hhmm = (iso: string) => iso.slice(11, 16);

export const intervalLabel = (start: string, end: string) => `${hhmm(start)} – ${hhmm(end)}`;

export function todayISO(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

/*
  Reconoce nombres tipo "08-00-08_2ta.mkv" (HH-MM-SS al principio) —
  patrón habitual en las exportaciones de cámaras de tránsito. Ahorra
  teclear la hora real de cada segmento, que es lo que ubica los conteos
  en su intervalo correcto.
*/
export function guessStartTime(filename: string): string | null {
  const m = filename.match(/^(\d{2})[-:_.](\d{2})[-:_.](\d{2})/);
  if (!m) return null;
  const [, hh, mm, ss] = m;
  if (+hh > 23 || +mm > 59 || +ss > 59) return null;
  return `${hh}:${mm}:${ss}`;
}

export function fileExtension(filename: string): string {
  const i = filename.lastIndexOf('.');
  return i === -1 ? '' : filename.slice(i).toLowerCase();
}
