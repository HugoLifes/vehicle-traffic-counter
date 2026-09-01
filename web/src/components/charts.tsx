/*
  Gráficas en SVG puro — sin librería, para no cargar otro bundle en un
  equipo que ya está ocupado corriendo YOLO.

  Decisiones de encoding:
  · Barras para comparar intervalos, con el eje SIEMPRE anclado en cero:
    en un aforo, truncar el eje exagera visualmente diferencias de tránsito
    que pueden ser de dos o tres vehículos.
  · Etiqueta directa sobre la barra en lugar de leyenda cuando cabe.
  · La paleta por tipo de vehículo sale de tokens de tema (--veh-*), así
    que se re-mapea en modo oscuro. La paleta anterior estaba fijada a
    valores de tema claro y el azul de "automóvil" quedaba en 2.54:1
    sobre el fondo oscuro: la categoría más frecuente era la menos
    legible justo donde más se usa la pantalla.
  · Toda gráfica va acompañada de su tabla equivalente, que es la
    alternativa accesible y además lo que un ingeniero necesita para
    copiar cifras exactas al informe.
*/

import { vehicleColorVar, vehicleLabel } from '../lib/format';
import type { Interval } from '../lib/types';

const W = 720;
const H = 260;
const PAD = { top: 24, right: 16, bottom: 46, left: 46 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

interface IntervalChartProps {
  intervals: Interval[];
  peakIntervalStart?: string | null;
}

export function IntervalChart({ intervals, peakIntervalStart }: IntervalChartProps) {
  if (!intervals.length) {
    return <div className="chart-empty">Todavía no hay cruces que graficar en este carril.</div>;
  }

  const maxVal = Math.max(...intervals.map((i) => i.total), 1);
  // Escala redondeada hacia arriba para que la cuadrícula caiga en
  // números limpios (0, 5, 10, 15, 20) y no en 3.7 o 7.4.
  const step = Math.max(1, Math.ceil(maxVal / 4));
  const yMax = step * 4;

  const slot = PLOT_W / intervals.length;
  const barGap = Math.min(4, slot * 0.2);
  /*
    Se limita el ancho de barra. Con un aforo corto (dos o tres intervalos)
    cada barra ocupaba un tercio del ancho y la gráfica dejaba de leerse
    como una serie de tiempo para parecer un bloque de color. Cuando sobra
    espacio, la barra se centra en su casilla en vez de estirarse.
  */
  const barW = Math.max(2, Math.min(slot - barGap, 56));
  const x = (i: number) => PAD.left + i * slot + (slot - barW) / 2;
  const y = (v: number) => PAD.top + PLOT_H - (v / yMax) * PLOT_H;

  const avg = intervals.reduce((s, i) => s + i.total, 0) / intervals.length;

  /*
    Con muchos intervalos (una hora entera en tramos de un minuto son 60
    barras) las etiquetas del eje se encimaban hasta volverse una mancha.
    Se dibuja una de cada N, calculando N a partir del ancho real que
    ocupa "08:15" a 11px. Prefiero menos etiquetas legibles que todas
    ilegibles.
  */
  const LABEL_W = 34;
  const stride = Math.max(1, Math.ceil(LABEL_W / slot));
  const showValues = barW >= 22;

  const ticks = Array.from({ length: 5 }, (_, t) => step * t);

  return (
    <svg
      className="chart"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      aria-label={`Volumen de vehículos por intervalo. Máximo ${maxVal}, promedio ${avg.toFixed(1)}. Las cifras exactas están en la tabla debajo de la gráfica.`}
    >
      {ticks.map((val) => (
        <g key={val}>
          <line className="chart-grid" x1={PAD.left} y1={y(val)} x2={W - PAD.right} y2={y(val)} />
          <text className="chart-axis" x={PAD.left - 8} y={y(val) + 4} textAnchor="end">
            {val}
          </text>
        </g>
      ))}

      {/* Referencia: promedio del periodo. Sin ella no se puede saber si
          un intervalo está por encima o por debajo de lo normal del aforo. */}
      <line className="chart-avg" x1={PAD.left} y1={y(avg)} x2={W - PAD.right} y2={y(avg)} />
      <text className="chart-avg-label" x={W - PAD.right} y={y(avg) - 5} textAnchor="end">
        promedio {avg.toFixed(1)}
      </text>

      {intervals.map((iv, i) => {
        const isPeak = Boolean(peakIntervalStart) && iv.start === peakIntervalStart;
        const h = Math.max(iv.total > 0 ? 2 : 0, (iv.total / yMax) * PLOT_H);
        const top = PAD.top + PLOT_H - h;
        const label = iv.start.slice(11, 16);
        return (
          <g className="chart-bar-group" key={iv.start}>
            <rect
              className={`chart-bar${isPeak ? ' is-peak' : ''}`}
              x={x(i)}
              y={top}
              width={barW}
              height={h}
              rx={Math.min(3, barW / 2)}
              /* Escalón de 12 ms, no de los 30-50 habituales, y con tope
                 a 300 ms. Un aforo de 24 horas trae 96 barras: a 30 ms el
                 recorrido duraría 2,9 s, muy por encima del máximo de
                 700 ms que hace que una secuencia se lea como una sola
                 cosa. Con el tope, el total queda en 700 ms exactos sin
                 importar cuántas barras haya. */
              style={{ animationDelay: `${Math.min(i * 12, 300)}ms` }}
            >
              <title>{`${label} — ${iv.total} vehículos (${iv.in} entrada / ${iv.out} salida)`}</title>
            </rect>
            {showValues && iv.total > 0 && (
              <text className="chart-value" x={x(i) + barW / 2} y={top - 6} textAnchor="middle">
                {iv.total}
              </text>
            )}
            {i % stride === 0 && (
              <text
                className="chart-axis"
                x={x(i) + barW / 2}
                y={H - PAD.bottom + 18}
                textAnchor="middle"
              >
                {label}
              </text>
            )}
          </g>
        );
      })}

      <text className="chart-axis-title" x={PAD.left} y={H - 6}>
        Hora de inicio del intervalo
      </text>
    </svg>
  );
}

/*
  Composición vehicular como barra apilada horizontal.

  Apilada y no dona porque el dato que importa es la proporción relativa
  entre dos y cuatro categorías, y una barra permite leer los porcentajes
  en línea sin comparar ángulos.
*/
export function CompositionChart({
  composition,
  total,
}: {
  composition: Record<string, number>;
  total: number;
}) {
  const entries = Object.entries(composition)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1]);

  if (!entries.length || !total) {
    return <div className="chart-empty">Ningún vehículo clasificado todavía.</div>;
  }

  const summary = entries
    .map(([t, n]) => `${vehicleLabel(t)} ${((n / total) * 100).toFixed(1)} por ciento`)
    .join(', ');

  return (
    <>
      <div className="comp-bar" role="img" aria-label={`Composición vehicular: ${summary}.`}>
        {entries.map(([type, n]) => (
          <div
            key={type}
            className="comp-seg"
            style={{ width: `${(n / total) * 100}%`, background: vehicleColorVar(type) }}
            title={`${vehicleLabel(type)}: ${n} (${((n / total) * 100).toFixed(1)}%)`}
          />
        ))}
      </div>
      {/* La leyenda lleva el nombre y la cifra, no solo el color: la barra
          por sí sola no se puede leer sin distinguir los tonos. */}
      <div className="comp-legend">
        {entries.map(([type, n]) => (
          <div className="comp-legend-item" key={type}>
            <span className="comp-swatch" style={{ background: vehicleColorVar(type) }} />
            <span className="comp-label">{vehicleLabel(type)}</span>
            <span className="comp-num">{n}</span>
            <span className="comp-pct">{((n / total) * 100).toFixed(1)}%</span>
          </div>
        ))}
      </div>
    </>
  );
}
