/*
  Carga de Leaflet bajo demanda.

  Se carga solo cuando se abre un formulario que necesita el mapa (crear
  o editar una intersección), no en cada página: son 147 KB que la
  mayoría de las pantallas —la mesa de trabajo, el reporte, la cámara en
  vivo— no usan nunca.

  Existe además porque la alternativa falló en silencio: la página traía
  el CSS de Leaflet en un <link> pero nunca su JavaScript, y el código
  del mapa empezaba con `if (typeof L === 'undefined') return;`. El
  resultado era un rectángulo gris sin ningún error, ni en consola ni en
  pantalla. Aquí el fallo se propaga y el formulario puede decirlo.
*/

let promesa: Promise<void> | null = null;

export function cargarLeaflet(): Promise<void> {
  if (typeof window !== 'undefined' && (window as { L?: unknown }).L) return Promise.resolve();
  if (promesa) return promesa;

  promesa = new Promise<void>((resolve, reject) => {
    const script = document.createElement('script');
    script.src = '/leaflet/leaflet.js';
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => {
      // Se olvida el intento fallido: si el usuario reabre el formulario
      // con la red ya de vuelta, vale la pena volver a probar.
      promesa = null;
      reject(new Error('No se pudo cargar el mapa.'));
    };
    document.head.appendChild(script);
  });

  return promesa;
}
