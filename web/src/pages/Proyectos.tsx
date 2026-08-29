/*
  Proyectos de aforo: la lista de intersecciones con su histórico
  acumulado, y el formulario de creación con mapa.

  La búsqueda de direcciones va contra /api/geo (nuestro backend), no
  contra Nominatim directo: su política exige User-Agent propio, un
  máximo de una petición por segundo y cachear los resultados, y eso solo
  se puede garantizar del lado del servidor.
*/

import { useCallback, useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { Page } from '../components/Page';
import { Button, Card, EmptyState, Notice, SelectField, TextField } from '../components/ui';
import { IconPin, IconSearch } from '../components/Icons';
import { useCreateProject, useProjects } from '../lib/queries';
import { errorMessage, geoReverse, geoSearch } from '../lib/api';
import { formatNumber } from '../lib/format';
import type { Project } from '../lib/types';

const INTERVALS = [5, 10, 15, 30, 60];

/* --- Mapa --------------------------------------------------------------
   Leaflet se carga como <script> global desde /leaflet (autohospedado,
   igual que las fuentes). Los *tiles* sí necesitan internet: crear un
   proyecto se hace desde un navegador con conexión, no desde el Jetson en
   campo. Si no cargan, se puede fijar la ubicación tecleando lat/long. */

declare const L: any;

interface Location {
  latitude: number | null;
  longitude: number | null;
  address: string | null;
}

function useLeafletMap(
  containerRef: React.RefObject<HTMLDivElement | null>,
  active: boolean,
  onPick: (lat: number, lon: number) => void,
) {
  const mapRef = useRef<any>(null);
  const markerRef = useRef<any>(null);
  const onPickRef = useRef(onPick);
  onPickRef.current = onPick;

  useEffect(() => {
    if (!active || !containerRef.current || mapRef.current) return;
    if (typeof L === 'undefined') return;

    const map = L.map(containerRef.current).setView([23.6345, -102.5528], 5); // México
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19,
      attribution: '© OpenStreetMap',
    }).addTo(map);
    map.on('click', (e: any) => onPickRef.current(e.latlng.lat, e.latlng.lng));
    mapRef.current = map;

    // Leaflet calcula mal su tamaño si el contenedor estaba oculto al crearse.
    const t = setTimeout(() => map.invalidateSize(), 60);
    return () => clearTimeout(t);
  }, [active, containerRef]);

  useEffect(
    () => () => {
      mapRef.current?.remove();
      mapRef.current = null;
      markerRef.current = null;
    },
    [],
  );

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

  const clear = useCallback(() => {
    markerRef.current?.remove();
    markerRef.current = null;
  }, []);

  return { place, clear, ready: () => mapRef.current !== null };
}

/* --- Formulario de intersección nueva ---------------------------------- */

