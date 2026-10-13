/*
  Modo "colocar" de los mapas: el siguiente clic pone el punto (un pin, un
  acceso, la cámara) donde se hizo.

  Solo con el clic, colocar era imposible con teclado. Aquí hay además una
  mira en el centro del mapa: las flechas mueven el mapa (Leaflet ya lo
  hace con el foco en él) y "Poner aquí" coloca el punto bajo la mira.
  Escape cancela, como cualquier modo que se abre encima.
*/

import { useEffect } from 'react';
import type { MapaLeaflet } from './useMapa';

interface Props {
  mapa: MapaLeaflet | null;
  /** Qué se va a colocar, para el aviso: "el acceso 2", "la cámara"… */
  children: React.ReactNode;
  onPoner: (p: { lat: number; lon: number }) => void;
  onCancelar: () => void;
}

export function Colocar({ mapa, children, onPoner, onCancelar }: Props) {
  useEffect(() => {
    if (!mapa) return;
    const el = mapa.getContainer();
    el.classList.add('is-ubicando');
    const alClic = (e: { latlng: { lat: number; lng: number } }) => onPoner({ lat: e.latlng.lat, lon: e.latlng.lng });
    const alTeclado = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onCancelar();
    };
    mapa.once('click', alClic);
    document.addEventListener('keydown', alTeclado);
    return () => {
      el.classList.remove('is-ubicando');
      mapa.off('click', alClic);
      document.removeEventListener('keydown', alTeclado);
    };
  }, [mapa, onPoner, onCancelar]);

  const ponerAqui = () => {
    if (!mapa) return;
    const c = mapa.getCenter();
    onPoner({ lat: c.lat, lon: c.lng });
  };

  return (
    <>
      <div className="mp-mira" aria-hidden="true" />
      <div className="mp-aviso is-modo" role="status">
        <span>
          Haz clic en el mapa {children}, o mueve el mapa (flechas) hasta la mira y ponlo ahí.
        </span>
        <span className="mp-aviso-acciones">
          <button type="button" className="btn btn-primary" onClick={ponerAqui}>
            Poner aquí
          </button>
          <button type="button" className="mp-enlace" onClick={onCancelar}>
            Cancelar
          </button>
        </span>
      </div>
    </>
  );
}
