/*
  Un mapa de Leaflet montado en un contenedor, con las dos vistas que pide
  un aforo: satélite (para ver la intersección, dónde está cada acceso y a
  dónde apunta la cámara) y calles (para ubicarse en la ciudad).

  Leaflet ya venía autohospedado para el formulario de la intersección
  (lib/leaflet.ts); aquí se reusa el mismo cargador. Los mosaicos sí vienen
  de internet: sin conexión el mapa se queda en gris sin que Leaflet avise,
  así que se escucha `tileerror` y la pantalla lo dice.

  Satélite: World Imagery de Esri, con las calles y los nombres de Esri
  encima (sin ellos la vista aérea de una colonia no dice qué calle es
  cuál). Calles: OpenStreetMap.
*/

import { useCallback, useEffect, useRef, useState } from 'react';
import { cargarLeaflet } from '../../lib/leaflet';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare const L: any;

export type VistaMapa = 'satelite' | 'calles';

const ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services';

/* Leaflet sin tipos instalados: lo que se usa de él pasa por aquí. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type MapaLeaflet = any;

export function useMapa(
  contenedor: React.RefObject<HTMLDivElement | null>,
  inicio: { centro: [number, number]; zoom: number },
) {
  const mapaRef = useRef<MapaLeaflet>(null);
  const capasRef = useRef<Record<VistaMapa, MapaLeaflet[]> | null>(null);
  const inicioRef = useRef(inicio);
  const [listo, setListo] = useState(false);
  const [fallo, setFallo] = useState(false);
  const [sinMosaicos, setSinMosaicos] = useState(false);
  const [vista, setVistaEstado] = useState<VistaMapa>('satelite');

  useEffect(() => {
    if (!contenedor.current || mapaRef.current) return;
    let cancelado = false;
    cargarLeaflet()
      .then(() => {
        if (cancelado || !contenedor.current || mapaRef.current) return;
        const mapa = L.map(contenedor.current, {
          zoomControl: false,
          // Más fino que el paso por omisión: con la rueda se llega al nivel
          // de una calle sin brincarse el que se quería.
          zoomSnap: 0.5,
          wheelPxPerZoomLevel: 90,
        }).setView(inicioRef.current.centro, inicioRef.current.zoom);
        L.control.zoom({ position: 'bottomright' }).addTo(mapa);
        L.control.scale({ position: 'bottomleft', imperial: false }).addTo(mapa);

        const avisar = () => setSinMosaicos(true);
        const satelite = [
          L.tileLayer(`${ESRI}/World_Imagery/MapServer/tile/{z}/{y}/{x}`, {
            maxNativeZoom: 19,
            maxZoom: 21,
            attribution: 'Imágenes © Esri, Maxar, Earthstar Geographics',
          }),
          L.tileLayer(`${ESRI}/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}`, {
            maxNativeZoom: 19,
            maxZoom: 21,
            opacity: 0.7,
          }),
          L.tileLayer(`${ESRI}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`, {
            maxNativeZoom: 19,
            maxZoom: 21,
          }),
        ];
        const calles = [
          L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxNativeZoom: 19,
            maxZoom: 21,
            attribution: '© OpenStreetMap',
          }),
        ];
        [...satelite, ...calles].forEach((c) => c.on('tileerror', avisar));
        satelite.forEach((c) => c.addTo(mapa));
        capasRef.current = { satelite, calles };
        mapaRef.current = mapa;
        setListo(true);
        // Leaflet mide mal su contenedor si se creó antes de que la página
        // terminara de acomodarse.
        window.setTimeout(() => mapa.invalidateSize(), 80);
      })
      .catch(() => !cancelado && setFallo(true));
    return () => {
      cancelado = true;
    };
  }, [contenedor]);

  useEffect(
    () => () => {
      mapaRef.current?.remove();
      mapaRef.current = null;
    },
    [],
  );

  const setVista = useCallback((v: VistaMapa) => {
    const mapa = mapaRef.current;
    const capas = capasRef.current;
    if (!mapa || !capas) return;
    (Object.keys(capas) as VistaMapa[]).forEach((k) =>
      capas[k].forEach((c) => (k === v ? c.addTo(mapa) : mapa.removeLayer(c))),
    );
    setVistaEstado(v);
  }, []);

  return { mapa: listo ? mapaRef.current : null, fallo, sinMosaicos, vista, setVista };
}
