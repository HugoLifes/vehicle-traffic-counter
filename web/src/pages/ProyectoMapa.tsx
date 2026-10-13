/*
  Mapa de UNA intersección: el aforo puesto sobre la calle real.

  Pedido del dueño (12-oct-2026): "en el direccional hay que explotar más
  el mapa". En los direccionales la empresa trabaja por movimiento
  numerado (1_2, 2_3…) sobre un croquis; aquí ese croquis es la foto
  satelital, y los movimientos se dibujan como flechas encima, como las
  plataformas de referencia (diagrama de intersección de StreetLight, el
  explorador de giros de Replica): una flecha por movimiento, el grosor
  según cuántos vehículos lo hicieron y el color según el acceso de donde
  salen, para un periodo que se elige (el estudio, un día, su hora de
  máxima demanda o cualquier hora).

  Lo que se dibuja a mano es poco y se guarda solo:
    · cada acceso, por su NÚMERO de la empresa: un pin que se arrastra a
      su calle (dos zonas con el mismo número son un solo brazo);
    · la cámara (opcional), con su cono de visión: se arrastra el pin y la
      punta del cono para girarla.
  Las cifras salen de movimientos_por_acceso, el mismo camino del Excel.
*/

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useProjectParam } from '../lib/useProjectParam';
import { useMapa, type MapaLeaflet } from '../components/mapa/useMapa';
import { Colocar } from '../components/mapa/Colocar';
import { keys, useZones } from '../lib/queries';
import * as api from '../lib/api';
import { avisar } from '../lib/avisos';
import { formatNumber, plural } from '../lib/format';
import type { CuartoMovimientos, MapaProyecto, PuntoMapa } from '../lib/types';
import { TIPOS, tipoDe } from './Mapa';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
declare const L: any;

/* Un color por acceso de ORIGEN. Tonos separados entre sí y vivos para que
   se distingan sobre la foto satelital; la flecha lleva además su número y
   su cifra escritos, así que el color nunca es lo único que la identifica. */
const COLORES = ['#2f6fec', '#f76707', '#2f9e44', '#d6336c', '#f2b705', '#0c8599', '#7048e8', '#e03131'];
const colorDe = (claves: string[], clave: string) => COLORES[Math.max(0, claves.indexOf(clave)) % COLORES.length];

const ICONO_CAMARA =
  '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
  '<path d="M4 8h3l2-3h6l2 3h3v11H4z"/><circle cx="12" cy="13" r="3.5"/></svg>';

type Objetivo = { tipo: 'acceso'; clave: string } | { tipo: 'camara' } | { tipo: 'sitio' };

/* --- Periodos ------------------------------------------------------------ */

interface Periodo {
  id: string;
  etiqueta: string;
  grupo: string;
  cuartos: string[];
}

const DIAS = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb'];
const diaDe = (fecha: string) => {
  const [a, m, d] = fecha.split('-').map(Number);
  return `${DIAS[new Date(a, m - 1, d).getDay()]} ${String(d).padStart(2, '0')}`;
};
const hhmm = (min: number) => `${String(Math.floor(min / 60) % 24).padStart(2, '0')}:${String(min % 60).padStart(2, '0')}`;
const minutoDe = (intervalo: string) => Number(intervalo.slice(11, 13)) * 60 + Number(intervalo.slice(14, 16));

/** La hora de máxima demanda de cada día: los cuartos seguidos con más
 *  entradas, todos con video completo (mismo criterio que el Excel). */
