/*
  Kit de componentes básicos.

  Todos son elementos nativos con estilo, no reconstrucciones: <button>,
  <input>, <select>, <dialog>. Eso les da gratis el soporte de teclado, el
  anuncio correcto en lector de pantalla y el comportamiento de formulario
  que una versión hecha con <div> habría que reimplementar (y romper).
*/

import {
  useEffect,
  useId,
  useRef,
  type ButtonHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
  type InputHTMLAttributes,
  type Ref,
} from 'react';
import { IconAlert, IconCheck, IconClose, IconInfo } from './Icons';
import type { Tone } from '../lib/format';

const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(' ');

/* --- Botón -------------------------------------------------------------- */

type ButtonVariant = 'primary' | 'secondary' | 'danger';

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  block?: boolean;
}

export function Button({ variant = 'secondary', block, className, ...rest }: ButtonProps) {
  return (
    <button
      type="button"
      className={cx('btn', `btn-${variant}`, block && 'btn-block', className)}
      {...rest}
    />
  );
}

/*
  Botón de solo icono. `label` es obligatorio: sin él el control no tiene
  nombre accesible y para un lector de pantalla es un botón anónimo.
  Al ser un parámetro requerido del tipo, no se puede olvidar.
*/
interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  label: string;
  tone?: 'default' | 'danger' | 'accent';
}

export function IconButton({ label, tone = 'default', className, ...rest }: IconButtonProps) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cx(
        'btn-icon',
        tone === 'danger' && 'is-danger',
        tone === 'accent' && 'is-accent',
        className,
      )}
      {...rest}
    />
  );
}

/* --- Campos ------------------------------------------------------------- */

interface FieldShellProps {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  narrow?: boolean;
  className?: string;
  children: (ids: { inputId: string; describedBy: string | undefined }) => ReactNode;
}

/*
  Etiqueta, control, pista y error atados entre sí. El error se anuncia por
  `aria-describedby` y va pegado al campo que falló, no al final del
  formulario: quien usa lector de pantalla lo escucha al llegar al campo.
*/
export function FieldShell({ label, hint, error, narrow, className, children }: FieldShellProps) {
  const inputId = useId();
  const hintId = `${inputId}-hint`;
  const errorId = `${inputId}-error`;
  const describedBy = [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(' ');

  return (
    <div className={cx('field', narrow && 'field-narrow', className)}>
      <label className="field-label" htmlFor={inputId}>
        {label}
      </label>
      {children({ inputId, describedBy: describedBy || undefined })}
      {hint && (
        <span className="field-hint" id={hintId}>
          {hint}
        </span>
      )}
      {error && (
        <span className="field-error" id={errorId}>
          <IconAlert size={13} />
          {error}
        </span>
      )}
    </div>
  );
}

interface TextFieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'id'> {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  narrow?: boolean;
  wrapClassName?: string;
  /* En React 19 `ref` es una prop normal de los componentes de función,
     así que no hace falta forwardRef para poder enfocar el campo que
     falló al enviar. */
  ref?: Ref<HTMLInputElement>;
}

export function TextField({
  label,
  hint,
  error,
  narrow,
  wrapClassName,
  ...rest
}: TextFieldProps) {
  return (
    <FieldShell label={label} hint={hint} error={error} narrow={narrow} className={wrapClassName}>
      {({ inputId, describedBy }) => (
        <input
          id={inputId}
          type="text"
          aria-describedby={describedBy}
          aria-invalid={error ? true : undefined}
          {...rest}
        />
      )}
    </FieldShell>
  );
}

interface SelectFieldProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'id'> {
  label: string;
  hint?: ReactNode;
  error?: string | null;
  narrow?: boolean;
  children: ReactNode;
}

export function SelectField({
  label,
  hint,
  error,
  narrow,
  children,
  ...rest
}: SelectFieldProps) {
  return (
    <FieldShell label={label} hint={hint} error={error} narrow={narrow}>
      {({ inputId, describedBy }) => (
        <select
          id={inputId}
          aria-describedby={describedBy}
          aria-invalid={error ? true : undefined}
          {...rest}
        >
          {children}
        </select>
      )}
    </FieldShell>
  );
}

/* --- Pill de estado ------------------------------------------------------ */

interface PillProps {
  tone?: Tone;
  dot?: boolean;
  live?: boolean;
  children: ReactNode;
}

export function Pill({ tone = 'neutral', dot, live, children }: PillProps) {
  return (
    <span className={cx('pill', tone !== 'neutral' && `tone-${tone}`, live && 'is-live')}>
      {dot && <span className="dot" />}
      {children}
    </span>
  );
}

/* --- Tarjeta ------------------------------------------------------------- */

export function Card({
  accent,
  className,
  children,
  ...rest
}: { accent?: boolean } & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={cx('card', accent && 'card-accent', className)} {...rest}>
      {children}
    </div>
  );
}

