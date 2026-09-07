import { StrictMode, useEffect } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes, useNavigate } from 'react-router-dom';
import { Toaster } from 'sonner';

import './styles/tokens.css';
import './styles/base.css';
import './styles/components.css';
import './styles/layout.css';
import './styles/pages.css';
import './styles/print.css';

import Proyectos from './pages/Proyectos';
import Proyecto from './pages/Proyecto';
import ProyectoResumen from './pages/ProyectoResumen';
import ProyectoCamara from './pages/ProyectoCamara';
import ProyectoRegistro from './pages/ProyectoRegistro';
import Comparar from './pages/Comparar';
import Subir from './pages/Subir';
import Calibrar from './pages/Calibrar';
import Reporte from './pages/Reporte';
import EnVivo from './pages/EnVivo';
import Documentos from './pages/Documentos';
import ProyectoDocumentos from './pages/ProyectoDocumentos';
import { RedirigirALaIntersección } from './pages/redirects';
import { registrarNavegador } from './lib/navegar';
import { useVigilante } from './lib/useVigilante';
import { useTheme } from './lib/useTheme';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Los datos siguen sirviendo unos segundos: al cambiar de paso
      // (subir → calibrar → reporte) la pantalla nueva pinta de inmediato
      // con lo que ya se tenía y refresca por detrás.
      staleTime: 2000,
      // Un error de la API casi siempre es el backend caído; reintentar
      // tres veces solo retrasa el mensaje que el usuario necesita ver.
      retry: 1,
      refetchOnWindowFocus: true,
    },
  },
});

/*
  Lo que envuelve a toda la app: el vigilante de trabajos en segundo plano
  y el sitio donde salen los avisos.

  Van aquí y no dentro de una página porque su razón de ser es enterarse
  de lo que pasa cuando NO estás mirando la pantalla que lo provocó. Un
  <Toaster /> montado por página además duplicaría cada aviso.
*/
function App() {
  useVigilante();
  const { theme } = useTheme();

  // Los avisos de las mutaciones se arman fuera del árbol de React y
  // necesitan poder saltar a una pantalla; aquí les queda registrada la
  // única función de navegación que existe.
  const navigate = useNavigate();
  useEffect(() => registrarNavegador(navigate), [navigate]);

  return (
    <>
      <Routes>
        {/* La lista de intersecciones es la puerta de entrada. */}
        <Route path="/" element={<Proyectos />} />

        {/*
          El proyecto es el contenedor y las herramientas viven dentro.
          Cada una conserva su propia URL, así que el botón atrás
          funciona y se puede enlazar directo a la que importa.
        */}
        <Route path="/proyecto/:projectId" element={<Proyecto />}>
          <Route index element={<ProyectoResumen />} />
          <Route path="subir" element={<Subir />} />
          <Route path="calibrar" element={<Calibrar />} />
          <Route path="reporte" element={<Reporte />} />
          <Route path="camara" element={<ProyectoCamara />} />
          <Route path="registro" element={<ProyectoRegistro />} />
          <Route path="documentos" element={<ProyectoDocumentos />} />
        </Route>

        <Route path="/en-vivo" element={<EnVivo />} />
        <Route path="/documentos" element={<Documentos />} />
        <Route path="/comparar" element={<Comparar />} />

        {/* Rutas anteriores: había enlaces repartidos con ?project=, y
            romperlos no aporta nada. Se traducen a la forma nueva. */}
        <Route path="/subir" element={<RedirigirALaIntersección a="subir" />} />
        <Route path="/calibrar" element={<RedirigirALaIntersección a="calibrar" />} />
        <Route path="/reporte" element={<RedirigirALaIntersección a="reporte" />} />

        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>

      {/*
        `toast.custom` en avisos.tsx pone el aspecto; Sonner pone la
        mecánica. Abajo a la derecha para no tapar la navegación ni el
        contenido que se está leyendo, y siguiendo el tema elegido —
        Sonner arranca en claro y no mira la preferencia del sistema.
      */}
      <Toaster
        position="bottom-right"
        theme={theme}
        offset={24}
        mobileOffset={12}
        visibleToasts={4}
        gap={10}
      />
    </>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