function periodos(cuartos: CuartoMovimientos[], paso: number): Periodo[] {
  const salida: Periodo[] = [{ id: 'todo', etiqueta: 'Todo el estudio', grupo: 'Estudio', cuartos: cuartos.map((q) => q.intervalo) }];
  const porDia = new Map<string, CuartoMovimientos[]>();
  for (const q of cuartos) {
    const f = q.intervalo.slice(0, 10);
    porDia.set(f, [...(porDia.get(f) ?? []), q]);
  }
  const n = Math.max(1, Math.round(60 / paso));
  for (const [fecha, qs] of porDia) {
    const dia = diaDe(fecha);
    const completo = (q: CuartoMovimientos) => q.cobertura === null || q.cobertura >= 0.995;
    let mejor: { i: number; v: number } | null = null;
    for (let i = 0; i + n <= qs.length; i++) {
      const v = qs.slice(i, i + n);
      if (!v.every(completo)) continue;
      if (minutoDe(v[n - 1].intervalo) - minutoDe(v[0].intervalo) !== paso * (n - 1)) continue;
      const tot = v.reduce((s, q) => s + q.entradas, 0);
      if (!mejor || tot > mejor.v) mejor = { i, v: tot };
    }
    if (mejor) {
      const v = qs.slice(mejor.i, mejor.i + n);
      const a = minutoDe(v[0].intervalo);
      salida.push({
        id: `hmd:${fecha}`,
        etiqueta: `${dia} · hora de máxima demanda ${hhmm(a)}–${hhmm(a + 60)}`,
        grupo: 'Hora de máxima demanda',
        cuartos: v.map((q) => q.intervalo),
      });
    }
    salida.push({ id: `dia:${fecha}`, etiqueta: `${dia} · día completo`, grupo: 'Por día', cuartos: qs.map((q) => q.intervalo) });
    const horas = new Map<number, string[]>();
    for (const q of qs) {
      const h = Math.floor(minutoDe(q.intervalo) / 60);
      horas.set(h, [...(horas.get(h) ?? []), q.intervalo]);
    }
    for (const [h, ids] of horas)
      salida.push({ id: `hora:${fecha}:${h}`, etiqueta: `${dia} · ${hhmm(h * 60)}–${hhmm(h * 60 + 60)}`, grupo: `Por hora · ${dia}`, cuartos: ids });
  }
  return salida;
}

/* --- Geometría de las flechas --------------------------------------------
   En metros locales alrededor del cruce: con distancias de decenas de
   metros la tierra es plana. */

function aMetros(o: PuntoMapa, p: PuntoMapa): [number, number] {
  const k = (Math.PI / 180) * 6371000;
  return [(p.lon - o.lon) * k * Math.cos((o.lat * Math.PI) / 180), (p.lat - o.lat) * k];
}
function aGrados(o: PuntoMapa, m: [number, number]): [number, number] {
  const k = (Math.PI / 180) * 6371000;
  return [o.lat + m[1] / k, o.lon + m[0] / (k * Math.cos((o.lat * Math.PI) / 180))];
}

/** Curva de un acceso a otro que pasa por el centro del cruce, corrida a
 *  la derecha del sentido de marcha (se circula por la derecha) para que
 *  la ida y la vuelta entre los mismos accesos no se encimen. */
function curva(o: PuntoMapa, centro: PuntoMapa, a: PuntoMapa, b: PuntoMapa, corrimiento: number) {
  const A = aMetros(o, a);
  const B = aMetros(o, b);
  const C = aMetros(o, centro);
  const dx = B[0] - A[0];
  const dy = B[1] - A[1];
  const largo = Math.hypot(dx, dy) || 1;
  const der: [number, number] = [dy / largo, -dx / largo];
  const mover = (p: [number, number]): [number, number] => [p[0] + der[0] * corrimiento, p[1] + der[1] * corrimiento];
  const [A2, B2, C2] = [mover(A), mover(B), mover(C)];
  const puntos: [number, number][] = [];
  // Recorta un poco las puntas para que la flecha no tape el pin del acceso.
  for (let i = 0; i <= 28; i++) {
    const t = 0.1 + (0.8 * i) / 28;
    const u = 1 - t;
    puntos.push([u * u * A2[0] + 2 * u * t * C2[0] + t * t * B2[0], u * u * A2[1] + 2 * u * t * C2[1] + t * t * B2[1]]);
  }
  return puntos.map((p) => aGrados(o, p));
}

function conoCamara(c: NonNullable<MapaProyecto['camara']>, radio: number): [number, number][] {
  const pts: [number, number][] = [[c.lat, c.lon]];
  const a0 = c.rumbo - c.apertura / 2;
  for (let i = 0; i <= 16; i++) {
    const ang = ((a0 + (c.apertura * i) / 16) * Math.PI) / 180;
    pts.push(aGrados(c, [Math.sin(ang) * radio, Math.cos(ang) * radio]));
  }
  return pts;
}

