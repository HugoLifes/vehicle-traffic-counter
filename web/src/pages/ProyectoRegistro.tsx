/*
  Registro de la intersección: qué se le ha hecho y cuándo.

  Un aforo sustenta decisiones de obra, así que tiene que poder responder
  "¿de dónde salió esta cifra?". Sin historial, dos reportes distintos del
  mismo proyecto no se pueden explicar: no hay forma de saber si entre uno
  y otro se movió una línea, se volvió a contar o se borró un video.

  Se agrupa por día porque así es como se recuerda el trabajo ("el martes
  recalibramos"), no por marca de tiempo suelta.
*/

import { useParams } from 'react-router-dom';
import { Card, EmptyState, Notice } from '../components/ui';
import { IconCheck, IconPin, IconVideo } from '../components/Icons';
import { useEvents } from '../lib/queries';
import { errorMessage } from '../lib/api';
import type { EventoProyecto, TipoEvento } from '../lib/types';

const ETIQUETA: Record<TipoEvento, string> = {
  proyecto: 'Proyecto',
  video: 'Videos',
  calibracion: 'Calibración',
  conteo: 'Conteo',
};

function Icono({ kind }: { kind: TipoEvento }) {
  if (kind === 'video') return <IconVideo size={13} strokeWidth={2} />;
  if (kind === 'calibracion') return <IconPin size={13} />;
  if (kind === 'conteo') return <IconCheck size={13} />;
  return <IconPin size={13} />;
}

/** "2026-08-31 14:05:12" → "31 de agosto de 2026". El backend guarda hora
    local sin zona, así que se parte el texto en vez de pasar por Date,
    que la interpretaría como UTC y podría cambiar el día. */
function dia(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  const meses = [
    'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
    'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
  ];
  return `${d} de ${meses[m - 1]} de ${y}`;
}

const hora = (iso: string) => iso.slice(11, 16);

export default function ProyectoRegistro() {
  const { projectId } = useParams();
  const { data, isLoading, isError, error } = useEvents(Number(projectId));

  if (isLoading) return <EmptyState title="Cargando el registro…" />;
  if (isError) {
    return <Notice title="No se pudo cargar el registro">{errorMessage(error)}</Notice>;
  }
  if (!data || data.length === 0) {
    return (
      <EmptyState
        title="Todavía no hay nada registrado"
        body="A partir de ahora queda anotado lo que se le hace a esta intersección: videos que entran o salen, líneas que se mueven y cada vez que se cuenta. Los cambios anteriores a esta versión no están, porque nadie los estaba apuntando."
      />
    );
  }

  // Agrupado por día, conservando el orden de más reciente a más antiguo
  // que ya trae el backend.
  const dias: { fecha: string; eventos: EventoProyecto[] }[] = [];
  for (const ev of data) {
    const f = dia(ev.created_at);
    const ultimo = dias[dias.length - 1];
    if (ultimo && ultimo.fecha === f) ultimo.eventos.push(ev);
    else dias.push({ fecha: f, eventos: [ev] });
  }

  return (
    <div className="proj-resumen">
      <Card className="proj-tool-card">
        <h3 className="section-title">Historial</h3>
        <p className="ptc-body">
          De más reciente a más antiguo. Es lo que permite explicar por qué dos reportes del mismo
          aforo no dan lo mismo.
        </p>

        {dias.map((d) => (
          <section className="reg-dia" key={d.fecha}>
            <h4 className="reg-fecha">{d.fecha}</h4>
            <ol className="reg-lista">
              {d.eventos.map((ev) => (
                <li className="reg-evento" key={ev.id}>
                  <span className={`reg-icono tipo-${ev.kind}`}>
                    <Icono kind={ev.kind} />
                  </span>
                  <time className="reg-hora mono" dateTime={ev.created_at.replace(' ', 'T')}>
                    {hora(ev.created_at)}
                  </time>
                  <div className="reg-texto">
                    <span className="reg-resumen">{ev.summary}</span>
                    {ev.detail && <span className="reg-detalle">{ev.detail}</span>}
                  </div>
                  {/* La categoría va en palabra además de en el icono y su
                      color: tres señales, ninguna sola imprescindible. */}
                  <span className="reg-tipo">{ETIQUETA[ev.kind] ?? ev.kind}</span>
                </li>
              ))}
            </ol>
          </section>
        ))}
      </Card>
    </div>
  );
}
