/*
  El aforo en movimiento: una escena 3D donde cada carril medido es un
  tramo de calzada por el que circulan vehículos, en la proporción y con
  la mezcla que el conteo registró de verdad.

  Qué es y qué NO es
  ------------------
  Es un ESQUEMA, no un plano de la intersección. Los carriles calibrados
  están en píxeles del video, que es una vista en perspectiva; sin una
  homografía (cuatro puntos de suelo con medidas reales) no hay forma de
  reconstruir la planta. Inventar una geometría que parezca el crucero
  real sería mentir con precisión falsa, así que los tramos van en
  paralelo y el diagrama lo dice.

  Lo que sí es fiel, y es lo que aporta sobre la gráfica de barras:
   · La densidad de cada tramo es proporcional al volumen de ese carril.
   · El reparto entre los dos sentidos es el de entrada/salida medido.
   · La mezcla de formas es la composición real del carril: un tramo con
     muchos camiones se ve con muchos camiones.

  Peso
  ----
  three.js pesa más que toda la app junta, así que se carga con import()
  dinámico: Vite lo separa en su propio trozo y solo lo descarga quien
  abre esta pantalla. Los vehículos son cajas generadas por código, no
  modelos descargados — no hay ni un byte más de assets.
*/

import { useEffect, useRef, useState } from 'react';
import type { LaneMetrics } from '../lib/types';
import { vehicleLabel } from '../lib/format';

/** Alto de la escena. Suficiente para leer las formas sin robarle la
    pantalla a las cifras, que son el dato duro. */
const ALTO = 340;
/** Tope de vehículos vivos. Más que esto no aporta información y sí
    calienta el equipo — puede abrirse desde el propio Jetson. */
const MAX_VEHICULOS = 90;

interface Props {
  lanes: LaneMetrics[];
}

function leerColor(nombre: string, respaldo: string): string {
  const v = getComputedStyle(document.documentElement).getPropertyValue(nombre).trim();
  return v || respaldo;
}

