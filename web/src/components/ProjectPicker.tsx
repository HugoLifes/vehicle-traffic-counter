/*
  Selector de intersección, compartido por subir / calibrar / reporte.

  Reemplaza al campo de texto libre que había antes: si alguien escribía
  el nombre distinto (una mayúscula, un acento, un guion), los datos se
  separaban en silencio en dos aforos que parecían el mismo. Con un
  selector eso no puede pasar.
*/

import { SelectField } from './ui';
import type { Project } from '../lib/types';

interface Props {
  projects: Project[];
  value: number | null;
  onChange: (id: number | null) => void;
  hint?: React.ReactNode;
  error?: string | null;
}

export function ProjectPicker({ projects, value, onChange, hint, error }: Props) {
  const empty = projects.length === 0;

  return (
    <SelectField
      label="Intersección"
      hint={hint}
      error={error}
      value={value === null ? '' : String(value)}
      disabled={empty}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
    >
      {empty ? (
        <option value="">Todavía no hay intersecciones</option>
      ) : (
        <>
          <option value="">Selecciona una intersección…</option>
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </>
      )}
    </SelectField>
  );
}
