import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import './styles/tokens.css';
import './styles/base.css';
import './styles/components.css';
import './styles/layout.css';
import './styles/pages.css';

import Proyectos from './pages/Proyectos';
import Subir from './pages/Subir';
import Calibrar from './pages/Calibrar';
import Reporte from './pages/Reporte';
import EnVivo from './pages/EnVivo';

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
          {/* Los proyectos son la puerta de entrada: subir, calibrar y
              reportar necesitan una intersección elegida. */}
          <Route path="/" element={<Proyectos />} />
          <Route path="/subir" element={<Subir />} />
          <Route path="/calibrar" element={<Calibrar />} />
          <Route path="/reporte" element={<Reporte />} />
          <Route path="/en-vivo" element={<EnVivo />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
