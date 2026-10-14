/*
  Reporte de un aforo DIRECCIONAL, separado del aforo por línea.

  Enseña lo mismo que el Excel (aforo_excel.formato_direccional): la hora de
  máxima demanda de cada mañana y cada tarde con la tabla Hr/Mov de la
  empresa —movimientos numerados sobre su croquis, A, B y C por cuarto— y
  todos los cuartos de hora. Antes el Reporte de un direccional ponía la
  matriz con los nombres de los accesos y, debajo, las métricas y carriles
  del aforo por línea; la empresa no podía leerlo contra su conteo de campo
  (13-oct-2026).
*/

import { useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Card, Notice } from './ui';
import { borrarConteoManual, croquisUrl, errorMessage, getValidacion, subirConteoManual } from '../lib/api';
import { formatNumber } from '../lib/format';
import type { FilaHrMov, FormatoDireccional, HojaConteo, Validacion } from '../lib/types';

const DIA = new Intl.DateTimeFormat('es-MX', { weekday: 'long', day: 'numeric', month: 'long' });
const dia = (iso: string) => DIA.format(new Date(`${iso}T12:00:00`));

function TablaHrMov({ movs, filas }: { movs: string[]; filas: FilaHrMov[] }) {
  const suma = (mv: string, k: number) => filas.reduce((s, f) => s + (f.valores[mv]?.[k] ?? 0), 0);
  return (
    <div className="table-scroll">
      <table className="data-table hrmov">
        <thead>
          <tr>
            <th scope="col" rowSpan={2}>
              Hr/Mov
            </th>
            {movs.map((mv) => (
              <th scope="colgroup" colSpan={3} key={mv}>
                {mv}
              </th>
            ))}
          </tr>
          <tr>
            {movs.map((mv) =>
              ['A', 'B', 'C'].map((c) => (
                <th scope="col" key={mv + c}>
                  {c}
                </th>
              )),
            )}
          </tr>
        </thead>
        <tbody>
          {filas.map((f) => (
            <tr key={f.fecha + f.inicio}>
              <th scope="row">{f.etiqueta}</th>
              {movs.map((mv) => (f.valores[mv] ?? [0, 0, 0]).map((n, k) => <td key={mv + k}>{n}</td>))}
            </tr>
          ))}
          <tr className="hrmov-total">
            <th scope="row">TOTAL</th>
            {movs.map((mv) => [0, 1, 2].map((k) => <td key={mv + k}>{suma(mv, k)}</td>))}
          </tr>
          <tr className="hrmov-total">
            <th scope="row">TOTALES</th>
            {movs.map((mv) => (
              <td colSpan={3} key={mv}>
                <strong>{formatNumber(suma(mv, 0) + suma(mv, 1) + suma(mv, 2))}</strong>
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

/**
 * Qué tan exacto salió ESTE aforo: contra una hora contada a mano, el GEH de
 * cada movimiento y si pasa el criterio. La exactitud de un direccional
 * depende de la cámara (Terracería 6 de 6, Gómez Morín 1 de 6), así que se
 * declara por intersección y no como un número general.
 */
function Precision({ projectId, fechas }: { projectId: number; fechas: string[] }) {
  const qc = useQueryClient();
  const { data: v } = useQuery<Validacion | null>({
    queryKey: ['validacion', projectId],
    queryFn: () => getValidacion(projectId).catch(() => null),
  });
  const [archivo, setArchivo] = useState<File | null>(null);
  const [fecha, setFecha] = useState(fechas[fechas.length - 1] ?? '');
  const [hojas, setHojas] = useState<HojaConteo[] | null>(null);
  const [hoja, setHoja] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [subiendo, setSubiendo] = useState(false);

  const subir = async () => {
    if (!archivo || !fecha) return;
    setSubiendo(true);
    setError(null);
    try {
      const r = await subirConteoManual(projectId, archivo, fecha, hoja || undefined);
      if ('pedir_hoja' in r) {
        setHojas(r.pedir_hoja);
        setHoja(r.pedir_hoja[0]?.hoja ?? '');
      } else {
        setHojas(null);
        setArchivo(null);
        qc.setQueryData(['validacion', projectId], r);
      }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setSubiendo(false);
    }
  };

  const formulario = (
    <div className="precision-form">
      <label>
        Excel de campo (formato Hr/Mov)
        <input
          type="file"
          accept=".xlsx"
          onChange={(e) => {
            setArchivo(e.target.files?.[0] ?? null);
            setHojas(null);
            setHoja('');
          }}
        />
      </label>
      <label>
        Día que contaron
        <select value={fecha} onChange={(e) => setFecha(e.target.value)}>
          {fechas.map((x) => (
            <option key={x} value={x}>
              {dia(x)}
            </option>
          ))}
        </select>
      </label>
      {hojas && (
        <label>
          ¿Qué hoja es esta intersección?
          <select value={hoja} onChange={(e) => setHoja(e.target.value)}>
            {hojas.map((h) => (
              <option key={h.hoja} value={h.hoja}>
                {h.hoja}: {formatNumber(h.total)} vehículos, {h.desde}–{h.hasta}
              </option>
            ))}
          </select>
        </label>
      )}
      <button type="button" className="btn btn-primary" disabled={!archivo || !fecha || subiendo} onClick={() => void subir()}>
        {subiendo ? 'Comparando…' : hojas ? 'Usar esta hoja' : 'Comparar'}
      </button>
      {error && <p className="est-error">{error}</p>}
    </div>
  );

  const ultimo = v?.por_cuarto && v.por_cuarto.length > 0 ? v.por_cuarto[v.por_cuarto.length - 1].inicio : '';

  return (
    <Card className="chart-card">
      <h3>Precisión contra el conteo a mano</h3>
      {!v && (
        <>
          <p className="chart-sub">
            Sube el Excel de campo de una hora contada a mano y la plataforma dice qué tanto coincide,
            movimiento por movimiento. Es la forma de saber qué tan exacto es el aforo de esta
            intersección: depende de la cámara.
          </p>
          {formulario}
        </>
      )}
      {v?.error && (
        <Notice tone="warning" title="No se pudo comparar">
          {v.error}
        </Notice>
      )}
      {v && v.movimientos && (
        <>
          <p className="chart-sub">
            {v.archivo}, hoja {v.hoja}, {dia(v.fecha)} (cuartos de {v.por_cuarto?.[0]?.inicio} a {ultimo}).{' '}
            <strong>
              {formatNumber(v.total_plataforma ?? 0)} contra {formatNumber(v.total_manual ?? 0)} (
              {Math.round(100 * (v.razon ?? 0))} %) · {v.pasan} de {v.de} movimientos con GEH &lt; 5
            </strong>
          </p>
          <p className={`precision-veredicto ${v.aceptado ? 'is-ok' : 'is-mal'}`}>
            {v.aceptado ? 'ACEPTADO' : 'NO PASA'} — criterio: {v.criterio}
          </p>
          <div className="table-scroll">
            <table className="data-table hrmov">
              <thead>
                <tr>
                  <th scope="col">Movimiento</th>
                  <th scope="col">Plataforma</th>
                  <th scope="col">A mano</th>
                  <th scope="col">Diferencia</th>
                  <th scope="col">GEH</th>
                </tr>
              </thead>
              <tbody>
                {v.movimientos.map((r) => (
                  <tr key={r.movimiento}>
                    <th scope="row">
                      {r.movimiento.replace(/_/g, ' → ')}
                      {r.por_linea && <span className="precision-marca"> línea</span>}
                      {r.juntos && <span className="precision-marca"> juntos</span>}
                    </th>
                    <td>{formatNumber(r.plataforma)}</td>
                    <td>{formatNumber(r.manual)}</td>
                    <td>
                      {r.plataforma - r.manual > 0 ? '+' : ''}
                      {formatNumber(r.plataforma - r.manual)}
                    </td>
                    <td className={r.pasa ? 'geh-ok' : 'geh-mal'}>{r.geh.toFixed(1)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="chart-sub">
            GEH &lt; 5: la cifra se acepta como equivalente al conteo de campo. «línea»: medido con la
            línea de conteo de la calle. «juntos»: la cámara no separa esos movimientos y se compara su
            suma.
          </p>
          <details className="hrmov-dia">
            <summary>Cambiar el conteo a mano</summary>
            {formulario}
            <button
              type="button"
              className="est-enlace est-sec"
              onClick={() => void borrarConteoManual(projectId).then(() => qc.setQueryData(['validacion', projectId], null))}
            >
              Quitar el conteo a mano
            </button>
          </details>
        </>
      )}
    </Card>
  );
}

export function ReporteDireccional({ f, projectId }: { f: FormatoDireccional; projectId: number }) {
  const porDia = new Map<string, FilaHrMov[]>();
  for (const q of f.cuartos) porDia.set(q.fecha, [...(porDia.get(q.fecha) ?? []), q]);

  return (
    <>
      <div className="rr-grid stagger">
        {f.hmd.map((h) => (
          <Card className="metric-card" key={h.fecha + h.turno}>
            <div className="m-label">
              Hora de máxima demanda · {h.turno === 'MAÑANA' ? 'mañana' : 'tarde'}, {dia(h.fecha)}
            </div>
            <div className="m-value is-compact">
              {h.inicio}–{h.fin}
            </div>
            <div className="m-sub">
              {formatNumber(h.volumen)} vehículos{h.fhp !== null ? ` · FHP ${h.fhp.toFixed(2)}` : ''}
            </div>
          </Card>
        ))}
      </div>

      <Precision projectId={projectId} fechas={[...new Set(f.cuartos.map((q) => q.fecha))]} />

      {(f.juntos ?? []).map((g) => (
        <Notice tone="info" key={g.join()} title={`${g.join(' y ')}: esta cámara no los distingue`}>
          El vehículo dobla fuera de cuadro. La suma de esos movimientos es confiable; el reparto entre
          ellos no, y así lo dice también el Excel.
        </Notice>
      ))}

      {f.hmd.map((h) => (
        <Card className="chart-card" key={`t${h.fecha}${h.turno}`}>
          <h3>
            Hora de máxima demanda, {h.turno === 'MAÑANA' ? 'mañana' : 'tarde'} — {dia(h.fecha)}, {h.inicio}–{h.fin}
          </h3>
          <div className={f.croquis ? 'hrmov-con-croquis' : undefined}>
            {f.croquis && <img className="hrmov-croquis" src={croquisUrl(projectId)} alt="Croquis con los números de acceso" />}
            <TablaHrMov movs={f.movimientos} filas={h.filas} />
          </div>
        </Card>
      ))}

      {f.derivados.length > 0 && (
        <Notice tone="info" title={`${f.derivados.join(', ')}: medidos con la línea de conteo`}>
          La cámara no sigue esos movimientos de punta a punta. Se toman de lo que cruzó la línea de
          conteo de esa calle, menos las vueltas que sí se siguieron.
        </Notice>
      )}

      <Card className="chart-card">
        <h3>Todos los cuartos de hora</h3>
        <p className="chart-sub">
          {formatNumber(f.total)} vehículos con movimiento en el estudio. A: automóviles, camionetas,
          pickups y motos. B: autobuses. C: camiones y tractocamiones.
        </p>
        {[...porDia.entries()].map(([fecha, filas]) => (
          <details className="hrmov-dia" key={fecha}>
            <summary>{dia(fecha)}</summary>
            <TablaHrMov movs={f.movimientos} filas={filas} />
          </details>
        ))}
      </Card>
    </>
  );
}
