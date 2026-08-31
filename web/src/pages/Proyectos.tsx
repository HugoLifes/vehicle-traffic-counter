/*
  Lista de intersecciones: la puerta de entrada.

  Cada tarjeta responde "¿cómo va esto?" de un vistazo y se abre entera
  para ver el detalle y trabajar — divulgación progresiva, en vez de
  amontonar tres enlaces por tarjeta hacia herramientas que solo tienen
  sentido una vez dentro.

  El formulario de creación vive en components/ProjectForm porque es el
  mismo que edita: si un campo se agrega en uno, aparece en el otro.
*/

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Page } from '../components/Page';
import { Button, EmptyState, Notice } from '../components/ui';
import { ProjectForm } from '../components/ProjectForm';
import { IconArrowRight, IconPin } from '../components/Icons';
import { useCreateProject, useProjects } from '../lib/queries';
import { errorMessage } from '../lib/api';
import { formatNumber } from '../lib/format';
import type { Project } from '../lib/types';

/* --- Tarjeta de intersección -------------------------------------------- */

function ProjectCard({ p }: { p: Project }) {
  return (
    /*
      La tarjeta entera es el enlace, no solo un botón dentro de ella:
      es lo que se espera al ver una tarjeta de resumen, y evita tener
      que apuntar a un objetivo pequeño. Dentro no va ningún otro
      elemento interactivo — un enlace dentro de otro enlace no se puede
      anunciar ni activar de forma coherente.
    */
    <Link className="project-card card" to={`/proyecto/${p.id}`}>
      <div className="pc-head">
        <span className="pc-name">{p.name}</span>
        {p.awaiting_count > 0 && (
          <span className="pc-badge">{formatNumber(p.awaiting_count)} sin calibrar</span>
        )}
      </div>

      {p.address && (
        <div className="pc-address">
          <IconPin size={12} />
          <span>{p.address}</span>
        </div>
      )}

      <div className="pc-stats">
        <div className="pc-stat accent">
          <div className="pc-stat-label">Cruces</div>
          <div className="pc-stat-value">{formatNumber(p.crossing_count)}</div>
        </div>
        <div className="pc-stat">
          <div className="pc-stat-label">Videos</div>
          <div className="pc-stat-value">{formatNumber(p.video_count)}</div>
        </div>
        <div className="pc-stat">
          <div className="pc-stat-label">Carriles</div>
          <div className="pc-stat-value">{formatNumber(p.lane_count)}</div>
        </div>
      </div>

      <span className="pc-open">
        Abrir intersección
        <IconArrowRight size={15} />
      </span>
    </Link>
  );
}

/* --- Página -------------------------------------------------------------- */

export default function Proyectos() {
  const { data: projects, isLoading, isError, error } = useProjects();
  const create = useCreateProject();
  const [creating, setCreating] = useState(false);

  return (
    <Page
      title="Proyectos de aforo"
      subtitle="Una intersección por proyecto — acumula su histórico de conteos"
    >
      <div className="section-head">
        <h2 className="section-title">Intersecciones</h2>
        <Button variant="primary" onClick={() => setCreating(true)} disabled={creating}>
          Nueva intersección
        </Button>
      </div>

      {creating && (
        <ProjectForm
          titulo="Nueva intersección"
          etiquetaEnviar="Crear intersección"
          enviando={create.isPending}
          error={create.isError ? create.error : null}
          onCancel={() => setCreating(false)}
          onSubmit={async (data) => {
            await create.mutateAsync(data);
            setCreating(false);
          }}
        />
      )}

      {isError && (
        <div className="notice-stack">
          <Notice title="No se pudieron cargar las intersecciones">{errorMessage(error)}</Notice>
        </div>
      )}

      <div className="project-grid stagger">
        {isLoading && <EmptyState title="Cargando intersecciones…" />}

        {!isLoading && !isError && projects?.length === 0 && !creating && (
          <EmptyState
            title="Todavía no hay intersecciones"
            body="Una intersección agrupa los videos, los carriles y el histórico de conteos de un punto de medición."
            action={
              <Button variant="primary" onClick={() => setCreating(true)}>
                Crear la primera intersección
              </Button>
            }
          />
        )}

        {projects?.map((p) => (
          <ProjectCard key={p.id} p={p} />
        ))}
      </div>
    </Page>
  );
}
