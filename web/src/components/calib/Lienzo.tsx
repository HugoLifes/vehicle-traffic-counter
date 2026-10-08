/*
  Capa de dibujo del calibrador, en SVG sobre el cuadro del video.

  Antes era un <canvas> con trazos en píxeles DEL VIDEO: con la cámara de
  2560 px mostrada a ~1000, una línea de 3 px quedaba de 1 px y una etiqueta
  de 14 px se leía como de 5. Aquí todo se dibuja en coordenadas del video
  (viewBox = tamaño del video, así un punto guardado cae exacto sobre su
  píxel) pero el grosor de los trazos, el radio de los puntos y el tamaño
  del texto se multiplican por `unidad` —píxeles de video por píxel de
  pantalla—, así que se ven igual de nítidos a cualquier zoom y con
  cualquier cámara.

  Y en SVG cada figura es un elemento que recibe el puntero: arrastrar un
  vértice, el extremo de una línea o la figura entera no necesita calcular
  a mano qué hay bajo el cursor.
*/

import { useRef, useState } from 'react';
import type { FrameDetection, Point } from '../../lib/types';

export interface ZonaFig {
  id: number;
  nombre: string;
  color: string;
  puntos: Point[];
  acceso?: boolean;
}

export interface LineaFig {
  id: number;
  nombre: string;
  color: string;
  puntos: [Point, Point];
  tramo?: { linea: [Point, Point]; distancia_m: number } | null;
  /** Hay algo que revisar en esta calzada: se marca sobre la línea. */
  alerta?: boolean;
}

export type Seleccion = { tipo: 'zona' | 'linea' | 'tramo'; id: number } | null;

export interface Dibujo {
  tipo: 'poligono' | 'segmento';
  puntos: Point[];
  color: string;
}

interface Props {
  ancho: number;
  alto: number;
  /** Píxeles de video por píxel de pantalla (con el zoom aplicado). */
  unidad: number;
  zonas: ZonaFig[];
  lineas: LineaFig[];
  seleccion: Seleccion;
  onSeleccion: (s: Seleccion) => void;
  /** Se pueden mover puntos y figuras (herramienta Seleccionar). */
  editable: boolean;
  onMover: (tipo: 'zona' | 'linea' | 'tramo', id: number, puntos: Point[]) => void;
  onFinMover: () => void;
  dibujo: Dibujo | null;
  onPunto: (p: Point) => void;
  onCerrar: () => void;
  detecciones?: FrameDetection[];
  heatmap?: HTMLImageElement | null;
  verHeatmap?: boolean;
  /** Arrastre sobre el fondo: lo usa la mesa para desplazar la imagen. */
  onFondoPointerDown?: (e: React.PointerEvent) => void;
}

type ArrastreNuevo =
  | {
      modo: 'vertice';
      tipo: 'zona' | 'linea' | 'tramo';
      id: number;
      indice: number;
      base: Point[];
    }
  | {
      modo: 'figura';
      tipo: 'zona' | 'linea' | 'tramo';
      id: number;
      desde: Point;
      base: Point[];
    };
/* `pantalla` y `activo`: el arrastre no empieza hasta que el puntero se
   mueve unos píxeles. Un clic para seleccionar no debe correr la línea ni
   un píxel: moverla marca como desactualizados los videos ya contados. */
type Arrastre = ArrastreNuevo & { pantalla: [number, number]; activo: boolean };
const UMBRAL_ARRASTRE = 3;

/** Vector unitario hacia el lado "Entrada" (misma fórmula que counter.py). */
function entrada(p1: Point, p2: Point): [number, number] {
  const lx = p2[0] - p1[0];
  const ly = p2[1] - p1[1];
  const len = Math.hypot(lx, ly) || 1;
  const perp: [number, number] = [-ly / len, lx / len];
  return perp[0] * ly - perp[1] * lx > 0 ? perp : [-perp[0], -perp[1]];
}

