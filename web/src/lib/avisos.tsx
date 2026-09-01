/*
  Avisos (toasts).

  El problema que resuelven: casi todo lo que hace esta plataforma ocurre
  en segundo plano y tarda. Un video se encola, se procesa minutos
  después y termina cuando el usuario ya está en otra pantalla. Hasta
  ahora eso no se avisaba: había que volver a la cola y mirar. Y cuando
  algo fallaba —una subida a medias, un carril que no se guardó— el error
  vivía dentro de la pantalla que lo provocó, así que al cambiar de
  pestaña desaparecía sin que nadie lo hubiera leído.

  Por qué Sonner y no hecho a mano: un toast tiene partes que se ven
  fáciles y no lo son — apilar varios sin que salten, pausar el
  temporizador al pasar el cursor, deslizar para descartar, y anunciar en
  lector de pantalla sin interrumpir. Eso lo pone Sonner.

  Y por qué `toast.custom`: los estilos propios de Sonner habría que
  vencerlos con `!important` uno por uno. En modo headless conserva toda
  la mecánica y el aspecto lo pone nuestro componente, con nuestros
  tokens — que además es lo que la propia guía de Sonner recomienda para
  un sistema de diseño.

  Reglas de duración, de better-accessibility: un aviso con acción o un
  error se queda hasta que lo cierren, porque exige una decisión. Lo
  demás se va solo.
*/

import { toast } from 'sonner';
import type { ReactNode } from 'react';
import { IconAlert, IconCheck, IconClose, IconInfo } from '../components/Icons';

export type TonoAviso = 'good' | 'critical' | 'warning' | 'info';

interface Opciones {
  /** Segunda línea: el detalle, la causa o el siguiente paso. */
  detalle?: ReactNode;
  /** Un solo botón. Su presencia hace que el aviso no se cierre solo. */
  accion?: { etiqueta: string; alPulsar: () => void };
  /** Para reemplazar un aviso anterior en vez de apilar otro igual. */
  id?: string;
}

const ICONO = {
  good: IconCheck,
  critical: IconAlert,
  warning: IconAlert,
  info: IconInfo,
} as const;

function Aviso({
  tono,
  titulo,
  detalle,
  accion,
  cerrar,
}: {
  tono: TonoAviso;
  titulo: string;
  detalle?: ReactNode;
  accion?: Opciones['accion'];
  cerrar: () => void;
}) {
  const Icono = ICONO[tono];
  return (
    <div className={`aviso tono-${tono}`}>
      <span className="av-icono">
        <Icono size={16} />
      </span>
      <div className="av-texto">
        <span className="av-titulo">{titulo}</span>
        {detalle && <span className="av-detalle">{detalle}</span>}
      </div>
      {accion && (
        <button
          type="button"
          className="btn btn-secondary av-accion"
          onClick={() => {
            accion.alPulsar();
            cerrar();
          }}
        >
          {accion.etiqueta}
        </button>
      )}
      <button type="button" className="btn-icon av-cerrar" aria-label="Cerrar aviso" onClick={cerrar}>
        <IconClose size={15} />
      </button>
    </div>
  );
}

function mostrar(tono: TonoAviso, titulo: string, o: Opciones = {}) {
  // Un error o algo que pide decidir se queda hasta que lo cierren: si se
  // fuera solo, el usuario podría no haberlo leído nunca.
  const permanente = tono === 'critical' || Boolean(o.accion);

  return toast.custom(
    (id) => (
      <Aviso
        tono={tono}
        titulo={titulo}
        detalle={o.detalle}
        accion={o.accion}
        cerrar={() => toast.dismiss(id)}
      />
    ),
    {
      id: o.id,
      duration: permanente ? Infinity : tono === 'warning' ? 8000 : 5000,
    },
  );
}

export const avisar = {
  ok: (titulo: string, o?: Opciones) => mostrar('good', titulo, o),
  error: (titulo: string, o?: Opciones) => mostrar('critical', titulo, o),
  aviso: (titulo: string, o?: Opciones) => mostrar('warning', titulo, o),
  info: (titulo: string, o?: Opciones) => mostrar('info', titulo, o),
  cerrar: (id?: string) => toast.dismiss(id),
};
