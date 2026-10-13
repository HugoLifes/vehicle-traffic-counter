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

import { Card, Notice } from './ui';
import { croquisUrl } from '../lib/api';
import { formatNumber } from '../lib/format';
import type { FilaHrMov, FormatoDireccional } from '../lib/types';

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
        <Notice title={`${f.derivados.join(', ')}: medidos con la línea de conteo`}>
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
