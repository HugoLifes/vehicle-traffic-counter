/*
  Formulario de intersección, el mismo para crear y para editar.

  Estaba dentro de la página de Proyectos y solo servía para crear, así
  que una intersección mal nombrada o mal ubicada no tenía arreglo desde
  la interfaz: había que borrarla y volver a empezar, perdiendo su
  histórico. Al extraerlo, editar y crear comparten exactamente los
  mismos campos y las mismas validaciones — que es lo que evita que uno
  de los dos se quede atrás cuando se agregue un campo nuevo.

  La búsqueda de direcciones va contra /api/geo (nuestro backend), no
  contra Nominatim directo: su política exige User-Agent propio, un
  máximo de una petición por segundo y cachear los resultados, y eso solo
  se puede garantizar del lado del servidor.
*/

import { useCallback, useEffect, useRef, useState } from 'react';
import { Button, Card, Notice, SelectField, TextField } from './ui';
import { IconSearch } from './Icons';
import { errorMessage, geoReverse, geoSearch } from '../lib/api';
import { cargarLeaflet } from '../lib/leaflet';
import type { Project, ProjectCreate } from '../lib/types';

const INTERVALS = [5, 10, 15, 30, 60];

/* Leaflet se carga bajo demanda desde /leaflet (autohospedado, igual que
   las fuentes), así que la librería nunca depende de la red. Los mosaicos
   sí: crear o editar una intersección se hace desde un navegador con
   conexión, no desde el Jetson en campo.

   Cuando los mosaicos fallan la librería no se entera —el mapa sigue
   "vivo", solo que en gris— así que hay que escuchar `tileerror` y
   decirlo. Y decirlo no basta: por eso está la entrada manual de
   coordenadas, que es lo que hace que el aforo se pueda registrar
   igual. */
declare const L: any;

interface Location {
  latitude: number | null;
  longitude: number | null;
  address: string | null;
}

function useLeafletMap(
  containerRef: React.RefObject<HTMLDivElement | null>,
  onPick: (lat: number, lon: number) => void,
  inicial: Location,
) {
  const mapRef = useRef<any>(null);
  const markerRef = useRef<any>(null);
  const onPickRef = useRef(onPick);
  onPickRef.current = onPick;
  const inicialRef = useRef(inicial);
  const [fallo, setFallo] = useState(false);
  const [mosaicosCaidos, setMosaicosCaidos] = useState(false);

  const place = useCallback((lat: number, lon: number, zoom?: number) => {
    const map = mapRef.current;
    if (!map) return;
    if (!markerRef.current) {
      markerRef.current = L.marker([lat, lon], { draggable: true }).addTo(map);
      markerRef.current.on('dragend', () => {
        const p = markerRef.current.getLatLng();
        onPickRef.current(p.lat, p.lng);
      });
    } else {
      markerRef.current.setLatLng([lat, lon]);
    }
    if (zoom) map.setView([lat, lon], zoom);
  }, []);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    let cancelado = false;
    let t = 0;

    cargarLeaflet()
      .then(() => {
        if (cancelado || !containerRef.current || mapRef.current) return;

        const { latitude, longitude } = inicialRef.current;
        const tieneUbicacion = latitude !== null && longitude !== null;

        const map = L.map(containerRef.current).setView(
          tieneUbicacion ? [latitude, longitude] : [23.6345, -102.5528], // México
          tieneUbicacion ? 17 : 5,
        );
        const capa = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          maxZoom: 19,
          attribution: '© OpenStreetMap',
        }).addTo(map);
        // Sin internet los mosaicos fallan uno a uno y Leaflet no avisa:
        // el mapa queda en gris y parece que la app se rompió.
        capa.on('tileerror', () => setMosaicosCaidos(true));
        map.on('click', (e: any) => onPickRef.current(e.latlng.lat, e.latlng.lng));
        mapRef.current = map;

        // Al editar, el pin arranca donde ya estaba la intersección.
        if (tieneUbicacion) place(latitude as number, longitude as number);

        // Leaflet calcula mal su tamaño si el contenedor estaba oculto al crearse.
        t = window.setTimeout(() => map.invalidateSize(), 60);
      })
      .catch(() => !cancelado && setFallo(true));

    return () => {
      cancelado = true;
      window.clearTimeout(t);
    };
  }, [containerRef, place]);

  useEffect(
    () => () => {
      mapRef.current?.remove();
      mapRef.current = null;
      markerRef.current = null;
    },
    [],
  );

  return { place, fallo, mosaicosCaidos };
}

