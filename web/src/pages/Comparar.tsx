/*
  Comparar intersecciones.

  Es la pregunta que aparece en cuanto hay más de un punto medido: ¿cuál
  carga más?, ¿pican a la misma hora?, ¿por dónde pasan los camiones? Con
  una pantalla por intersección hay que ir y venir apuntando cifras en un
  papel, que es donde se pierden.

  Vive fuera del contenedor de proyecto a propósito: compara varios, así
  que no es de ninguno.

  Cada intersección se pide por separado a /api/videos/metrics. Son unas
  pocas peticiones y el backend ya las resuelve rápido; un endpoint que
  las juntara solo añadiría una forma más de que los números de aquí y los
  de la pantalla de reporte se desincronicen.
*/

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQueries } from '@tanstack/react-query';
import { Page } from '../components/Page';
import { Card, EmptyState, Notice, SelectField } from '../components/ui';
import { useProjects } from '../lib/queries';
import { errorMessage, getMetrics } from '../lib/api';
import { VEHICLE_LABEL_PLURAL, formatNumber, hhmm, vehicleColorVar, vehicleLabel } from '../lib/format';
import type { Project, ProjectMetrics } from '../lib/types';

const INTERVALS = [5, 10, 15, 30, 60];

/* Barra de una fila de la comparación: el valor relativo al mayor de la
   tabla. Sin esa referencia, "21.943" y "24.189" cuestan de comparar; con
   ella la diferencia se ve sin leer. */
function Barra({ valor, max, tono = 'accent' }: { valor: number; max: number; tono?: string }) {
  return (
    <div className="cmp-barra" aria-hidden="true">
      <div
        className={`cmp-relleno tono-${tono}`}
        style={{ width: `${max > 0 ? (valor / max) * 100 : 0}%` }}
      />
    </div>
  );
}

function Composicion({ m }: { m: ProjectMetrics }) {
  const entradas = Object.entries(m.composition)
    .filter(([, n]) => n > 0)
    .sort((a, b) => b[1] - a[1]);
  const total = m.totals.total || 1;
  if (!entradas.length) return <span className="cmp-sin">Sin clasificar</span>;

  return (
    <div className="cmp-comp">
      <div className="comp-bar" style={{ height: 14, marginBottom: 4 }}>
        {entradas.map(([t, n]) => (
          <div
            key={t}
            className="comp-seg"
            style={{ width: `${(n / total) * 100}%`, background: vehicleColorVar(t) }}
            title={`${vehicleLabel(t)}: ${((n / total) * 100).toFixed(1)}%`}
          />
        ))}
      </div>
      <span className="cmp-sin">
        {((entradas[0][1] / total) * 100).toFixed(0)} %{' '}
        {VEHICLE_LABEL_PLURAL[entradas[0][0]] ?? entradas[0][0]}
      </span>
    </div>
  );
}

