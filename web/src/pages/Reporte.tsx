/*
  Reporte de aforo: métricas de ingeniería de tránsito, gráficas por
  intervalo y la tabla con las cifras exactas.

  El orden no es casual — va de lo más resumido a lo más detallado:
   1. Métricas del estudio      → ¿cuál es la conclusión?
   2. Gráfica por intervalo     → ¿cómo se distribuyó el tránsito?
   3. Tabla exacta, plegada     → ¿qué cifras van al informe?
*/

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Card, EmptyState, Notice, Pill, SelectField } from '../components/ui';
import { IconDownload, IconPrint } from '../components/Icons';
import { CompositionChart, IntervalChart } from '../components/charts';
import { EscenaFlujo } from '../components/EscenaFlujo';
import { useMetrics } from '../lib/queries';
import { useProjectParam } from '../lib/useProjectParam';
import {
  errorMessage,
  exportAforoExcelUrl,
  exportIntervalsUrl,
  exportSummaryUrl,
} from '../lib/api';
import {
  VEHICLE_LABEL_PLURAL,
  formatNumber,
  hhmm,
  intervalLabel,
  plural,
} from '../lib/format';
import type { LaneMetrics, ProjectMetrics } from '../lib/types';

const INTERVALS = [5, 10, 15, 30, 60];

/* --- Resumen del estudio ------------------------------------------------ */

function Metrics({ m }: { m: ProjectMetrics }) {
  const peak = m.peak_hour;
  const topType = Object.entries(m.composition_pct).sort((a, b) => b[1] - a[1])[0];

  return (
    /*
      Una sola entrada visual y cuatro cifras de apoyo.

      Antes eran cinco tarjetas iguales, con los cinco números al mismo
      tamaño: el volumen del aforo, la hora pico, el FHP, la composición
      y el porcentaje sin desglose competían entre sí y ninguno leía
      como la conclusión. El volumen es lo que se entrega; el resto lo
      matiza.
    */
    <section className="reporte-resumen" aria-label="Resumen del estudio">
      <div className="rr-hero rise">
        <div className="rr-hero-label">Volumen total</div>
        <div className="rr-hero-n">{formatNumber(m.totals.total)}</div>
        <div className="rr-hero-sub">vehículos cruzaron las líneas de conteo</div>
        <div className="rr-split">
          <div className="rr-split-item">
            <span className="num">{formatNumber(m.totals.in)}</span>
            <span>entrada</span>
          </div>
          <div className="rr-split-item">
            <span className="num">{formatNumber(m.totals.out)}</span>
            <span>salida</span>
          </div>
        </div>
      </div>

      <div className="rr-grid stagger">
        {peak ? (
          <Card className="metric-card">
            <div className="m-label">Hora de máxima demanda</div>
            <div className="m-value is-compact">
              {hhmm(peak.start)}–{hhmm(peak.end)}
            </div>
            <div className="m-sub">
              {plural(peak.volume, 'vehículo en la hora', 'vehículos en la hora')}
            </div>
          </Card>
        ) : (
          <Card className="metric-card">
            <div className="m-label">Hora de máxima demanda</div>
            <div className="m-value is-compact" style={{ color: 'var(--text-muted)' }}>
              —
            </div>
            <div className="m-sub">
              Se necesita al menos una hora completa de aforo para calcular la hora pico y el FHP.
            </div>
          </Card>
        )}

        {peak && peak.fhp !== null && (
          <Card className="metric-card">
            <div className="m-label">Factor de hora pico (FHP)</div>
            <div className="m-value">{peak.fhp.toFixed(3)}</div>
            {/* El FHP se muestra siempre junto a su umbral: el número solo no
                dice nada si no sabes contra qué compararlo. */}
            <div className="m-sub">
              {peak.volume} ÷ ({peak.subperiodos} × {peak.peak_interval_volume})
            </div>
            <span className={`m-flag ${peak.flujo_irregular ? 'warn' : 'ok'}`}>
              {peak.flujo_irregular ? 'Flujo irregular (< 0.85)' : 'Flujo parejo (≥ 0.85)'}
            </span>
          </Card>
        )}

        {topType && (
          <Card className="metric-card">
            <div className="m-label">Composición dominante</div>
            <div className="m-value">{topType[1]}%</div>
            <div className="m-sub">
              {VEHICLE_LABEL_PLURAL[topType[0]] ?? topType[0]}
              {/* Sobre qué base está calculado ese porcentaje. Sin esto se
                  lee como si cubriera todo el aforo, cuando puede haber una
                  calzada entera sin desglose por tipo. */}
              {m.sin_clasificar > 0 &&
                ` · sobre ${formatNumber(m.totals.total - m.sin_clasificar)} de ${formatNumber(m.totals.total)} vehículos`}
            </div>
          </Card>
        )}

        {m.sin_clasificar > 0 && (
          <Card className="metric-card">
            <div className="m-label">Sin desglose por tipo</div>
            <div className="m-value">{m.sin_clasificar_pct}%</div>
            <div className="m-sub">
              {formatNumber(m.sin_clasificar)} vehículos en calzadas donde se ven
              demasiado pequeños para separar liviano de pesado
            </div>
          </Card>
        )}
      </div>
    </section>
  );
}

