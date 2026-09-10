/*
  Contenedor de una intersección.

  Antes las herramientas (subir, calibrar, reporte) eran páginas sueltas
  que llevaban la intersección en `?project=`, y la lista de proyectos
  solo servía para saltar a una de ellas. Eso dejaba el proyecto sin un
  sitio propio: no había dónde ver su estado de conjunto, ni dónde
  corregir su nombre o su ubicación, ni dónde vivían las acciones que son
  del proyecto entero y no de una herramienta (recontar, copiar la
  calibración, borrarlo).

  Ahora el proyecto es el contenedor y las herramientas viven dentro:

      /proyecto/3            resumen y ajustes
      /proyecto/3/subir      · calibrar · reporte

  Cada herramienta conserva su propia URL, así que el botón "atrás" y los
  enlaces compartidos siguen funcionando — que es lo que se pierde cuando
  las pestañas viven solo en el estado de un componente.

  El patrón es el de divulgación progresiva: la tarjeta responde "¿cómo
  va esto?" de un vistazo, y al abrirla aparece el detalle y las
  herramientas.
*/

import { NavLink, Outlet, useNavigate, useParams } from 'react-router-dom';
import { Page } from '../components/Page';
import { EmptyState, Pill } from '../components/ui';
import { IconPin } from '../components/Icons';
import { useProjects } from '../lib/queries';
import { formatNumber } from '../lib/format';
import type { Project } from '../lib/types';

/*
  Las tres primeras van numeradas porque son el flujo de un aforo, en
  orden. Las de después no llevan número: son consultas sobre lo hecho,
  no pasos que haya que recorrer, y numerarlas sugeriría un quinto y un
  sexto paso que no existen.
*/
const HERRAMIENTAS = [
  { to: '', label: 'Resumen', end: true, paso: false },
  { to: 'subir', label: 'Subir videos', end: false, paso: true },
  { to: 'calibrar', label: 'Calibrar', end: false, paso: true },
  { to: 'reporte', label: 'Reporte', end: false, paso: true },
  { to: 'camara', label: 'Cámara', end: false, paso: false },
  { to: 'registro', label: 'Registro', end: false, paso: false },
  // Documentos de ESTA intersección: proyecto ejecutivo, requisitos del
  // cliente, oficios. La normativa general vive en el menú de arriba.
  { to: 'documentos', label: 'Documentos', end: false, paso: false },
];

/*
  Las cifras que responden "¿cómo va esto?" antes de entrar en detalle.
  Van en la cabecera, no dentro de una herramienta, porque describen el
  proyecto entero.
*/
function Resumen({ p }: { p: Project }) {
  return (
    <div className="proj-stats">
      {/* Los cruces mandan: van a --text-2xl y las otras dos a --text-lg,
          2.1× de diferencia. Antes las tres iban al mismo tamaño y la
          cabecera no decía cuál era el dato del estudio. */}
      <div className="proj-stat is-principal">
        <span className="ps-value">{formatNumber(p.crossing_count)}</span>
        <span className="ps-label">Vehículos contados</span>
      </div>
      <div className="proj-stat-menores">
        <div className="proj-stat">
          <span className="ps-value">{formatNumber(p.video_count)}</span>
          <span className="ps-label">Videos</span>
        </div>
        <div className="proj-stat">
          <span className="ps-value">{formatNumber(p.lane_count)}</span>
          <span className="ps-label">Carriles</span>
        </div>
      </div>
    </div>
  );
}

export default function Proyecto() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const { data: projects, isLoading } = useProjects();

  const id = projectId && /^\d+$/.test(projectId) ? Number(projectId) : null;
  const project = projects?.find((p) => p.id === id) ?? null;

  if (isLoading) {
    return (
      <Page title="Intersección" subtitle="Cargando…">
        <EmptyState title="Cargando la intersección…" />
      </Page>
    );
  }

  if (!project) {
    return (
      <Page title="Intersección no encontrada" subtitle="El enlace apunta a algo que ya no existe">
        <EmptyState
          title="Esta intersección ya no existe"
          body="Puede que se haya borrado, o que el enlace esté mal. La lista de intersecciones sigue disponible."
          action={
            <button className="btn btn-primary" type="button" onClick={() => navigate('/')}>
              Ver todas las intersecciones
            </button>
          }
        />
      </Page>
    );
  }

  return (
    /* `hideHeader`: la cabecera de esta pantalla lleva ubicación, etiquetas
       y cifras. Poner encima el título genérico repetiría el nombre de la
       intersección dos veces en 60 px. */
    <Page
      title={project.name}
      subtitle="Intersección — todo su aforo en un solo lugar"
      hideHeader
    >
      {/* Identidad y pestañas dentro del mismo panel: son el armazón de la
          intersección, y separarlas en dos bloques sueltos hacía que las
          pestañas parecieran pertenecer al contenido de abajo. */}
      <div className="proj-shell">
        <div className="proj-head">
          <div className="proj-identity">
            <h1 className="proj-name">{project.name}</h1>
            {project.address ? (
              <p className="proj-address">
                <IconPin size={13} />
                {project.address}
              </p>
            ) : (
              <p className="proj-address proj-address-missing">
                <IconPin size={13} />
                Sin ubicación — se puede añadir en Resumen
              </p>
            )}
            <div className="proj-tags">
              <Pill>
                Intervalo <span className="value">{project.interval_minutes} min</span>
              </Pill>
              {project.awaiting_count > 0 && (
                <Pill tone="warning">
                  {formatNumber(project.awaiting_count)} sin calibrar
                </Pill>
              )}
            </div>
            {project.description && <p className="proj-notes">{project.description}</p>}
          </div>

          <Resumen p={project} />
        </div>

        {/*
          Pestañas como enlaces reales, no como botones que cambian estado:
          así cada herramienta tiene su URL, el botón atrás funciona y se
          puede mandar a alguien directo a la que importa.
        */}
        <nav className="proj-tools" aria-label="Herramientas de la intersección">
          {HERRAMIENTAS.map((h, i) => (
            <NavLink
              key={h.label}
              to={h.to}
              end={h.end}
              className={({ isActive }) => (isActive ? 'proj-tool active' : 'proj-tool')}
            >
              {h.paso && <span className="pt-num">{i}</span>}
              {h.label}
            </NavLink>
          ))}
        </nav>
      </div>

      <Outlet />
    </Page>
  );
}