const pts = (p: Point[]) => p.map(([x, y]) => `${x},${y}`).join(' ');

export function Lienzo({
  ancho,
  alto,
  unidad: u,
  zonas,
  lineas,
  seleccion,
  onSeleccion,
  editable,
  onMover,
  onFinMover,
  dibujo,
  onPunto,
  onCerrar,
  detecciones = [],
  heatmap,
  verHeatmap,
  onFondoPointerDown,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const arrastre = useRef<Arrastre | null>(null);
  const [cursor, setCursor] = useState<Point | null>(null);

  /** Del puntero a coordenadas del video. El rectángulo ya trae el zoom y
      el desplazamiento de la mesa (transformaciones CSS), así que basta
      una regla de tres. */
  const aVideo = (e: { clientX: number; clientY: number }): Point => {
    const r = svgRef.current!.getBoundingClientRect();
    return [((e.clientX - r.left) / r.width) * ancho, ((e.clientY - r.top) / r.height) * alto];
  };

  const empezar = (e: React.PointerEvent, a: ArrastreNuevo) => {
    if (!editable || e.button !== 0) return;
    e.stopPropagation();
    arrastre.current = {
      ...a,
      pantalla: [e.clientX, e.clientY],
      activo: false,
    };
    svgRef.current?.setPointerCapture(e.pointerId);
  };

  const onMove = (e: React.PointerEvent) => {
    const p = aVideo(e);
    if (dibujo) setCursor(p);
    const a = arrastre.current;
    if (!a) return;
    if (!a.activo) {
      if (Math.hypot(e.clientX - a.pantalla[0], e.clientY - a.pantalla[1]) < UMBRAL_ARRASTRE) return;
      a.activo = true;
    }
    const x = Math.max(0, Math.min(ancho, p[0]));
    const y = Math.max(0, Math.min(alto, p[1]));
    if (a.modo === 'vertice') {
      const nuevos = a.base.map((q, i) => (i === a.indice ? ([x, y] as Point) : q));
      onMover(a.tipo, a.id, nuevos);
    } else {
      const dx = x - a.desde[0];
      const dy = y - a.desde[1];
      onMover(
        a.tipo,
        a.id,
        a.base.map(([qx, qy]) => [qx + dx, qy + dy] as Point),
      );
    }
  };

  const onUp = (e: React.PointerEvent) => {
    const a = arrastre.current;
    if (a) {
      arrastre.current = null;
      svgRef.current?.releasePointerCapture(e.pointerId);
      if (a.activo) onFinMover();
    }
  };

  /* Mientras se dibuja, cualquier clic pone un punto, caiga donde caiga:
     sobre el fondo o encima de una calzada ya dibujada (las figuras no
     detienen el evento en ese modo y llega hasta aquí). */
  const onDibujoDown = (e: React.PointerEvent) => {
    if (!dibujo || e.button !== 0) return;
    const p = aVideo(e);
    // Cerrar el polígono tocando su primer punto.
    if (
      dibujo.tipo === 'poligono' &&
      dibujo.puntos.length >= 3 &&
      Math.hypot(p[0] - dibujo.puntos[0][0], p[1] - dibujo.puntos[0][1]) < 12 * u
    ) {
      onCerrar();
      return;
    }
    // El doble clic que cierra la zona no deja un vértice repetido.
    const ultimo = dibujo.puntos[dibujo.puntos.length - 1];
    if (ultimo && Math.hypot(p[0] - ultimo[0], p[1] - ultimo[1]) < 4 * u) return;
    onPunto([Math.max(0, Math.min(ancho, p[0])), Math.max(0, Math.min(alto, p[1]))]);
  };

  const onFondoDown = (e: React.PointerEvent) => {
    if (dibujo) return;
    onSeleccion(null);
    onFondoPointerDown?.(e);
  };

  /* --- Tamaños en pantalla (multiplicados por la unidad) ------------- */
  const trazo = 2 * u;
  const trazoLinea = 3.5 * u;
  const halo = 3 * u;
  const radio = 5.5 * u;
  const radioSel = 7 * u;
  const fuente = 12 * u;

  const etiqueta = (x: number, y: number, texto: string, color: string, alerta = false) => {
    const w = texto.length * fuente * 0.6 + 14 * u + (alerta ? 14 * u : 0);
    const h = fuente + 10 * u;
    return (
      <g pointerEvents="none">
        <rect
          x={x}
          y={y - h / 2}
          width={w}
          height={h}
          rx={h / 2}
          fill="rgba(10,14,20,0.82)"
          stroke={color}
          strokeWidth={1.2 * u}
        />
        {alerta && (
          <text x={x + 8 * u} y={y + fuente * 0.36} fontSize={fuente} fill="#ffb020" fontWeight={700}>
            !
          </text>
        )}
        <text
          x={x + 7 * u + (alerta ? 12 * u : 0)}
          y={y + fuente * 0.36}
          fontSize={fuente}
          fill="#fff"
          fontWeight={600}
          fontFamily="system-ui, sans-serif"
        >
          {texto}
        </text>
      </g>
    );
  };

  const asa = (
    p: Point,
    color: string,
    onDown: (e: React.PointerEvent) => void,
    extra?: { onContextMenu?: (e: React.MouseEvent) => void; titulo?: string },
  ) => (
    <circle
      cx={p[0]}
      cy={p[1]}
      r={radioSel}
      fill="#fff"
      stroke={color}
      strokeWidth={2.5 * u}
      className="lz-asa"
      onPointerDown={onDown}
      onContextMenu={extra?.onContextMenu}
    >
      {extra?.titulo && <title>{extra.titulo}</title>}
    </circle>
  );

  return (
    <svg
      ref={svgRef}
      className={`lienzo${dibujo ? ' is-dibujando' : ''}${editable ? ' is-editable' : ''}`}
      viewBox={`0 0 ${ancho} ${alto}`}
      preserveAspectRatio="none"
      onPointerDown={onDibujoDown}
      onPointerMove={onMove}
      onPointerUp={onUp}
      onPointerLeave={() => setCursor(null)}
      onDoubleClick={() => dibujo?.tipo === 'poligono' && dibujo.puntos.length >= 3 && onCerrar()}
    >
      {/* Fondo que recibe los clics: dibujar, deseleccionar, desplazar. */}
      <rect x={0} y={0} width={ancho} height={alto} fill="transparent" onPointerDown={onFondoDown} />

      {verHeatmap && heatmap && (
        <image
          href={heatmap.src}
          x={0}
          y={0}
          width={ancho}
          height={alto}
          opacity={0.55}
          preserveAspectRatio="none"
          pointerEvents="none"
        />
      )}

      {/* Zonas: debajo de todo lo demás. */}
      {zonas.map((z) => {
        const sel = seleccion?.tipo === 'zona' && seleccion.id === z.id;
        return (
          <g key={`z${z.id}`}>
            <polygon
              points={pts(z.puntos)}
              fill={z.color}
              fillOpacity={sel ? 0.26 : 0.14}
              stroke="rgba(0,0,0,0.55)"
              strokeWidth={trazo + halo}
              strokeLinejoin="round"
              strokeDasharray={z.acceso ? `${8 * u} ${5 * u}` : undefined}
              className={editable ? 'lz-figura' : undefined}
              onPointerDown={(e) => {
                if (dibujo) return;
                e.stopPropagation();
                onSeleccion({ tipo: 'zona', id: z.id });
                if (sel)
                  empezar(e, {
                    modo: 'figura',
                    tipo: 'zona',
                    id: z.id,
                    desde: aVideo(e),
                    base: z.puntos,
                  });
              }}
            />
            <polygon
              points={pts(z.puntos)}
              fill="none"
              stroke={z.color}
              strokeWidth={sel ? trazo * 1.4 : trazo}
              strokeLinejoin="round"
              strokeDasharray={z.acceso ? `${8 * u} ${5 * u}` : undefined}
              pointerEvents="none"
            />
          </g>
        );
      })}

      {/* Cajas del detector en el cuadro actual. */}
      {detecciones.map((d, i) => {
        const [x1, y1, x2, y2] = d.bbox;
        const color = !d.en_zona ? '#8a8f98' : d.confidence >= 0.4 ? '#4ade80' : '#fb923c';
        return (
          <g key={`d${i}`} pointerEvents="none">
            <rect
              x={x1}
              y={y1}
              width={x2 - x1}
              height={y2 - y1}
              fill="none"
              stroke={color}
              strokeWidth={1.5 * u}
              strokeDasharray={d.en_zona ? undefined : `${4 * u} ${3 * u}`}
            />
            <text x={x1} y={y1 - 3 * u} fontSize={10 * u} fill={color}>
              {d.confidence.toFixed(2)}
            </text>
          </g>
        );
      })}

      {/* Tramos de velocidad: la segunda "manguera", punteada. */}
      {lineas.map((l) => {
        if (!l.tramo) return null;
        const [q1, q2] = l.tramo.linea;
        const sel = seleccion?.tipo === 'tramo' && seleccion.id === l.id;
        const m1: Point = [(l.puntos[0][0] + l.puntos[1][0]) / 2, (l.puntos[0][1] + l.puntos[1][1]) / 2];
        const m2: Point = [(q1[0] + q2[0]) / 2, (q1[1] + q2[1]) / 2];
        return (
          <g key={`t${l.id}`}>
            <line
              x1={m1[0]}
              y1={m1[1]}
              x2={m2[0]}
              y2={m2[1]}
              stroke={l.color}
              strokeWidth={1.2 * u}
              strokeDasharray={`${2 * u} ${4 * u}`}
              pointerEvents="none"
            />
            <line
              x1={q1[0]}
              y1={q1[1]}
              x2={q2[0]}
              y2={q2[1]}
              stroke="rgba(0,0,0,0.55)"
              strokeWidth={trazo + halo}
              pointerEvents="none"
            />
            <line
              x1={q1[0]}
              y1={q1[1]}
              x2={q2[0]}
              y2={q2[1]}
              stroke={l.color}
              strokeWidth={sel ? trazo * 1.4 : trazo}
              strokeDasharray={`${7 * u} ${5 * u}`}
              pointerEvents="none"
            />
            {/* Franja de agarre: el trazo visible mide 2 px y no se le atina. */}
            <line
              x1={q1[0]}
              y1={q1[1]}
              x2={q2[0]}
              y2={q2[1]}
              stroke="transparent"
              strokeWidth={16 * u}
              strokeLinecap="round"
              className={editable ? 'lz-figura' : undefined}
              onPointerDown={(e) => {
                if (dibujo) return;
                e.stopPropagation();
                onSeleccion({ tipo: 'tramo', id: l.id });
                empezar(e, {
                  modo: 'figura',
                  tipo: 'tramo',
                  id: l.id,
                  desde: aVideo(e),
                  base: [q1, q2],
                });
              }}
            />
            {etiqueta((m1[0] + m2[0]) / 2 + 8 * u, (m1[1] + m2[1]) / 2, `${l.tramo.distancia_m} m`, l.color)}
          </g>
        );
      })}

      {/* Líneas de conteo. */}
      {lineas.map((l) => {
        const [p1, p2] = l.puntos;
        const sel = seleccion?.tipo === 'linea' && seleccion.id === l.id;
        const mid: Point = [(p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2];
        const dir = entrada(p1, p2);
        const largo = 22 * u;
        const punta: Point = [mid[0] + dir[0] * largo, mid[1] + dir[1] * largo];
        const ang = Math.atan2(dir[1], dir[0]);
        const arriba = p1[1] < p2[1] ? p1 : p2;
        return (
          <g key={`l${l.id}`}>
            <line
              x1={p1[0]}
              y1={p1[1]}
              x2={p2[0]}
              y2={p2[1]}
              stroke="rgba(0,0,0,0.6)"
              strokeWidth={trazoLinea + halo}
              strokeLinecap="round"
              pointerEvents="none"
            />
            <line
              x1={p1[0]}
              y1={p1[1]}
              x2={p2[0]}
              y2={p2[1]}
              stroke={l.color}
              strokeWidth={sel ? trazoLinea * 1.3 : trazoLinea}
              strokeLinecap="round"
              pointerEvents="none"
            />
            <line
              x1={p1[0]}
              y1={p1[1]}
              x2={p2[0]}
              y2={p2[1]}
              stroke="transparent"
              strokeWidth={16 * u}
              strokeLinecap="round"
              className={editable ? 'lz-figura' : undefined}
              onPointerDown={(e) => {
                if (dibujo) return;
                e.stopPropagation();
                onSeleccion({ tipo: 'linea', id: l.id });
                empezar(e, {
                  modo: 'figura',
                  tipo: 'linea',
                  id: l.id,
                  desde: aVideo(e),
                  base: [p1, p2],
                });
              }}
            />
            {/* Flecha hacia el lado que el informe llama "Entrada". */}
            <g pointerEvents="none" stroke={l.color} fill={l.color}>
              <line x1={mid[0]} y1={mid[1]} x2={punta[0]} y2={punta[1]} strokeWidth={2.2 * u} />
              <polygon
                points={pts([
                  punta,
                  [punta[0] - 7 * u * Math.cos(ang - 0.45), punta[1] - 7 * u * Math.sin(ang - 0.45)],
                  [punta[0] - 7 * u * Math.cos(ang + 0.45), punta[1] - 7 * u * Math.sin(ang + 0.45)],
                ])}
              />
            </g>
            {!sel &&
              [p1, p2].map((p, i) => (
                <g key={i}>
                  <circle
                    cx={p[0]}
                    cy={p[1]}
                    r={radio * 0.8}
                    fill={l.color}
                    stroke="rgba(0,0,0,0.6)"
                    strokeWidth={1.2 * u}
                    pointerEvents="none"
                  />
                  {/* Un extremo se agarra sin seleccionar antes la línea. */}
                  <circle
                    cx={p[0]}
                    cy={p[1]}
                    r={radioSel * 1.3}
                    fill="transparent"
                    className={editable ? 'lz-asa' : undefined}
                    onPointerDown={(e) => {
                      if (dibujo || !editable) return;
                      onSeleccion({ tipo: 'linea', id: l.id });
                      empezar(e, {
                        modo: 'vertice',
                        tipo: 'linea',
                        id: l.id,
                        indice: i,
                        base: [p1, p2],
                      });
                    }}
                  />
                </g>
              ))}
            {etiqueta(arriba[0] + 10 * u, arriba[1] - 4 * u, l.nombre, l.color, l.alerta)}
          </g>
        );
      })}

      {/* Asas de la figura seleccionada. */}
      {editable &&
        seleccion &&
        (() => {
          if (seleccion.tipo === 'zona') {
            const z = zonas.find((q) => q.id === seleccion.id);
            if (!z) return null;
            const n = z.puntos.length;
            return (
              <g>
                {/* Puntos medios: arrastrarlos agrega un vértice ahí. */}
                {z.puntos.map((a, i) => {
                  const b = z.puntos[(i + 1) % n];
                  const m: Point = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
                  return (
                    <circle
                      key={`m${i}`}
                      cx={m[0]}
                      cy={m[1]}
                      r={radio * 0.75}
                      fill={z.color}
                      fillOpacity={0.55}
                      stroke="#fff"
                      strokeWidth={1.2 * u}
                      className="lz-asa"
                      onPointerDown={(e) => {
                        // El vértice nuevo solo aparece si de verdad se arrastra.
                        const base = [...z.puntos.slice(0, i + 1), m, ...z.puntos.slice(i + 1)];
                        empezar(e, {
                          modo: 'vertice',
                          tipo: 'zona',
                          id: z.id,
                          indice: i + 1,
                          base,
                        });
                      }}
                    >
                      <title>Arrastra para agregar un vértice</title>
                    </circle>
                  );
                })}
                {z.puntos.map((p, i) =>
                  asa(
                    p,
                    z.color,
                    (e) =>
                      empezar(e, {
                        modo: 'vertice',
                        tipo: 'zona',
                        id: z.id,
                        indice: i,
                        base: z.puntos,
                      }),
                    {
                      titulo: 'Arrastra para mover · clic derecho para quitar',
                      onContextMenu: (e) => {
                        e.preventDefault();
                        if (n > 3) {
                          onMover(
                            'zona',
                            z.id,
                            z.puntos.filter((_, j) => j !== i),
                          );
                          onFinMover();
                        }
                      },
                    },
                  ),
                )}
              </g>
            );
          }
          const l = lineas.find((q) => q.id === seleccion.id);
          if (!l) return null;
          const base = seleccion.tipo === 'tramo' && l.tramo ? l.tramo.linea : l.puntos;
          return (
            <g>
              {base.map((p, i) =>
                asa(p, l.color, (e) =>
                  empezar(e, {
                    modo: 'vertice',
                    tipo: seleccion.tipo,
                    id: l.id,
                    indice: i,
                    base: [...base],
                  }),
                ),
              )}
            </g>
          );
        })()}

      {/* Lo que se está dibujando, con una guía hasta el cursor. */}
      {dibujo && (
        <g pointerEvents="none">
          {dibujo.tipo === 'poligono' && dibujo.puntos.length >= 3 && (
            <polygon points={pts(dibujo.puntos)} fill={dibujo.color} fillOpacity={0.12} stroke="none" />
          )}
          {dibujo.puntos.length >= 2 && (
            <polyline
              points={pts(dibujo.puntos)}
              fill="none"
              stroke="rgba(0,0,0,0.6)"
              strokeWidth={trazoLinea + halo}
              strokeLinejoin="round"
            />
          )}
          {dibujo.puntos.length >= 2 && (
            <polyline
              points={pts(dibujo.puntos)}
              fill="none"
              stroke={dibujo.color}
              strokeWidth={trazoLinea}
              strokeLinejoin="round"
            />
          )}
          {cursor && dibujo.puntos.length > 0 && (
            <line
              x1={dibujo.puntos[dibujo.puntos.length - 1][0]}
              y1={dibujo.puntos[dibujo.puntos.length - 1][1]}
              x2={cursor[0]}
              y2={cursor[1]}
              stroke={dibujo.color}
              strokeWidth={1.8 * u}
              strokeDasharray={`${6 * u} ${4 * u}`}
            />
          )}
          {cursor && dibujo.tipo === 'poligono' && dibujo.puntos.length >= 2 && (
            <line
              x1={cursor[0]}
              y1={cursor[1]}
              x2={dibujo.puntos[0][0]}
              y2={dibujo.puntos[0][1]}
              stroke={dibujo.color}
              strokeOpacity={0.4}
              strokeWidth={1.2 * u}
              strokeDasharray={`${3 * u} ${5 * u}`}
            />
          )}
          {dibujo.puntos.map((p, i) => (
            <circle
              key={i}
              cx={p[0]}
              cy={p[1]}
              r={i === 0 && dibujo.tipo === 'poligono' && dibujo.puntos.length >= 3 ? radioSel * 1.2 : radio}
              fill={i === 0 ? '#fff' : dibujo.color}
              stroke={i === 0 ? dibujo.color : 'rgba(0,0,0,0.6)'}
              strokeWidth={2 * u}
            />
          ))}
        </g>
      )}
    </svg>
  );
}
