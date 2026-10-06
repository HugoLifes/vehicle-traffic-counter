/*
  Importar los videos que llegaron a la carpeta de entrada del Jetson —por
  WinSCP o en un disco conectado— sin pasar por el navegador. Por la
  dirección pública el navegador sube a ~25 KB/s desde Juárez; por SFTP va a
  la velocidad de su internet y retoma solo si se corta.

  Un día de grabación son ~700 archivos en carpetas por hora (14/00.mp4 …
  14/59.mp4), así que se eligen por CARPETA, no archivo por archivo. La hora
  sale de la ruta; lo que no la trae se despliega sin marcar hasta que se la
  pongan, porque un video sin hora no cae en ningún cuarto de hora del
  reporte. Cada carpeta avisa de los minutos que faltan: un archivo cortado
  (como el de las 12:25 del frontal) se nota aquí y no después en el reporte.
  Importar copia cada video al disco de los videos; lo subido no se toca.
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
import { formatSize, plural } from '../lib/format';

interface Fila {
  fecha: string;
  hora: string;
  elegido: boolean;
}

interface Grupo {
  carpeta: string;
  archivos: ArchivoEntrada[];
}

const conHora = (f?: Fila) => Boolean(f && f.fecha && f.hora);
const minutos = (h: string) => {
  const [hh, mm] = h.split(':').map(Number);
  return hh * 60 + mm;
};
const reloj = (m: number) =>
  `${String(Math.floor(m / 60) % 24).padStart(2, '0')}:${String(m % 60).padStart(2, '0')}`;

/* Los minutos que faltan entre el primero y el último de una carpeta, solo
   cuando la carpeta es de un video por minuto (lo de Juárez). */
function huecos(horas: string[]): string[] {
  const ms = [...new Set(horas.map(minutos))].sort((a, b) => a - b);
  if (ms.length < 5) return [];
  const pasos = ms.slice(1).map((m, i) => m - ms[i]);
  if (pasos.filter((p) => p === 1).length < pasos.length * 0.8) return [];
  const faltan: string[] = [];
  for (let m = ms[0]; m <= ms[ms.length - 1]; m++) if (!ms.includes(m)) faltan.push(reloj(m));
  return faltan;
}

