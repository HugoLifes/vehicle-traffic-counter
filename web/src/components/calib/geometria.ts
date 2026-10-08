/*
  Geometría del calibrador: lo que se puede comprobar de una calzada sin
  contar nada, mientras se dibuja.

  Las tres revisiones salen de errores que costaron conteos reales:
   · La línea no cruza toda la calzada → los vehículos de un lado pasan
     sin tocarla (Cd. Juárez, `Carril 2` dejaba fuera el 33 % del alto de su
     calzada sin ningún aviso).
   · La línea corre a lo largo del tránsito → el vehículo avanza junto a
     ella y casi nunca la cruza (Campos Eliseos, 6-oct-2026: 13 de 13
     videos contaron casi nada).
   · La línea pegada a la orilla de la imagen → el vehículo entra o sale
     del cuadro justo ahí y el rastreador no alcanza a ver el cruce.
*/

import type { Point } from '../../lib/types';

export function dentroDe(p: Point, poly: Point[]): boolean {
  let dentro = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i];
    const [xj, yj] = poly[j];
    if (yi > p[1] !== yj > p[1] && p[0] < ((xj - xi) * (p[1] - yi)) / (yj - yi) + xi) {
      dentro = !dentro;
    }
  }
  return dentro;
}

/** Distancia de un punto al borde de un polígono. */
export function distanciaAlBorde(p: Point, poly: Point[]): number {
  let mejor = Infinity;
  for (let i = 0; i < poly.length; i++) {
    mejor = Math.min(mejor, distanciaASegmento(p, poly[i], poly[(i + 1) % poly.length]));
  }
  return mejor;
}

export function distanciaASegmento(p: Point, a: Point, b: Point): number {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const l2 = dx * dx + dy * dy || 1;
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / l2));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

/** Eje largo de un polígono (dirección de la calzada), por componentes
    principales sobre su contorno muestreado: una calzada es una franja larga
    y su eje es la dirección del tránsito. */
export function ejeDe(poly: Point[]): [number, number] {
  const pts: Point[] = [];
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i];
    const b = poly[(i + 1) % poly.length];
    for (let t = 0; t < 1; t += 0.1) pts.push([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t]);
  }
  const mx = pts.reduce((s, p) => s + p[0], 0) / pts.length;
  const my = pts.reduce((s, p) => s + p[1], 0) / pts.length;
  let sxx = 0;
  let syy = 0;
  let sxy = 0;
  for (const [x, y] of pts) {
    sxx += (x - mx) ** 2;
    syy += (y - my) ** 2;
    sxy += (x - mx) * (y - my);
  }
  const ang = 0.5 * Math.atan2(2 * sxy, sxx - syy);
  return [Math.cos(ang), Math.sin(ang)];
}

/** Ángulo (0–90°) entre una línea y una dirección. */
export function anguloCon(p1: Point, p2: Point, dir: [number, number]): number {
  const lx = p2[0] - p1[0];
  const ly = p2[1] - p1[1];
  const l = Math.hypot(lx, ly) || 1;
  const cos = Math.abs((lx * dir[0] + ly * dir[1]) / l);
  return (Math.acos(Math.min(1, cos)) * 180) / Math.PI;
}

/** Ancho de la calzada medido a lo largo de la línea: el tramo de la recta
    de la línea que cae dentro del polígono. */
function cruceConPoligono(p1: Point, p2: Point, poly: Point[]): [number, number] | null {
  const dx = p2[0] - p1[0];
  const dy = p2[1] - p1[1];
  const ts: number[] = [];
  for (let i = 0; i < poly.length; i++) {
    const a = poly[i];
    const b = poly[(i + 1) % poly.length];
    const ex = b[0] - a[0];
    const ey = b[1] - a[1];
    const den = dx * ey - dy * ex;
    if (Math.abs(den) < 1e-9) continue;
    const t = ((a[0] - p1[0]) * ey - (a[1] - p1[1]) * ex) / den;
    const u = ((a[0] - p1[0]) * dy - (a[1] - p1[1]) * dx) / den;
    if (u >= 0 && u <= 1) ts.push(t);
  }
  if (ts.length < 2) return null;
  return [Math.min(...ts), Math.max(...ts)];
}

export interface Aviso {
  nivel: 'error' | 'aviso';
  texto: string;
}

export function revisarCalzada(
  zona: Point[] | null,
  linea: [Point, Point] | null,
  ancho: number,
  alto: number,
): Aviso[] {
  const avisos: Aviso[] = [];
  if (!linea) {
    avisos.push({ nivel: 'error', texto: 'Falta la línea de conteo: sin ella esta calzada no cuenta nada.' });
    return avisos;
  }
  const [p1, p2] = linea;
  if (zona && zona.length >= 3) {
    const cruce = cruceConPoligono(p1, p2, zona);
    if (!cruce) {
      avisos.push({ nivel: 'error', texto: 'La línea no toca su calzada.' });
    } else {
      // Cada extremo tiene que llegar a la orilla de la calzada: si uno cae
      // dentro, el lado que queda sin cubrir no se cuenta. Se mide qué
      // fracción del ancho queda fuera. Las zonas se dibujan con algo de
      // margen, así que un 5 % no es falla: Campos Eliseos cuenta bien con
      // sus líneas 10–12 px dentro (5 % de una calzada de 200 px). Juárez
      // dejaba fuera el 33 %.
      const largoLinea = Math.hypot(p2[0] - p1[0], p2[1] - p1[1]);
      const anchoCalzada = Math.max(1, (cruce[1] - cruce[0]) * largoLinea);
      const fuera = [p1, p2]
        .filter((p) => dentroDe(p, zona))
        .map((p) => distanciaAlBorde(p, zona) / anchoCalzada)
        .reduce((s, f) => s + f, 0);
      if (fuera > 0.15) {
        const pct = Math.round(fuera * 100);
        avisos.push({
          nivel: fuera > 0.25 ? 'error' : 'aviso',
          texto: `La línea no cruza toda la calzada: queda fuera cerca del ${pct} % de su ancho, y los vehículos que pasan por ahí no se cuentan. Alárgala hasta las orillas.`,
        });
      }
    }
    const ang = anguloCon(p1, p2, ejeDe(zona));
    if (ang < 40) {
      avisos.push({
        nivel: 'error',
        texto: `La línea va casi a lo largo de la calzada (${Math.round(ang)}°). Tiene que cruzarla de través, como una raya de alto.`,
      });
    } else if (ang < 60) {
      avisos.push({
        nivel: 'aviso',
        texto: `La línea cruza la calzada muy inclinada (${Math.round(ang)}°). Más de través cuenta mejor.`,
      });
    }
  }
  // Pegada a la orilla de la imagen: el vehículo entra o sale del cuadro
  // ahí y no se alcanza a ver antes de la línea.
  const margen = Math.min(ancho, alto) * 0.04;
  const mx = (p1[0] + p2[0]) / 2;
  const my = (p1[1] + p2[1]) / 2;
  if (mx < margen || my < margen || mx > ancho - margen || my > alto - margen) {
    avisos.push({
      nivel: 'aviso',
      texto: 'La línea está pegada a la orilla de la imagen: muévela hacia dentro, donde el vehículo se ve antes y después de cruzarla.',
    });
  }
  return avisos;
}
