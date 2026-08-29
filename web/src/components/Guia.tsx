/*
  Guía de primeros pasos.

  No es un carrusel de diapositivas: cada paso se marca como completado
  leyendo el estado REAL del proyecto (¿existe?, ¿tiene videos?, ¿tiene
  carriles?, ¿ya hay conteos?). Eso la hace útil también para quien vuelve
  a mitad del proceso — que es el caso normal aquí, porque un aforo se
  levanta en varias sesiones y a veces en varios días.

  Se actualiza sola porque lee la misma consulta de proyectos que el resto
  de la página: cuando se sube un video o se crea un carril, esa consulta
  se invalida y la guía avanza sin recargar ni sondear por su cuenta.
*/

import { useCallback, useState } from 'react';
import { Link } from 'react-router-dom';
import { IconCheck, IconClose } from './Icons';
import { IconButton } from './ui';
import type { Project } from '../lib/types';

const DISMISSED_KEY = 'guia-dismissed';

interface GuiaState {
  /** La intersección que se está viendo, si hay una elegida. */
  project: Project | null;
  /** Cuántas intersecciones existen en total. */
  projectCount: number;
}

interface Step {
  id: string;
  title: string;
  body: string;
  action: { label: string; to: string };
  done: (s: GuiaState) => boolean;
}

const STEPS: Step[] = [
  {
    id: 'crear',
    title: 'Crea la intersección',
    body: 'Cada punto donde mides tránsito es un proyecto. Ahí se acumula todo su histórico.',
    action: { label: 'Ir a Proyectos', to: '/' },
    done: (s) => s.projectCount > 0,
  },
  {
    id: 'subir',
    title: 'Sube los videos',
    body: 'Uno o varios segmentos. Si son partes de la misma hora, se unen solos en el reporte.',
    action: { label: 'Subir videos', to: '/subir' },
    done: (s) => (s.project?.video_count ?? 0) > 0,
  },
  {
    id: 'calibrar',
    title: 'Marca los carriles',
    body: 'Dibuja la línea cruzando el carril completo, justo donde pasan los vehículos, y presiona "Empezar conteo".',
    action: { label: 'Calibrar', to: '/calibrar' },
    done: (s) => (s.project?.lane_count ?? 0) > 0,
  },
  {
    id: 'reporte',
    title: 'Consulta el reporte',
    body: 'Volumen por intervalo, hora de máxima demanda y factor de hora pico (FHP).',
    action: { label: 'Ver reporte', to: '/reporte' },
    done: (s) => (s.project?.crossing_count ?? 0) > 0,
  },
];

function readDismissed(): boolean {
  try {
    return localStorage.getItem(DISMISSED_KEY) === '1';
  } catch {
    return false;
  }
}

export function Guia({ project, projectCount }: GuiaState) {
  const [dismissed, setDismissed] = useState(readDismissed);

  const dismiss = useCallback(() => {
    try {
      localStorage.setItem(DISMISSED_KEY, '1');
    } catch {
      // Sin almacenamiento la guía vuelve al recargar. No es grave.
    }
    setDismissed(true);
  }, []);

  const results = STEPS.map((step) => step.done({ project, projectCount }));
  const currentIndex = results.findIndex((r) => !r);

  // Si ya completó todo, la guía cumplió su función y desaparece sola.
  if (dismissed || currentIndex === -1) return null;

  const query = project ? `?project=${project.id}` : '';

  return (
    <section className="guia rise" aria-labelledby="guia-title">
      <div className="guia-head">
        <div>
          <h2 id="guia-title">Primeros pasos</h2>
          <p className="guia-sub">
            Paso {currentIndex + 1} de {STEPS.length} — la guía se cierra sola al terminar.
          </p>
        </div>
        <IconButton label="Cerrar la guía de primeros pasos" onClick={dismiss}>
          <IconClose />
        </IconButton>
      </div>

      <ol className="guia-steps">
        {STEPS.map((step, i) => {
          const done = results[i];
          const isCurrent = i === currentIndex;
          return (
            <li
              key={step.id}
              className={`guia-step${done ? ' done' : ''}${isCurrent ? ' current' : ''}`}
            >
              {/* El paso completado se distingue por la palomita y el
                  tachado, no solo por el color. */}
              <span className={`gs-mark${done ? ' done' : isCurrent ? ' current' : ''}`}>
                {done && <IconCheck size={12} />}
              </span>
              <div className="gs-text">
                <div className="gs-title">{step.title}</div>
                {isCurrent && <div className="gs-body">{step.body}</div>}
              </div>
              {isCurrent && (
                /* El enlace se estiliza como botón en vez de envolver uno:
                   un <button> dentro de un <a> es contenido interactivo
                   anidado y los lectores de pantalla lo anuncian mal. */
                <Link
                  className="gs-action btn btn-primary"
                  to={step.action.to === '/' ? '/' : `${step.action.to}${query}`}
                >
                  {step.action.label}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </section>
  );
}
