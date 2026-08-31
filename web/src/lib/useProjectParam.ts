/*
  La intersección seleccionada vive en la URL, no en el estado de un
  componente. Así el enlace se puede compartir, recargar y guardar en
  favoritos, y las herramientas del proyecto hablan todas del mismo aforo
  sin pasarse nada entre ellas.

  Se lee de dos sitios, en este orden:

    1. El segmento de la ruta — /proyecto/3/calibrar. Es la forma
       canónica: el proyecto es el contenedor y las herramientas viven
       dentro de él.
    2. `?project=3` — la forma anterior. Se conserva porque hay enlaces
       ya repartidos (y guardados) que la usan, y romperlos no aporta
       nada.
*/

import { useCallback, useEffect } from 'react';
import { useNavigate, useParams, useSearchParams } from 'react-router-dom';
import { useProjects } from './queries';

export function useProjectParam() {
  const { projectId: routeId } = useParams();
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { data: projects, isLoading, isError } = useProjects();

  const raw = routeId ?? params.get('project');
  const parsed = raw !== null && raw !== undefined && /^\d+$/.test(raw) ? Number(raw) : null;

  // Un id que no corresponde a ningún proyecto (borrado, o tecleado a
  // mano) se trata como "ninguno" en vez de dejar la página pidiendo
  // datos que no existen.
  const valid = projects?.some((p) => p.id === parsed) ?? false;
  const projectId = valid ? parsed : null;

  const setProjectId = useCallback(
    (id: number | null) => {
      // Dentro del contenedor del proyecto, cambiar de intersección es
      // navegar a otra: la URL tiene que seguir describiendo lo que se ve.
      if (routeId !== undefined) {
        if (id !== null) navigate(`/proyecto/${id}`);
        else navigate('/');
        return;
      }
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          if (id === null) next.delete('project');
          else next.set('project', String(id));
          return next;
        },
        { replace: true },
      );
    },
    [routeId, navigate, setParams],
  );

  // Con una sola intersección no tiene sentido obligar a elegirla.
  useEffect(() => {
    if (routeId !== undefined) return;
    if (projectId !== null || !projects || projects.length !== 1) return;
    setProjectId(projects[0].id);
  }, [routeId, projectId, projects, setProjectId]);

  const project = projects?.find((p) => p.id === projectId) ?? null;

  return { projectId, project, projects: projects ?? [], setProjectId, isLoading, isError };
}
