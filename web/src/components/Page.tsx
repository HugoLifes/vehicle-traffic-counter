/*
  Armazón común a todas las páginas: salto al contenido, barra de
  navegación, guía y el punto de referencia <main>.

  Vive en un solo lugar a propósito. Cuando cada página lo repetía por su
  cuenta bastaba con olvidar un margen en una para que el contenido
  quedara pegado al borde — que es exactamente lo que llegó a pasar.
*/

import { useEffect, type ReactNode } from 'react';
import { Nav } from './Nav';
import { Guia } from './Guia';
import { useProjectParam } from '../lib/useProjectParam';

interface PageProps {
  title: string;
  subtitle: string;
  /** Muestra la barra de pasos del proyecto (subir → calibrar → reporte). */
  projectScoped?: boolean;
  /** Oculta la guía en pantallas donde no aporta (la cámara en vivo). */
  hideGuide?: boolean;
  children: ReactNode;
}

export function Page({ title, subtitle, projectScoped, hideGuide, children }: PageProps) {
  const { project, projects } = useProjectParam();

  /*
    En la lista de proyectos no hay ninguna intersección elegida, pero la
    guía sí tiene que decir algo útil. Toma como referencia la más
    avanzada: si el usuario ya calibró y contó en alguna, la guía no
    debería seguir pidiéndole que suba videos.
  */
  const guideReference =
    projects.length === 0
      ? null
      : projects.reduce((best, p) => (p.crossing_count > best.crossing_count ? p : best));

  // El título de la pestaña identifica la página, no solo el producto:
  // con varias abiertas hay que poder distinguirlas.
  useEffect(() => {
    document.title = `${title} — Aforo Vehicular`;
  }, [title]);

  return (
    <>
      {/* Primer elemento enfocable de la página: quien navega con teclado
          no tiene que recorrer la barra completa en cada pantalla. */}
      <a className="skip-link" href="#contenido">
        Saltar al contenido
      </a>
      <div className="wrap">
        <Nav
          title={title}
          subtitle={subtitle}
          projectScoped={projectScoped}
          projectId={project?.id ?? null}
          projectName={project?.name ?? null}
        />
        {!hideGuide && <Guia project={project ?? guideReference} projectCount={projects.length} />}
        <main id="contenido" tabIndex={-1}>
          {children}
        </main>
      </div>
    </>
  );
}
