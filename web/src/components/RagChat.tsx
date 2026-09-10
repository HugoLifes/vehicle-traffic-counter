/*
  Chat sobre los documentos.

  El mismo componente sirve para las dos vistas: sin projectId consulta la
  normativa general, y con él, los documentos de esa intersección más los
  generales. Los hilos NO se mezclan entre proyectos.

  Es un chat y no un buscador de una sola pregunta porque así es como se
  consulta la normativa de verdad: se pregunta algo, se lee, y la siguiente
  pregunta parte de la respuesta anterior. "¿Y el umbral de NMS?" no
  significa nada suelta, pero con el hilo detrás sí.
*/

import { useEffect, useRef, useState } from 'react';
import { Button, Card, EmptyState, IconButton, Notice, Pill } from './ui';
import { IconClose } from './Icons';
import {
  useCreateRagChat,
  useDeleteRagChat,
  useRagChat,
  useRagChats,
  useRagDocs,
  useSendRagMessage,
  useUploadRagDoc,
} from '../lib/queries';
import { errorMessage } from '../lib/api';
import { plural } from '../lib/format';
import type { RagFuente } from '../lib/types';

const SUGERENCIAS_GENERAL = [
  '¿Qué umbral de confianza recomienda la PT-914?',
  '¿Cómo se calcula el factor de hora pico?',
  '¿Qué exactitud reporta el estudio del IMT?',
];

const SUGERENCIAS_PROYECTO = [
  '¿Qué pide el cliente para este tramo?',
  '¿Qué clasificación vehicular hay que entregar?',
  '¿Qué días y horarios cubre el estudio?',
];

