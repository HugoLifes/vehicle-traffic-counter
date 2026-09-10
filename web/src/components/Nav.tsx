/*
  Barra superior: la marca, los modos de la app y el tema.

  La marca dice el PRODUCTO, no la página. Antes llevaba el título de la
  pantalla como <h1>, y dentro de una intersección eso significaba ver el
  nombre del proyecto dos veces con 60 px de separación y dos tamaños
  distintos. Lo que identifica dónde estás es la cabecera de la página;
  lo que identifica la app se queda quieto arriba.

  Los pasos de un aforo (subir → calibrar → reporte) estuvieron aquí, en
  un segundo nivel. Ya no: son las pestañas del contenedor de la
  intersección, porque solo tienen sentido dentro de una.
*/

import { NavLink, Link } from 'react-router-dom';
import { IconBrand, IconMoon, IconSun } from './Icons';
import { useTheme } from '../lib/useTheme';

const GLOBAL = [
  { to: '/', label: 'Proyectos', end: true },
  // Comparar es de varias intersecciones a la vez, así que no cabe dentro
  // de ninguna: va al nivel global.
  { to: '/comparar', label: 'Comparar', end: false },
  { to: '/en-vivo', label: 'Cámara en vivo', end: false },
  // La normativa aplica a todas las intersecciones, no a una: va aquí y
  // no dentro de un proyecto.
  { to: '/documentos', label: 'Documentos', end: false },
];

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const isDark = theme === 'dark';
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={toggle}
      /* El nombre dice lo que va a pasar al pulsar, no el estado actual. */
      aria-label={isDark ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro'}
      title={isDark ? 'Cambiar a tema claro' : 'Cambiar a tema oscuro'}
    >
      {/* Los dos iconos se quedan montados y se cruzan con opacidad,
          escala y desenfoque: alternar `display` no tendría salida. */}
      <IconSun data-state={isDark ? 'shown' : 'hidden'} />
      <IconMoon data-state={isDark ? 'hidden' : 'shown'} />
    </button>
  );
}

export function Nav() {
  return (
    <div className="topbar">
      <Link className="brand" to="/">
        <IconBrand size={26} />
        <span className="brand-name">Aforo Vehicular</span>
      </Link>
      <div className="topbar-right">
        <nav className="nav-links" aria-label="Navegación principal">
          {GLOBAL.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              /* El estado activo NO depende solo del color: también
                 cambia el peso de la tipografía. */
              className={({ isActive }) => (isActive ? 'active' : undefined)}
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
        <ThemeToggle />
      </div>
    </div>
  );
}
