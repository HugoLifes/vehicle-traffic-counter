/*
  Ficha de la cámara: qué tan buen material está recibiendo el detector.

  El aforo de 24 horas dejó claro que el límite de este sistema no está en
  el modelo sino en lo que le llega — un vehículo ocupa 18 px de alto de
  día y 13 de noche, cuando el detector necesita unos 40. Esa conclusión
  vivía en docs/REQUISITOS_CAMARA.md, que es exactamente donde no la ve
  quien está a punto de comprar la cámara. Aquí está delante, medida sobre
  el material de esta intersección y no en general.
*/

import { useParams } from 'react-router-dom';
import { Card, EmptyState, Notice } from '../components/ui';
import { useCameraCard } from '../lib/queries';
import { errorMessage } from '../lib/api';
import { formatNumber, plural } from '../lib/format';
import type { FichaCamara } from '../lib/types';

/*
  Barra que sitúa una medida contra el umbral que tiene que alcanzar.
  Una cifra sola ("18 px") no dice nada a quien no se sabe el requisito de
  memoria; puesta contra su marca, se lee de un vistazo.
*/
function Medida({
  etiqueta,
  valor,
  unidad,
  minimo,
  detalle,
}: {
  etiqueta: string;
  valor: number | null;
  unidad: string;
  minimo: number;
  detalle?: string;
}) {
  if (valor === null) {
    return (
      <div className="medida">
        <div className="med-cabeza">
          <span className="med-etiqueta">{etiqueta}</span>
          <span className="med-valor med-sin">Sin medir</span>
        </div>
        {detalle && <p className="med-detalle">{detalle}</p>}
      </div>
    );
  }

  const cumple = valor >= minimo;
  // La escala llega a 1.4× el mínimo para que superarlo se vea como
  // holgura y no como un tope alcanzado por los pelos.
  const pct = Math.min(100, (valor / (minimo * 1.4)) * 100);
  const marca = (minimo / (minimo * 1.4)) * 100;

  return (
    <div className="medida">
      <div className="med-cabeza">
        <span className="med-etiqueta">{etiqueta}</span>
        {/* El veredicto va en palabra además de en color y posición. */}
        <span className={`med-valor ${cumple ? 'ok' : 'corto'}`}>
          {formatNumber(Math.round(valor))} {unidad}
          <span className="med-veredicto">{cumple ? 'suficiente' : 'por debajo'}</span>
        </span>
      </div>
      <div className="med-barra">
        <div className={`med-relleno ${cumple ? 'ok' : 'corto'}`} style={{ width: `${pct}%` }} />
        <div className="med-marca" style={{ insetInlineStart: `${marca}%` }} />
      </div>
      <p className="med-detalle">
        Mínimo: {formatNumber(minimo)} {unidad}
        {detalle ? ` · ${detalle}` : ''}
      </p>
    </div>
  );
}

