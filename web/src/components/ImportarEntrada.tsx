/*
  Importar los videos que llegaron a la carpeta de entrada del Jetson —por
  WinSCP o en un disco conectado— sin pasar por el navegador. Por la
  dirección pública el navegador sube a ~25 KB/s desde Juárez; por SFTP va a
  la velocidad de su internet y retoma solo si se corta.

  La hora sale de la ruta cuando se puede (carpeta por hora y archivo por
  minuto: 14/05.mp4 = 14:05) y se corrige aquí antes de importar. Importar
  copia cada video al disco de los videos; lo que subieron no se toca.
*/

import { useEffect, useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Card, Notice } from './ui';
import {
  errorMessage,
  getEntrada,
  getEstadoImportacion,
  importarEntrada,
  type ArchivoEntrada,
} from '../lib/api';
import { formatSize, plural, todayISO } from '../lib/format';

interface Fila {
  fecha: string;
  hora: string;
  elegido: boolean;
}

export function ImportarEntrada({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const { data, refetch, isFetching } = useQuery({
    queryKey: ['entrada', projectId],
    queryFn: () => getEntrada(projectId),
    refetchInterval: 30000,
  });
  const [filas, setFilas] = useState<Record<string, Fila>>({});
  const [error, setError] = useState<string | null>(null);
  const [activa, setActiva] = useState(false);
  const { data: estado } = useQuery({
    queryKey: ['entrada-estado'],
    queryFn: getEstadoImportacion,
    refetchInterval: activa ? 1000 : false,
    enabled: activa,
  });

  const archivos: ArchivoEntrada[] = useMemo(() => data?.archivos ?? [], [data]);

  // Al llegar archivos nuevos se proponen su fecha y hora (de la ruta) y se
  // eligen los que aún no se importaron a esta intersección.
  useEffect(() => {
    setFilas((prev) => {
      const n: Record<string, Fila> = {};
      for (const a of archivos) {
        n[a.ruta] = prev[a.ruta] ?? {
          fecha: a.fecha ?? todayISO(),
          hora: a.hora ?? '',
          elegido: a.importado == null,
        };
      }
      return n;
    });
  }, [archivos]);

  useEffect(() => {
    if (data?.importacion?.activa) setActiva(true);
  }, [data]);

  useEffect(() => {
    if (activa && estado && !estado.activa) {
      setActiva(false);
      void refetch();
      void qc.invalidateQueries({ queryKey: ['videos'] });
    }
  }, [activa, estado, refetch, qc]);

  if (!data?.disponible || archivos.length === 0) return null;

  const elegidos = archivos.filter((a) => filas[a.ruta]?.elegido && a.importado == null);
  const sinHora = elegidos.filter((a) => !filas[a.ruta]?.fecha || !filas[a.ruta]?.hora);
  const bytes = elegidos.reduce((s, a) => s + a.tamano, 0);
  const pendientes = archivos.filter((a) => a.importado == null).length;

  async function importar() {
    setError(null);
    if (sinHora.length) {
      setError(
        `Falta la hora de inicio de ${plural(sinHora.length, 'video', 'videos')}: sin ella sus vehículos no caen en ningún cuarto de hora del reporte.`,
      );
      return;
    }
    try {
      await importarEntrada(
        projectId,
        elegidos.map((a) => {
          const f = filas[a.ruta];
          const h = f.hora.length === 5 ? `${f.hora}:00` : f.hora;
          return { ruta: a.ruta, inicio: `${f.fecha} ${h}` };
        }),
      );
      setActiva(true);
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  const progreso =
    estado?.bytes_total && estado.bytes_total > 0
      ? Math.min(1, (estado.bytes_hechos ?? 0) / estado.bytes_total)
      : 0;

  return (
    <Card className="staging rise">
      <h2 className="section-title">Videos en la carpeta de entrada</h2>
      <p className="field-hint">
        Llegaron por WinSCP o en un disco conectado al equipo:{' '}
        {plural(archivos.length, 'video', 'videos')}, {pendientes} sin importar a esta intersección.
        Importar los copia al disco de los videos; lo que se subió no se borra.
      </p>

      <div className="sf-start sf-todos">
        <span>Para todos:</span>
        <input
          type="date"
          aria-label="Fecha de grabación de todos los videos de la entrada"
          disabled={activa}
          onChange={(e) => {
            const v = e.target.value;
            if (v)
              setFilas((p) =>
                Object.fromEntries(Object.entries(p).map(([k, f]) => [k, { ...f, fecha: v }])),
              );
          }}
        />
        <Button onClick={() => void refetch()} disabled={isFetching || activa}>
          {isFetching ? 'Buscando…' : 'Volver a buscar'}
        </Button>
      </div>

      <div className="staging-files entrada-lista">
        {archivos.map((a) => {
          const f = filas[a.ruta];
          if (!f) return null;
          const hecho = a.importado != null;
          return (
            <div className={`staging-file-row${hecho ? ' is-hecho' : ''}`} key={a.ruta}>
              <input
                type="checkbox"
                checked={!hecho && f.elegido}
                disabled={hecho || activa}
                aria-label={`Importar ${a.nombre}`}
                onChange={(e) =>
                  setFilas((p) => ({ ...p, [a.ruta]: { ...f, elegido: e.target.checked } }))
                }
              />
              <span className="sf-name" title={a.nombre}>
                {a.nombre}
              </span>
              <span className="sf-meta">{formatSize(a.tamano)}</span>
              {hecho ? (
                <span className="sf-meta">ya importado</span>
              ) : (
                <div className="sf-start">
                  <span>Inicio real:</span>
                  <input
                    type="date"
                    value={f.fecha}
                    disabled={activa}
                    aria-label={`Fecha de inicio de ${a.nombre}`}
                    onChange={(e) =>
                      setFilas((p) => ({ ...p, [a.ruta]: { ...f, fecha: e.target.value } }))
                    }
                  />
                  <input
                    type="time"
                    step={1}
                    value={f.hora}
                    disabled={activa}
                    aria-label={`Hora de inicio de ${a.nombre}`}
                    onChange={(e) =>
                      setFilas((p) => ({ ...p, [a.ruta]: { ...f, hora: e.target.value } }))
                    }
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>

      {activa && estado && (
        <div className="sf-progreso">
          <div
            className="job-progress"
            role="progressbar"
            aria-valuenow={Math.round(progreso * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label="Importación de la carpeta de entrada"
          >
            <div className="bar" style={{ scale: `${progreso} 1` }} />
          </div>
          <span className="sf-meta">
            {estado.hechos ?? 0} de {estado.total ?? 0} · {formatSize(estado.bytes_hechos ?? 0)} de{' '}
            {formatSize(estado.bytes_total ?? 0)}
            {estado.actual ? ` · ${estado.actual}` : ''}
          </span>
        </div>
      )}

      {!activa && estado && (estado.videos?.length || estado.errores?.length) ? (
        <Notice tone={estado.errores?.length ? 'warning' : 'good'}>
          {plural(estado.videos?.length ?? 0, 'video importado', 'videos importados')}
          {estado.omitidos ? `, ${estado.omitidos} ya estaban` : ''}.
          {estado.errores?.map((e) => (
            <div key={e.ruta}>
              {e.ruta}: {e.motivo}
            </div>
          ))}
        </Notice>
      ) : null}
      {error && <Notice tone="critical">{error}</Notice>}

      <div className="staging-actions">
        <Button
          variant="primary"
          onClick={() => void importar()}
          disabled={activa || elegidos.length === 0}
        >
          {activa
            ? 'Importando…'
            : `Importar ${plural(elegidos.length, 'video', 'videos')} (${formatSize(bytes)})`}
        </Button>
      </div>
    </Card>
  );
}
