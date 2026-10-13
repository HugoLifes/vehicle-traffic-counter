/*
  Mapa de aforos: la puerta de entrada.

  Pedido del dueño (12-oct-2026): que la plataforma no se sienta pesada y
  que se trabaje "como en Google Maps" — cada intersección es un pin donde
  se hizo el aforo, y desde el pin se llega a todo. Es como lo organizan
  las plataformas de referencia (Miovision DataLink, el portal de conteos
  de Manitoba): estudios como puntos en el mapa, filtrables, y una tarjeta
  con lo esencial al tocarlos.

  Un pin es un SITIO, no un proyecto: varias corridas del mismo cruce
  (Campos Elíseos tiene tres por un cambio de encuadre; el frontal de
  Juárez, la beta y su ejemplo) caen en el mismo punto y se taparían. Se
  juntan los que están a menos de 60 m, y la tarjeta lista cada proyecto.

  El color del pin dice el tipo de aforo, y el tipo lo dice lo calibrado
  (traffic_db.tipo_de_aforo): nadie tiene que acordarse de marcarlo.

  La lista de tarjetas de siempre sigue en /proyectos (botón "Lista").
*/

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useQueryClient } from '@tanstack/react-query';
import { Nav } from '../components/Nav';
import { Button } from '../components/ui';
import { ProjectForm } from '../components/ProjectForm';
import { IconClose, IconSearch } from '../components/Icons';
import { irSuave, useMapa, type MapaLeaflet } from '../components/mapa/useMapa';
import { Colocar } from '../components/mapa/Colocar';
import { keys, useCreateProject, useProjects } from '../lib/queries';
import * as api from '../lib/api';
import { avisar } from '../lib/avisos';
import { formatNumber, plural } from '../lib/format';
import type { Project, TipoAforo } from '../lib/types';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare const L: any;

export const TIPOS: Record<TipoAforo, { nombre: string; corto: string; ayuda: string }> = {
  lineal: { nombre: 'Lineal', corto: 'L', ayuda: 'Cruces de línea por sentido' },
  direccional: { nombre: 'Direccional', corto: 'D', ayuda: 'Movimientos entre accesos (1_2, 2_3…)' },
  mixto: { nombre: 'Mixto', corto: 'M', ayuda: 'Accesos para los giros y una línea por calle' },
  sin_calibrar: { nombre: 'Sin calibrar', corto: '·', ayuda: 'Todavía sin líneas ni accesos' },
};
const ORDEN: TipoAforo[] = ['direccional', 'mixto', 'lineal', 'sin_calibrar'];

/* Juárez: ahí está casi todo lo aforado. */
const INICIO = { centro: [31.66, -106.42] as [number, number], zoom: 11.5 };
const RADIO_SITIO_M = 60;

/* El servidor lo manda (tipo_aforo); se deduce igual aquí con lo que ya
   traía la lista, para que el mapa no dependa de esa versión. */
export function tipoDe(p: Project): TipoAforo {
  if (p.tipo_aforo) return p.tipo_aforo;
  const lineas = p.lane_count > 0;
  const accesos = (p.access_count ?? 0) > 0;
  return lineas && accesos ? 'mixto' : accesos ? 'direccional' : lineas ? 'lineal' : 'sin_calibrar';
}

/** Lo contado: movimientos en un direccional, cruces de línea en los demás. */
function cifra(p: Project): { n: number; que: string } {
  const t = tipoDe(p);
  if (t === 'direccional') return { n: p.movement_count ?? 0, que: 'movimientos' };
  if (t === 'mixto') return { n: p.movement_count ?? 0, que: 'movimientos (y sus líneas)' };
  return { n: p.crossing_count, que: 'vehículos' };
}

interface Sitio {
  clave: string;
  lat: number;
  lon: number;
  proyectos: Project[];
  tipo: TipoAforo;
}

function metros(a: [number, number], b: [number, number]): number {
  const r = 6371000;
  const dLat = ((b[0] - a[0]) * Math.PI) / 180;
  const dLon = ((b[1] - a[1]) * Math.PI) / 180 * Math.cos((a[0] * Math.PI) / 180);
  return r * Math.hypot(dLat, dLon);
}

