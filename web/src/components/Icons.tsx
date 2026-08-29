/*
  Un solo juego de iconos para toda la app.

  Reglas que se cumplen aquí y no hay que recordar caso por caso:
   · Todos usan `currentColor`, así que el color y los estados salen del
     CSS y nunca hacen falta dos archivos para el mismo icono.
   · El grosor del trazo acompaña el peso del texto de al lado: 1.5 junto
     a texto normal, 2 junto a texto en seminegrita. De ahí la prop
     `strokeWidth`, con 1.8 como término medio.
   · Los decorativos llevan `aria-hidden`; el nombre accesible lo pone el
     botón que los contiene, nunca el icono.
*/

import type { ReactNode, SVGProps } from 'react';

interface IconProps extends Omit<SVGProps<SVGSVGElement>, 'width' | 'height'> {
  size?: number;
  strokeWidth?: number;
}

function Svg({
  size = 16,
  strokeWidth = 1.8,
  children,
  ...rest
}: IconProps & { children: ReactNode }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
      {...rest}
    >
      {children}
    </svg>
  );
}

export const IconBrand = (p: IconProps) => (
  <Svg {...p} strokeWidth={p.strokeWidth ?? 2}>
    <rect x="2" y="2" width="20" height="20" rx="5" strokeOpacity="0.35" />
    <path d="M7 16 L7 8 L11 8" />
    <path d="M9.5 5.5 L7 8 L9.5 10.5" />
    <path d="M17 8 L17 16 L13 16" />
    <path d="M14.5 18.5 L17 16 L14.5 13.5" />
  </Svg>
);

export const IconPin = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 21s-7-6-7-11a7 7 0 1114 0c0 5-7 11-7 11z" />
    <circle cx="12" cy="10" r="2.5" />
  </Svg>
);

export const IconUpload = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3v13" />
    <path d="M7 8l5-5 5 5" />
    <path d="M4 15v3a2 2 0 002 2h12a2 2 0 002-2v-3" />
  </Svg>
);

export const IconVideo = (p: IconProps) => (
  <Svg {...p}>
    <rect x="2.5" y="5" width="14" height="14" rx="2" />
    <path d="M16.5 9.5l5-2.5v10l-5-2.5z" />
  </Svg>
);

export const IconEye = (p: IconProps) => (
  <Svg {...p}>
    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
    <circle cx="12" cy="12" r="3" />
  </Svg>
);

export const IconTrash = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13" />
  </Svg>
);

export const IconClose = (p: IconProps) => (
  <Svg {...p} strokeWidth={p.strokeWidth ?? 2}>
    <path d="M6 6l12 12M18 6L6 18" />
  </Svg>
);

export const IconCheck = (p: IconProps) => (
  <Svg {...p} strokeWidth={p.strokeWidth ?? 3}>
    <path d="M20 6L9 17l-5-5" />
  </Svg>
);

export const IconAlert = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 3l9.5 17h-19z" />
    <path d="M12 9v5M12 17.2v.1" />
  </Svg>
);

export const IconInfo = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5M12 7.8v.1" />
  </Svg>
);

export const IconSearch = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="11" cy="11" r="7" />
    <path d="M16.5 16.5L21 21" />
  </Svg>
);

export const IconSun = (p: IconProps) => (
  <Svg {...p} strokeWidth={p.strokeWidth ?? 2}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
  </Svg>
);

export const IconMoon = (p: IconProps) => (
  <Svg {...p} strokeWidth={p.strokeWidth ?? 2}>
    <path d="M21 12.8A9 9 0 1111.2 3a7 7 0 009.8 9.8z" />
  </Svg>
);