function rumboEntre(a: PuntoMapa, b: PuntoMapa): number {
  const [x, y] = aMetros(a, b);
  return ((Math.atan2(x, y) * 180) / Math.PI + 360) % 360;
}

/* --- Página -------------------------------------------------------------- */

export default function ProyectoMapa() {
  const { project } = useProjectParam();
  const qc = useQueryClient();
  const contenedor = useRef<HTMLDivElement>(null);
  const tieneSitio = project?.latitude != null && project?.longitude != null;
  const { mapa, fallo, sinMosaicos, vista, setVista } = useMapa(contenedor, {
    centro: tieneSitio ? [project!.latitude!, project!.longitude!] : [31.66, -106.42],
    zoom: tieneSitio ? 19 : 12,
  });
  const tipo = project ? tipoDe(project) : 'sin_calibrar';
  const conMovimientos = tipo === 'direccional' || tipo === 'mixto';

  const { data: zonas } = useZones(project?.id ?? null);
  const { data: mov, isFetching: calculando, error: errorMov, refetch: reintentarMov } = useQuery({
    queryKey: ['movimientos-mapa', project?.id],
    queryFn: () => api.getMovimientosMapa(project!.id),
    enabled: !!project && conMovimientos,
    staleTime: 60_000,
  });

  /* Accesos: de las zonas dibujadas, agrupadas por número; si ya llegaron
     los movimientos, de ahí (mismo agrupamiento que el servidor). */
  const accesos = useMemo(() => {
    if (mov) return mov.accesos;
    const grupos = new Map<string, string[]>();
    for (const z of zonas ?? []) {
      if (z.kind !== 'acceso') continue;
      const m = /^\s*(\d+)/.exec(z.name);
      const k = m ? String(Number(m[1])) : z.name;
      grupos.set(k, [...(grupos.get(k) ?? []), z.name]);
    }
    return [...grupos].map(([clave, nombres]) => ({ clave, nombres })).sort((a, b) => a.clave.localeCompare(b.clave, 'es', { numeric: true }));
  }, [mov, zonas]);
  const claves = accesos.map((a) => a.clave);

  /* Lo dibujado: copia local que se guarda sola tras cada cambio. */
  const [dibujo, setDibujo] = useState<MapaProyecto>({});
  const cargado = useRef<number | null>(null);
  useEffect(() => {
    if (project && cargado.current !== project.id) {
      cargado.current = project.id;
      setDibujo(project.mapa ?? {});
    }
  }, [project]);
  const [guardado, setGuardado] = useState<'listo' | 'guardando' | 'error'>('listo');
  const pendiente = useRef<number | undefined>(undefined);
  const guardar = (nuevo: MapaProyecto) => {
    setDibujo(nuevo);
    if (!project) return;
    window.clearTimeout(pendiente.current);
    setGuardado('guardando');
    pendiente.current = window.setTimeout(async () => {
      try {
        await api.updateProject(project.id, { mapa: nuevo });
        setGuardado('listo');
        qc.invalidateQueries({ queryKey: keys.projects });
      } catch (e) {
        setGuardado('error');
        avisar.error('No se pudo guardar el mapa', {
          detalle: `${api.errorMessage(e)}. Revisa la conexión y mueve el punto otra vez para volver a guardarlo.`,
        });
      }
    }, 500);
  };

  /* --- Periodo y flujos --- */
  const opciones = useMemo(() => (mov ? periodos(mov.cuartos, mov.intervalo_minutos) : []), [mov]);
  const [periodo, setPeriodo] = useState<string>('');
  useEffect(() => {
    if (opciones.length && !opciones.some((o) => o.id === periodo))
      setPeriodo((opciones.find((o) => o.id.startsWith('hmd:')) ?? opciones[0]).id);
  }, [opciones, periodo]);
  const elegido = opciones.find((o) => o.id === periodo) ?? null;
  const flujos = useMemo(() => {
    const suma = new Map<string, number>();
    if (!mov || !elegido) return [];
    const ids = new Set(elegido.cuartos);
    for (const q of mov.cuartos) {
      if (!ids.has(q.intervalo)) continue;
      for (const [k, n] of Object.entries(q.movs)) suma.set(k, (suma.get(k) ?? 0) + n);
    }
    return [...suma]
      .map(([k, n]) => {
        const [o, d] = k.split('_');
        return { k, o, d, n };
      })
      .filter((f) => f.n > 0)
      .sort((a, b) => b.n - a.n);
  }, [mov, elegido]);
  const totalFlujos = flujos.reduce((s, f) => s + f.n, 0);
  const [resaltado, setResaltado] = useState<string | null>(null);

  /* --- Colocar: un clic, o la mira y "Poner aquí" con teclado --- */
  const [objetivo, setObjetivo] = useState<Objetivo | null>(null);
  const dibujoRef = useRef(dibujo);
  dibujoRef.current = dibujo;
  const guardarRef = useRef(guardar);
  guardarRef.current = guardar;
  const poner = useCallback(
    async (p: PuntoMapa) => {
      if (!objetivo) return;
      setObjetivo(null);
      const d = dibujoRef.current;
      if (objetivo.tipo === 'acceso') guardarRef.current({ ...d, accesos: { ...(d.accesos ?? {}), [objetivo.clave]: p } });
      else if (objetivo.tipo === 'camara')
        guardarRef.current({ ...d, camara: { ...p, rumbo: d.camara?.rumbo ?? 0, apertura: d.camara?.apertura ?? 70 } });
      else if (project) {
        try {
          await api.updateProject(project.id, { latitude: p.lat, longitude: p.lon });
          await qc.invalidateQueries({ queryKey: keys.projects });
          avisar.ok('La intersección quedó ubicada');
        } catch (err) {
          avisar.error('No se pudo guardar la ubicación', {
            detalle: `${api.errorMessage(err)}. Revisa la conexión y vuelve a ubicarla.`,
          });
        }
      }
    },
    [objetivo, project, qc],
  );
  const cancelar = useCallback(() => setObjetivo(null), []);

  /* Al ubicarse la intersección por primera vez, el mapa va hacia ella. */
  useEffect(() => {
    if (mapa && tieneSitio) mapa.setView([project!.latitude!, project!.longitude!], Math.max(mapa.getZoom(), 18));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapa, tieneSitio]);

  /* --- Capas ---
     Tres efectos y no uno: antes todo se rehacía al pasar el cursor por una
     flecha o al mover el control de la cámara. Las flechas cambian con los
     accesos o el periodo; resaltar solo les cambia el estilo; la cámara y
     los pines de los accesos se rehacen solos. */
  const capaFlechas = useRef<MapaLeaflet>(null);
  const capaPuntos = useRef<MapaLeaflet>(null);
  const flechas = useRef(new Map<string, { linea: MapaLeaflet; punta: MapaLeaflet; cifra: MapaLeaflet | null }>());
  const claveAccesos = claves.join('|');
  useEffect(() => {
    if (!mapa) return;
    capaFlechas.current?.remove();
    flechas.current.clear();
    const g = L.layerGroup().addTo(mapa);
    capaFlechas.current = g;
    const puestos = Object.entries(dibujo.accesos ?? {}).filter(([k]) => claves.includes(k));

    // Flechas: debajo de los pines.
    if (puestos.length >= 2 && flujos.length) {
      const centro: PuntoMapa = {
        lat: puestos.reduce((s, [, p]) => s + p.lat, 0) / puestos.length,
        lon: puestos.reduce((s, [, p]) => s + p.lon, 0) / puestos.length,
      };
      const maximo = Math.max(...flujos.map((f) => f.n));
      for (const f of [...flujos].reverse()) {
        const a = dibujo.accesos?.[f.o];
        const b = dibujo.accesos?.[f.d];
        if (!a || !b || f.o === f.d) continue;
        const ancho = 3 + 16 * Math.sqrt(f.n / maximo);
        const pts = curva(centro, centro, a, b, 2.5 + ancho * 0.15);
        const color = colorDe(claves, f.o);
        const linea = L.polyline(pts, {
          color,
          weight: ancho,
          opacity: 0.88,
          lineCap: 'round',
        })
          .bindTooltip(`${f.o} → ${f.d}: ${formatNumber(f.n)} vehículos`, { sticky: true, className: 'mp-etiqueta' })
          .on('mouseover', () => setResaltado(f.k))
          .on('mouseout', () => setResaltado(null))
          .addTo(g);
        // Punta: un triángulo en píxeles, girado como el último tramo.
        const p1 = mapa.latLngToLayerPoint(pts[pts.length - 2]);
        const p2 = mapa.latLngToLayerPoint(pts[pts.length - 1]);
        const ang = (Math.atan2(p2.y - p1.y, p2.x - p1.x) * 180) / Math.PI;
        const tam = 8 + ancho * 0.9;
        const punta = L.marker(pts[pts.length - 1], {
          interactive: false,
          icon: L.divIcon({
            className: 'pm-punta-caja',
            html: `<span class="pm-punta" style="--c:${color};--t:${tam}px;rotate:${ang}deg"></span>`,
            iconSize: [0, 0],
          }),
        }).addTo(g);
        const cifra =
          f.n / maximo > 0.04
            ? L.marker(pts[Math.floor(pts.length * 0.62)], {
                interactive: false,
                icon: L.divIcon({
                  className: 'pm-cifra-caja',
                  html: `<span class="pm-cifra" style="--c:${color}">${f.o}→${f.d} · ${formatNumber(f.n)}</span>`,
                  iconSize: [0, 0],
                }),
              }).addTo(g)
            : null;
        flechas.current.set(f.k, { linea, punta, cifra });
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapa, dibujo.accesos, flujos, claveAccesos]);

  useEffect(() => {
    for (const [k, f] of flechas.current) {
      const apagada = resaltado !== null && resaltado !== k;
      f.linea.setStyle({ opacity: apagada ? 0.18 : 0.88 });
      f.punta.setOpacity(apagada ? 0.18 : 1);
      f.cifra?.setOpacity(apagada ? 0 : 1);
    }
  }, [resaltado, flujos, dibujo.accesos]);

  useEffect(() => {
    if (!mapa) return;
    capaPuntos.current?.remove();
    const g = L.layerGroup().addTo(mapa);
    capaPuntos.current = g;
    const puestos = Object.entries(dibujo.accesos ?? {}).filter(([k]) => claves.includes(k));

    // Cámara y su cono.
    const cam = dibujo.camara;
    if (cam) {
      const radio = 45;
      L.polygon(conoCamara(cam, radio), {
        color: '#ffffff',
        weight: 1.5,
        fillColor: '#ffd43b',
        fillOpacity: 0.22,
        interactive: false,
      }).addTo(g);
      const pin = L.marker([cam.lat, cam.lon], {
        draggable: true,
        icon: L.divIcon({ className: 'pm-camara-caja', html: `<span class="pm-camara" aria-hidden="true">${ICONO_CAMARA}</span>`, iconSize: [30, 30], iconAnchor: [15, 15] }),
        title: 'Cámara: arrástrala a donde está',
      }).addTo(g);
      pin.on('dragend', () => {
        const ll = pin.getLatLng();
        guardar({ ...dibujoRef.current, camara: { ...dibujoRef.current.camara!, lat: ll.lat, lon: ll.lng } });
      });
      const puntaM = aGrados(cam, [Math.sin((cam.rumbo * Math.PI) / 180) * radio, Math.cos((cam.rumbo * Math.PI) / 180) * radio]);
      const giro = L.marker(puntaM, {
        draggable: true,
        // 28 px de agarre alrededor de un punto de 18: el mínimo de 24 px.
        icon: L.divIcon({ className: 'pm-giro-caja', html: '<span class="pm-giro" title="Arrastra para girar la cámara"></span>', iconSize: [28, 28], iconAnchor: [14, 14] }),
      }).addTo(g);
      giro.on('dragend', () => {
        const ll = giro.getLatLng();
        const c = dibujoRef.current.camara!;
        guardar({ ...dibujoRef.current, camara: { ...c, rumbo: Math.round(rumboEntre(c, { lat: ll.lat, lon: ll.lng })) } });
      });
    }

    // Accesos: pines numerados que se arrastran.
    for (const [k, p] of puestos) {
      const color = colorDe(claves, k);
      const m = L.marker([p.lat, p.lon], {
        draggable: true,
        icon: L.divIcon({ className: 'pm-acceso-caja', html: `<span class="pm-acceso" style="--c:${color}">${k.length <= 3 ? k : k.slice(0, 2)}</span>`, iconSize: [34, 34], iconAnchor: [17, 17] }),
        title: `Acceso ${k}: arrástralo a su calle`,
        zIndexOffset: 500,
      }).addTo(g);
      m.on('dragend', () => {
        const ll = m.getLatLng();
        guardar({ ...dibujoRef.current, accesos: { ...(dibujoRef.current.accesos ?? {}), [k]: { lat: ll.lat, lon: ll.lng } } });
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapa, dibujo.camara, dibujo.accesos, claveAccesos]);

  if (!project) return null;
  const faltan = accesos.filter((a) => !dibujo.accesos?.[a.clave]);

  return (
    <div className="pm-estudio">
      <div ref={contenedor} className="mp-mapa" role="region" aria-label={`Mapa de ${project.name}`} />
      {fallo && (
        <p className="mp-aviso is-error" role="alert">
          No se pudo cargar el mapa. Recarga la página para intentarlo otra vez.
        </p>
      )}
      {sinMosaicos && !fallo && <p className="mp-aviso">Las imágenes del mapa vienen de internet y no están llegando: revisa la conexión.</p>}
      {objetivo && (
        <Colocar mapa={mapa} onPoner={poner} onCancelar={cancelar}>
          {objetivo.tipo === 'acceso' ? (
            <>
              sobre la calle del <strong>acceso {objetivo.clave}</strong>
            </>
          ) : objetivo.tipo === 'camara' ? (
            <>
              donde está la <strong>cámara</strong>
            </>
          ) : (
            <>
              donde está la <strong>intersección</strong>
            </>
          )}
        </Colocar>
      )}

      <div className="mp-vistas" role="group" aria-label="Tipo de mapa">
        {(['satelite', 'calles'] as const).map((v) => (
          <button key={v} type="button" aria-pressed={vista === v} onClick={() => setVista(v)}>
            {v === 'satelite' ? 'Satélite' : 'Calles'}
          </button>
        ))}
      </div>

      <aside className="mp-panel pm-panel" aria-label="Mapa de la intersección">
        <div className="mp-panel-cab">
          <div className="mp-panel-titulo">
            <h2>
              <span className="mp-tipo" data-tipo={tipo}>{TIPOS[tipo].nombre}</span>
            </h2>
            <span role="status">{guardado === 'guardando' ? 'Guardando…' : guardado === 'error' ? 'Sin guardar' : 'Guardado'}</span>
          </div>
          {!tieneSitio && (
            <div className="pm-bloque is-aviso">
              Esta intersección no tiene ubicación.{' '}
              <button type="button" className="mp-enlace" onClick={() => setObjetivo({ tipo: 'sitio' })}>
                Ubicarla en el mapa
              </button>
            </div>
          )}
        </div>

        <div className="pm-cuerpo">
          {conMovimientos && (
            <section className="pm-bloque">
              <h2>Accesos</h2>
              {accesos.length === 0 && <p className="mp-item-meta">Todavía no hay accesos dibujados en Calibrar.</p>}
              <ul className="pm-accesos">
                {accesos.map((a) => (
                  <li key={a.clave}>
                    <span className="pm-acceso is-chico" style={{ ['--c' as string]: colorDe(claves, a.clave) }}>
                      {a.clave.length <= 3 ? a.clave : '·'}
                    </span>
                    <span className="mp-item-txt">
                      <span className="mp-item-nombre" title={a.nombres.join(' · ')}>
                        {a.nombres.map((n) => n.replace(/^\s*\d+\s*[·\-–—:.]?\s*/, '')).join(' · ') || a.clave}
                      </span>
                    </span>
                    <button
                      type="button"
                      className="mp-enlace"
                      aria-label={`${dibujo.accesos?.[a.clave] ? 'Mover' : 'Poner'} el acceso ${a.clave}`}
                      onClick={() => setObjetivo({ tipo: 'acceso', clave: a.clave })}
                    >
                      {dibujo.accesos?.[a.clave] ? 'Mover' : 'Poner'}
                    </button>
                  </li>
                ))}
              </ul>
              {faltan.length > 0 && accesos.length > 0 && (
                <p className="mp-item-meta">
                  Pon cada acceso sobre su calle: las flechas van de uno a otro. {plural(faltan.length, 'falta', 'faltan')} por poner.
                </p>
              )}
            </section>
          )}

          {conMovimientos && (
            <section className="pm-bloque">
              <h2>Movimientos</h2>
              {calculando && !mov && <p className="mp-item-meta">Calculando los movimientos… la primera vez en un aforo grande tarda unos minutos.</p>}
              {errorMov && (
                <p className="mp-item-meta">
                  No se pudieron leer los movimientos ({api.errorMessage(errorMov)}).{' '}
                  <button type="button" className="mp-enlace" onClick={() => void reintentarMov()}>
                    Reintentar
                  </button>
                </p>
              )}
              {opciones.length > 0 && (
                <label className="pm-periodo">
                  <span className="sr-only">Periodo</span>
                  <select value={periodo} onChange={(e) => setPeriodo(e.target.value)}>
                    {[...new Set(opciones.map((o) => o.grupo))].map((g) => (
                      <optgroup key={g} label={g}>
                        {opciones.filter((o) => o.grupo === g).map((o) => (
                          <option key={o.id} value={o.id}>
                            {o.etiqueta}
                          </option>
                        ))}
                      </optgroup>
                    ))}
                  </select>
                </label>
              )}
              {elegido && (
                <p className="pm-total">
                  <strong>{formatNumber(totalFlujos)}</strong> vehículos con movimiento decidido
                </p>
              )}
              <ul className="pm-flujos">
                {flujos.map((f) => (
                  <li
                    key={f.k}
                    className={resaltado === f.k ? 'is-resaltado' : undefined}
                    onMouseEnter={() => setResaltado(f.k)}
                    onMouseLeave={() => setResaltado(null)}
                  >
                    <span className="pm-flujo-color" style={{ background: colorDe(claves, f.o) }} />
                    <span className="pm-flujo-mov">{f.o}_{f.d}</span>
                    <span className="pm-flujo-barra">
                      <span style={{ width: `${(100 * f.n) / (flujos[0]?.n || 1)}%`, background: colorDe(claves, f.o) }} />
                    </span>
                    <span className="pm-flujo-n">{formatNumber(f.n)}</span>
                    <span className="pm-flujo-pct">{totalFlujos ? Math.round((100 * f.n) / totalFlujos) : 0}%</span>
                  </li>
                ))}
              </ul>
              {mov && mov.sin_decidir > 0 && (
                <p className="mp-item-meta">
                  Además, {formatNumber(mov.sin_decidir)} vehículos en todo el estudio cuyo movimiento no se pudo decidir.
                  {tipo === 'mixto' && ' En este cruce el tránsito de paso lo miden las líneas de cada calle (Reporte).'}
                </p>
              )}
            </section>
          )}

          <section className="pm-bloque">
            <h2>Cámara</h2>
            {dibujo.camara ? (
              <>
                <label className="pm-control">
                  <span>Hacia dónde mira</span>
                  <input
                    type="range"
                    min={0}
                    max={359}
                    value={Math.round(dibujo.camara.rumbo)}
                    onChange={(e) => guardar({ ...dibujo, camara: { ...dibujo.camara!, rumbo: Number(e.target.value) } })}
                  />
                  <output>{Math.round(dibujo.camara.rumbo)}°</output>
                </label>
                <label className="pm-control">
                  <span>Apertura</span>
                  <input
                    type="range"
                    min={20}
                    max={150}
                    value={Math.round(dibujo.camara.apertura)}
                    onChange={(e) => guardar({ ...dibujo, camara: { ...dibujo.camara!, apertura: Number(e.target.value) } })}
                  />
                  <output>{Math.round(dibujo.camara.apertura)}°</output>
                </label>
                <p className="mp-item-meta">También puedes arrastrar la cámara y el punto blanco del cono para girarla.</p>
                <button type="button" className="mp-enlace" onClick={() => guardar({ ...dibujo, camara: null })}>
                  Quitar la cámara
                </button>
              </>
            ) : (
              <>
                <p className="mp-item-meta">Opcional: marca dónde estaba la cámara y hacia dónde apuntaba.</p>
                <button type="button" className="mp-enlace" onClick={() => setObjetivo({ tipo: 'camara' })}>
                  Poner la cámara
                </button>
              </>
            )}
          </section>
        </div>
      </aside>
    </div>
  );
}
