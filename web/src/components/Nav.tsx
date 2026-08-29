/*
  Navegación en dos niveles, porque la app tiene dos modos que no son del
  mismo rango:

    Global →  Proyectos  |  Cámara en vivo
    Local  →  (dentro de un proyecto)  1 Subir · 2 Calibrar · 3 Reporte

  El nivel local solo aparece en las páginas de un proyecto, y lleva el
  nombre de la intersección: estando en "Calibrar" hay que poder saber qué
  intersección se está calibrando sin volver atrás.
*/

import { NavLink, Link } from 'react-router-dom';
import { IconBrand, IconMoon, IconPin, IconSun } from './Icons';
import { useTheme } from '../lib/useTheme';

const GLOBAL = [
  { to: '/', label: 'Proyectos', end: true },
  { to: '/en-vivo', label: 'Cámara en vivo', end: false },
];

const STEPS = [
  { to: '/subir', label: 'Subir videos' },
  { to: '/calibrar', label: 'Calibrar' },
  { to: '/reporte', label: 'Reporte' },
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
  /** Muestra la barra de pasos del proyecto. */
  projectScoped?: boolean;
  projectId?: number | null;
  projectName?: string | null;
}

export function Nav({ title, subtitle, projectScoped, projectId, projectName }: NavProps) {
  const query = projectId !== null && projectId !== undefined ? `?project=${projectId}` : '';

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
                className={({ isActive }) =>
                  isActive || (projectScoped && item.end) ? 'active' : undefined
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>
          <ThemeToggle />
        </div>
      </div>

      {projectScoped && (
        <div className="nav-local">
          <div className="nav-project">
            <IconPin size={13} />
            <span className="np-name">{projectName ?? 'Sin intersección seleccionada'}</span>
          </div>
          <nav className="nav-steps" aria-label="Pasos del proyecto">
            {STEPS.map((step, i) => (
              <NavLink
                key={step.to}
                to={`${step.to}${query}`}
                className={({ isActive }) => (isActive ? 'nav-step active' : 'nav-step')}
              >
                <span className="step-num">{i + 1}</span>
                {step.label}
              </NavLink>
            ))}
          </nav>
        </div>
      )}
    </div>
  );
}