function Contenido({ f }: { f: FichaCamara }) {
  const alturas = f.altura_vehiculo;
  const resolucion = f.resoluciones[0]?.resolucion ?? null;
  const altoPx = resolucion ? Number(resolucion.split('x')[1]) : null;

  return (
    <div className="proj-resumen">
      {f.avisos.length > 0 && (
        <div className="notice-stack">
          {f.avisos.map((a, i) => (
            <Notice key={i} tone="warning" title="El material limita lo que el detector puede ver">
              {a}
            </Notice>
          ))}
        </div>
      )}

      <Card className="proj-tool-card">
        <h3 className="section-title">Lo que recibe el detector</h3>

        <Medida
          etiqueta="Alto del vehículo en la línea de conteo"
          valor={alturas.mediana}
          unidad="px"
          minimo={f.alto_necesario_px}
          detalle={
            alturas.con_medida > 0
              ? `Mediana de ${plural(alturas.con_medida, 'cruce medido', 'cruces medidos')}` +
                (alturas.p10 !== null ? ` · el 10 % más pequeño baja de ${alturas.p10} px` : '')
              : undefined
          }
        />

        {alturas.con_medida === 0 && (
          <p className="ptc-empty" style={{ marginTop: 'calc(var(--space-3) * -1)' }}>
            El alto se guarda en cada cruce desde ahora. Los conteos anteriores no lo traen, así
            que aparecerá en cuanto se vuelva a contar esta intersección. No se estima a partir de
            la resolución a propósito: un número calculado se leería como uno medido.
          </p>
        )}

        <Medida
          etiqueta="Bitrate del material"
          valor={f.bitrate_kbps}
          unidad="kb/s"
          minimo={f.bitrate_minimo_kbps}
          detalle="Determina cuánto detalle sobrevive al compresor"
        />

        <Medida
          etiqueta="Resolución vertical"
          valor={altoPx}
          unidad="p"
          minimo={720}
          detalle={resolucion ? `Grabación en ${resolucion}` : undefined}
        />
      </Card>

      <div className="proj-tools-grid">
        <Card className="proj-tool-card">
          <h3 className="section-title">El material</h3>
          <dl className="proj-dl">
            <div>
              <dt>Resolución</dt>
              <dd>
                {f.resoluciones.length === 0
                  ? 'No se pudo leer'
                  : f.resoluciones.map((r) => r.resolucion).join(' · ')}
                <span className="proj-coords">
                  Muestreados {f.videos_muestreados} de {plural(f.videos, 'video', 'videos')}
                </span>
              </dd>
            </div>
            <div>
              <dt>Cuadros por segundo</dt>
              <dd>{f.fps ?? '—'}</dd>
            </div>
            <div>
              <dt>Bitrate medio</dt>
              <dd>{f.bitrate_kbps !== null ? `${formatNumber(Math.round(f.bitrate_kbps))} kb/s` : '—'}</dd>
            </div>
          </dl>
        </Card>

        <Card className="proj-tool-card">
          <h3 className="section-title">Qué cámara pedir</h3>
          <p className="ptc-body">
            Con la misma escena, subir de 360p a 1080p lleva al vehículo de unos 18 px a unos 54:
            de por debajo del límite a trabajar con holgura.
          </p>
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Resolución</th>
                  <th scope="col" className="num">Alto del vehículo</th>
                  <th scope="col">Veredicto</th>
                </tr>
              </thead>
              <tbody>
                <tr className={altoPx === 360 ? 'is-peak' : undefined}>
                  <td>640×360{altoPx === 360 ? ' — la actual' : ''}</td>
                  <td className="num">18 px</td>
                  <td>Al límite, y de noche se cae</td>
                </tr>
                <tr>
                  <td>1280×720</td>
                  <td className="num">36 px</td>
                  <td>Mínimo aceptable</td>
                </tr>
                <tr>
                  <td>1920×1080</td>
                  <td className="num">54 px</td>
                  <td>Recomendado</td>
                </tr>
                <tr>
                  <td>2560×1440</td>
                  <td className="num">72 px</td>
                  <td>Cómodo, más carga para el Jetson</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p className="ptc-empty" style={{ marginTop: 'var(--space-3)' }}>
            El bitrate pesa tanto como la resolución: 1080p mal comprimido vuelve al mismo problema.
            Y encuadrar más cerrado sobre la vía vale tanto como subir la resolución, y es gratis.
          </p>
        </Card>
      </div>
    </div>
  );
}

export default function ProyectoCamara() {
  const { projectId } = useParams();
  const id = Number(projectId);
  const { data, isLoading, isError, error } = useCameraCard(id);

  if (isLoading) return <EmptyState title="Midiendo el material…" />;
  if (isError) {
    return <Notice title="No se pudo leer la ficha de la cámara">{errorMessage(error)}</Notice>;
  }
  if (!data || data.videos === 0) {
    return (
      <EmptyState
        title="Todavía no hay material que medir"
        body="La ficha sale de los videos de esta intersección: su resolución, su bitrate y el tamaño real de los vehículos en la línea de conteo."
      />
    );
  }
  return <Contenido f={data} />;
}