/* --- Estado vacío --------------------------------------------------------
   Dice qué es este lugar, cómo se llena y ofrece un siguiente paso. Un
   "sin datos" a secas deja al usuario sin saber qué hacer. */

export function EmptyState({
  title,
  body,
  action,
}: {
  title: string;
  body?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty-state">
      <div className="es-title">{title}</div>
      {body && <p className="es-body">{body}</p>}
      {action && <div className="es-action">{action}</div>}
    </div>
  );
}

/* --- Aviso en línea ------------------------------------------------------
   Reemplaza a `alert()`. El nativo saca al usuario de la página, no se
   puede leer junto a lo que falló y no ofrece ninguna salida. */

export function Notice({
  tone = 'critical',
  title,
  children,
  onDismiss,
}: {
  tone?: 'critical' | 'warning' | 'info' | 'good';
  title?: string;
  children: ReactNode;
  onDismiss?: () => void;
}) {
  const Icon = tone === 'good' ? IconCheck : tone === 'info' ? IconInfo : IconAlert;
  return (
    <div
      className={cx('notice', `notice-${tone}`)}
      // Un error necesita interrumpir; un aviso informativo, no.
      role={tone === 'critical' ? 'alert' : 'status'}
    >
      <Icon size={16} />
      <div className="notice-body">
        {title && <div className="notice-title">{title}</div>}
        <div>{children}</div>
      </div>
      {onDismiss && (
        <IconButton
          label="Descartar aviso"
          onClick={onDismiss}
          style={{ marginInlineStart: 'auto', color: 'inherit' }}
        >
          <IconClose size={15} />
        </IconButton>
      )}
    </div>
  );
}

/* --- Diálogo de confirmación --------------------------------------------
   Reemplaza a `confirm()`. Usa <dialog> nativo, que ya trae la retención
   del foco, el cierre con Escape y el fondo inerte. */

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  destructive,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  body: ReactNode;
  confirmLabel: string;
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (open && !el.open) el.showModal();
    if (!open && el.open) el.close();
  }, [open]);

  // Escape cierra el diálogo nativo por su cuenta; hay que enterarse para
  // que el estado de React no quede pensando que sigue abierto.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const onClose = () => onCancel();
    el.addEventListener('close', onClose);
    return () => el.removeEventListener('close', onClose);
  }, [onCancel]);

  return (
    <dialog ref={ref} className="dialog" aria-labelledby="confirm-title">
      <h2 id="confirm-title">{title}</h2>
      <p>{body}</p>
      <div className="dialog-actions">
        <Button onClick={onCancel}>Cancelar</Button>
        {/* La etiqueta repite la consecuencia, para poder responder sin
            releer el cuerpo del diálogo. */}
        <Button variant={destructive ? 'danger' : 'primary'} onClick={onConfirm}>
          {confirmLabel}
        </Button>
      </div>
    </dialog>
  );
}

/* --- Región de anuncios --------------------------------------------------
   Región educada y estable: se monta vacía y solo cambia su texto. Si se
   creara en el momento del mensaje, muchos lectores de pantalla no lo
   anunciarían. */

export function LiveMessage({ children }: { children?: ReactNode }) {
  return (
    <div role="status" aria-live="polite" className="visually-hidden">
      {children}
    </div>
  );
}
