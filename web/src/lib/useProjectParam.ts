/*
  La intersección seleccionada vive en la URL (`?project=<id>`), no en el
  estado de un componente.

  Así el enlace se puede compartir, recargar y guardar en favoritos, y las
  tres pantallas del flujo (subir → calibrar → reporte) hablan del mismo
  proyecto sin pasarse nada entre ellas. Antes cada página tenía su propio
  selector y su propia idea de cuál estaba activo, y la guía llegó a
  reportar el avance de un proyecto distinto al que se estaba viendo.
*/

import { useCallback, useEffect } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useProjects } from './queries';

export function useProjectParam() {
  const [params, setParams] = useSearchParams();
  const { data: projects, isLoading, isError } = useProjects();

  const raw = params.get('project');
  const parsed = raw !== null && /^\d+$/.test(raw) ? Number(raw) : null;

  // Un id que no corresponde a ningún proyecto (borrado, o tecleado a mano)
  // se trata como "ninguno" en vez de dejar la página pidiendo datos que
  // no existen.
  const valid = projects?.some((p) => p.id === parsed) ?? false;
  const projectId = valid ? parsed : null;

  const setProjectId = useCallback(
    (id: number | null) => {
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
    [setParams],
  );

  // Con una sola intersección no tiene sentido obligar a elegirla.
  useEffect(() => {
    if (projectId !== null || !projects || projects.length !== 1) return;
    setProjectId(projects[0].id);
  }, [projectId, projects, setProjectId]);

  const project = projects?.find((p) => p.id === projectId) ?? null;

  return { projectId, project, projects: projects ?? [], setProjectId, isLoading, isError };
}
