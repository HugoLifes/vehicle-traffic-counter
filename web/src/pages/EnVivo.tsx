/*
  Cámara en vivo: conteo en tiempo real de la fuente RTSP conectada al
  Jetson. Aquí no se sube nada ni se guarda video — solo se muestran los
  eventos de cruce conforme ocurren.

  Es el otro modo de la app, no un paso del flujo de un proyecto, y por
  eso vive en el nivel superior de la navegación.
*/

import { Page } from '../components/Page';
import { Card, EmptyState, Notice, Pill } from '../components/ui';
import { useCounts, useEngineState } from '../lib/queries';
import { errorMessage } from '../lib/api';
import { ENGINE_STATUS_LABEL, ENGINE_STATUS_TONE, formatNumber, vehicleLabel } from '../lib/format';
import type { LaneCount } from '../lib/types';

function StatusBar() {
  const { data: engine, isError, error } = useEngineState();

  if (isError) {
    return (
      <div className="notice-stack">
        <Notice title="Sin conexión con el motor de conteo">
          {errorMessage(error)} La plataforma sigue reintentando sola.
        </Notice>
      </div>
    );
  }

  if (!engine) {
    return (
      <div className="pill-row" style={{ marginBottom: 'var(--space-6)' }}>
        <Pill>Consultando el estado…</Pill>
      </div>
    );
  }

  return (
    <div className="pill-row" style={{ marginBottom: 'var(--space-6)' }}>
      {/* El estado va en español y con texto además del color, nunca con
          la etiqueta cruda del backend. */}
      <Pill
        tone={ENGINE_STATUS_TONE[engine.status]}
        dot
        live={engine.status === 'running'}
      >
        {ENGINE_STATUS_LABEL[engine.status] ?? engine.status}
      </Pill>
      <Pill>
        Fuente <span className="value">{engine.camera_source}</span>
      </Pill>
      <Pill>
        Resolución{' '}
        <span className="value">
          {engine.frame_width}×{engine.frame_height}
        </span>
      </Pill>
      <Pill>
        Cuadros por segundo <span className="value">{engine.fps_estimate}</span>
      </Pill>
      {engine.last_error && <Pill tone="critical">{engine.last_error}</Pill>}
    </div>
  );
}

function LaneCard({ c }: { c: LaneCount }) {
  const types = Object.entries(c.by_vehicle_type);
  const maxTotal = Math.max(...types.map(([, v]) => (v.in ?? 0) + (v.out ?? 0)), 1);

  return (
    <Card className="lane-card">
      <div className="lane-head">
        <span className="lane-name">{c.lane_name}</span>
        <span className="lane-total">{formatNumber(c.total)}</span>
      </div>

      <div className="lane-io">
        <div className="io-item">
          <div className="io-label">Entrada</div>
          <div className="io-value">{formatNumber(c.in)}</div>
        </div>
        <div className="io-item">
          <div className="io-label">Salida</div>
          <div className="io-value">{formatNumber(c.out)}</div>
        </div>
      </div>

      {types.length === 0 ? (
        <p className="io-label" style={{ margin: 0 }}>
          Sin vehículos clasificados todavía.
        </p>
      ) : (
        types.map(([type, v]) => (
          <div className="vt-row" key={type}>
            <span className="vt-name">{vehicleLabel(type)}</span>
            <span className="vt-bar">
              <span className="seg-in" style={{ width: `${((v.in ?? 0) / maxTotal) * 100}%` }} />
              <span className="seg-out" style={{ width: `${((v.out ?? 0) / maxTotal) * 100}%` }} />
            </span>
            {/* La cifra acompaña siempre a la barra: la barra sola no se
                puede leer con exactitud, y aquí la exactitud es el punto. */}
            <span className="vt-count">
              {v.in ?? 0} / {v.out ?? 0}
            </span>
          </div>
        ))
      )}
    </Card>
  );
}

export default function EnVivo() {
  const { data: counts } = useCounts();

  const totals = (counts ?? []).reduce(
    (acc, c) => ({ in: acc.in + (c.in ?? 0), out: acc.out + (c.out ?? 0) }),
    { in: 0, out: 0 },
  );
  const total = totals.in + totals.out;
  const net = totals.in - totals.out;

  return (
    <Page
      title="Cámara en vivo"
      subtitle="Conteo en tiempo real — sin grabación de video"
      hideGuide
    >
      <StatusBar />

      <div className="stat-cluster stagger">
        <Card className="stat-tile accent">
          <div className="label">Total</div>
          <div className="value">{formatNumber(total)}</div>
        </Card>
        <Card className="stat-tile">
          <div className="label">Entrada</div>
          <div className="value">{formatNumber(totals.in)}</div>
        </Card>
        <Card className="stat-tile">
          <div className="label">Salida</div>
          <div className="value">{formatNumber(totals.out)}</div>
        </Card>
        <Card className="stat-tile">
          <div className="label">Flujo neto</div>
          <div className="value">{formatNumber(net)}</div>
        </Card>
      </div>

      <h2 className="section-title">Carriles</h2>
      <div className="lane-grid">
        {counts?.length === 0 && (
          <EmptyState
            title="Sin cruces registrados todavía"
            body="El conteo aparece aquí en cuanto un vehículo cruce una de las líneas configuradas."
          />
        )}
        {counts?.map((c) => (
          <LaneCard key={c.lane_id} c={c} />
        ))}
      </div>
    </Page>
  );
}