export default function Comparar() {
  const { data: projects } = useProjects();
  const [minutes, setMinutes] = useState(15);

  // Se comparan las que ya tienen algo que comparar.
  const candidatas = (projects ?? []).filter((p) => p.crossing_count > 0);
  const [elegidas, setElegidas] = useState<number[] | null>(null);
  const seleccion = elegidas ?? candidatas.slice(0, 3).map((p) => p.id);

  const consultas = useQueries({
    queries: seleccion.map((id) => ({
      queryKey: ['metrics', id, minutes],
      queryFn: () => getMetrics(id, minutes),
    })),
  });

  const filas = seleccion
    .map((id, i) => ({
      proyecto: candidatas.find((p) => p.id === id) as Project | undefined,
      m: consultas[i]?.data,
      cargando: consultas[i]?.isLoading,
      error: consultas[i]?.error,
    }))
    .filter((f) => f.proyecto);

  const maxVolumen = Math.max(1, ...filas.map((f) => f.m?.totals.total ?? 0));
  const maxPico = Math.max(1, ...filas.map((f) => f.m?.peak_hour?.volume ?? 0));

  return (
    <Page
      title="Comparar intersecciones"
      subtitle="Volumen, hora de máxima demanda y composición, lado a lado"
      hideGuide
    >
      {candidatas.length === 0 && (
        <EmptyState
          title="Todavía no hay aforos que comparar"
          body="Aquí aparecen las intersecciones que ya tienen conteos. Cuando haya al menos dos, se pueden ver sus cifras una junto a otra."
          action={
            <Link className="btn btn-primary" to="/">
              Ver intersecciones
            </Link>
          }
        />
      )}

      {candidatas.length > 0 && (
        <>
          <div className="page-controls">
            <SelectField
              label="Intervalo"
              narrow
              value={minutes}
              hint="El mismo para todas, o las cifras no serían comparables."
              onChange={(e) => setMinutes(Number(e.target.value))}
            >
              {INTERVALS.map((v) => (
                <option key={v} value={v}>
                  {v} minutos
                </option>
              ))}
            </SelectField>
          </div>

          <Card className="proj-tool-card cmp-picker">
            <h2 className="section-title">Qué intersecciones comparar</h2>
            <div className="cmp-opciones">
              {candidatas.map((p) => {
                const marcada = seleccion.includes(p.id);
                return (
                  <label key={p.id} className={`cmp-opcion${marcada ? ' is-on' : ''}`}>
                    <input
                      type="checkbox"
                      checked={marcada}
                      onChange={(e) =>
                        setElegidas(
                          e.target.checked
                            ? [...seleccion, p.id]
                            : seleccion.filter((x) => x !== p.id),
                        )
                      }
                    />
                    <span>{p.name}</span>
                  </label>
                );
              })}
            </div>
          </Card>

          {seleccion.length === 0 && (
            <EmptyState
              title="No hay ninguna marcada"
              body="Elige al menos una intersección de la lista de arriba."
            />
          )}

          {filas.some((f) => f.error) && (
            <div className="notice-stack">
              {filas
                .filter((f) => f.error)
                .map((f) => (
                  <Notice key={f.proyecto!.id} title={`No se pudo cargar ${f.proyecto!.name}`}>
                    {errorMessage(f.error)}
                  </Notice>
                ))}
            </div>
          )}

          {seleccion.length > 0 && (
            <div className="table-scroll">
              <table className="data-table cmp-tabla">
                <caption className="visually-hidden">
                  Comparación de intersecciones en periodos de {minutes} minutos.
                </caption>
                <thead>
                  <tr>
                    <th scope="col">Intersección</th>
                    <th scope="col">Volumen total</th>
                    <th scope="col">Hora de máxima demanda</th>
                    <th scope="col" className="num">FHP</th>
                    <th scope="col">Composición</th>
                    <th scope="col" className="num">Carriles</th>
                  </tr>
                </thead>
                <tbody>
                  {filas.map(({ proyecto, m, cargando }) => (
                    <tr key={proyecto!.id}>
                      <th scope="row" className="cmp-nombre">
                        <Link to={`/proyecto/${proyecto!.id}`}>{proyecto!.name}</Link>
                        {proyecto!.address && <span className="cmp-sin">{proyecto!.address}</span>}
                      </th>

                      <td>
                        {cargando ? (
                          <span className="cmp-sin">Calculando…</span>
                        ) : (
                          <>
                            <span className="mono cmp-cifra">
                              {formatNumber(m?.totals.total ?? 0)}
                            </span>
                            <Barra valor={m?.totals.total ?? 0} max={maxVolumen} />
                          </>
                        )}
                      </td>

                      <td>
                        {m?.peak_hour ? (
                          <>
                            <span className="mono cmp-cifra">
                              {hhmm(m.peak_hour.start)}–{hhmm(m.peak_hour.end)}
                            </span>
                            <Barra valor={m.peak_hour.volume} max={maxPico} tono="warning" />
                            <span className="cmp-sin">
                              {formatNumber(m.peak_hour.volume)} vehículos
                            </span>
                          </>
                        ) : (
                          <span className="cmp-sin">Falta una hora completa</span>
                        )}
                      </td>

                      <td className="num">
                        {m?.peak_hour?.fhp != null ? (
                          <>
                            {m.peak_hour.fhp.toFixed(3)}
                            {/* El veredicto en palabra, no solo el número:
                                el umbral de 0.85 no lo lleva todo el mundo
                                en la cabeza. */}
                            <span className="cmp-sin">
                              {m.peak_hour.flujo_irregular ? 'irregular' : 'parejo'}
                            </span>
                          </>
                        ) : (
                          <span className="cmp-sin">—</span>
                        )}
                      </td>

                      <td>{m ? <Composicion m={m} /> : <span className="cmp-sin">—</span>}</td>

                      <td className="num">{formatNumber(proyecto!.lane_count)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Page>
  );
}
