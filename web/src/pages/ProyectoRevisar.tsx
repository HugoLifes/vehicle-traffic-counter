/*
  Vehículos a revisar: solo los dudosos de este aforo, con el recorte de su
  cuadro, para confirmar o corregir con un clic (src/engine/revision.py).

  Es lo que hacen las plataformas del ramo después de contar —OpenTrafficCam
  aparta los de clase insegura, Miovision revisa a mano lo anómalo— y lo que
  aquí solo se podía hacer con herramientas de línea de comandos. No hace
  falta revisarlos todos: unos cuantos de cada motivo ya dicen si el aforo
  tiene un problema que se repite.
*/

import { useState } from 'react';
import { useParams } from 'react-router-dom';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button, Card, ConfirmDialog, EmptyState, Notice, Pill } from '../components/ui';
import {
  decidirRevision,
  devolverDobles,
  errorMessage,
  getRevision,
  quitarDobles,
  recorteRevisionUrl,
  restaurarDescartado,
} from '../lib/api';
import { formatNumber } from '../lib/format';
import type { ColaRevision, ItemRevision, MotivoRevision } from '../lib/types';

const NOMBRE_CLASE: Record<string, string> = {
  A: 'Liviano (A)',
  MOTO: 'Moto',
  B: 'Autobús (B)',
  C: 'Camión (C)',
  'T-S': 'Tractocamión',
  TRACTOR: 'Tractor sin caja',
  PESADO: 'Pesado',
  SIN_RESOLVER: 'Sin clase',
};
const nombreClase = (c: string | null) => (c ? NOMBRE_CLASE[c] ?? c : 'Sin clase');

const POR_PAGINA = 24;

function Tarjeta({
  projectId,
  it,
  opciones,
  onHecho,
}: {
  projectId: number;
  it: ItemRevision;
  opciones: string[];
  onHecho: () => void;
}) {
  const [enviando, setEnviando] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [roto, setRoto] = useState(false);
  const esDoble = it.motivos.some((m) => m.motivo === 'doble');

  const decidir = async (decision: string) => {
    setEnviando(true);
    setError(null);
    try {
      await decidirRevision(projectId, it.tipo, it.id, decision);
      onHecho();
    } catch (e) {
      setError(errorMessage(e));
      setEnviando(false);
    }
  };

  return (
    <Card className="rev-tarjeta">
      {roto ? (
        <div className="rev-sin-imagen">No se pudo leer ese cuadro del video</div>
      ) : (
        <img
          className="rev-recorte"
          src={recorteRevisionUrl(projectId, it.tipo, it.id, it.pareja)}
          alt={`Vehículo de las ${it.hora.slice(11, 19)}`}
          loading="lazy"
          onError={() => setRoto(true)}
        />
      )}
      <div className="rev-datos">
        <div className="rev-cabeza">
          <strong>{nombreClase(it.clase)}</strong>
          <span className="rev-hora">{it.hora.slice(11, 19)}</span>
        </div>
        <div className="rev-donde">
          {it.tipo === 'movimiento' ? `Movimiento ${it.movimiento}` : it.linea}
          {it.alto ? ` · ${it.alto} px` : ''}
        </div>
        <ul className="rev-motivos">
          {it.motivos.map((m) => (
            <li key={m.motivo}>{m.texto}</li>
          ))}
        </ul>
        {esDoble && (
          <p className="rev-ayuda">
            Verde: este cruce. Naranja: el anterior. Si es el mismo vehículo, quítalo.
          </p>
        )}
        <div className="rev-botones">
          {esDoble && (
            <Button variant="primary" disabled={enviando} onClick={() => void decidir('descartar')}>
              Es el mismo, quitar
            </Button>
          )}
          {it.clase && opciones.includes(it.clase) && (
            <Button variant={esDoble ? 'secondary' : 'primary'} disabled={enviando} onClick={() => void decidir(it.clase!)}>
              {esDoble ? 'Son distintos' : `Correcto: ${nombreClase(it.clase)}`}
            </Button>
          )}
        </div>
        <div className="rev-otras">
          <span>Es otro tipo:</span>
          {opciones
            .filter((c) => c !== it.clase)
            .map((c) => (
              <button key={c} type="button" className="rev-clase" disabled={enviando} onClick={() => void decidir(c)}>
                {nombreClase(c)}
              </button>
            ))}
          {!esDoble && (
            <button type="button" className="rev-clase is-quitar" disabled={enviando} onClick={() => void decidir('descartar')}>
              No es vehículo
            </button>
          )}
        </div>
        {error && <p className="est-error">{error}</p>}
      </div>
    </Card>
  );
}