function agrupar(proyectos: Project[]): Sitio[] {
  const sitios: Sitio[] = [];
  for (const p of proyectos) {
    if (p.latitude == null || p.longitude == null) continue;
    const s = sitios.find((x) => metros([x.lat, x.lon], [p.latitude!, p.longitude!]) < RADIO_SITIO_M);
    if (s) s.proyectos.push(p);
    else sitios.push({ clave: `s${p.id}`, lat: p.latitude, lon: p.longitude, proyectos: [p], tipo: tipoDe(p) });
  }
  for (const s of sitios) {
    const tipos = new Set(s.proyectos.map(tipoDe));
    s.tipo = tipos.size === 1 ? [...tipos][0] : tipos.has('direccional') || tipos.has('mixto') ? 'mixto' : 'lineal';
  }
  return sitios;
}

function nombreSitio(s: Sitio): string {
  const conDireccion = s.proyectos.find((p) => p.address);
  return s.proyectos.length === 1 ? s.proyectos[0].name : conDireccion?.address?.split(',')[0] ?? s.proyectos[0].name;
}

function iconoPin(s: Sitio, elegido: boolean) {
  const n = s.proyectos.length;
  return L.divIcon({
    className: 'mp-pin-caja',
    html:
      `<span class="mp-pin${elegido ? ' is-elegido' : ''}" data-tipo="${s.tipo}">` +
      `<span class="mp-pin-letra">${TIPOS[s.tipo].corto}</span>` +
      (n > 1 ? `<span class="mp-pin-n">${n}</span>` : '') +
      `</span>`,
    iconSize: [36, 44],
    iconAnchor: [18, 42],
  });
}

/* --- Tarjeta del sitio elegido ------------------------------------------ */

function TarjetaSitio({
  sitio,
  enfocar,
  onCerrar,
  onMover,
}: {
  sitio: Sitio;
  /** Se abrió con teclado: el foco tiene que llegar aquí, no quedarse en el pin. */
  enfocar: boolean;
  onCerrar: () => void;
  onMover: () => void;
}) {
  const titulo = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (enfocar) titulo.current?.focus();
  }, [enfocar, sitio.clave]);
  /* Un solo botón relleno por vista: con varios aforos en el cruce,
     "Abrir" relleno en cada uno competía entre sí. */
  const unico = sitio.proyectos.length === 1;
  return (
    <section className="mp-tarjeta" aria-label={`Intersección ${nombreSitio(sitio)}`}>
      <header className="mp-tarjeta-cab">
        <div>
          <h2 ref={titulo} tabIndex={-1}>
            {nombreSitio(sitio)}
          </h2>
          <p className="mp-tarjeta-sub">
            {sitio.proyectos.length > 1 ? plural(sitio.proyectos.length, 'aforo', 'aforos') + ' en este cruce · ' : ''}
            {sitio.lat.toFixed(5)}, {sitio.lon.toFixed(5)}
          </p>
        </div>
        <button type="button" className="mp-icono" onClick={onCerrar} aria-label="Cerrar">
          <IconClose size={16} />
        </button>
      </header>
      <ul className="mp-aforos">
        {sitio.proyectos.map((p) => {
          const c = cifra(p);
          const t = tipoDe(p);
          return (
            <li key={p.id} className="mp-aforo">
              <div className="mp-aforo-fila">
                <span className="mp-tipo" data-tipo={t} title={TIPOS[t].ayuda}>
                  {TIPOS[t].nombre}
                </span>
                <Link className="mp-aforo-nombre" to={`/proyecto/${p.id}`}>
                  {p.name}
                </Link>
              </div>
              <div className="mp-aforo-cifra">
                <strong>{c.n ? formatNumber(c.n) : '—'}</strong>
                <span>{c.n ? c.que : 'sin contar todavía'}</span>
                <span className="mp-sep">·</span>
                <span>{plural(p.video_count, 'video', 'videos')}</span>
                {p.awaiting_count > 0 && <span className="mp-pendiente">{formatNumber(p.awaiting_count)} sin contar</span>}
              </div>
              <div className="mp-acciones">
                <Link className={`btn ${unico ? 'btn-primary' : 'btn-secondary'}`} to={`/proyecto/${p.id}`}>
                  Abrir
                </Link>
                {(t === 'direccional' || t === 'mixto') && (
                  <Link className="btn btn-secondary" to={`/proyecto/${p.id}/mapa`}>
                    Movimientos
                  </Link>
                )}
                <Link className="btn btn-secondary" to={`/proyecto/${p.id}/reporte`}>
                  Reporte
                </Link>
                {c.n > 0 && (
                  <a className="btn btn-secondary" href={api.exportAforoExcelUrl(p.id)}>
                    Excel
                  </a>
                )}
              </div>
            </li>
          );
        })}
      </ul>
      <footer className="mp-tarjeta-pie">
        <button type="button" className="mp-enlace" onClick={onMover}>
          Mover el pin
        </button>
      </footer>
    </section>
  );
}

