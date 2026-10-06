/*
  Cuánto espacio queda para videos, en lo que le importa a quien opera:
  horas de grabación que todavía caben, no solo gigas. El peso de una hora
  sale de los videos ya subidos (el frontal 2560x1440 pesa ~1 GB/h).
*/

import { useQuery } from '@tanstack/react-query';
import { getAlmacenamiento } from '../lib/api';
import { formatNumber } from '../lib/format';

export function Almacenamiento({ compacto = false }: { compacto?: boolean }) {
  const { data: a } = useQuery({
    queryKey: ['almacenamiento'],
    queryFn: getAlmacenamiento,
    refetchInterval: 60000,
  });
  if (!a || !a.total_gb) return null;
  const usado = Math.max(0, a.total_gb - a.libre_gb);
  const pct = Math.min(100, (100 * usado) / a.total_gb);
  const tono = a.problema ? 'critical' : pct >= 85 ? 'warning' : 'good';
  const lugar = a.exigido ? 'Disco de videos' : 'Espacio para videos';

  return (
    <div className={`almacen almacen--${tono}${compacto ? ' almacen--compacto' : ''}`}>
      <div className="almacen-linea">
        <span className="almacen-titulo">{lugar}</span>
        <span className="almacen-cifras num">
          <strong>{formatNumber(Math.round(a.libre_gb))} GB libres</strong> de{' '}
          {formatNumber(Math.round(a.total_gb))} GB
          {a.horas_que_caben != null && (
            <>
              {' · '}caben ~{formatNumber(a.horas_que_caben)} h de video
            </>
          )}
          {!compacto && a.usado_videos_gb > 0 && (
            <>
              {' · '}los videos subidos ocupan {formatNumber(Math.round(a.usado_videos_gb))} GB
            </>
          )}
        </span>
      </div>
      <div
        className="almacen-barra"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(pct)}
        aria-label={`${lugar}: ${Math.round(pct)} % usado`}
      >
        <div className="almacen-relleno" style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}
