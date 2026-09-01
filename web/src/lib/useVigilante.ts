/*
  Vigilante de trabajos en segundo plano.

  Un video se encola y se procesa minutos después. El usuario se va a otra
  pestaña —revisa el reporte, calibra otra intersección— y cuando el
  conteo termina no se entera: tiene que volver a la cola y mirar. Este
  vigilante mira por él.

  Compara el estado de cada video entre un sondeo y el siguiente, y avisa
  solo de las TRANSICIONES. Avisar del estado, en vez de del cambio,
  dispararía el mismo aviso cada tres segundos.

  Vive una sola vez, montado en la raíz, y no en la pantalla de subir: el
  sentido de esto es enterarse justo cuando NO estás mirando la cola.

  La primera lectura no avisa de nada. Al abrir la aplicación con diez
  videos ya terminados de ayer, diez avisos de golpe no informan de nada
  y entierran lo que sí importa.
*/

import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import * as api from './api';
import { avisar } from './avisos';
import { plural } from './format';
import type { JobStatus, VideoJob } from './types';

/** Ritmo del vigilante. Más lento que la cola en pantalla: aquí no se
    está mirando una barra de progreso, solo esperando un desenlace. */
const RITMO_MS = 5000;

export function useVigilante() {
  const navigate = useNavigate();
  const previos = useRef<Map<number, JobStatus> | null>(null);
  const sinRedAvisado = useRef(false);

  const { data: jobs, dataUpdatedAt, errorUpdatedAt } = useQuery({
    queryKey: ['videos', 'all'],
    queryFn: () => api.listVideos(),
    refetchInterval: RITMO_MS,
  });

  /* --- Conexión con el servidor -----------------------------------
     Si el Jetson se apaga o se cae la red, todo deja de actualizarse en
     silencio y la pantalla se queda con cifras viejas que parecen
     vigentes. Eso hay que decirlo.

     La caída se mide como "hace demasiado que no llega un dato bueno",
     comparando la marca de tiempo del último error con la del último
     dato. Los dos candidatos obvios no sirven:

      · `isError` nunca se enciende aquí. Una consulta que ya trajo datos
        alguna vez se queda en estado "éxito" aunque todos los sondeos
        siguientes fallen.
      · `failureCount` parpadea. Se reinicia a cero al empezar cada ronda
        de sondeo, así que con la red caída alternaba entre 0 y 2 y
        sacaba "se perdió la conexión" y "conexión restablecida" en bucle.

     El margen de dos sondeos y medio evita que un bache de un segundo
     saque un aviso rojo: si el siguiente sondeo responde, nunca se
     alcanza el umbral. */
  const sinRed = errorUpdatedAt > dataUpdatedAt && errorUpdatedAt - dataUpdatedAt > RITMO_MS * 2.5;

  useEffect(() => {
    if (sinRed && !sinRedAvisado.current) {
      sinRedAvisado.current = true;
      avisar.error('Se perdió la conexión con la plataforma', {
        id: 'sin-conexion',
        detalle:
          'Lo que ves en pantalla puede estar desactualizado. Se sigue reintentando solo.',
      });
    }
    if (!sinRed && sinRedAvisado.current) {
      sinRedAvisado.current = false;
      avisar.cerrar('sin-conexion');
      avisar.ok('Conexión restablecida', { id: 'con-conexion' });
    }
  }, [sinRed]);

  /* --- Transiciones de los videos ---------------------------------- */
  useEffect(() => {
    if (!jobs) return;

    const ahora = new Map<number, JobStatus>(jobs.map((j) => [j.id, j.status]));

    // Primera lectura: solo se toma la foto de partida.
    if (previos.current === null) {
      previos.current = ahora;
      return;
    }

    const terminados: VideoJob[] = [];
    const fallidos: VideoJob[] = [];

    for (const job of jobs) {
      const antes = previos.current.get(job.id);
      if (antes === undefined || antes === job.status) continue;
      if (job.status === 'done') terminados.push(job);
      if (job.status === 'error') fallidos.push(job);
    }

    previos.current = ahora;

    /* Se agrupa por proyecto y por tanda. Al reprocesar un aforo de 24
       horas terminan 144 videos: uno a uno serían 144 avisos, que es
       ruido, no información. */
    if (terminados.length === 1) {
      const j = terminados[0];
      avisar.ok('Video contado', {
        detalle: j.original_name,
        accion: {
          etiqueta: 'Ver el reporte',
          alPulsar: () => navigate(`/proyecto/${j.project_id}/reporte`),
        },
      });
    } else if (terminados.length > 1) {
      const proyecto = terminados[0].project_id;
      const mismoProyecto = terminados.every((j) => j.project_id === proyecto);
      avisar.ok(`${plural(terminados.length, 'video contado', 'videos contados')}`, {
        detalle: mismoProyecto ? undefined : 'En varias intersecciones.',
        accion: mismoProyecto
          ? {
              etiqueta: 'Ver el reporte',
              alPulsar: () => navigate(`/proyecto/${proyecto}/reporte`),
            }
          : undefined,
      });
    }

    // Los fallos van por separado y sin agrupar con los éxitos: mezclar
    // "3 contados" con "1 falló" en un solo aviso esconde el fallo.
    for (const j of fallidos) {
      avisar.error('Un video no se pudo contar', {
        detalle: `${j.original_name}${j.error ? ` — ${j.error}` : ''}`,
        accion: {
          etiqueta: 'Ver la cola',
          alPulsar: () => navigate(`/proyecto/${j.project_id}/subir`),
        },
      });
    }
  }, [jobs, navigate]);
}
