/*
  Resumen de la intersección: en qué punto va el aforo, y las acciones
  que son del proyecto entero y no de una herramienta concreta.

  Recontar, copiar la calibración y borrar el proyecto vivían dentro de
  la página de calibrar, que ya pasaba de 700 líneas. No son parte de
  calibrar: son cosas que se le hacen al proyecto. Aquí tienen su sitio y
  calibrar recupera su trabajo, que es dibujar líneas.

  El orden va de "qué hago ahora" a "qué puedo cambiar" y termina en lo
  irreversible, que va aparte y al final.
*/

import { useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  Button,
  Card,
  ConfirmDialog,
  Notice,
  SelectField,
} from '../components/ui';
import { ProjectForm } from '../components/ProjectForm';
import { IconCheck } from '../components/Icons';
import {
  useCalibrationStatus,
  useCopyCalibration,
  useDeleteProject,
  useLanes,
  useProjects,
  useRecount,
  useUpdateProject,
} from '../lib/queries';
import { plural } from '../lib/format';
import type { Project } from '../lib/types';

/* --- Qué toca ahora ------------------------------------------------------
   Los mismos cuatro pasos que la guía, pero aquí en el contexto del
   proyecto y con el enlace a la herramienta que resuelve el paso. */

function Progreso({ p, base }: { p: Project; base: string }) {
  const pasos = [
    {
      titulo: 'Subir los videos',
      hecho: p.video_count > 0,
      detalle:
        p.video_count > 0
          ? plural(p.video_count, 'video subido', 'videos subidos')
          : 'Todavía no hay grabaciones.',
      a: `${base}/subir`,
      accion: 'Subir videos',
    },
    {
      titulo: 'Marcar los carriles',
      hecho: p.lane_count > 0,
      detalle:
        p.lane_count > 0
          ? plural(p.lane_count, 'carril definido', 'carriles definidos')
          : 'Sin líneas de conteo no hay nada que contar.',
      a: `${base}/calibrar`,
      accion: 'Calibrar',
    },
    {
      titulo: 'Contar',
      hecho: p.crossing_count > 0,
      detalle:
        p.crossing_count > 0
          ? plural(p.crossing_count, 'cruce registrado', 'cruces registrados')
          : 'El conteo arranca desde Calibrar, con los carriles ya puestos.',
      a: `${base}/calibrar`,
      accion: 'Ir a calibrar',
    },
    {
      titulo: 'Leer el reporte',
      hecho: p.crossing_count > 0,
      detalle: 'Volumen por intervalo, hora de máxima demanda y FHP.',
      a: `${base}/reporte`,
      accion: 'Ver reporte',
    },
  ];

  const siguiente = pasos.findIndex((s) => !s.hecho);

  return (
    <Card className="proj-progress">
      <h3 className="section-title">Avance del aforo</h3>
      <ol className="pp-list">
        {pasos.map((s, i) => {
          const actual = i === siguiente;
          return (
            <li key={s.titulo} className={`pp-step${s.hecho ? ' done' : ''}${actual ? ' current' : ''}`}>
              {/* El paso hecho se marca con palomita y tachado, no solo
                  con color. */}
              <span className={`pp-mark${s.hecho ? ' done' : actual ? ' current' : ''}`}>
                {s.hecho && <IconCheck size={12} />}
              </span>
              <div className="pp-text">
                <span className="pp-title">{s.titulo}</span>
                <span className="pp-detail">{s.detalle}</span>
              </div>
              {actual && (
                <Link className="btn btn-primary pp-action" to={s.a}>
                  {s.accion}
                </Link>
              )}
            </li>
          );
        })}
      </ol>
    </Card>
  );
}

/* --- Página --------------------------------------------------------------- */