/* --- Reporte por carril -------------------------------------------------- */

function LaneReport({ lane, intervalMinutes }: { lane: LaneMetrics; intervalMinutes: number }) {
  if (!lane.intervals.length) {
    return (
      <section className="lane-report">
        <h2>{lane.lane_name}</h2>
        <EmptyState
          title="Sin cruces registrados"
          body="Este carril todavía no ha contado ningún vehículo. Revisa que la línea cruce la trayectoria del tránsito."
        />
      </section>
    );
  }

  const peakStart = lane.peak_hour?.peak_interval_start ?? null;
  const maxTotal = Math.max(...lane.intervals.map((i) => i.total));

  return (
    <section className="lane-report">
      <h2>{lane.lane_name}</h2>

      <div className="summary-row">
        <Pill>
          Total <span className="value">{formatNumber(lane.total)}</span>
        </Pill>
        <Pill>
          Entrada <span className="value">{formatNumber(lane.in)}</span>
        </Pill>
        <Pill>
          Salida <span className="value">{formatNumber(lane.out)}</span>
        </Pill>
        <Pill>
          {lane.intervals.length} × {intervalMinutes} min
        </Pill>
        {lane.peak_hour?.fhp != null && (
          <Pill>
            FHP <span className="value">{lane.peak_hour.fhp.toFixed(3)}</span>
          </Pill>
        )}
      </div>

      <Card className="chart-card">
        <h3>Volumen por intervalo</h3>
        <p className="chart-sub">
          Cada barra es un periodo de {intervalMinutes} minutos. La barra ámbar es el intervalo de
          mayor demanda.
        </p>
        <IntervalChart intervals={lane.intervals} peakIntervalStart={peakStart} />
      </Card>

      {lane.total > 0 && (
        <Card className="chart-card">
          <h3>Composición vehicular</h3>
          <p className="chart-sub">Proporción por tipo sobre el total del carril.</p>
          <CompositionChart composition={lane.composition} total={lane.total} />
        </Card>
      )}

      <details className="disclosure">
        <summary>Ver la tabla de cifras exactas</summary>
        <div className="table-scroll">
          <table className="data-table">
            <caption className="visually-hidden">
              Conteos por intervalo del carril {lane.lane_name}.
            </caption>
            <thead>
              <tr>
                <th scope="col">Intervalo</th>
                <th scope="col" className="num">
                  Entrada
                </th>
                <th scope="col" className="num">
                  Salida
                </th>
                <th scope="col" className="num">
                  Total
                </th>
              </tr>
            </thead>
            <tbody>
              {lane.intervals.map((iv) => {
                const isPeak = peakStart
                  ? iv.start === peakStart
                  : iv.total === maxTotal && maxTotal > 0;
                return (
                  <tr key={iv.start} className={isPeak ? 'is-peak' : undefined}>
                    <td>
                      {intervalLabel(iv.start, iv.end)}
                      {/* El pico se marca con texto además del color de fila. */}
                      {isPeak && ' — pico'}
                    </td>
                    <td className="num">{iv.in}</td>
                    <td className="num">{iv.out}</td>
                    <td className="num">{iv.total}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}

/* --- Página --------------------------------------------------------------- */

export default function Reporte() {
  const { projectId, project } = useProjectParam();
  const [minutes, setMinutes] = useState<number | null>(null);

  // El intervalo por defecto es el que se eligió al crear la intersección;
  // el selector solo lo cambia para esta vista, sin tocar el proyecto.
  const effective = minutes ?? project?.interval_minutes ?? 15;
  const { data: m, isLoading, isError, error } = useMetrics(projectId, effective);

  return (
    <>
      <div className="page-controls">
        <SelectField
          label="Intervalo"
          narrow
          value={effective}
          onChange={(e) => setMinutes(Number(e.target.value))}
        >
          {INTERVALS.map((v) => (
            <option key={v} value={v}>
              {v} minutos
            </option>
          ))}
        </SelectField>

        {/* La exportación es lo que se entrega al cliente, así que vive
            junto al control que define qué se exporta: cambiar el
            intervalo cambia el archivo. */}
        {projectId !== null && m && m.lanes.length > 0 && (
          <div className="report-export">
            <span className="re-label">Exportar</span>
            <div className="re-actions">
              {/* Descargas de verdad: el navegador pone su barra de
                  progreso y respeta el nombre que manda el servidor. */}
              {/* El entregable es UNO. Antes los cuatro botones tenían el
                  mismo peso, así que el informe que se manda al cliente
                  se veía igual de importante que un CSV de trabajo. */}
              <a className="btn btn-primary" href={exportAforoExcelUrl(projectId)} download>
                <IconDownload size={15} />
                Informe de aforo (Excel)
              </a>
              <div className="re-grupo">
                <a className="re-mini" href={exportSummaryUrl(projectId, effective)} download>
                  <IconDownload size={14} />
                  Resumen
                </a>
                <a className="re-mini" href={exportIntervalsUrl(projectId, effective)} download>
                  <IconDownload size={14} />
                  Por intervalo
                </a>
                {/* El PDF lo hace el propio navegador con la hoja de
                    impresión: así las gráficas salen vectoriales y no hay
                    que mantener una segunda versión del informe en el
                    servidor. */}
                <button type="button" className="re-mini" onClick={() => window.print()}>
                  <IconPrint size={14} />
                  PDF
                </button>
              </div>
            </div>
          </div>
        )}
      </div>


      {projectId !== null && isLoading && <EmptyState title="Calculando el reporte…" />}

      {isError && (
        <Notice title="No se pudo cargar el reporte">{errorMessage(error)}</Notice>
      )}

      {m && m.lanes.length === 0 && (
        <EmptyState
          title="Esta intersección todavía no tiene carriles"
          body="Un carril es la línea que los vehículos cruzan para ser contados. Sin al menos uno, no hay nada que reportar."
          action={
            <Link className="btn btn-primary" to={`/proyecto/${projectId}/calibrar`}>
              Calibrar carriles
            </Link>
          }
        />
      )}

      {m && m.lanes.length > 0 && (
        <>
          <Metrics m={m} />

          {m.totals.total > 0 && (
            <Card className="chart-card">
              <h3>El aforo en movimiento</h3>
              <p className="chart-sub">
                Cada tramo es un carril medido: lleva los vehículos que le tocan por su volumen,
                repartidos entre los dos sentidos y con la mezcla de tipos que se contó.
              </p>
              <EscenaFlujo lanes={m.lanes} />
            </Card>
          )}
          {m.lanes.map((lane) => (
            <LaneReport key={lane.lane_id} lane={lane} intervalMinutes={m.interval_minutes} />
          ))}
        </>
      )}
    </>
  );
}