export function EscenaFlujo({ lanes }: Props) {
  const hostRef = useRef<HTMLDivElement>(null);
  const [estado, setEstado] = useState<'cargando' | 'lista' | 'sin-soporte'>('cargando');

  useEffect(() => {
    const host = hostRef.current;
    if (!host) return;

    let vivo = true;
    let limpiar: (() => void) | undefined;

    (async () => {
      const THREE = await import('three');
      if (!vivo || !hostRef.current) return;

      const ancho = () => hostRef.current?.clientWidth ?? 640;

      let renderer: InstanceType<typeof THREE.WebGLRenderer>;
      try {
        renderer = new THREE.WebGLRenderer({ antialias: true });
      } catch {
        // Sin WebGL la pantalla sigue teniendo sus gráficas y su tabla;
        // esto es un complemento, no la fuente del dato.
        setEstado('sin-soporte');
        return;
      }

      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
      // Fondo propio en vez de transparente: la escena se lee como una
      // superficie con su propio espacio, y además deja ver de inmediato
      // si está dibujando algo o no.
      renderer.setClearColor(new THREE.Color(leerColor('--surface-0', '#f2f5f8')), 1);
      renderer.setSize(ancho(), ALTO);
      hostRef.current.appendChild(renderer.domElement);

      const escena = new THREE.Scene();
      const FOV = 38;
      const camara = new THREE.PerspectiveCamera(FOV, ancho() / ALTO, 0.1, 400);

      /* --- Luz -----------------------------------------------------
         Una direccional marcada más un relleno ambiental suave: las
         formas se distinguen por su silueta y su sombreado, que es lo
         único que separa un camión de un autobús a este tamaño. */
      escena.add(new THREE.AmbientLight(0xffffff, 1.5));
      const sol = new THREE.DirectionalLight(0xffffff, 2.2);
      sol.position.set(18, 30, 20);
      escena.add(sol);

      const colores = {
        calzada: leerColor('--surface-2', '#e7ecf1'),
        marca: leerColor('--border-strong', '#7d8b9c'),
        car: leerColor('--veh-car', '#1d54b3'),
        truck: leerColor('--veh-truck', '#9a5a12'),
        bus: leerColor('--veh-bus', '#6b34a1'),
        motorcycle: leerColor('--veh-motorcycle', '#0d6b72'),
        otro: leerColor('--veh-other', '#4d5967'),
      };
      const colorDe = (t: string) =>
        new THREE.Color((colores as Record<string, string>)[t] ?? colores.otro);

      /* --- Vehículos por código, no por modelo descargado ------------
         Cuatro siluetas de cajas. A esta escala lo que distingue a un
         vehículo de otro es su proporción —largo, alto y si tiene
         cabina separada—, no su detalle. */
      function construir(tipo: string, color: InstanceType<typeof THREE.Color>) {
        const g = new THREE.Group();
        const mat = new THREE.MeshLambertMaterial({ color });
        const matOscuro = new THREE.MeshLambertMaterial({ color: color.clone().multiplyScalar(0.6) });

        const caja = (w: number, h: number, d: number, y: number, m = mat) => {
          const malla = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), m);
          malla.position.y = y;
          return malla;
        };

        if (tipo === 'bus') {
          g.add(caja(1.5, 1.5, 4.6, 0.95));
          g.add(caja(1.52, 0.45, 4.0, 1.35, matOscuro)); // franja de ventanas
        } else if (tipo === 'truck') {
          g.add(caja(1.5, 1.2, 1.5, 0.85)); // cabina
          const cama = caja(1.6, 1.5, 3.0, 1.0, matOscuro);
          cama.position.z = 2.2;
          g.add(cama);
        } else if (tipo === 'motorcycle') {
          g.add(caja(0.45, 0.5, 1.5, 0.6));
        } else {
          g.add(caja(1.4, 0.65, 3.4, 0.55)); // carrocería
          const techo = caja(1.25, 0.55, 1.7, 1.1, matOscuro);
          techo.position.z = -0.2;
          g.add(techo);
        }
        return g;
      }

      /* --- Un tramo de calzada por carril --------------------------- */
      const LARGO = 34;
      const ANCHO_CARRIL = 5.2;
      const separacion = ANCHO_CARRIL + 1.6;
      const x0 = -((lanes.length - 1) * separacion) / 2;

      const totalGlobal = Math.max(
        1,
        lanes.reduce((s, l) => s + l.total, 0),
      );

      interface Movil {
        grupo: InstanceType<typeof THREE.Group>;
        vel: number;
        dir: 1 | -1;
      }
      const moviles: Movil[] = [];

      lanes.forEach((carril, i) => {
        const x = x0 + i * separacion;

        const calzada = new THREE.Mesh(
          new THREE.PlaneGeometry(ANCHO_CARRIL, LARGO),
          new THREE.MeshLambertMaterial({ color: new THREE.Color(colores.calzada) }),
        );
        calzada.rotation.x = -Math.PI / 2;
        calzada.position.set(x, 0, 0);
        escena.add(calzada);

        // Raya discontinua central: da referencia de movimiento, sin ella
        // los vehículos parecen flotar en un plano liso.
        const matMarca = new THREE.MeshLambertMaterial({ color: new THREE.Color(colores.marca) });
        for (let z = -LARGO / 2 + 2; z < LARGO / 2; z += 4) {
          const raya = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.02, 1.6), matMarca);
          raya.position.set(x, 0.02, z);
          escena.add(raya);
        }

        /* Cuántos vehículos viven en este tramo: proporcional a su parte
           del volumen total. El carril con más tránsito se ve más lleno,
           que es justo lo que la gráfica de barras no transmite. */
        const cuota = carril.total / totalGlobal;
        const cuantos = Math.max(carril.total > 0 ? 2 : 0, Math.round(cuota * MAX_VEHICULOS));

        // La mezcla de formas sale de la composición REAL del carril.
        const composicion = Object.entries(carril.composition).filter(([, n]) => n > 0);
        const sumaComp = composicion.reduce((s, [, n]) => s + n, 0) || 1;
        const elegirTipo = () => {
          let r = Math.random() * sumaComp;
          for (const [tipo, n] of composicion) {
            r -= n;
            if (r <= 0) return tipo;
          }
          return composicion[0]?.[0] ?? 'car';
        };

        // El reparto entre sentidos es el de entrada/salida medido.
        const propEntrada = carril.total > 0 ? carril.in / carril.total : 0.5;

        for (let k = 0; k < cuantos; k++) {
          const tipo = elegirTipo();
          const g = construir(tipo, colorDe(tipo));
          const dir: 1 | -1 = Math.random() < propEntrada ? 1 : -1;
          g.position.set(x + (dir === 1 ? -1.2 : 1.2), 0, Math.random() * LARGO - LARGO / 2);
          if (dir === -1) g.rotation.y = Math.PI;
          escena.add(g);
          moviles.push({ grupo: g, vel: 7 + Math.random() * 5, dir });
        }
      });

      /* --- Encuadre --------------------------------------------------
         La cámara se calcula desde el contenido, no a ojo: con un carril
         o con seis la escena tiene que llenar el lienzo igual. Se toma la
         esfera que envuelve todos los tramos y se retrocede hasta que
         cabe en el menor de los dos ángulos de visión — el vertical o el
         horizontal, según la forma del lienzo.

         Además la escena va girada: con los tramos en diagonal se ve su
         largo y a la vez el costado de los vehículos, que es lo que
         permite distinguir un camión de un autobús. De frente solo se
         verían rectángulos. */
      const anchoContenido = (lanes.length - 1) * separacion + ANCHO_CARRIL;

      /* El contenido es una superficie plana y alargada, no una pelota, así
         que ajustar por esfera envolvente lo deja diminuto: con dos
         carriles ocupaba el 24 % del ancho del lienzo. Se calcula la
         huella real ya girada y se ajusta por separado en alto y ancho,
         tomando la distancia que satisface a las dos. */
      const GIRO = 0.75;   // ~43°: los tramos cruzan el lienzo en diagonal
      const ELEV = (32 * Math.PI) / 180;

      const hx = (anchoContenido / 2) * Math.cos(GIRO) + (LARGO / 2) * Math.sin(GIRO);
      const hz = (anchoContenido / 2) * Math.sin(GIRO) + (LARGO / 2) * Math.cos(GIRO);

      const encuadrar = () => {
        const a = ancho() / ALTO;
        const fovV = (FOV * Math.PI) / 180;
        const fovH = 2 * Math.atan(Math.tan(fovV / 2) * a);
        // Visto desde arriba en ángulo, el largo del suelo se acorta en
        // pantalla por el seno de la elevación; el ancho no.
        const distV = (hz * Math.sin(ELEV)) / Math.tan(fovV / 2);
        const distH = hx / Math.tan(fovH / 2);
        const dist = Math.max(distV, distH) * 1.5 + 6;
        camara.position.set(0, Math.sin(ELEV) * dist, Math.cos(ELEV) * dist);
        camara.lookAt(0, 0, 0);
        camara.aspect = a;
        camara.updateProjectionMatrix();
      };

      // Girar la escena, no la cámara: así los vehículos siguen avanzando
      // en su eje y se ve a la vez el largo del tramo y el costado de cada
      // vehículo, que es lo que separa un camión de un autobús.
      escena.rotation.y = -GIRO;
      encuadrar();

      /* --- Animación ------------------------------------------------
         Se apaga con prefers-reduced-motion y con la pestaña en segundo
         plano: una escena girando que nadie mira es calor por nada. */
      const sinMovimiento = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      const reloj = new THREE.Clock();
      let raf = 0;

      const dibujar = () => {
        if (!vivo) return;
        const dt = Math.min(reloj.getDelta(), 0.05);
        if (!sinMovimiento && !document.hidden) {
          for (const m of moviles) {
            m.grupo.position.z += m.vel * m.dir * dt;
            if (m.grupo.position.z > LARGO / 2) m.grupo.position.z = -LARGO / 2;
            if (m.grupo.position.z < -LARGO / 2) m.grupo.position.z = LARGO / 2;
          }
        }
        renderer.render(escena, camara);
        raf = requestAnimationFrame(dibujar);
      };
      dibujar();

      const alRedimensionar = () => {
        renderer.setSize(ancho(), ALTO);
        encuadrar();
      };
      window.addEventListener('resize', alRedimensionar);

      setEstado('lista');

      limpiar = () => {
        cancelAnimationFrame(raf);
        window.removeEventListener('resize', alRedimensionar);
        // Sin esto la memoria de la tarjeta gráfica no se suelta al
        // cambiar de pestaña, y se acumula en cada visita.
        escena.traverse((o) => {
          const m = o as InstanceType<typeof THREE.Mesh>;
          if (m.geometry) m.geometry.dispose();
          if (m.material) {
            const mats = Array.isArray(m.material) ? m.material : [m.material];
            mats.forEach((x) => x.dispose());
          }
        });
        renderer.dispose();
        renderer.domElement.remove();
      };
    })().catch(() => vivo && setEstado('sin-soporte'));

    return () => {
      vivo = false;
      limpiar?.();
    };
  }, [lanes]);

  if (estado === 'sin-soporte') return null;

  // Leyenda: las formas por sí solas no dicen qué es cada una, y el color
  // tampoco basta para quien no lo distingue.
  const tipos = [...new Set(lanes.flatMap((l) => Object.keys(l.composition)))];

  return (
    <div className="escena">
      <div className="escena-lienzo" ref={hostRef} style={{ height: ALTO }}>
        {estado === 'cargando' && <p className="escena-cargando">Preparando la escena…</p>}
      </div>
      {tipos.length > 0 && (
        <div className="comp-legend escena-leyenda">
          {tipos.map((t) => (
            <div className="comp-legend-item" key={t}>
              <span className="comp-swatch" style={{ background: `var(--veh-${t}, var(--veh-other))` }} />
              <span className="comp-label">{vehicleLabel(t)}</span>
            </div>
          ))}
        </div>
      )}
      <p className="escena-nota">
        Esquema, no plano: los carriles calibrados están en píxeles del video, que es una vista en
        perspectiva, así que la planta real no se puede reconstruir. Lo que sí es fiel es la
        proporción — cada tramo lleva los vehículos que le tocan por su volumen, repartidos entre
        los dos sentidos y con la mezcla de tipos que se contó de verdad.
      </p>
    </div>
  );
}