export function ImportarEntrada({ projectId }: { projectId: number }) {
  const qc = useQueryClient();
  const { data, refetch, isFetching } = useQuery({
    queryKey: ['entrada', projectId],
    queryFn: () => getEntrada(projectId),
    refetchInterval: 30000,
  });
  const [filas, setFilas] = useState<Record<string, Fila>>({});
  const [abiertos, setAbiertos] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);
  const [activa, setActiva] = useState(false);
  const { data: estado } = useQuery({
    queryKey: ['entrada-estado'],
    queryFn: getEstadoImportacion,
    refetchInterval: activa ? 1000 : false,
    enabled: activa,
  });

  const archivos: ArchivoEntrada[] = useMemo(() => data?.archivos ?? [], [data]);
  const grupos: Grupo[] = useMemo(() => {
    const m = new Map<string, ArchivoEntrada[]>();
    for (const a of archivos) {
      const i = a.nombre.lastIndexOf('/');
      const carpeta = i < 0 ? '' : a.nombre.slice(0, i);
      m.set(carpeta, [...(m.get(carpeta) ?? []), a]);
    }
    return [...m.entries()].map(([carpeta, lista]) => ({ carpeta, archivos: lista }));
  }, [archivos]);

  // Fecha y hora propuestas desde la ruta. Solo se marca lo que ya trae las
  // dos y no se importó a esta intersección.
  useEffect(() => {
    setFilas((prev) => {
      const n: Record<string, Fila> = {};
      for (const a of archivos) {
        n[a.ruta] = prev[a.ruta] ?? {
          fecha: a.fecha ?? '',
          hora: a.hora ?? '',
          elegido: a.importado == null && Boolean(a.fecha && a.hora),
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

  const pendientes = archivos.filter((a) => a.importado == null);
  const elegidos = pendientes.filter((a) => filas[a.ruta]?.elegido);
  const elegidosSinHora = elegidos.filter((a) => !conHora(filas[a.ruta]));
  const bytes = elegidos.reduce((s, a) => s + a.tamano, 0);
  const inicios = elegidos
    .filter((a) => conHora(filas[a.ruta]))
    .map((a) => `${filas[a.ruta].fecha} ${filas[a.ruta].hora.slice(0, 5)}`)
    .sort();

  function cambiar(ruta: string, cambio: Partial<Fila>) {
    setFilas((p) => {
      const f = { ...p[ruta], ...cambio };
      // Al completar la hora de un archivo que no la traía, se marca solo.
      if (!('elegido' in cambio) && conHora(f) && !conHora(p[ruta])) f.elegido = true;
      return { ...p, [ruta]: f };
    });
  }

  function marcarGrupo(g: Grupo, si: boolean) {
    setFilas((p) => {
      const n = { ...p };
      for (const a of g.archivos) {
        if (a.importado != null) continue;
        n[a.ruta] = { ...n[a.ruta], elegido: si && conHora(n[a.ruta]) };
      }
      return n;
    });
  }

  function marcarTodo(si: boolean) {
    for (const g of grupos) marcarGrupo(g, si);
  }

  async function importar() {
    setError(null);
    if (elegidosSinHora.length) {
      setError(`Falta la hora de inicio de ${plural(elegidosSinHora.length, 'video', 'videos')}.`);
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
    <Card className="staging entrada rise">
      <div className="entrada-cabeza">
        <h2 className="section-title">Videos en la carpeta de entrada</h2>
        <Button onClick={() => void refetch()} disabled={isFetching || activa}>
          {isFetching ? 'Buscando…' : 'Volver a buscar'}
        </Button>
      </div>
      <p className="field-hint">
        Llegaron por WinSCP o en un disco conectado al equipo:{' '}
        {plural(archivos.length, 'video', 'videos')} en{' '}
        {plural(grupos.length, 'carpeta', 'carpetas')}, {pendientes.length} sin importar a esta
        intersección. Se elige por carpeta; la hora sale del nombre (carpeta 14, archivo 05 =
        14:05). Importar los copia al disco de los videos; lo que se subió no se borra.
      </p>

      <div className="entrada-herramientas">
        <Button onClick={() => marcarTodo(true)} disabled={activa}>
          Marcar todo lo que tiene hora
        </Button>
        <Button onClick={() => marcarTodo(false)} disabled={activa}>
          Desmarcar todo
        </Button>
        <label className="entrada-fecha">
          Fecha para los que no la traen{' '}
          <input
            type="date"
            disabled={activa}
            onChange={(e) => {
              const v = e.target.value;
              if (!v) return;
              setFilas((p) => {
                const n = { ...p };
                for (const a of pendientes) if (!n[a.ruta].fecha) n[a.ruta] = { ...n[a.ruta], fecha: v };
                return n;
              });
            }}
          />
        </label>
      </div>

      <div className="entrada-grupos">
        {grupos.map((g) => {
          const pend = g.archivos.filter((a) => a.importado == null);
          const sinHora = pend.filter((a) => !conHora(filas[a.ruta]));
          const marcados = pend.filter((a) => filas[a.ruta]?.elegido).length;
          const horas = g.archivos.filter((a) => conHora(filas[a.ruta])).map((a) => filas[a.ruta].hora);
          const orden = [...horas].sort();
          const faltan = huecos(horas);
          const fechas = [...new Set(g.archivos.map((a) => filas[a.ruta]?.fecha).filter(Boolean))];
          const abierto = abiertos[g.carpeta] ?? sinHora.length > 0;
          const peso = g.archivos.reduce((s, a) => s + a.tamano, 0);
          return (
            <section className="entrada-grupo" key={g.carpeta || '(raíz)'}>
              <div className="eg-cabeza">
                <input
                  type="checkbox"
                  aria-label={`Importar la carpeta ${g.carpeta || 'principal'}`}
                  checked={pend.length > 0 && marcados === pend.length - sinHora.length && marcados > 0}
                  ref={(el) => {
                    if (el) el.indeterminate = marcados > 0 && marcados < pend.length - sinHora.length;
                  }}
                  disabled={activa || pend.length === sinHora.length}
                  onChange={(e) => marcarGrupo(g, e.target.checked)}
                />
                <button
                  type="button"
                  className="eg-titulo"
                  aria-expanded={abierto}
                  onClick={() => setAbiertos((p) => ({ ...p, [g.carpeta]: !abierto }))}
                >
                  <span className="eg-flecha" aria-hidden="true">
                    {abierto ? '▾' : '▸'}
                  </span>
                  <span className="eg-nombre">{g.carpeta || 'Archivos sueltos'}</span>
                </button>
                <span className="eg-datos num">
                  {plural(g.archivos.length, 'video', 'videos')}
                  {orden.length > 0 &&
                    ` · ${fechas.length === 1 ? `${fechas[0]} ` : ''}${orden[0].slice(0, 5)}–${orden[orden.length - 1].slice(0, 5)}`}
                  {` · ${formatSize(peso)}`}
                </span>
                <span className="eg-estado">
                  {pend.length === 0 && <span className="eg-chip is-hecho">ya importada</span>}
                  {pend.length > 0 && pend.length < g.archivos.length && (
                    <span className="eg-chip">{g.archivos.length - pend.length} ya importados</span>
                  )}
                  {sinHora.length > 0 && (
                    <span className="eg-chip is-aviso">{sinHora.length} sin hora</span>
                  )}
                  {faltan.length > 0 && (
                    <span className="eg-chip is-aviso" title={faltan.join(', ')}>
                      {faltan.length === 1 ? `falta ${faltan[0]}` : `faltan ${faltan.length} minutos`}
                    </span>
                  )}
                </span>
              </div>

              {abierto && (
                <div className="eg-archivos">
                  {g.archivos.map((a) => {
                    const f = filas[a.ruta];
                    if (!f) return null;
                    const hecho = a.importado != null;
                    const nombre = a.nombre.slice(a.nombre.lastIndexOf('/') + 1);
                    return (
                      <div className={`eg-archivo${hecho ? ' is-hecho' : ''}`} key={a.ruta}>
                        <input
                          type="checkbox"
                          checked={!hecho && f.elegido}
                          disabled={hecho || activa || !conHora(f)}
                          aria-label={`Importar ${a.nombre}`}
                          onChange={(e) => cambiar(a.ruta, { elegido: e.target.checked })}
                        />
                        <span className="ea-nombre" title={a.nombre}>
                          {nombre}
                        </span>
                        <span className="ea-peso num">{formatSize(a.tamano)}</span>
                        {hecho ? (
                          <span className="ea-nota">ya importado</span>
                        ) : (
                          <span className="ea-inicio">
                            <input
                              type="date"
                              value={f.fecha}
                              disabled={activa}
                              aria-label={`Fecha de inicio de ${a.nombre}`}
                              onChange={(e) => cambiar(a.ruta, { fecha: e.target.value })}
                            />
                            <input
                              type="time"
                              step={1}
                              value={f.hora}
                              disabled={activa}
                              aria-label={`Hora de inicio de ${a.nombre}`}
                              onChange={(e) => cambiar(a.ruta, { hora: e.target.value })}
                            />
                            {!conHora(f) && <span className="ea-nota is-aviso">falta la hora</span>}
                          </span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </section>
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
          {estado.omitidos ? `, ${estado.omitidos} ya estaban` : ''}. El siguiente paso es calibrar
          (si la intersección es nueva) y empezar el conteo.
          {estado.errores?.map((e) => (
            <div key={e.ruta}>
              {e.ruta}: {e.motivo}
            </div>
          ))}
        </Notice>
      ) : null}
      {error && <Notice tone="critical">{error}</Notice>}

      <div className="entrada-resumen">
        <span className="num">
          {elegidos.length === 0
            ? 'Nada marcado'
            : `${plural(elegidos.length, 'video', 'videos')} · ${formatSize(bytes)}` +
              (inicios.length ? ` · de ${inicios[0]} a ${inicios[inicios.length - 1]}` : '')}
        </span>
        <Button
          variant="primary"
          onClick={() => void importar()}
          disabled={activa || elegidos.length === 0}
        >
          {activa ? 'Importando…' : `Importar ${plural(elegidos.length, 'video', 'videos')}`}
        </Button>
      </div>
    </Card>
  );
}
