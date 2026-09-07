/*
  Chat sobre los documentos.

  El mismo componente sirve para las dos vistas: sin projectId consulta la
  normativa general, y con él, los documentos de esa intersección más los
  generales. Los hilos NO se mezclan entre proyectos: preguntar dentro de
  una intersección no debe mostrar la conversación de otra, aunque el
  documento de fondo sea el mismo.

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

function tamano(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function Fuentes({ fuentes }: { fuentes: RagFuente[] }) {
  const [abierto, setAbierto] = useState(false);
  if (!fuentes.length) return null;
  return (
    <div className="chat-fuentes">
      <button className="chat-fuentes-btn" onClick={() => setAbierto((v) => !v)}>
        {abierto ? '▾' : '▸'} {plural(fuentes.length, 'fuente citada', 'fuentes citadas')}
      </button>
      {abierto && (
        <ol className="rag-fuentes">
          {fuentes.map((f) => (
            <li key={f.n}>
              <div className="rag-fuente-cab">
                <strong>{f.documento}</strong>
                {f.pagina !== null && <span className="rag-pagina">pág. {f.pagina}</span>}
                {/* De qué motor de búsqueda vino. Deja ver si la híbrida
                    está aportando o si uno solo carga con todo. */}
                {f.en_vectorial && f.en_lexica ? (
                  <Pill tone="good">ambas búsquedas</Pill>
                ) : f.en_vectorial ? (
                  <Pill>por significado</Pill>
                ) : (
                  <Pill>por palabras</Pill>
                )}
              </div>
              <p className="rag-extracto">{f.extracto}…</p>
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
  const { data: hilo } = useRagChat(activo);
  const finRef = useRef<HTMLDivElement>(null);
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

  async function mandar() {
    const p = texto.trim();
    if (!p) return;
    let id = activo;
    if (id === null) {
      id = (await crear.mutateAsync()).id;
      setActivo(id);
    }
    setTexto('');
    enviar.mutate({ id, pregunta: p });
  }

  function onArchivos(files: FileList | null) {
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
            <EmptyState
              title={hayDocs ? 'Pregunta lo que necesites' : 'Sube un documento para empezar'}
              body={
                hayDocs
                  ? 'Las respuestas salen solo de tus documentos y vienen con la cita de dónde salió cada dato.'
                  : projectId
                    ? 'Sube aquí los documentos de esta intersección: el proyecto ejecutivo, los requisitos del cliente.'
                    : 'Sube la normativa que apliques a todos los estudios: la PT-914, manuales de ingeniería de tránsito.'
              }
            />
          )}

          {mensajes.map((m) => (
            <div key={m.id} className={`chat-msg chat-${m.rol}`}>
              <div className="chat-burbuja">{m.texto}</div>
              {m.rol === 'assistant' && <Fuentes fuentes={m.fuentes} />}
            </div>
          ))}

          {enviar.isPending && (
            <div className="chat-msg chat-assistant">
              <div className="chat-burbuja chat-pensando">Buscando en tus documentos…</div>
            </div>
          )}
          <div ref={finRef} />
        </div>

        {enviar.isError && (
          <Notice title="No se pudo responder">{errorMessage(enviar.error)}</Notice>
        )}

        <div className="chat-entrada">
          <textarea
            rows={2}
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
          <div className="lane-list">
            {(chats?.length ?? 0) === 0 && <p className="sc-info">Ninguna todavía.</p>}
            {chats?.map((c) => (
              <div className={`chat-item${c.id === activo ? ' is-activo' : ''}`} key={c.id}>
                <button className="chat-item-btn" onClick={() => setActivo(c.id)}>
                  <span className="chat-item-titulo">{c.titulo}</span>
                  <span className="sc-info">{plural(c.mensajes, 'mensaje', 'mensajes')}</span>
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
              : 'Aplican a todas las intersecciones.'}{' '}
            PDF, TXT, MD o CSV.
          </p>
          <input
            ref={fileRef}
            type="file"
            multiple
            accept=".pdf,.txt,.md,.csv"
            className="rag-file"
            onChange={(e) => onArchivos(e.target.files)}
          />
          {subir.isPending && <p className="sc-info">Indexando…</p>}
          {subir.isError && (
            <Notice title="No se pudo indexar">{errorMessage(subir.error)}</Notice>
          )}
          {subir.isSuccess && (
            <Notice tone="good" title="Documento indexado">
              {subir.data.nombre} — {plural(subir.data.fragmentos, 'fragmento', 'fragmentos')}
            </Notice>
          )}
          <div className="lane-list" style={{ marginTop: 'var(--space-3)' }}>
            {!cargandoDocs && !hayDocs && <p className="sc-info">Sin documentos.</p>}
            {docs?.map((d) => (
              <div className="lane-item" key={d.id}>
                <div className="rag-doc">
                  <strong>{d.name}</strong>
                  <span className="sc-info">
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
