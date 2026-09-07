/*
  Documentos y consultas (RAG).

  Un aforo produce cifras, pero el informe que las acompaña se apoya en
  normativa: la PT-914 del IMT, manuales de ingeniería de tránsito, los
  requisitos del cliente. Esta pantalla deja subir esos documentos y
  preguntarles, y la respuesta viene con la cita de dónde salió cada cosa.

  Las citas no son decoración: un aforo sustenta decisiones de obra, así
  que quien lea la respuesta tiene que poder ir al documento y verificarla.
*/

import { useRef, useState } from 'react';
import { Page } from '../components/Page';
import { Button, Card, EmptyState, IconButton, Notice, Pill } from '../components/ui';
import { IconClose } from '../components/Icons';
import { useAskRag, useDeleteRagDoc, useRagDocs, useUploadRagDoc } from '../lib/queries';
import { errorMessage } from '../lib/api';
import { plural } from '../lib/format';
import type { RagDocumento } from '../lib/types';

const EJEMPLOS = [
  '¿Qué umbral de confianza recomienda la PT-914?',
  '¿Cómo se calcula el factor de hora pico?',
  '¿Qué exactitud reporta el estudio del IMT?',
];

function tamano(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export default function Documentos() {
  const { data: docs, isLoading } = useRagDocs();
  const subir = useUploadRagDoc();
  const borrar = useDeleteRagDoc();
  const preguntar = useAskRag();

  const [pregunta, setPregunta] = useState('');
  const [aBorrar, setABorrar] = useState<RagDocumento | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const hayDocs = (docs?.length ?? 0) > 0;

  function onArchivos(files: FileList | null) {
    if (!files?.length) return;
    // De uno en uno: indexar es síncrono del lado del servidor (para poder
    // avisar en el momento si un PDF viene escaneado y sin texto), así que
    // mandarlos en paralelo solo haría que se estorben.
    Array.from(files).forEach((f) => {
      const form = new FormData();
      form.append('file', f);
      subir.mutate(form);
    });
    if (inputRef.current) inputRef.current.value = '';
  }

  function enviar() {
    const p = pregunta.trim();
    if (p) preguntar.mutate(p);
  }

  const respuesta = preguntar.data;

  return (
    <Page
      title="Documentos y consultas"
      subtitle="Pregunta sobre tu normativa y recibe la respuesta con su cita"
    >
      <div className="rag-layout">
        <div className="rag-main">
          <Card>
            <h2>Preguntar</h2>
            <textarea
              className="rag-input"
              rows={3}
              value={pregunta}
              placeholder="¿Qué dice la norma sobre…?"
              aria-label="Tu pregunta"
              onChange={(e) => setPregunta(e.target.value)}
              onKeyDown={(e) => {
                // Enter envía; Shift+Enter deja escribir varias líneas.
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault();
                  enviar();
                }
              }}
            />
            <div className="rag-acciones">
              <Button
                variant="primary"
                disabled={!pregunta.trim() || preguntar.isPending || !hayDocs}
                onClick={enviar}
              >
                {preguntar.isPending ? 'Buscando…' : 'Preguntar'}
              </Button>
              {!hayDocs && !isLoading && (
                <span className="sc-info">Sube un documento primero.</span>
              )}
            </div>

            {hayDocs && !respuesta && !preguntar.isPending && (
              <div className="rag-ejemplos">
                {EJEMPLOS.map((e) => (
                  <button key={e} className="rag-chip" onClick={() => setPregunta(e)}>
                    {e}
                  </button>
                ))}
              </div>
            )}

            {preguntar.isError && (
              <div style={{ marginTop: 'var(--space-3)' }}>
                <Notice title="No se pudo responder">{errorMessage(preguntar.error)}</Notice>
              </div>
            )}
          </Card>

          {respuesta && (
            <Card className="rise">
              <h2>Respuesta</h2>
              <p className="rag-respuesta">{respuesta.respuesta}</p>

              {respuesta.fuentes.length > 0 && (
                <>
                  <h3 className="rag-subtitulo">
                    {plural(respuesta.fuentes.length, 'Fuente citada', 'Fuentes citadas')}
                  </h3>
                  <ol className="rag-fuentes">
                    {respuesta.fuentes.map((f) => (
                      <li key={f.n}>
                        <div className="rag-fuente-cab">
                          <strong>{f.documento}</strong>
                          {f.pagina !== null && <span className="rag-pagina">pág. {f.pagina}</span>}
                          {/* De qué motor vino: deja ver si la búsqueda
                              híbrida está aportando o si uno solo carga
                              con todo. */}
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
                </>
              )}
            </Card>
          )}
        </div>

        <Card className="rag-panel">
          <h2>Documentos</h2>
          <p className="sc-info">
            PDF, TXT, MD o CSV. Se indexan al subirlos, así que si un PDF viene escaneado y sin
            texto te lo dice en el momento.
          </p>

          <input
            ref={inputRef}
            type="file"
            multiple
            accept=".pdf,.txt,.md,.csv"
            className="rag-file"
            onChange={(e) => onArchivos(e.target.files)}
          />

          {subir.isPending && <p className="sc-info">Indexando…</p>}
          {subir.isError && (
            <div style={{ marginTop: 'var(--space-2)' }}>
              <Notice title="No se pudo indexar">{errorMessage(subir.error)}</Notice>
            </div>
          )}
          {subir.isSuccess && (
            <div style={{ marginTop: 'var(--space-2)' }}>
              <Notice tone="good" title="Documento indexado">
                {subir.data.nombre} — {plural(subir.data.fragmentos, 'fragmento', 'fragmentos')}
              </Notice>
            </div>
          )}

          <div className="lane-list" style={{ marginTop: 'var(--space-3)' }}>
            {!isLoading && !hayDocs && (
              <EmptyState
                title="Sin documentos"
                body="Sube la normativa que quieras consultar: la PT-914, manuales, requisitos del cliente."
              />
            )}
            {docs?.map((d) => (
              <div className="lane-item" key={d.id}>
                <div className="rag-doc">
                  <strong>{d.name}</strong>
                  <span className="sc-info">
                    {plural(d.chunks, 'fragmento', 'fragmentos')} · {tamano(d.size_bytes)}
                  </span>
                </div>
                <IconButton
                  label={`Eliminar ${d.name}`}
                  tone="danger"
                  onClick={() => setABorrar(d)}
                >
                  <IconClose />
                </IconButton>
              </div>
            ))}
          </div>

          {aBorrar && (
            <div style={{ marginTop: 'var(--space-3)' }}>
              <Notice tone="warning" title={`¿Eliminar ${aBorrar.name}?`}>
                Se borran sus {aBorrar.chunks} fragmentos y deja de aparecer en las respuestas.
                <div style={{ display: 'flex', gap: 'var(--space-2)', marginTop: 'var(--space-3)' }}>
                  <Button
                    onClick={() => {
                      borrar.mutate(aBorrar.id);
                      setABorrar(null);
                    }}
                  >
                    Eliminar
                  </Button>
                  <Button onClick={() => setABorrar(null)}>Cancelar</Button>
                </div>
              </Notice>
            </div>
          )}
        </Card>
      </div>
    </Page>
  );
}
