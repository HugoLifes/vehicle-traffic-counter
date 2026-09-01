/*
  Puente para navegar desde fuera de un componente.

  Los avisos de las mutaciones se arman en `queries.ts`, que no es un
  componente y por tanto no puede llamar a `useNavigate()`. Y sin un modo
  de navegar, el botón del aviso no puede existir: "Reconteo encolado" sin
  un enlace a la cola obliga a buscarla a mano, que es justo lo que los
  avisos en línea que esto reemplaza sí resolvían.

  `location.href` no sirve: recarga la aplicación entera y tira el estado
  y la caché de consultas.

  Se guarda la función que React Router entrega en el árbol. Es una sola
  aplicación con un solo router, así que un único registro basta; se
  escribe en el App raíz, antes de que ninguna mutación pueda terminar.
*/

type Navegar = (a: string) => void;

let navegador: Navegar | null = null;

export function registrarNavegador(fn: Navegar) {
  navegador = fn;
}

/** Salta a una ruta. Si aún no hay router montado, no hace nada. */
export function navegarA(a: string) {
  navegador?.(a);
}
