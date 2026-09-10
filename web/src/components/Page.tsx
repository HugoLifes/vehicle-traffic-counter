/*
  Armazón común a todas las páginas: salto al contenido, barra de
  navegación, cabecera, guía y el punto de referencia <main>.

  Vive en un solo lugar a propósito. Cuando cada página lo repetía por su
  cuenta bastaba con olvidar un margen en una para que el contenido
  quedara pegado al borde — que es exactamente lo que llegó a pasar.

  La barra va FUERA del contenedor centrado y pegada arriba: su fondo
  cruza la pantalla de lado a lado mientras el contenido sigue dentro de
  sus márgenes. Con la barra dentro del `.wrap` el contenido pasaba por
  detrás de los costados al hacer scroll.
*/

import { useEffect, type ReactNode } from 'react';
import { Nav } from './Nav';
import { Guia } from './Guia';
import { useProjectParam } from '../lib/useProjectParam';

interface PageProps {
  title: string;
  subtitle: string;
  /** Oculta la guía en pantallas donde no aporta (la cámara en vivo). */
  hideGuide?: boolean;
  /**
   * Deja que la página ponga su propia cabecera. Lo usa el contenedor de
   * intersección, cuya cabecera lleva ubicación y cifras: repetir encima
   * el título genérico sería decir dos veces lo mismo.
   */
  hideHeader?: boolean;
  /** Acciones de la página, alineadas con el título (crear, exportar…). */
  actions?: ReactNode;
  children: ReactNode;
}

export function Page({ title, subtitle, hideGuide, hideHeader, actions, children }: PageProps) {
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

      <header className="chrome">
        <div className="chrome-inner">
          <Nav />
        </div>
      </header>

      <div className="wrap">
        {!hideHeader && (
          <div className="page-head">
            <div className="page-head-txt">
              <h1 className="page-title">{title}</h1>
              <p className="page-sub">{subtitle}</p>
            </div>
            {actions && <div className="page-head-acciones">{actions}</div>}
          </div>
        )}
        {!hideGuide && <Guia project={project ?? guideReference} projectCount={projects.length} />}
        <main id="contenido" tabIndex={-1}>
          {children}
        </main>
      </div>
    </>
  );
}
