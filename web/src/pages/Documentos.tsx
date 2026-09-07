/*
  Consultas sobre la normativa general.

  Aquí van los documentos que aplican a TODAS las intersecciones: la
  PT-914 del IMT, manuales de ingeniería de tránsito, criterios internos
  de la empresa. Lo específico de un estudio vive dentro de su proyecto.
*/

import { Page } from '../components/Page';
import { RagChat } from '../components/RagChat';

export default function Documentos() {
  return (
    <Page
      title="Documentos y consultas"
      subtitle="Pregunta sobre tu normativa y recibe la respuesta con su cita"
    >
      <RagChat />
    </Page>
  );
}