export default function ProyectoResumen() {
  const { projectId } = useParams();
  const navigate = useNavigate();
  const id = Number(projectId);

  const { data: projects } = useProjects();
  const project = projects?.find((p) => p.id === id) ?? null;

  const { data: lanes } = useLanes(id);
  const { data: calib } = useCalibrationStatus(id);
  const actualizar = useUpdateProject(id);
  const borrar = useDeleteProject();
  const recontar = useRecount();
  const copiar = useCopyCalibration(id);

  const [editando, setEditando] = useState(false);
  const [origen, setOrigen] = useState<number | ''>('');
  const [confirmarBorrado, setConfirmarBorrado] = useState(false);
  const [confirmarReconteo, setConfirmarReconteo] = useState(false);

  if (!project) return null;
  const base = `/proyecto/${project.id}`;

  // Solo tiene sentido copiar de una intersección que ya tenga carriles.
  const candidatas = (projects ?? []).filter((p) => p.id !== id && p.lane_count > 0);

  if (editando) {
    return (
      <ProjectForm
        project={project}
        titulo="Editar la intersección"
        etiquetaEnviar="Guardar cambios"
        enviando={actualizar.isPending}
        error={actualizar.isError ? actualizar.error : null}
        onCancel={() => setEditando(false)}
        onSubmit={async (data) => {
          await actualizar.mutateAsync(data);
          setEditando(false);
        }}
      />
    );
  }

  return (
    <div className="proj-resumen">
      <Progreso p={project} base={base} />

      {/* Aviso de calibración desfasada: editar las líneas después de
          contar no cambia los cruces ya guardados, y sin este aviso no
          había forma de notarlo. */}
      {calib && calib.stale > 0 && (
        <Notice tone="warning" title="Los conteos son de una calibración anterior">
          {plural(calib.stale, 'video se contó', 'videos se contaron')} con líneas distintas a las
          de ahora. Vuelve a contar para que todo el aforo salga de la misma calibración.{' '}
          <Button
            variant="primary"
            disabled={recontar.isPending}
            onClick={() => setConfirmarReconteo(true)}
            style={{ marginInlineStart: 'var(--space-2)' }}
          >
            {recontar.isPending ? 'Encolando…' : 'Volver a contar'}
          </Button>
        </Notice>
      )}

      <div className="proj-tools-grid">
        {/* --- Datos de la intersección --- */}
        <Card className="proj-tool-card">
          <h3 className="section-title">Datos de la intersección</h3>
          <dl className="proj-dl">
            <div>
              <dt>Nombre</dt>
              <dd>{project.name}</dd>
            </div>
            <div>
              <dt>Ubicación</dt>
              <dd>
                {project.address ?? 'Sin definir'}
                {project.latitude !== null && project.longitude !== null && (
                  <span className="mono proj-coords">
                    {project.latitude.toFixed(5)}, {project.longitude.toFixed(5)}
                  </span>
                )}
              </dd>
            </div>
            <div>
              <dt>Intervalo</dt>
              <dd>{project.interval_minutes} minutos</dd>
            </div>
            <div>
              <dt>Notas</dt>
              <dd>{project.description || 'Sin notas'}</dd>
            </div>
          </dl>
          <Button variant="primary" onClick={() => setEditando(true)}>
            Editar nombre y ubicación
          </Button>
        </Card>

        {/* --- Reutilizar calibración --- */}
        <Card className="proj-tool-card">
          <h3 className="section-title">Reutilizar una calibración</h3>
          <p className="ptc-body">
            La cámara de un punto de medición no se mueve entre grabaciones, así que la calibración
            suele ser la misma sesión tras sesión. Copiar los carriles de otra intersección evita
            volver a dibujarlos a mano.
          </p>
          {candidatas.length === 0 ? (
            <p className="ptc-empty">
              Ninguna otra intersección tiene carriles todavía. Cuando calibres una segunda, podrás
              copiar entre ellas.
            </p>
          ) : (
            <>
              <SelectField
                label="Copiar carriles desde"
                value={origen}
                onChange={(e) => setOrigen(e.target.value ? Number(e.target.value) : '')}
              >
                <option value="">Elige una intersección…</option>
                {candidatas.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name} — {plural(p.lane_count, 'carril', 'carriles')}
                  </option>
                ))}
              </SelectField>
              <Button
                disabled={origen === '' || copiar.isPending}
                onClick={() => origen !== '' && copiar.mutate(origen)}
                style={{ marginTop: 'var(--space-3)' }}
              >
                {copiar.isPending ? 'Copiando…' : 'Copiar calibración'}
              </Button>
              {(lanes?.length ?? 0) > 0 && (
                <p className="ptc-empty" style={{ marginTop: 'var(--space-2)' }}>
                  Esta intersección ya tiene {plural(lanes!.length, 'carril', 'carriles')}. Copiar
                  añade los de la otra encima de los que ya hay.
                </p>
              )}
            </>
          )}
        </Card>

        {/* --- Volver a contar --- */}
        <Card className="proj-tool-card">
          <h3 className="section-title">Volver a contar</h3>
          <p className="ptc-body">
            Reprocesa todos los videos ya terminados con la calibración actual. Los cruces
            anteriores de cada video se reemplazan, no se suman, así que el aforo no se duplica.
          </p>
          <p className="ptc-empty">
            {calib?.calibrated_at
              ? `Calibración actual del ${calib.calibrated_at.slice(0, 16).replace('T', ' ')}.`
              : 'Esta intersección todavía no tiene calibración.'}
          </p>
          <Button
            disabled={recontar.isPending || (project.lane_count === 0)}
            onClick={() => setConfirmarReconteo(true)}
            style={{ marginTop: 'var(--space-3)' }}
          >
            {recontar.isPending ? 'Encolando…' : 'Volver a contar todo'}
          </Button>
        </Card>

        {/* --- Zona irreversible ---
            Va aparte y al final, con su propio tratamiento: mezclarla
            con las demás acciones invita al clic por error. */}
        <Card className="proj-tool-card proj-danger">
          <h3 className="section-title">Borrar la intersección</h3>
          <p className="ptc-body">
            Se borran sus videos, sus carriles, sus zonas y todos sus conteos. El histórico
            acumulado de este punto de medición se pierde.
          </p>
          <Button variant="danger" onClick={() => setConfirmarBorrado(true)}>
            Borrar esta intersección
          </Button>
        </Card>
      </div>

      <ConfirmDialog
        open={confirmarReconteo}
        title="¿Volver a contar todo?"
        body={`Se reprocesan los ${project.video_count} videos de "${project.name}" con la calibración actual. Los conteos anteriores se reemplazan. Puede tardar un buen rato.`}
        confirmLabel="Volver a contar"
        onConfirm={() => {
          recontar.mutate(id);
          setConfirmarReconteo(false);
        }}
        onCancel={() => setConfirmarReconteo(false)}
      />

      <ConfirmDialog
        open={confirmarBorrado}
        title="¿Borrar esta intersección?"
        body={`Se borra "${project.name}" con sus ${project.video_count} videos y sus ${project.crossing_count} cruces registrados. Esta acción no se puede deshacer.`}
        confirmLabel="Borrar intersección"
        destructive
        onConfirm={async () => {
          setConfirmarBorrado(false);
          await borrar.mutateAsync(id);
          navigate('/');
        }}
        onCancel={() => setConfirmarBorrado(false)}
      />
    </div>
  );
}
