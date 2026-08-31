/*
  Traducción de las rutas anteriores a la forma nueva.

  Antes cada herramienta era una página suelta que llevaba la
  intersección en la cadena de consulta (`/calibrar?project=3`). Ahora el
  proyecto es el contenedor (`/proyecto/3/calibrar`). Había enlaces ya
  repartidos —y guardados en favoritos— con la forma vieja, y romperlos
  no habría aportado nada.

  Sin intersección en la URL no hay a dónde ir, así que se cae en la
  lista, que es donde se elige una.
*/

import { Navigate, useSearchParams } from 'react-router-dom';

export function RedirigirALaIntersección({ a }: { a: 'subir' | 'calibrar' | 'reporte' }) {
  const [params] = useSearchParams();
  const id = params.get('project');

  if (!id || !/^\d+$/.test(id)) return <Navigate to="/" replace />;

  // El resto de la consulta se conserva: la mesa de trabajo usa `job` y
  // `ver` para aterrizar en un video concreto.
  const resto = new URLSearchParams(params);
  resto.delete('project');
  const cola = resto.toString();

  return <Navigate to={`/proyecto/${id}/${a}${cola ? `?${cola}` : ''}`} replace />;
}
