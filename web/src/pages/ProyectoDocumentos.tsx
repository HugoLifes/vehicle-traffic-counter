/*
  Consultas sobre los documentos de UNA intersección.

  Mismo chat que la vista general, acotado al proyecto: aquí se suben el
  proyecto ejecutivo, los requisitos del cliente, los oficios. Las
  respuestas usan esos documentos MÁS la normativa general, porque un
  requisito particular casi siempre se lee contra la norma que lo respalda.
*/

import { useParams } from 'react-router-dom';
import { RagChat } from '../components/RagChat';

export default function ProyectoDocumentos() {
  const { projectId } = useParams();
  const id = Number(projectId);
  if (!id) return null;
  return <RagChat projectId={id} />;
}
