/*
  Selector de proyecto compartido por subir / calibrar / reporte.

  Reemplaza el campo de texto libre que había antes: si alguien escribía
  el nombre distinto (mayúsculas, un acento, un guion), los datos se
  separaban en silencio. Con un selector eso no puede pasar.

  Respeta ?project=<id> en la URL para que los enlaces desde la página de
  proyectos abran ya con la intersección correcta seleccionada.
*/

async function loadProjectsInto(selectEl, { onChange, autoSelectFirst = false } = {}) {
  let projects = [];
  try {
    const res = await fetch('/api/projects');
    if (res.ok) projects = await res.json();
  } catch (e) { /* se reintenta cuando el usuario recargue */ }

  if (!projects.length) {
    selectEl.innerHTML = '<option value="">No hay proyectos — crea uno primero</option>';
    selectEl.disabled = true;
    return [];
  }

  selectEl.disabled = false;
  selectEl.innerHTML = '<option value="">Selecciona una intersección…</option>' +
    projects.map(p => `<option value="${p.id}">${p.name}</option>`).join('');

  const fromUrl = new URLSearchParams(location.search).get('project');
  if (fromUrl && projects.some(p => String(p.id) === fromUrl)) {
    selectEl.value = fromUrl;
  } else if (autoSelectFirst && projects.length === 1) {
    selectEl.value = String(projects[0].id);
  }

  // Mantiene la barra de navegación local en sincronía: al cambiar de
  // intersección, los pasos (Subir/Calibrar/Reporte) deben apuntar a la
  // nueva y el nombre mostrado debe actualizarse.
  const syncNav = () => {
    if (typeof syncNavProject !== 'function') return;
    const selected = projects.find(p => String(p.id) === selectEl.value);
    syncNavProject(selectEl.value, selected ? selected.name : null);
  };

  selectEl.addEventListener('change', syncNav);
  syncNav();

  if (onChange) {
    selectEl.addEventListener('change', onChange);
    if (selectEl.value) onChange();
  }
  return projects;
}