export default function ProyectoRevisar() {
  const projectId = Number(useParams().projectId);
  const qc = useQueryClient();
  const [motivo, setMotivo] = useState<MotivoRevision | undefined>(undefined);
  const [cuantos, setCuantos] = useState(POR_PAGINA);
  const clave = ['revision', projectId, motivo, cuantos];
  const { data, isLoading, isError, error } = useQuery<ColaRevision>({
    queryKey: clave,
    queryFn: () => getRevision(projectId, motivo, 0, cuantos),
  });
  // Lo que ya se decidió sale de la lista enseguida, sin esperar a la base.
  const [hechos, setHechos] = useState<Set<string>>(new Set());
  const [pregunta, setPregunta] = useState<'quitar' | 'devolver' | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const enBloque = async (que: 'quitar' | 'devolver') => {
    setPregunta(null);
    try {
      const r = que === 'quitar' ? await quitarDobles(projectId) : await devolverDobles(projectId);
      setAviso(
        que === 'quitar'
          ? `Se quitaron ${formatNumber(r.quitados ?? 0)} posibles dobles del conteo.`
          : `Se devolvieron ${formatNumber(r.devueltos ?? 0)} al conteo.`,
      );
      setHechos(new Set());
      void qc.invalidateQueries({ queryKey: ['revision', projectId] });
      void qc.invalidateQueries({ queryKey: ['validacion', projectId] });
    } catch (e) {
      setAviso(errorMessage(e));
    }
  };
  const marcar = (it: ItemRevision) => {
    setHechos((h) => new Set(h).add(`${it.tipo}${it.id}`));
    void qc.invalidateQueries({ queryKey: ['revision', projectId] });
  };

  if (isLoading) return <EmptyState title="Buscando los vehículos dudosos…" />;
  if (isError || !data) return <Notice title="No se pudo cargar la revisión">{errorMessage(error)}</Notice>;

  const total = data.total;
  const dobles = data.resumen.find((r) => r.motivo === 'doble')?.total ?? 0;
  const enBloqueQuitados = data.descartados.filter((d) => d.motivo === 'doble (en bloque)').length;
  const items = data.items.filter((it) => !hechos.has(`${it.tipo}${it.id}`));

  return (
    <div className="rev-pagina">
      <Card className="chart-card">
        <h3>Vehículos a revisar</h3>
        <p className="chart-sub">
          La plataforma aparta los vehículos de los que no está segura: posibles dobles conteos, los que
          quedan justo entre liviano y pesado, y los que el detector vio poco. Revisar unos cuantos de cada
          grupo dice si el aforo tiene un problema que se repite. Lo que se decide aquí cambia el Excel y el
          Reporte.
        </p>
        <div className="rev-filtros">
          <button type="button" className={`rev-filtro ${!motivo ? 'is-activo' : ''}`} onClick={() => { setMotivo(undefined); setCuantos(POR_PAGINA); }}>
            Todos <Pill>{formatNumber(total)}</Pill>
          </button>
          {data.resumen.map((r) => (
            <button
              type="button"
              key={r.motivo}
              className={`rev-filtro ${motivo === r.motivo ? 'is-activo' : ''}`}
              onClick={() => { setMotivo(r.motivo); setCuantos(POR_PAGINA); }}
            >
              {r.nombre} <Pill tone={r.motivo === 'doble' ? 'warning' : 'neutral'}>{formatNumber(r.total)}</Pill>
            </button>
          ))}
        </div>
        <p className="chart-sub">
          {formatNumber(data.revisados)} revisados a mano · {formatNumber(data.descartados.length)} quitados del conteo
        </p>
        {(dobles > 0 || enBloqueQuitados > 0) && (
          <div className="rev-bloque">
            {dobles > 0 && (
              <Button onClick={() => setPregunta('quitar')}>Quitar los {formatNumber(dobles)} posibles dobles</Button>
            )}
            {enBloqueQuitados > 0 && (
              <Button onClick={() => setPregunta('devolver')}>
                Devolver los {formatNumber(enBloqueQuitados)} dobles quitados
              </Button>
            )}
          </div>
        )}
        {aviso && (
          <Notice tone="info" onDismiss={() => setAviso(null)}>
            {aviso}
          </Notice>
        )}
      </Card>

      {items.length === 0 ? (
        <EmptyState
          title="No queda nada por revisar aquí"
          body="Cuando se cuenten más videos, los vehículos dudosos aparecen en esta lista."
        />
      ) : (
        <div className="rev-rejilla">
          {items.map((it) => (
            <Tarjeta key={`${it.tipo}${it.id}`} projectId={projectId} it={it} opciones={data.opciones} onHecho={() => marcar(it)} />
          ))}
        </div>
      )}
      {data.pendientes > data.items.length && (
        <Button onClick={() => setCuantos((n) => n + POR_PAGINA)}>
          Ver más ({formatNumber(data.pendientes - data.items.length)} por revisar)
        </Button>
      )}

      <ConfirmDialog
        open={pregunta !== null}
        title={pregunta === 'quitar' ? `¿Quitar los ${formatNumber(dobles)} posibles dobles?` : '¿Devolver los dobles quitados?'}
        body={
          pregunta === 'quitar'
            ? 'Revisados a ojo en Fraccionamiento, unos 9 de cada 10 eran el mismo vehículo contado dos veces. Cambian el Excel y el Reporte; se pueden devolver todos con un clic.'
            : `Vuelven al conteo los ${formatNumber(enBloqueQuitados)} que se quitaron en bloque.`
        }
        confirmLabel={pregunta === 'quitar' ? 'Quitar del conteo' : 'Devolver al conteo'}
        destructive={pregunta === 'quitar'}
        onConfirm={() => pregunta && void enBloque(pregunta)}
        onCancel={() => setPregunta(null)}
      />

      {data.descartados.length > 0 && (
        <Card className="chart-card">
          <details className="hrmov-dia">
            <summary>Quitados del conteo ({formatNumber(data.descartados.length)})</summary>
            <table className="data-table">
              <thead>
                <tr>
                  <th scope="col">Hora</th>
                  <th scope="col">Qué era</th>
                  <th scope="col">Quitado</th>
                  <th scope="col" />
                </tr>
              </thead>
              <tbody>
                {data.descartados.map((d) => (
                  <tr key={d.id}>
                    <td>{d.hora?.slice(0, 19) ?? '—'}</td>
                    <td>{d.tipo === 'cruce' ? 'Cruce de línea' : 'Movimiento'}</td>
                    <td>{d.fecha.slice(0, 16)}</td>
                    <td>
                      <button
                        type="button"
                        className="est-enlace"
                        onClick={() =>
                          void restaurarDescartado(projectId, d.id).then(() =>
                            qc.invalidateQueries({ queryKey: ['revision', projectId] }),
                          )
                        }
                      >
                        Devolver al conteo
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </details>
        </Card>
      )}
    </div>
  );
}