interface Props {
  /** Si viene, el formulario edita esa intersección; si no, crea una. */
  project?: Project | null;
  titulo: string;
  etiquetaEnviar: string;
  enviando: boolean;
  error: unknown;
  onSubmit: (data: ProjectCreate) => void | Promise<void>;
  onCancel: () => void;
}

export function ProjectForm({
  project = null,
  titulo,
  etiquetaEnviar,
  enviando,
  error,
  onSubmit,
  onCancel,
}: Props) {
  const [name, setName] = useState(project?.name ?? '');
  const [description, setDescription] = useState(project?.description ?? '');
  const [interval, setInterval] = useState(project?.interval_minutes ?? 15);
  const [nameError, setNameError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [location, setLocation] = useState<Location>({
    latitude: project?.latitude ?? null,
    longitude: project?.longitude ?? null,
    address: project?.address ?? null,
  });
  const [mapStatus, setMapStatus] = useState(
    project?.address ?? 'Busca una dirección o haz clic en el mapa para poner el pin.',
  );

  const nameRef = useRef<HTMLInputElement>(null);
  const mapRef = useRef<HTMLDivElement>(null);

  const pick = useCallback(async (lat: number, lon: number) => {
    setLocation({ latitude: lat, longitude: lon, address: null });
    setMapStatus('Buscando la dirección…');
    try {
      const data = await geoReverse(lat, lon);
      setLocation({ latitude: lat, longitude: lon, address: data.display_name ?? null });
      setMapStatus(data.display_name || 'Ubicación fijada.');
    } catch {
      setMapStatus('Ubicación fijada. No se encontró una dirección para este punto.');
    }
  }, []);

  const map = useLeafletMap(
    mapRef,
    (lat, lon) => {
      map.place(lat, lon);
      void pick(lat, lon);
    },
    { latitude: project?.latitude ?? null, longitude: project?.longitude ?? null, address: null },
  );

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  /*
    Coordenada escrita a mano. No se llama a la geocodificación inversa:
    quien teclea una coordenada ya sabe dónde está, y pedirle la dirección
    a Nominatim en cada pulsación sería un abuso de un servicio gratuito
    cuya política pide una petición por segundo.
  */
  function aplicarCoordenada(campo: 'latitude' | 'longitude', bruto: string) {
    const valor = bruto.trim() === '' ? null : Number(bruto);
    if (valor !== null && Number.isNaN(valor)) return;

    setLocation((prev) => {
      const siguiente = { ...prev, [campo]: valor };
      if (siguiente.latitude !== null && siguiente.longitude !== null) {
        map.place(siguiente.latitude, siguiente.longitude, 16);
      }
      return siguiente;
    });
    setMapStatus(
      valor === null
        ? 'Escribe las dos coordenadas para fijar la ubicación.'
        : 'Ubicación fijada a mano.',
    );
  }

  async function search() {
    const q = query.trim();
    if (q.length < 3) {
      setMapStatus('Escribe al menos tres letras para buscar.');
      return;
    }
    setMapStatus('Buscando…');
    try {
      const results = await geoSearch(q);
      if (!results.length) {
        setMapStatus('No se encontró esa dirección. Prueba con otra o haz clic en el mapa.');
        return;
      }
      const first = results[0];
      if (first.latitude === null || first.longitude === null) {
        setMapStatus('El resultado no trae coordenadas. Haz clic en el mapa para fijar el punto.');
        return;
      }
      setLocation({
        latitude: first.latitude,
        longitude: first.longitude,
        address: first.display_name,
      });
      map.place(first.latitude, first.longitude, 17);
      setMapStatus(first.display_name);
    } catch (e) {
      setMapStatus(`No se pudo buscar. ${errorMessage(e)}`);
    }
  }

  function submit(e: React.FormEvent) {
    e.preventDefault();
    // Se valida al enviar, no mientras se escribe: marcar en rojo un campo
    // que todavía se está llenando es regañar antes de tiempo.
    if (!name.trim()) {
      setNameError('Escribe el nombre de la intersección.');
      nameRef.current?.focus();
      return;
    }
    void onSubmit({
      name: name.trim(),
      description: description.trim() || null,
      latitude: location.latitude,
      longitude: location.longitude,
      address: location.address,
      interval_minutes: interval,
    });
  }

  return (
    <Card className="project-form rise">
      <form onSubmit={submit} noValidate>
        <h2 className="section-title">{titulo}</h2>

        {Boolean(error) && (
          <div style={{ marginBottom: 'var(--space-4)' }}>
            <Notice title="No se pudo guardar">{errorMessage(error)}</Notice>
          </div>
        )}

        <div className="form-row">
          <TextField
            label="Nombre de la intersección"
            ref={nameRef}
            value={name}
            placeholder="Reforma × Insurgentes"
            hint="Todos los videos y carriles de este punto de medición cuelgan de aquí."
            error={nameError}
            autoComplete="off"
            onChange={(e) => {
              setName(e.target.value);
              setNameError(null);
            }}
          />
          <SelectField
            label="Intervalo de conteo"
            narrow
            value={interval}
            hint="Se puede cambiar al ver el reporte."
            onChange={(e) => setInterval(Number(e.target.value))}
          >
            {INTERVALS.map((m) => (
              <option key={m} value={m}>
                {m} minutos
              </option>
            ))}
          </SelectField>
        </div>

        <div className="form-row">
          <TextField
            label="Notas"
            value={description}
            placeholder="Aforo solicitado por el municipio, acceso norte"
            hint="Opcional."
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>

        <div className="map-block">
          <div className="map-search">
            <TextField
              label="Ubicación"
              value={query}
              placeholder="Busca la dirección o el cruce de calles"
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  void search();
                }
              }}
            />
            <Button
              onClick={() => void search()}
              style={{ alignSelf: 'flex-end', marginBottom: '2px' }}
            >
              <IconSearch size={15} />
              Buscar
            </Button>
          </div>

          <div className="map-canvas" ref={mapRef}>
            {map.fallo && (
              /* El mapa necesita internet para sus mosaicos. Sin él la
                 intersección se puede guardar igual, solo sin ubicación —
                 pero eso hay que decirlo, no dejar un rectángulo gris. */
              <p className="map-offline">
                No se pudo cargar el mapa. Puedes guardar la intersección sin ubicación y añadirla
                más tarde desde el Resumen.
              </p>
            )}
          </div>

          {/* Región educada: el resultado de la búsqueda se anuncia sin
              interrumpir lo que el usuario esté haciendo. */}
          <div className="map-hint" role="status" aria-live="polite">
            <span>{mapStatus}</span>
            <span className="coords">
              {location.latitude !== null && location.longitude !== null
                ? `${location.latitude.toFixed(5)}, ${location.longitude.toFixed(5)}`
                : ''}
            </span>
          </div>
          {map.mosaicosCaidos && (
            <div style={{ marginTop: 'var(--space-3)' }}>
              <Notice tone="warning" title="El mapa no puede cargar sus imágenes">
                Los mosaicos vienen de internet. Sin conexión el mapa se queda en gris, pero la
                intersección se puede registrar igual: escribe las coordenadas abajo.
              </Notice>
            </div>
          )}

          {/*
            Entrada manual de coordenadas. Plegada por defecto para no
            competir con el mapa, y abierta sola cuando los mosaicos
            fallan — que es justo cuando pasa a ser el único camino.
            Sirve además a quien ya trae la coordenada de un GPS y no
            necesita buscarla.
          */}
          <details className="disclosure coord-manual" open={map.mosaicosCaidos}>
            <summary>Escribir las coordenadas a mano</summary>
            <div className="coord-campos">
              <TextField
                label="Latitud"
                type="number"
                step="any"
                inputMode="decimal"
                placeholder="28.63530"
                value={location.latitude ?? ''}
                onChange={(e) => aplicarCoordenada('latitude', e.target.value)}
              />
              <TextField
                label="Longitud"
                type="number"
                step="any"
                inputMode="decimal"
                placeholder="-106.08890"
                value={location.longitude ?? ''}
                onChange={(e) => aplicarCoordenada('longitude', e.target.value)}
              />
            </div>
            <p className="field-hint">
              En grados decimales. Si el mapa está cargado, el pin sigue lo que escribas.
            </p>
          </details>

          <p className="map-attribution">
            Mapa ©{' '}
            <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
              OpenStreetMap
            </a>
          </p>
        </div>

        <div className="form-actions">
          <Button onClick={onCancel}>Cancelar</Button>
          <Button type="submit" variant="primary" disabled={enviando}>
            {enviando ? 'Guardando…' : etiquetaEnviar}
          </Button>
        </div>
      </form>
    </Card>
  );
}
