import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

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
import { RedirigirALaIntersección } from './pages/redirects';

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

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
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
          </Route>

          <Route path="/comparar" element={<Comparar />} />

          <Route path="/en-vivo" element={<EnVivo />} />

          {/* Rutas anteriores: había enlaces repartidos con ?project=, y
              romperlos no aporta nada. Se traducen a la forma nueva. */}
          <Route path="/subir" element={<RedirigirALaIntersección a="subir" />} />
          <Route path="/calibrar" element={<RedirigirALaIntersección a="calibrar" />} />
          <Route path="/reporte" element={<RedirigirALaIntersección a="reporte" />} />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