/* --- Página -------------------------------------------------------------- */

export default function Mapa() {
  const { data: proyectos, isLoading } = useProjects();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const contenedor = useRef<HTMLDivElement>(null);
  const { mapa, fallo, sinMosaicos, vista, setVista } = useMapa(contenedor, INICIO);

  const [texto, setTexto] = useState('');
  const [tipos, setTipos] = useState<Set<TipoAforo>>(new Set(ORDEN));
  const [elegido, setElegido] = useState<string | null>(null);
  const [conTeclado, setConTeclado] = useState(false);
  /* Proyecto que se está ubicando con un clic (o el sitio que se mueve). */
  const [ubicando, setUbicando] = useState<{ ids: number[]; nombre: string } | null>(null);
  const [creando, setCreando] = useState(false);
  const crear = useCreateProject();
  const dialogo = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = dialogo.current;
    if (!d) return;
    if (creando && !d.open) d.showModal();
    if (!creando && d.open) d.close();
  }, [creando]);

  useEffect(() => {
    document.title = 'Mapa de aforos — Aforo Vehicular';
  }, []);

  const lista = useMemo(() => proyectos ?? [], [proyectos]);
  const busca = texto.trim().toLowerCase();
  const visibles = useMemo(
    () =>
      lista.filter(
        (p) =>
          tipos.has(tipoDe(p)) &&
          (!busca || p.name.toLowerCase().includes(busca) || (p.address ?? '').toLowerCase().includes(busca)),
      ),
    [lista, tipos, busca],
  );
  const sitios = useMemo(() => agrupar(visibles), [visibles]);
  const sinUbicar = visibles.filter((p) => p.latitude == null || p.longitude == null);
  const conteoTipo = (t: TipoAforo) => lista.filter((p) => tipoDe(p) === t).length;
  const sitioElegido = sitios.find((s) => s.clave === elegido) ?? null;

  /* Pines: se crean cuando cambian los sitios; elegir uno solo le cambia
     el ícono, sin rehacer los demás. */
  const capaPines = useRef<MapaLeaflet>(null);
  const pines = useRef(new Map<string, MapaLeaflet>());
  useEffect(() => {
    if (!mapa) return;
    capaPines.current?.remove();
    pines.current.clear();
    const grupo = L.layerGroup().addTo(mapa);
    for (const s of sitios) {
      const pin = L.marker([s.lat, s.lon], {
        icon: iconoPin(s, false),
        keyboard: true,
        title: nombreSitio(s),
        riseOnHover: true,
      })
        .bindTooltip(nombreSitio(s), { direction: 'top', offset: [0, -40], className: 'mp-etiqueta' })
        .on('click', () => {
          setConTeclado(false);
          setElegido(s.clave);
        })
        // Leaflet solo usa Enter sobre un pin para abrir un popup, y aquí no
        // hay: sin esto el pin tomaba el foco y no respondía.
        .on('keypress', (e: { originalEvent: KeyboardEvent }) => {
          if (e.originalEvent.key === 'Enter' || e.originalEvent.key === ' ') {
            e.originalEvent.preventDefault();
            setConTeclado(true);
            setElegido(s.clave);
          }
        })
        .addTo(grupo);
      pines.current.set(s.clave, pin);
    }
    capaPines.current = grupo;
  }, [mapa, sitios]);
  useEffect(() => {
    for (const s of sitios) {
      const pin = pines.current.get(s.clave);
      if (!pin) continue;
      pin.setIcon(iconoPin(s, s.clave === elegido));
      pin.setZIndexOffset(s.clave === elegido ? 1000 : 0);
    }
  }, [sitios, elegido]);

  /* La primera vez que hay pines, el mapa se encuadra para verlos todos. */
  const encuadrado = useRef(false);
  useEffect(() => {
    if (!mapa || encuadrado.current || !sitios.length) return;
    // Se mide antes de encuadrar: si el mapa se creó mientras la página se
    // acomodaba, Leaflet cree que mide otra cosa y los pines quedaban a
    // miles de píxeles fuera de la vista. Y se deja libre el lugar del
    // panel, que tapa el lado izquierdo (o el de abajo en el teléfono).
    // "Ya encuadrado" se marca al encuadrar, no antes: si la lista se
    // refrescaba en estos 150 ms el temporizador se cancelaba y el mapa se
    // quedaba en el zoom de arranque, sin ningún pin a la vista.
    const t = window.setTimeout(() => {
      encuadrado.current = true;
      mapa.invalidateSize();
      const angosta = window.innerWidth <= 760;
      mapa.fitBounds(
        sitios.map((s) => [s.lat, s.lon]),
        {
          paddingTopLeft: angosta ? [40, 60] : [400, 70],
          paddingBottomRight: angosta ? [40, Math.round(window.innerHeight * 0.42) + 20] : [70, 70],
          maxZoom: 15,
        },
      );
    }, 150);
    return () => window.clearTimeout(t);
  }, [mapa, sitios]);

  /* Ubicar o mover: el siguiente clic (o "Poner aquí") es la nueva posición. */
  const poner = useCallback(
    async ({ lat, lon }: { lat: number; lon: number }) => {
      if (!ubicando) return;
      const { ids, nombre } = ubicando;
      setUbicando(null);
      try {
        await Promise.all(ids.map((id) => api.updateProject(id, { latitude: lat, longitude: lon })));
        await qc.invalidateQueries({ queryKey: keys.projects });
        avisar.ok(`«${nombre}» quedó en el mapa`);
      } catch (err) {
        avisar.error('No se pudo guardar la ubicación', {
          detalle: `${api.errorMessage(err)}. Revisa la conexión y vuelve a ubicarla.`,
        });
      }
    },
    [ubicando, qc],
  );
  const cancelarUbicar = useCallback(() => setUbicando(null), []);

  const irA = (p: Project) => {
    if (p.latitude == null || p.longitude == null || !mapa) return;
    const s = sitios.find((x) => x.proyectos.some((q) => q.id === p.id));
    irSuave(mapa, [p.latitude, p.longitude], Math.max(mapa.getZoom(), 16));
    if (s) setElegido(s.clave);
  };

  const alternarTipo = (t: TipoAforo) =>
    setTipos((prev) => {
      const nuevo = new Set(prev);
      if (nuevo.has(t) && nuevo.size > 1) nuevo.delete(t);
      else nuevo.add(t);
      return nuevo;
    });

  return (
    <div className="mp-pagina">
      <a className="skip-link" href="#mp-panel">
        Saltar a la lista de intersecciones
      </a>
      <header className="chrome">
        <div className="chrome-inner">
          <Nav />
        </div>
      </header>

      <main className="mp-escena">
        {/* Sin role="application": apagaba la navegación normal del lector
            de pantalla en toda la zona, y Leaflet ya da el teclado. */}
        <div ref={contenedor} className="mp-mapa" role="region" aria-label="Mapa de intersecciones aforadas" />

        {fallo && (
          <p className="mp-aviso is-error" role="alert">
            No se pudo cargar el mapa. Recarga la página para intentarlo otra vez; mientras, la lista de la izquierda
            sigue funcionando.
          </p>
        )}
        {sinMosaicos && !fallo && (
          <p className="mp-aviso">Las imágenes del mapa vienen de internet y no están llegando: revisa la conexión.</p>
        )}
        {ubicando && (
          <Colocar mapa={mapa} onPoner={poner} onCancelar={cancelarUbicar}>
            donde está <strong>{ubicando.nombre}</strong>
          </Colocar>
        )}

        {/* --- Panel de intersecciones --- */}
        <aside id="mp-panel" className="mp-panel" aria-label="Intersecciones">
          <div className="mp-panel-cab">
            <div className="mp-panel-titulo">
              <h1>Intersecciones</h1>
              <span>{isLoading ? '…' : plural(lista.length, 'aforo', 'aforos')}</span>
            </div>
            <label className="mp-busca">
              <IconSearch size={15} />
              <input
                type="search"
                value={texto}
                onChange={(e) => setTexto(e.target.value)}
                placeholder="Buscar por nombre o dirección"
                aria-label="Buscar intersección"
              />
            </label>
            <div className="mp-chips" role="group" aria-label="Tipo de aforo">
              {ORDEN.filter((t) => conteoTipo(t) > 0).map((t) => (
                <button
                  key={t}
                  type="button"
                  className="mp-chip"
                  data-tipo={t}
                  aria-pressed={tipos.has(t)}
                  title={TIPOS[t].ayuda}
                  onClick={() => alternarTipo(t)}
                >
                  <span className="mp-chip-punto" />
                  {TIPOS[t].nombre}
                  <span className="mp-chip-n">{conteoTipo(t)}</span>
                </button>
              ))}
            </div>
          </div>

          <ul className="mp-lista">
            {visibles
              .filter((p) => p.latitude != null && p.longitude != null)
              .map((p) => {
                const c = cifra(p);
                const sitio = sitios.find((s) => s.proyectos.some((q) => q.id === p.id));
                return (
                  <li key={p.id}>
                    <button
                      type="button"
                      className={`mp-item${sitio && sitio.clave === elegido ? ' is-elegido' : ''}`}
                      onClick={() => irA(p)}
                    >
                      <span className="mp-item-punto" data-tipo={tipoDe(p)} />
                      <span className="mp-item-txt">
                        <span className="mp-item-nombre">{p.name}</span>
                        <span className="mp-item-meta">
                          {TIPOS[tipoDe(p)].nombre} · {c.n ? `${formatNumber(c.n)} ${c.que}` : 'sin contar'}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
          </ul>

          {sinUbicar.length > 0 && (
            <div className="mp-sin-ubicar">
              <h2>Sin ubicar ({sinUbicar.length})</h2>
              <ul>
                {sinUbicar.map((p) => (
                  <li key={p.id} className="mp-item is-plano">
                    <span className="mp-item-punto" data-tipo={tipoDe(p)} />
                    <span className="mp-item-txt">
                      <Link className="mp-item-nombre" to={`/proyecto/${p.id}`}>
                        {p.name}
                      </Link>
                    </span>
                    <button
                      type="button"
                      className="mp-enlace"
                      aria-label={`Ubicar ${p.name}`}
                      onClick={() => setUbicando({ ids: [p.id], nombre: p.name })}
                    >
                      Ubicar
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="mp-panel-pie">
            <Button variant="primary" onClick={() => setCreando(true)}>
              Nueva intersección
            </Button>
            <Link className="mp-enlace" to="/proyectos">
              Ver como lista
            </Link>
          </div>
        </aside>

        {/* --- Vista: satélite o calles --- */}
        <div className="mp-vistas" role="group" aria-label="Tipo de mapa">
          {(['satelite', 'calles'] as const).map((v) => (
            <button key={v} type="button" aria-pressed={vista === v} onClick={() => setVista(v)}>
              {v === 'satelite' ? 'Satélite' : 'Calles'}
            </button>
          ))}
        </div>

        {sitioElegido && (
          <TarjetaSitio
            sitio={sitioElegido}
            enfocar={conTeclado}
            onCerrar={() => setElegido(null)}
            onMover={() =>
              setUbicando({ ids: sitioElegido.proyectos.map((p) => p.id), nombre: nombreSitio(sitioElegido) })
            }
          />
        )}

        <dialog ref={dialogo} className="mp-modal" aria-label="Nueva intersección" onClose={() => setCreando(false)}>
          {creando && (
            <ProjectForm
              titulo="Nueva intersección"
              etiquetaEnviar="Crear intersección"
              enviando={crear.isPending}
              error={crear.error}
              onCancel={() => setCreando(false)}
              onSubmit={async (data) => {
                const p = await crear.mutateAsync(data);
                setCreando(false);
                navigate(`/proyecto/${p.id}`);
              }}
            />
          )}
        </dialog>
      </main>
    </div>
  );
}
