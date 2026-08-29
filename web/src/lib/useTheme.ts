/*
  Tema claro/oscuro.

  Por defecto sigue la preferencia del sistema; el botón fija una
  elección que se recuerda. El valor inicial se lee en index.html antes de
  pintar, para que no haya un destello blanco al cargar en modo oscuro.

  La versión anterior deducía el tema activo leyendo el CSS calculado y
  comprobando si `--surface-0` empezaba con "#0a". Aquí el estado es
  explícito, así que cambiar un color de la paleta ya no puede romper el
  botón.
*/

import { useCallback, useEffect, useState } from 'react';

export type Theme = 'light' | 'dark';

const KEY = 'theme';

function systemTheme(): Theme {
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
}

function storedTheme(): Theme | null {
  try {
    const v = localStorage.getItem(KEY);
    return v === 'light' || v === 'dark' ? v : null;
  } catch {
    // Modo privado o almacenamiento bloqueado: se sigue con el del sistema.
    return null;
  }
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => storedTheme() ?? systemTheme());
  const [explicit, setExplicit] = useState<boolean>(() => storedTheme() !== null);

  // Mientras el usuario no elija, el tema sigue al sistema en vivo.
  useEffect(() => {
    if (explicit) return;
    const mq = window.matchMedia('(prefers-color-scheme: dark)');
    const onChange = () => setTheme(mq.matches ? 'dark' : 'light');
    mq.addEventListener('change', onChange);
    return () => mq.removeEventListener('change', onChange);
  }, [explicit]);

  useEffect(() => {
    if (explicit) document.documentElement.setAttribute('data-theme', theme);
    else document.documentElement.removeAttribute('data-theme');
  }, [theme, explicit]);

  const toggle = useCallback(() => {
    const root = document.documentElement;
    /*
      Un cambio de tema modifica color, fondo, borde y sombra de casi todo
      a la vez. Si cada elemento anima el suyo, el cambio se ve como una
      mancha que se corre por la página. Se apagan todas las transiciones,
      se fuerza un reflujo para que el navegador aplique ese apagado, y se
      restauran en el cuadro siguiente.
    */
    root.classList.add('theme-switching');
    void root.offsetHeight;

    setExplicit(true);
    setTheme((t) => {
      const next: Theme = t === 'dark' ? 'light' : 'dark';
      try {
        localStorage.setItem(KEY, next);
      } catch {
        // Sin almacenamiento la elección dura lo que la pestaña. Aceptable.
      }
      return next;
    });

    /*
      Se restauran en el cuadro siguiente. El `setTimeout` de respaldo no
      es redundante: `requestAnimationFrame` no se ejecuta en una pestaña
      en segundo plano, así que si el usuario cambia de pestaña justo al
      pulsar, la clase se quedaría puesta y la interfaz perdería todas sus
      transiciones hasta recargar. Comprobado: pasaba.
    */
    const restore = () => root.classList.remove('theme-switching');
    requestAnimationFrame(() => requestAnimationFrame(restore));
    setTimeout(restore, 120);
  }, []);

  return { theme, toggle };
}
