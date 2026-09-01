/*
  Barra superior: la marca, los dos modos de la app y el tema.

  Los pasos de un aforo (subir → calibrar → reporte) estuvieron aquí, en
  un segundo nivel. Ya no: son las pestañas del contenedor de la
  intersección, porque solo tienen sentido dentro de una — y tenerlos
  arriba obligaba a arrastrar la intersección elegida hasta la barra de
  navegación para que el usuario supiera de cuál estaba hablando.
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

interface NavProps {
  title: string;
  subtitle: string;
}

/*
  Solo el nivel global: Proyectos y Cámara en vivo, los dos modos de la
  app. Los pasos de un aforo (subir → calibrar → reporte) ya no viven
  aquí — son las pestañas del contenedor de la intersección, que es donde
  tienen contexto.
*/
export function Nav({ title, subtitle }: NavProps) {
  return (
    <div className="nav-host">
      <div className="topbar">
        <Link className="brand" to="/">
          <IconBrand size={30} />
          <div>
            <h1>{title}</h1>
            <div className="tagline">{subtitle}</div>
          </div>
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

    </div>
  );
}