function ProjectForm({ onDone, onCancel }: { onDone: () => void; onCancel: () => void }) {
  const create = useCreateProject();

  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [interval, setInterval] = useState(15);
  const [nameError, setNameError] = useState<string | null>(null);
  const [query, setQuery] = useState('');
  const [location, setLocation] = useState<Location>({
    latitude: null,
    longitude: null,
    address: null,
  });
  const [mapStatus, setMapStatus] = useState(
    'Busca una dirección o haz clic en el mapa para poner el pin.',
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

  const map = useLeafletMap(mapRef, true, (lat, lon) => {
    map.place(lat, lon);
    void pick(lat, lon);
  });

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

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

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    // Se valida al enviar, no mientras se escribe: marcar en rojo un campo
    // que todavía se está llenando es regañar antes de tiempo.
    if (!name.trim()) {
      setNameError('Escribe el nombre de la intersección.');
      nameRef.current?.focus();
      return;
    }
    try {
      await create.mutateAsync({
        name: name.trim(),
        description: description.trim() || null,
        latitude: location.latitude,
        longitude: location.longitude,
        address: location.address,
        interval_minutes: interval,
      });
      onDone();
    } catch {
      /* El error se muestra abajo con create.error; no hace falta más. */
    }
  }

  return (
    <Card className="project-form rise">
      <form onSubmit={submit} noValidate>
        <h2 className="section-title">Nueva intersección</h2>

        {create.isError && (
          <div style={{ marginBottom: 'var(--space-4)' }}>
            <Notice title="No se pudo crear la intersección">{errorMessage(create.error)}</Notice>
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
            hint="Se puede cambiar después al ver el reporte."
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

          <div className="map-canvas" ref={mapRef} />

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
          <p className="map-attribution">
            Mapa ©{' '}
            <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">
              OpenStreetMap
            </a>
          </p>
        </div>

        <div className="form-actions">
          <Button onClick={onCancel}>Cancelar</Button>
          <Button type="submit" variant="primary" disabled={create.isPending}>
            {create.isPending ? 'Creando…' : 'Crear intersección'}
          </Button>
        </div>
      </form>
    </Card>
  );
}

/* --- Tarjeta de intersección -------------------------------------------- */

function ProjectCard({ p }: { p: Project }) {
  return (
    <Card className="project-card">
      <div className="pc-head">
        <span className="pc-name">{p.name}</span>
        {p.awaiting_count > 0 && (
          <span className="pc-badge">{formatNumber(p.awaiting_count)} sin calibrar</span>
        )}
      </div>

      {p.address && (
        <div className="pc-address">
          <IconPin size={12} />
          <span>{p.address}</span>
        </div>
      )}

      <div className="pc-stats">
        <div className="pc-stat accent">
          <div className="pc-stat-label">Cruces</div>
          <div className="pc-stat-value">{formatNumber(p.crossing_count)}</div>
        </div>
        <div className="pc-stat">
          <div className="pc-stat-label">Videos</div>
          <div className="pc-stat-value">{formatNumber(p.video_count)}</div>
        </div>
        <div className="pc-stat">
          <div className="pc-stat-label">Carriles</div>
          <div className="pc-stat-value">{formatNumber(p.lane_count)}</div>
        </div>
      </div>

      <div className="pc-actions">
        <Link to={`/subir?project=${p.id}`}>Subir videos</Link>
        <Link to={`/calibrar?project=${p.id}`}>Calibrar</Link>
        <Link to={`/reporte?project=${p.id}`}>Reporte</Link>
      </div>
    </Card>
  );
}

/* --- Página -------------------------------------------------------------- */

export default function Proyectos() {
  const { data: projects, isLoading, isError, error } = useProjects();
  const [creating, setCreating] = useState(false);

  return (
    <Page
      title="Proyectos de aforo"
      subtitle="Una intersección por proyecto — acumula su histórico de conteos"
    >
      <div className="section-head">
        <h2 className="section-title">Intersecciones</h2>
        <Button variant="primary" onClick={() => setCreating(true)} disabled={creating}>
          Nueva intersección
        </Button>
      </div>

      {creating && (
        <ProjectForm onDone={() => setCreating(false)} onCancel={() => setCreating(false)} />
      )}

      {isError && (
        <div className="notice-stack">
          <Notice title="No se pudieron cargar las intersecciones">{errorMessage(error)}</Notice>
        </div>
      )}

      <div className="project-grid stagger">
        {isLoading && <EmptyState title="Cargando intersecciones…" />}

        {!isLoading && !isError && projects?.length === 0 && !creating && (
          <EmptyState
            title="Todavía no hay intersecciones"
            body="Una intersección agrupa los videos, los carriles y el histórico de conteos de un punto de medición."
            action={
              <Button variant="primary" onClick={() => setCreating(true)}>
                Crear la primera intersección
              </Button>
            }
          />
        )}

        {projects?.map((p) => (
          <ProjectCard key={p.id} p={p} />
        ))}
      </div>
    </Page>
  );
}