function tamano(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/* Las citas son el producto de esta función: sin ellas la respuesta no se
   puede verificar. Van plegadas porque lo que se lee es la respuesta, pero
   el control de abrirlas es visible y cuenta cuántas hay. */
function Fuentes({ fuentes }: { fuentes: RagFuente[] }) {
  const [abierto, setAbierto] = useState(false);
  if (!fuentes.length) return null;
  return (
    <div className="chat-fuentes">
      <button
        className="chat-fuentes-btn"
        aria-expanded={abierto}
        onClick={() => setAbierto((v) => !v)}
      >
        <svg className="chat-flecha" width="10" height="10" viewBox="0 0 10 10" aria-hidden="true">
          <path d="M3 1.5 L7 5 L3 8.5" fill="none" stroke="currentColor" strokeWidth="1.5"
            strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        {plural(fuentes.length, 'fuente citada', 'fuentes citadas')}
      </button>
      {abierto && (
        <ol className="rag-fuentes">
          {fuentes.map((f) => (
            <li className="rag-fuente" key={f.n}>
              <span className="rag-fuente-n">{f.n}</span>
              <div>
                <div className="rag-fuente-cab">
                  <span className="rag-fuente-doc" title={f.documento}>
                    {f.documento}
                  </span>
                  {f.pagina !== null && <span className="rag-pagina">pág. {f.pagina}</span>}
                  {/* De qué motor de búsqueda vino: deja ver si la híbrida
                      aporta o si uno solo carga con todo. */}
                  {f.en_vectorial && f.en_lexica ? (
                    <Pill tone="good">ambas búsquedas</Pill>
                  ) : f.en_vectorial ? (
                    <Pill>por significado</Pill>
                  ) : (
                    <Pill>por palabras</Pill>
                  )}
                </div>
                <p className="rag-extracto">{f.extracto}…</p>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function RagChat({ projectId }: { projectId?: number }) {
  const { data: chats } = useRagChats(projectId);
  const { data: docs, isLoading: cargandoDocs } = useRagDocs(projectId);
  const crear = useCreateRagChat(projectId);
  const borrarChat = useDeleteRagChat();
  const enviar = useSendRagMessage();
  const subir = useUploadRagDoc();

  const [activo, setActivo] = useState<number | null>(null);
  const [texto, setTexto] = useState('');
  const [encima, setEncima] = useState(false);
  const { data: hilo } = useRagChat(activo);
  const finRef = useRef<HTMLDivElement>(null);
  const areaRef = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  // Al entrar se abre la conversación más reciente en vez de una pantalla
  // vacía: lo normal es continuar lo último, no empezar de cero.
  useEffect(() => {
    if (activo === null && chats?.length) setActivo(chats[0].id);
  }, [chats, activo]);

  useEffect(() => {
    finRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' });
  }, [hilo?.mensajes.length, enviar.isPending]);

  const hayDocs = (docs?.length ?? 0) > 0;
  const mensajes = hilo?.mensajes ?? [];
  const sugerencias = projectId ? SUGERENCIAS_PROYECTO : SUGERENCIAS_GENERAL;

  async function mandar(pregunta?: string) {
    const p = (pregunta ?? texto).trim();
    if (!p) return;
    let id = activo;
    if (id === null) {
      id = (await crear.mutateAsync()).id;
      setActivo(id);
    }
    setTexto('');
    enviar.mutate({ id, pregunta: p });
  }

  function indexar(files: FileList | null) {
    if (!files?.length) return;
    // De uno en uno: el indexado es síncrono del lado del servidor para
    // poder avisar en el momento si un PDF viene escaneado y sin texto.
    Array.from(files).forEach((f) => {
      const form = new FormData();
      form.append('file', f);
      if (projectId) form.append('project_id', String(projectId));
      subir.mutate(form);
    });
    if (fileRef.current) fileRef.current.value = '';
  }

  return (
    <div className="rag-layout">
      <Card className="chat-card">
        <div className="chat-hilo" role="log" aria-live="polite">
          {mensajes.length === 0 && !enviar.isPending && (
            <>
              <EmptyState
                title={hayDocs ? 'Pregunta lo que necesites' : 'Sube un documento para empezar'}
                body={
                  hayDocs
                    ? 'Las respuestas salen solo de tus documentos, y cada una viene con la cita de dónde salió el dato.'
                    : projectId
                      ? 'Sube aquí los documentos de esta intersección: el proyecto ejecutivo, los requisitos del cliente, los oficios.'
                      : 'Sube la normativa que apliques a todos los estudios: la PT-914, manuales de ingeniería de tránsito.'
                }
              />
              {hayDocs && (
                <div className="chat-sugerencias">
                  {sugerencias.map((s) => (
                    <button key={s} className="chat-chip" onClick={() => void mandar(s)}>
                      {s}
                    </button>
                  ))}
                </div>
              )}
            </>
          )}

          {mensajes.map((m) => (
            <div key={m.id} className={`chat-msg chat-${m.rol}`}>
              {m.rol === 'assistant' && (
                <span className="chat-quien">
                  <span className="chat-punto" aria-hidden="true" />
                  Respuesta
                </span>
              )}
              <div className="chat-burbuja">{m.texto}</div>
              {m.rol === 'assistant' && <Fuentes fuentes={m.fuentes} />}
            </div>
          ))}

          {enviar.isPending && (
            <div className="chat-msg chat-assistant">
              <span className="chat-quien">
                <span className="chat-punto" aria-hidden="true" />
                Buscando en tus documentos
              </span>
              {/* Tres puntos + la etiqueta de arriba: la señal no depende
                  solo del movimiento. */}
              <div className="chat-pensando" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
            </div>
          )}
          <div ref={finRef} />
        </div>

        {enviar.isError && (
          <div style={{ padding: 'var(--space-4) var(--space-5) 0' }}>
            <Notice title="No se pudo responder">{errorMessage(enviar.error)}</Notice>
          </div>
        )}

        <div className="chat-entrada">
          {/*
            La caja crece con el texto sin una línea de JavaScript: el
            contenedor lleva el mismo texto en un `::after` invisible y es
            ese duplicado el que define el alto. La versión anterior lo
            medía al montar con `scrollHeight`, y si la pestaña todavía no
            estaba visible la medición salía disparada y el campo se
            quedaba clavado en su tope de 160 px.
          */}
          <div className="chat-crece" data-replica={texto}>
            <textarea
              ref={areaRef}
              rows={1}
              value={texto}
              placeholder={hayDocs ? 'Escribe tu pregunta…' : 'Primero sube un documento'}
              aria-label="Tu pregunta"
              disabled={!hayDocs}
              onChange={(e) => setTexto(e.target.value)}
              onKeyDown={(e) => {
                // Enter envía, Shift+Enter salta de línea: lo que ya espera
                // cualquiera que haya usado un chat.
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  void mandar();
                }
              }}
            />
          </div>
          <Button
            variant="primary"
            disabled={!texto.trim() || enviar.isPending || !hayDocs}
            onClick={() => void mandar()}
          >
            Enviar
          </Button>
        </div>
      </Card>

      <div className="rag-lateral">
        <Card>
          <div className="chat-cab">
            <h2>Conversaciones</h2>
            <Button
              onClick={async () => {
                const { id } = await crear.mutateAsync();
                setActivo(id);
              }}
            >
              Nueva
            </Button>
          </div>
          <div className="chat-lista">
            {(chats?.length ?? 0) === 0 && <p className="sc-info">Ninguna todavía.</p>}
            {chats?.map((c) => (
              <div className={`chat-item${c.id === activo ? ' is-activo' : ''}`} key={c.id}>
                <button
                  className="chat-item-btn"
                  aria-current={c.id === activo ? 'true' : undefined}
                  onClick={() => setActivo(c.id)}
                >
                  <span className="chat-item-titulo">{c.titulo}</span>
                  <span className="chat-item-meta">
                    {plural(c.mensajes, 'mensaje', 'mensajes')}
                  </span>
                </button>
                <IconButton
                  label={`Eliminar ${c.titulo}`}
                  tone="danger"
                  onClick={() => {
                    borrarChat.mutate(c.id);
                    if (c.id === activo) setActivo(null);
                  }}
                >
                  <IconClose />
                </IconButton>
              </div>
            ))}
          </div>
        </Card>

        <Card>
          <h2>Documentos</h2>
          <p className="sc-info">
            {projectId
              ? 'De esta intersección. Las respuestas también usan la normativa general.'
              : 'Aplican a todas las intersecciones.'}
          </p>

          <label
            className={`rag-soltar${encima ? ' is-encima' : ''}`}
            onDragOver={(e) => {
              e.preventDefault();
              setEncima(true);
            }}
            onDragLeave={() => setEncima(false)}
            onDrop={(e) => {
              e.preventDefault();
              setEncima(false);
              indexar(e.dataTransfer.files);
            }}
          >
            <input
              ref={fileRef}
              type="file"
              multiple
              accept=".pdf,.txt,.md,.csv"
              onChange={(e) => indexar(e.target.files)}
            />
            <span className="rag-soltar-titulo">
              {subir.isPending ? 'Indexando…' : 'Arrastra archivos aquí'}
            </span>
            <span className="rag-soltar-nota">PDF, TXT, MD o CSV — o haz clic para elegir</span>
          </label>

          {subir.isError && (
            <div style={{ marginTop: 'var(--space-3)' }}>
              <Notice title="No se pudo indexar">{errorMessage(subir.error)}</Notice>
            </div>
          )}
          {subir.isSuccess && (
            <div style={{ marginTop: 'var(--space-3)' }}>
              <Notice tone="good" title="Documento indexado">
                {subir.data.nombre} — {plural(subir.data.fragmentos, 'fragmento', 'fragmentos')}
              </Notice>
            </div>
          )}

          <div className="rag-docs">
            {!cargandoDocs && !hayDocs && <p className="sc-info">Sin documentos todavía.</p>}
            {docs?.map((d) => (
              <div className="rag-doc" key={d.id}>
                <div className="rag-doc-txt">
                  <span className="rag-doc-nombre" title={d.name}>
                    {d.name}
                  </span>
                  <span className="rag-doc-meta">
                    {plural(d.chunks, 'fragmento', 'fragmentos')} · {tamano(d.size_bytes)}
                    {projectId && d.project_id === null && ' · general'}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    </div>
  );
}
