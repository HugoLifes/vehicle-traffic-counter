/*
  Lista de intersecciones: la puerta de entrada.

  Cada tarjeta responde "¿cómo va esto?" de un vistazo y se abre entera
  para ver el detalle y trabajar — divulgación progresiva, en vez de
  amontonar tres enlaces por tarjeta hacia herramientas que solo tienen
  sentido una vez dentro.

  Dentro de la tarjeta manda UNA cifra: los vehículos contados. Antes las
  tres estadísticas iban al mismo tamaño y con la misma tinta, así que
  "22 508 cruces" pesaba lo mismo que "1 video" y la tarjeta no decía
  nada de un vistazo. Ahora el conteo va a --text-2xl y el resto a
  --text-sm: 2.8× de diferencia.

  El formulario de creación vive en components/ProjectForm porque es el
  mismo que edita: si un campo se agrega en uno, aparece en el otro.
*/

import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Page } from '../components/Page';
import { Button, EmptyState, Notice } from '../components/ui';
import { ProjectForm } from '../components/ProjectForm';
import { IconArrowRight, IconPin, IconVideo } from '../components/Icons';
import { useCreateProject, useProjects } from '../lib/queries';
import { errorMessage } from '../lib/api';
import { formatNumber, plural } from '../lib/format';
import type { Project } from '../lib/types';

/* --- Tarjeta de intersección -------------------------------------------- */

function ProjectCard({ p }: { p: Project }) {
  const contado = p.crossing_count > 0;
  return (
    /*
      La tarjeta entera es el enlace, no solo un botón dentro de ella:
      es lo que se espera al ver una tarjeta de resumen, y evita tener
      que apuntar a un objetivo pequeño. Dentro no va ningún otro
      elemento interactivo — un enlace dentro de otro enlace no se puede
      anunciar ni activar de forma coherente.
    */
    <Link className="project-card" to={`/proyecto/${p.id}`}>
      <div className="pc-body">
        <div className="pc-identity">
          <h3 className="pc-name">{p.name}</h3>
          {p.address ? (
            <p className="pc-address">
              <IconPin size={13} />
              <span>{p.address}</span>
            </p>
          ) : (
            <p className="pc-address is-missing">
              <IconPin size={13} />
              <span>Sin ubicación</span>
            </p>
          )}
        </div>

        {/* La cifra que importa, sola y grande. Las demás la acompañan
            una línea abajo, en el tamaño del texto corriente. */}
        <div className={`pc-figure${contado ? '' : ' is-empty'}`}>
          <span className="pc-figure-n">{contado ? formatNumber(p.crossing_count) : '—'}</span>
          <span className="pc-figure-label">
            {contado ? 'vehículos contados' : 'sin contar todavía'}
          </span>
        </div>
      </div>

      <div className="pc-foot">
        <span className="pc-meta">
          <IconVideo size={14} />
          {plural(p.video_count, 'video', 'videos')}
          <span className="pc-sep" aria-hidden="true">·</span>
          {plural(p.lane_count, 'carril', 'carriles')}
          {p.awaiting_count > 0 && (
            <span className="pc-badge">{formatNumber(p.awaiting_count)} sin calibrar</span>
          )}
        </span>
        <span className="pc-open">
          Abrir
          <IconArrowRight size={15} />
        </span>
      </div>
    </Link>
  );
}

/* --- Página -------------------------------------------------------------- */

export default function Proyectos() {
  const { data: projects, isLoading, isError, error } = useProjects();
  const create = useCreateProject();
  const [creating, setCreating] = useState(false);

  const lista = projects ?? [];
  const totalCruces = lista.reduce((s, p) => s + p.crossing_count, 0);
  const totalVideos = lista.reduce((s, p) => s + p.video_count, 0);

  return (
    <Page
      title="Proyectos de aforo"
      subtitle="Una intersección por proyecto — acumula su histórico de conteos"
      actions={
        <Button variant="primary" onClick={() => setCreating(true)} disabled={creating}>
          Nueva intersección
        </Button>
      }
    >
      {/* Lo acumulado de todas las intersecciones, en una línea. Va como
          texto y no como tarjetas: la emphasis de esta pantalla es elegir
          una intersección, y un segundo bloque de cifras grandes le
          quitaría el sitio. */}
      {lista.length > 0 && (
        <p className="proyectos-total">
          <strong className="num">{formatNumber(lista.length)}</strong>{' '}
          {lista.length === 1 ? 'intersección' : 'intersecciones'}
          <span className="pt-sep" aria-hidden="true">·</span>
          <strong className="num">{formatNumber(totalCruces)}</strong> vehículos contados
          <span className="pt-sep" aria-hidden="true">·</span>
          <strong className="num">{formatNumber(totalVideos)}</strong>{' '}
          {totalVideos === 1 ? 'video procesado' : 'videos procesados'}
        </p>
      )}

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

      {isLoading && <EmptyState title="Cargando intersecciones…" />}

      {!isLoading && !isError && lista.length === 0 && !creating && (
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

      {lista.length > 0 && (
        <div className="project-grid stagger">
          {lista.map((p) => (
            <ProjectCard key={p.id} p={p} />
          ))}
          {/*
            Baldosa de creación al final de la rejilla. No es adorno para
            rellenar: con una sola intersección la rejilla dejaba dos
            tercios de la pantalla en blanco, y el botón de crear estaba
            arriba del todo, lejos de donde el ojo termina de leer.
          */}
          <button
            type="button"
            className="project-nueva"
            onClick={() => setCreating(true)}
            disabled={creating}
          >
            <span className="pn-cruz" aria-hidden="true">
              +
            </span>
            <span className="pn-titulo">Nueva intersección</span>
            <span className="pn-nota">Un punto de medición con sus videos y su calibración</span>
          </button>
        </div>
      )}
    </Page>
  );
}
