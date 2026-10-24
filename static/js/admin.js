/* ============================================================
   admin.js — S.I.P.A. · GNA 2026
   Plana Mayor: Monitor táctico, KPIs, grid de aulas, reportes
   ============================================================ */
'use strict';

let _monitorInterval = null;   // Autorefresh cada 60s
let _aulasDiaInterval = null;
let _aulasDiaCargando = false;
let _aulasDiaRecargar = false;

let _catalogoAulasTimer = null;

async function guardarFilaCatalogo(button) {
    const row = button.closest('tr');
    if (!row) return;
    const payload = {
        aula_original: row.dataset.aulaOriginal,
        turno_original: row.dataset.turnoOriginal,
        aula: row.querySelector('.cat-aula')?.value.trim().toUpperCase(),
        turno: row.querySelector('.cat-turno')?.value,
        nombre: row.querySelector('.cat-nombre')?.value.trim(),
        anio: row.querySelector('.cat-anio')?.value.trim(),
        especialidad: row.querySelector('.cat-especialidad')?.value.trim(),
        curso: row.querySelector('.cat-curso')?.value.trim(),
    };
    if (!payload.aula || !payload.turno || !payload.nombre) {
        return mostrarToast('Aula, turno y nombre son obligatorios.', 'warning');
    }
    button.disabled = true;
    try {
        const r = await fetch('/api/aulas_catalogo', {
            method: 'PUT',
            headers: {'Content-Type': 'application/json', 'X-SU-Token': window.SIPA.suToken || ''},
            body: JSON.stringify(payload),
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || 'No se pudo guardar el aula');
        mostrarToast('✅ Aula actualizada.', 'success');
        cargarCatalogoAulas();
    } catch (e) {
        mostrarToast(e.message, 'error');
    } finally {
        button.disabled = false;
    }
}

async function cargarCatalogoAulas() {
    const body = document.getElementById('body-catalogo-aulas');
    if (!body) return;
    clearTimeout(_catalogoAulasTimer);
    _catalogoAulasTimer = setTimeout(async () => {
        const turno = document.getElementById('catalogo-turno')?.value || '';
        const q = document.getElementById('catalogo-busqueda')?.value.trim() || '';
        body.innerHTML = '<tr><td colspan="7">Cargando…</td></tr>';
        try {
            const r = await fetch(`/api/aulas_catalogo?turno=${encodeURIComponent(turno)}&q=${encodeURIComponent(q)}`);
            const datos = await r.json();
            if (!r.ok) throw new Error(datos.error || 'No se pudo cargar el catálogo');
            body.innerHTML = datos.length ? datos.map(a => `
                <tr data-aula-original="${escapeHTML(a.aula)}" data-turno-original="${escapeHTML(a.turno)}">
                    <td><select class="cat-turno">
                        <option value="TM" ${a.turno === 'TM' ? 'selected' : ''}>TM</option>
                        <option value="TT" ${a.turno === 'TT' ? 'selected' : ''}>TT</option>
                    </select></td>
                    <td><input class="cat-aula" value="${escapeHTML(a.aula)}" maxlength="50"></td>
                    <td><input class="cat-nombre" value="${escapeHTML(a.nombre)}" maxlength="150"></td>
                    <td><input class="cat-anio" value="${escapeHTML(a.anio)}" maxlength="20"></td>
                    <td><input class="cat-especialidad" value="${escapeHTML(a.especialidad)}" maxlength="150"></td>
                    <td><input class="cat-curso" value="${escapeHTML(a.curso)}" maxlength="150"></td>
                    <td><button class="btn btn-success btn-small" onclick="guardarFilaCatalogo(this)">💾 Guardar</button></td>
                </tr>`).join('') :
                '<tr><td colspan="7">No hay aulas que coincidan.</td></tr>';
        } catch (e) {
            body.innerHTML = `<tr><td colspan="7">❌ ${escapeHTML(e.message)}</td></tr>`;
        }
    }, 180);
}

// ══════════════════════════════════════════════════════════════
// BÚSQUEDA GLOBAL Ctrl+K — Bloque TIC 1
// ══════════════════════════════════════════════════════════════
let _searchDebounce = null;
let _searchIndex = 0;
let _searchResultados = [];

function abrirBusquedaGlobal() {
    const overlay = document.getElementById('search-global-overlay');
    if (!overlay) return;
    overlay.style.display = 'flex';
    const input = document.getElementById('search-global-input');
    if (input) { input.value = ''; setTimeout(() => input.focus(), 50); }
    _searchIndex = 0;
    _searchResultados = [];
    renderHintBusqueda();
}

function cerrarBusquedaGlobal() {
    const overlay = document.getElementById('search-global-overlay');
    if (overlay) overlay.style.display = 'none';
}

function renderHintBusqueda() {
    const cont = document.getElementById('search-global-results');
    if (!cont) return;
    cont.innerHTML = `
        <div class="search-global-hint">
            <div style="font-size:1.4em;margin-bottom:8px;">⚡</div>
            <div>Escribí al menos 2 caracteres para buscar.</div>
            <div style="margin-top:18px;font-size:.85em;color:var(--texto-tenue);">
                <kbd>↑↓</kbd> navegar · <kbd>Enter</kbd> abrir · <kbd>Esc</kbd> cerrar
            </div>
        </div>`;
}

async function ejecutarBusquedaGlobal(q) {
    if (!window.SIPA?.suToken) {
        document.getElementById('search-global-results').innerHTML =
            '<div class="search-global-empty">⚠️ Requiere autenticación de TIC.</div>';
        return;
    }
    if (q.length < 2) { renderHintBusqueda(); return; }
    try {
        const r = await fetch(`/api/su/buscar_global?q=${encodeURIComponent(q)}`,
                              { headers: { 'X-SU-Token': window.SIPA.suToken } });
        const d = await r.json();
        _searchResultados = d.resultados || [];
        _searchIndex = 0;
        renderResultadosBusqueda();
    } catch (e) {
        document.getElementById('search-global-results').innerHTML =
            `<div class="search-global-empty">❌ ${e.message}</div>`;
    }
}

function renderResultadosBusqueda() {
    const cont = document.getElementById('search-global-results');
    if (!cont) return;
    if (!_searchResultados.length) {
        cont.innerHTML = '<div class="search-global-empty">🔎 Sin resultados.</div>';
        return;
    }
    // Agrupar por tipo
    const grupos = {};
    _searchResultados.forEach((r, idx) => {
        const g = r.tipo;
        if (!grupos[g]) grupos[g] = [];
        grupos[g].push({ ...r, _idx: idx });
    });
    const labelGrupo = {
        'docente':            '👨‍🏫 Docentes registrados',
        'docente-cronograma': '📋 Docentes en cronograma',
        'aula':               '🏫 Aulas',
        'justif':             '📋 Justificaciones',
        'minuta':             '📝 Minutas',
        'audit':              '📜 Auditoría',
    };
    const orden = ['docente','docente-cronograma','aula','justif','minuta','audit'];
    let html = '';
    orden.forEach(tipo => {
        if (!grupos[tipo]) return;
        html += `<div class="search-global-group">
            <div class="search-global-group-title">${labelGrupo[tipo] || tipo}</div>`;
        grupos[tipo].forEach(r => {
            const cls = r._idx === _searchIndex ? 'active' : '';
            html += `<div class="search-global-item ${cls}" data-idx="${r._idx}"
                          onclick="ejecutarAccionBusqueda(${r._idx})">
                <span class="search-global-item-icon">${r.icono}</span>
                <div class="search-global-item-text">
                    <div class="search-global-item-title">${escapeHTML(r.titulo)}</div>
                    <div class="search-global-item-sub">${escapeHTML(r.subtitulo)}</div>
                </div>
                <span class="search-global-item-arrow">→</span>
            </div>`;
        });
        html += '</div>';
    });
    cont.innerHTML = html;
    // Scroll al activo
    const act = cont.querySelector('.search-global-item.active');
    if (act) act.scrollIntoView({ block: 'nearest' });
}

function escapeHTML(s) {
    if (s == null) return '';
    return String(s).replace(/[&<>"']/g, c => ({
        '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'
    })[c]);
}

function ejecutarAccionBusqueda(idx) {
    const r = _searchResultados[idx];
    if (!r) return;
    cerrarBusquedaGlobal();
    try {
        // Ejecutar la acción como JS
        if (r.accion) new Function(r.accion)();
    } catch (e) {
        console.warn('Acción de búsqueda falló:', e);
        mostrarToast('No se pudo abrir el resultado.', 'warning');
    }
}

function bindBusquedaGlobalEventos() {
    // Atajo global Ctrl+K
    document.addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') {
            e.preventDefault();
            abrirBusquedaGlobal();
        }
    });
    // Eventos del overlay
    const overlay = document.getElementById('search-global-overlay');
    const input   = document.getElementById('search-global-input');
    if (overlay) overlay.addEventListener('click', cerrarBusquedaGlobal);
    if (input) {
        input.addEventListener('input', () => {
            clearTimeout(_searchDebounce);
            _searchDebounce = setTimeout(() => ejecutarBusquedaGlobal(input.value.trim()), 220);
        });
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') { cerrarBusquedaGlobal(); return; }
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                if (_searchResultados.length) {
                    _searchIndex = Math.min(_searchIndex + 1, _searchResultados.length - 1);
                    renderResultadosBusqueda();
                }
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                if (_searchResultados.length) {
                    _searchIndex = Math.max(_searchIndex - 1, 0);
                    renderResultadosBusqueda();
                }
            } else if (e.key === 'Enter') {
                e.preventDefault();
                if (_searchResultados.length) ejecutarAccionBusqueda(_searchIndex);
            }
        });
    }
}
document.addEventListener('DOMContentLoaded', bindBusquedaGlobalEventos);

// Helpers de acción que la búsqueda puede llamar
function abrirPerfilDocente(nombre) {
    // Cambia a la sub-tab de Cuentas Admin (donde están los docentes)
    if (typeof mostrarCfgTab === 'function') {
        const btn = document.querySelector('[onclick*="cfg-cuentas"]');
        if (btn) mostrarCfgTab('cfg-cuentas', btn);
    }
    mostrarToast(`👨‍🏫 ${nombre}`, 'info');
}
function abrirAulaDetalle(aula, turno) {
    if (typeof mostrarCfgTab === 'function') {
        const btn = document.querySelector('[onclick*="cfg-cronograma"]');
        if (btn) mostrarCfgTab('cfg-cronograma', btn);
    }
    mostrarToast(`🏫 Aula ${aula} (${turno})`, 'info');
}
function abrirAuditoriaInasistencias() {
    if (typeof mostrarCfgTab === 'function') {
        const btn = document.querySelector('[onclick*="cfg-auditoria"]');
        if (btn) mostrarCfgTab('cfg-auditoria', btn);
    }
}

// ══════════════════════════════════════════════════════════════
// SESIONES ACTIVAS — Bloque TIC 2
// ══════════════════════════════════════════════════════════════
let _sesionesInterval = null;

async function cargarSesionesActivas() {
    if (!window.SIPA?.suToken) return;
    try {
        const r = await fetch('/api/su/sesiones_activas',
                              { headers: { 'X-SU-Token': window.SIPA.suToken } });
        const d = await r.json();
        renderSesionesStats(d.stats || {}, d.total);
        renderSesionesTabla(d.sesiones || []);
    } catch (e) {
        const cont = document.getElementById('ses-tabla');
        if (cont) cont.innerHTML = `<div class="bd-error-banner">❌ ${e.message}</div>`;
    }
}

function renderSesionesStats(stats, total) {
    const cont = document.getElementById('ses-stats');
    if (!cont) return;
    const tipos = [
        { rol: 'super_usuario', label: 'TIC',         ico: '🛡️',   color: '#dc2626' },
        { rol: 'plana_mayor',   label: 'Plana Mayor', ico: '🎖️',   color: '#0ea5e9' },
        { rol: 'bedel',         label: 'Bedeles',     ico: '📝',   color: '#f59e0b' },
        { rol: 'docente',       label: 'Docentes',    ico: '👨‍🏫', color: '#16a34a' },
    ];
    cont.innerHTML = tipos.map(t => `
        <div class="card" style="text-align:center;padding:12px;border-top:3px solid ${t.color};margin:0;">
            <div style="font-size:1.5em;">${t.ico}</div>
            <div style="font-size:.74em;color:var(--texto-suave);margin-top:4px;">${t.label.toUpperCase()}</div>
            <div style="font-size:1.7em;font-weight:800;color:${t.color};font-family:'Barlow Condensed';">${stats[t.rol] || 0}</div>
        </div>
    `).join('');
}

function renderSesionesTabla(sesiones) {
    const cont = document.getElementById('ses-tabla');
    if (!cont) return;
    if (!sesiones.length) {
        cont.innerHTML = '<div class="empty-state"><span class="empty-state-icon">😴</span><span class="empty-state-text">Nadie está conectado ahora mismo.</span></div>';
        return;
    }
    const roleLabel = (rol) => ({
        'super_usuario': '🛡️ TIC',
        'plana_mayor':   '🎖️ Plana Mayor',
        'bedel':         '📝 Bedel',
        'docente':       '👨‍🏫 Docente',
    }[rol] || rol);
    const formatTiempo = (seg) => {
        if (seg < 60)   return `hace ${seg}s`;
        if (seg < 3600) return `hace ${Math.floor(seg/60)} min`;
        return `hace ${Math.floor(seg/3600)}h ${Math.floor((seg%3600)/60)}m`;
    };
    const iconoActividad = (seg) => {
        if (seg < 60)   return '🟢';
        if (seg < 300)  return '🟡';
        return '⚪';
    };
    const html = `
        <div class="table-responsive">
        <table>
            <thead><tr>
                <th>Estado</th>
                <th>Rol</th>
                <th>Usuario</th>
                <th>IP</th>
                <th>Activo</th>
                <th>Última actividad</th>
                <th>Acción</th>
            </tr></thead>
            <tbody>
            ${sesiones.map(s => `
                <tr>
                    <td style="font-size:1.2em;text-align:center;">${iconoActividad(s.segundos_ultimo)}</td>
                    <td><b>${roleLabel(s.rol)}</b></td>
                    <td>${escapeHTML(s.usuario)}</td>
                    <td><code style="font-size:.84em;">${escapeHTML(s.ip)}</code></td>
                    <td style="white-space:nowrap;">${s.minutos_activo} min</td>
                    <td style="white-space:nowrap;color:var(--texto-suave);">${formatTiempo(s.segundos_ultimo)}</td>
                    <td>
                        ${s.token_full ? `<button class="btn btn-small" style="background:#dc2626;color:white;padding:4px 10px;" onclick="forzarLogoutSesion('${s.token_full}','${escapeHTML(s.usuario)}')">🚪 Cerrar</button>` : '<span style="color:var(--texto-tenue);font-size:.85em;">—</span>'}
                    </td>
                </tr>
            `).join('')}
            </tbody>
        </table>
        </div>`;
    cont.innerHTML = html;
}

async function forzarLogoutSesion(token, usuario) {
    if (!confirm(`¿Forzar el cierre de la sesión de ${usuario}?\n\nEl usuario será desconectado al próximo intento de acción.`)) return;
    try {
        const r = await fetch('/api/su/forzar_logout', {
            method:'POST',
            headers:{ 'Content-Type':'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify({ token }),
        });
        const d = await r.json();
        if (d.ok) {
            mostrarToast(`✅ ${d.msj}`, 'success');
            cargarSesionesActivas();
        } else {
            mostrarToast(`❌ ${d.error}`, 'error');
        }
    } catch (e) {
        mostrarToast(`❌ ${e.message}`, 'error');
    }
}

function toggleSesionesAuto(on) {
    if (_sesionesInterval) { clearInterval(_sesionesInterval); _sesionesInterval = null; }
    if (on) {
        _sesionesInterval = setInterval(cargarSesionesActivas, 30000);
    }
}

// ══════════════════════════════════════════════════════════════
// LIMPIEZA — Bloque TIC 3
// ══════════════════════════════════════════════════════════════
async function analizarSaludDB() {
    if (!window.SIPA?.suToken) return mostrarToast('Requiere TIC.', 'warning');
    mostrarToast('🔍 Analizando base de datos...', 'info');
    try {
        const [rd, rh, rv] = await Promise.all([
            fetch('/api/su/duplicados', { headers: { 'X-SU-Token': window.SIPA.suToken } }).then(r => r.json()),
            fetch('/api/su/huerfanos',  { headers: { 'X-SU-Token': window.SIPA.suToken } }).then(r => r.json()),
            fetch('/api/su/vinculaciones_docentes', { headers: { 'X-SU-Token': window.SIPA.suToken } }).then(r => r.json()),
        ]);
        if (rd.error || rh.error || rv.error) throw new Error(rd.error || rh.error || rv.error);
        renderDuplicados(rd);
        renderHuerfanos(rh);
        renderVinculacionesDocentes(rv);
        mostrarToast('✅ Análisis completo', 'success');
    } catch (e) {
        mostrarToast(`❌ ${e.message}`, 'error');
    }
}

function renderVinculacionesDocentes(datos) {
    const cont = document.getElementById('vinc-docentes-resultados');
    if (!cont) return;
    const grupos = Array.isArray(datos.sin_cuenta) ? datos.sin_cuenta : [];
    const cuentas = Array.isArray(datos.cuentas) ? datos.cuentas : [];
    const seguras = Array.isArray(datos.auto_vinculables) ? datos.auto_vinculables : [];
    const cuentasHtml = cuentas.length ? `<details style="margin-top:14px;">
        <summary style="cursor:pointer;font-weight:700;color:#4338ca;">👥 Ver aulas y horarios vinculados por cuenta (${cuentas.length})</summary>
        <div style="display:grid;gap:8px;margin-top:10px;">${cuentas.map(cuenta => `
            <details class="card" style="margin:0;padding:10px;">
                <summary style="cursor:pointer;"><b>${escapeHTML(cuenta.nombre)}</b> · DNI ${escapeHTML(cuenta.dni || '—')} · ${escapeHTML(cuenta.email || '—')} · ${(cuenta.aulas_vinculadas || []).length} bloque(s)</summary>
                <ul style="margin:8px 0 0;padding-left:22px;">${(cuenta.aulas_vinculadas || []).map(b => `
                    <li>${b.ambiguo ? '⚠️ Posible homónimo · ' : ''}<b>Aula ${escapeHTML(b.aula)} (${escapeHTML(b.turno)})</b> · ${escapeHTML(b.dia)} ${escapeHTML(b.hora)} · ${escapeHTML(b.materia)}</li>`).join('') || '<li>Sin clases asociadas en el cronograma.</li>'}</ul>
            </details>`).join('')}</div>
    </details>` : '';

    if (!grupos.length) {
        cont.innerHTML = '<div class="bd-ok-banner">✅ Todos los nombres del cronograma están vinculados a una cuenta docente titular.</div>' + cuentasHtml;
        return;
    }

    const segurasHtml = seguras.length ? `
        <section class="card" style="border-left:4px solid #16a34a;margin:12px 0;">
            <h4 style="margin:0 0 6px;color:#166534;">✅ Coincidencias de alta confianza (${seguras.length})</h4>
            <p style="margin:0 0 10px;color:var(--texto-suave);font-size:.88em;">
                Son propuestas conservadoras: mismo orden y apellido, misma cantidad de partes del nombre y una diferencia ortográfica pequeña.
                Revisá los datos y desmarcá cualquier caso dudoso. El sistema vuelve a validarlas al aplicar.
            </p>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px;">
                <button class="btn btn-success btn-small" onclick="aplicarVinculacionesSeguras()">🔗 Aplicar coincidencias seleccionadas</button>
                <button class="btn btn-success btn-small" onclick="aplicarTodasVinculacionesSeguras()">🔗 Vincular todas las coincidencias seguras</button>
                <button class="btn btn-secondary btn-small" onclick="marcarVinculacionesSeguras(true)">Seleccionar todas</button>
                <button class="btn btn-secondary btn-small" onclick="marcarVinculacionesSeguras(false)">Desmarcar todas</button>
            </div>
            <div style="display:grid;gap:8px;">${seguras.map((item, idx) => `
                <details class="card vinc-segura-card" data-filtro="${escapeHTML(`${item.nombre} ${item.docente} ${item.bloques.map(b => `${b.aula} ${b.turno} ${b.dia} ${b.materia}`).join(' ')}`.toLocaleLowerCase())}" style="margin:0;padding:10px;">
                    <summary style="display:flex;gap:9px;align-items:flex-start;cursor:pointer;">
                        <input class="vinc-segura-check" type="checkbox" checked data-nombre="${escapeHTML(item.nombre)}" data-docente-id="${Number(item.docente_id)}" onclick="event.stopPropagation()" style="margin-top:4px;">
                        <span><strong>${escapeHTML(item.nombre)}</strong> → <strong>${escapeHTML(item.docente)}</strong>
                            <span class="badge-mini badge-mini-verde">${Number(item.similitud)}% · ${item.bloques.length} bloque(s)</span>
                            <small style="display:block;color:var(--texto-suave);margin-top:3px;">DNI ${escapeHTML(item.dni || '—')} · ${escapeHTML(item.email || '—')}</small>
                            <button type="button" class="btn btn-success btn-small" style="margin-top:6px;" onclick="event.preventDefault();event.stopPropagation();vincularCoincidenciaSegura('${escapeHTML(item.nombre)}')">🔗 Vincular este nombre</button>
                        </span>
                    </summary>
                    <ul style="margin:8px 0 0 28px;padding-left:18px;font-size:.88em;color:var(--texto-suave);">
                        ${item.bloques.map(b => `<li>Aula ${escapeHTML(b.aula)} (${escapeHTML(b.turno)}) · ${escapeHTML(b.dia)} ${escapeHTML(b.hora)} · ${escapeHTML(b.materia)}</li>`).join('')}
                    </ul>
                </details>`).join('')}</div>
        </section>` : `
        <div class="bd-ok-banner" style="margin:12px 0;">
            No hay coincidencias que cumplan los criterios automáticos conservadores. Los nombres restantes necesitan revisión.
        </div>`;

    const autoNames = new Set(seguras.map(item => item.nombre));
    const pendientes = grupos.filter(grupo => !autoNames.has(grupo.nombre));
    const grupoRevisionHtml = grupos.map((grupo, grupoIdx) => {
            if (autoNames.has(grupo.nombre)) return '';
            const sugeridos = new Set((grupo.sugerencias || []).map(c => c.id));
            const ordenadas = [
                ...(grupo.sugerencias || []),
                ...cuentas.filter(c => !sugeridos.has(c.id)),
            ];
            const opciones = ordenadas.map(cuenta => {
                const sugerencia = (grupo.sugerencias || []).find(c => c.id === cuenta.id);
                const detalle = [cuenta.dni ? `DNI ${cuenta.dni}` : '', cuenta.email || '']
                    .filter(Boolean).join(' · ');
                const prefijo = sugerencia ? `Sugerencia ${sugerencia.similitud}% · ` : '';
                return `<option value="${Number(cuenta.id)}">${escapeHTML(prefijo + cuenta.nombre)}${detalle ? ` — ${escapeHTML(detalle)}` : ''}</option>`;
            }).join('');
            const sugerenciaSegura = grupo.auto_sugerencia;
            const filtro = `${grupo.nombre} ${(grupo.sugerencias || []).map(c => `${c.nombre} ${c.email || ''} ${c.dni || ''}`).join(' ')} ${grupo.bloques.map(b => `${b.aula} ${b.turno} ${b.dia} ${b.materia}`).join(' ')}`.toLocaleLowerCase();
            const contenido = `<h5 style="margin:0 0 8px;color:#92400e;">⚠️ Nombre en cronograma: <code>${escapeHTML(grupo.nombre)}</code></h5>
                ${sugerenciaSegura ? `<p style="margin:0 0 8px;color:#166534;font-size:.88em;">Coincidencia segura disponible: <strong>${escapeHTML(sugerenciaSegura.docente)}</strong> (${sugerenciaSegura.similitud}%). Podés aplicarla desde el panel verde superior.</p>` : ''}
                <p style="margin:0 0 8px;color:${grupo.ambigua ? '#b91c1c' : 'var(--texto-suave)'};font-size:.88em;">${grupo.ambigua ? '⚠️ Hay varias cuentas con el mismo nombre; verificá DNI/correo y resolvé posibles duplicados antes de vincular.' : `${grupo.bloques.length} bloque(s) sin cuenta asociada.`} Si el texto contiene varios nombres juntos, corregí primero el cronograma; no lo asignes por similitud.</p>
                <div style="display:grid;gap:7px;">${grupo.bloques.map(bloque => `
                    <label style="display:flex;align-items:flex-start;gap:8px;padding:8px;border:1px solid var(--borde);border-radius:7px;">
                        <input class="vinc-doc-bloque-${grupoIdx}" type="checkbox"
                            data-aula="${escapeHTML(bloque.aula)}" data-turno="${escapeHTML(bloque.turno)}"
                            data-indice="${Number(bloque.indice)}" style="margin-top:3px;">
                        <span><b>Aula ${escapeHTML(bloque.aula)} (${escapeHTML(bloque.turno)})</b> · ${escapeHTML(bloque.dia)} ${escapeHTML(bloque.hora)}<br><span style="color:var(--texto-suave);">${escapeHTML(bloque.materia)}</span></span>
                    </label>`).join('')}</div>
                ${grupo.ambigua ? '<div class="bd-error-banner">Vinculación bloqueada por seguridad: verificá si las cuentas son duplicadas o si son homónimos reales. No se asignarán aulas hasta resolver esa identidad.</div>' : cuentas.length ? `<div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-top:10px;">
                    <select id="vinc-doc-cuenta-${grupoIdx}" style="flex:1;min-width:260px;">
                        <option value="">— Elegir cuenta docente (verificar DNI/email) —</option>${opciones}
                    </select>
                    <button class="btn btn-primary btn-small" onclick="vincularNombreCronograma(${grupoIdx})">🔗 Vincular bloques seleccionados</button>
                    <button class="btn btn-success btn-small" onclick="vincularGrupoCompleto(${grupoIdx})">🔗 Vincular todos los bloques del nombre</button>
                </div>` : '<div class="bd-error-banner">No hay cuentas titulares disponibles. Corrija el cronograma o espere a que el docente cree su cuenta con su nombre oficial.</div>'}
                ${(grupo.sugerencias || []).length ? `<small style="display:block;margin-top:8px;color:var(--texto-suave);">Coincidencias aproximadas no verificadas: ${(grupo.sugerencias || []).map(c => `${escapeHTML(c.nombre)} (${c.similitud}%)`).join(' · ')}</small>` : ''}
            `;
            return `<details class="card vinc-revision-card" data-filtro="${escapeHTML(filtro)}" style="border-left:4px solid ${grupo.ambigua ? '#dc2626' : '#f59e0b'};margin:8px 0;padding:12px;">
                <summary style="cursor:pointer;font-weight:700;">
                    <input class="vinc-manual-check" type="checkbox" data-grupo-idx="${grupoIdx}" ${grupo.ambigua ? 'disabled' : ''} onclick="event.stopPropagation()" title="Incluir todos los bloques de este nombre en la vinculación general">
                    ${grupo.ambigua ? '⚠️ Posible homónimo · ' : ''}<code>${escapeHTML(grupo.nombre)}</code> · ${grupo.bloques.length} bloque(s)
                </summary>
                <div style="margin-top:10px;">${contenido}</div>
            </details>`;
        }).join('');

    cont.innerHTML = cuentasHtml + `
        <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;margin:14px 0;">
            <label style="flex:1;min-width:240px;">Buscar en pendientes
                <input id="vinc-doc-busqueda" type="search" placeholder="Nombre, cuenta, DNI, aula, materia…" oninput="filtrarColaVinculaciones()">
            </label>
            <span class="badge-mini">${grupos.length} nombres · ${grupos.reduce((total, grupo) => total + grupo.bloques.length, 0)} bloques</span>
            <button class="btn btn-primary btn-small" onclick="aplicarLoteVinculaciones()">🔗 Vincular selección general</button>
        </div>
        <p style="color:var(--texto-suave);margin:0 0 8px;">
            La lista se agrupa por nombre y permanece plegada para facilitar la revisión. Las sugerencias no se guardan hasta que confirmes la acción.
        </p>
        ${segurasHtml}
        <details id="vinc-doc-cola-manual" style="margin-top:12px;">
            <summary style="cursor:pointer;font-weight:700;color:#92400e;">📝 Revisar o corregir manualmente (${pendientes.length} sin coincidencia segura · ${grupos.length} en total)</summary>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin:10px 0;">
                <button class="btn btn-secondary btn-small" onclick="marcarGruposManual(true)">Seleccionar grupos visibles</button>
                <button class="btn btn-secondary btn-small" onclick="marcarGruposManual(false)">Desmarcar grupos</button>
                <button class="btn btn-primary btn-small" onclick="aplicarLoteVinculaciones()">🔗 Vincular grupos seleccionados</button>
            </div>
            <div style="margin-top:10px;">${grupoRevisionHtml}</div>
        </details>`;
}

function marcarVinculacionesSeguras(marcadas) {
    document.querySelectorAll('#vinc-docentes-resultados .vinc-segura-check')
        .forEach(checkbox => { checkbox.checked = marcadas; });
}

function marcarGruposManual(marcados) {
    document.querySelectorAll('#vinc-doc-cola-manual .vinc-manual-check:not(:disabled)').forEach(checkbox => {
        const card = checkbox.closest('.vinc-revision-card');
        if (!marcados || !card || card.style.display !== 'none') checkbox.checked = marcados;
    });
}

async function vincularCoincidenciaSegura(nombre) {
    const checkbox = [...document.querySelectorAll('#vinc-docentes-resultados .vinc-segura-check')]
        .find(item => item.dataset.nombre === nombre);
    if (!checkbox) return mostrarToast('Actualice el análisis antes de vincular.', 'warning');
    checkbox.checked = true;
    await aplicarLoteVinculaciones({ soloSeguras: true, nombres: [nombre] });
}

async function aplicarTodasVinculacionesSeguras() {
    marcarVinculacionesSeguras(true);
    await aplicarLoteVinculaciones({ soloSeguras: true });
}

async function vincularGrupoCompleto(grupoIdx) {
    const checks = [...document.querySelectorAll(`.vinc-doc-bloque-${grupoIdx}`)];
    checks.forEach(check => { check.checked = true; });
    await vincularNombreCronograma(grupoIdx);
}

function filtrarColaVinculaciones() {
    const query = (document.getElementById('vinc-doc-busqueda')?.value || '').trim().toLocaleLowerCase();
    document.querySelectorAll('#vinc-docentes-resultados [data-filtro]').forEach(item => {
        item.style.display = !query || item.dataset.filtro.includes(query) ? '' : 'none';
    });
    const cola = document.getElementById('vinc-doc-cola-manual');
    if (cola && query) cola.open = true;
}

async function aplicarLoteVinculaciones({soloSeguras = false, nombres = null} = {}) {
    const segurasSeleccionadas = [...document.querySelectorAll('#vinc-docentes-resultados .vinc-segura-check:checked')]
        .filter(checkbox => !nombres || nombres.includes(checkbox.dataset.nombre))
        .map(checkbox => ({
            nombre: checkbox.dataset.nombre,
            docente_id: Number(checkbox.dataset.docenteId),
            modo: 'segura',
        }));
    const manualesSeleccionadas = soloSeguras ? [] :
        [...document.querySelectorAll('#vinc-doc-cola-manual .vinc-manual-check:checked')]
            .map(checkbox => {
                const idx = checkbox.dataset.grupoIdx;
                const selector = document.getElementById(`vinc-doc-cuenta-${idx}`);
                const checks = [...document.querySelectorAll(`.vinc-doc-bloque-${idx}`)];
                return {
                    nombre: checkbox.closest('.vinc-revision-card')?.querySelector('code')?.textContent || '',
                    docente_id: Number(selector?.value || 0),
                    modo: 'manual',
                    bloques: checks.map(check => ({
                        aula: check.dataset.aula,
                        turno: check.dataset.turno,
                        indice: Number(check.dataset.indice),
                    })),
                };
            });
    const vinculaciones = [...segurasSeleccionadas, ...manualesSeleccionadas];
    if (!vinculaciones.length) return mostrarToast('Seleccione al menos un nombre para vincular.', 'warning');
    const sinCuenta = manualesSeleccionadas.find(item => !item.docente_id);
    if (sinCuenta) {
        return mostrarToast(`Seleccione la cuenta destino para "${sinCuenta.nombre}".`, 'warning');
    }
    const resumen = vinculaciones.map(item => `${item.nombre} → cuenta #${item.docente_id}`).join('\n');
    if (!confirm(`Se vincularán ${vinculaciones.length} nombre(s); los grupos manuales incluirán todos sus bloques.\n\n${resumen}\n\nLa operación se validará nuevamente y quedará auditada. ¿Continuar?`)) return;
    try {
        const response = await fetch('/api/su/vinculaciones_docentes/aplicar-lote', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify({ vinculaciones }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        mostrarToast(data.msj, 'success');
        await analizarSaludDB();
    } catch (error) {
        mostrarToast(`No se pudieron aplicar las vinculaciones: ${error.message}`, 'error');
    }
}

async function aplicarVinculacionesSeguras() {
    const vinculaciones = [...document.querySelectorAll('#vinc-docentes-resultados .vinc-segura-check:checked')]
        .map(checkbox => ({
            nombre: checkbox.dataset.nombre,
            docente_id: Number(checkbox.dataset.docenteId),
        }));
    if (!vinculaciones.length) return mostrarToast('Marque al menos una coincidencia segura.', 'warning');
    const resumen = vinculaciones.map(item => {
        const fila = [...document.querySelectorAll('#vinc-docentes-resultados .vinc-segura-check')]
            .find(checkbox => checkbox.dataset.nombre === item.nombre);
        return `${item.nombre} → ${fila?.closest('details')?.querySelector('summary')?.textContent.trim() || 'cuenta seleccionada'}`;
    }).join('\n');
    if (!confirm(`Se vincularán únicamente los nombres seleccionados, con coincidencia conservadora, tras validar el estado actual del cronograma.\n\n${resumen}\n\n¿Continuar?`)) return;
    try {
        const response = await fetch('/api/su/vinculaciones_docentes/aplicar-seguras', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify({ vinculaciones }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        mostrarToast(data.msj, 'success');
        await analizarSaludDB();
    } catch (error) {
        mostrarToast(`No se pudieron aplicar las coincidencias: ${error.message}`, 'error');
    }
}

async function vincularNombreCronograma(grupoIdx) {
    const selector = document.getElementById(`vinc-doc-cuenta-${grupoIdx}`);
    const checks = [...document.querySelectorAll(`.vinc-doc-bloque-${grupoIdx}:checked`)];
    const tarjeta = checks[0]?.closest('.vinc-revision-card');
    const nombre = tarjeta?.querySelector('summary code')?.textContent.trim() || '';
    const bloques = checks
        .map(el => ({
            aula: el.dataset.aula,
            turno: el.dataset.turno,
            indice: Number(el.dataset.indice),
        }));
    if (!nombre) return mostrarToast('No se pudo identificar el nombre del cronograma. Actualice el análisis e intente nuevamente.', 'error');
    if (!selector?.value) return mostrarToast('Seleccione la cuenta correcta y verifique su DNI/email.', 'warning');
    if (!bloques.length) return mostrarToast('Marque al menos un bloque del cronograma.', 'warning');
    const cuenta = selector.options[selector.selectedIndex].text;
    if (!confirm(`¿Vincular ${bloques.length} bloque(s) seleccionado(s) a:\n${cuenta}\n\nSolo se cambiarán las aulas y horarios marcados. La operación quedará auditada.`)) return;
    try {
        const response = await fetch('/api/su/vinculaciones_docentes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify({
                nombre,
                docente_id: Number(selector.value),
                bloques,
            }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        mostrarToast(data.msj, 'success');
        await analizarSaludDB();
    } catch (error) {
        mostrarToast(`No se pudo vincular: ${error.message}`, 'error');
    }
}

function renderDuplicados(d) {
    const stats = document.getElementById('dup-stats');
    const cont  = document.getElementById('dup-resultados');
    if (!cont) return;
    const dupN = (d.duplicados_por_nombre || []).length;
    const dupE = (d.duplicados_por_email  || []).length;
    if (stats) {
        stats.innerHTML = `
            <span>👨‍🏫 <b>${d.total_docentes || 0}</b> docentes en total</span>
            <span>🧬 <b>${dupN}</b> grupos sospechosos por nombre</span>
            <span>📧 <b>${dupE}</b> emails duplicados</span>
        `;
    }
    if (!dupN && !dupE) {
        cont.innerHTML = '<div class="bd-ok-banner">✅ No se detectaron duplicados.</div>';
        return;
    }
    let html = '';
    if (dupN) {
        html += '<h5 style="color:var(--azul-oscuro);margin:10px 0;">📛 Por nombre similar</h5>';
        d.duplicados_por_nombre.forEach((g, idx) => {
            html += `<div class="card" style="background:#fffbeb;border-left:4px solid #f59e0b;margin-bottom:10px;">
                <div style="font-weight:700;color:#92400e;margin-bottom:8px;">
                    🧬 Grupo #${idx+1} · Canónico: <code>${escapeHTML(g.canonico)}</code>
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">`;
            g.docentes.forEach(doc => {
                html += `<div style="background:white;padding:10px;border-radius:6px;border:1px solid #fde68a;">
                    <div><b>${escapeHTML(doc.nombre)}</b> <small style="color:#94a3b8;">#${doc.id}</small></div>
                    <div style="font-size:.85em;color:var(--texto-suave);">${escapeHTML(doc.email) || '—'} · DNI ${escapeHTML(doc.dni) || '—'}</div>
                </div>`;
            });
            html += '</div>';
            // Botones de fusión por pares (A→B y B→A)
            if (g.docentes.length === 2) {
                html += `<div style="margin-top:10px;display:flex;gap:8px;flex-wrap:wrap;">
                    <button class="btn btn-small" style="background:#7c3aed;color:white;" onclick="fusionarDocenteUI(${g.docentes[0].id},${g.docentes[1].id},'${escapeHTML(g.docentes[0].nombre)}','${escapeHTML(g.docentes[1].nombre)}')">
                        🔄 Fusionar A → B
                    </button>
                    <button class="btn btn-small" style="background:#7c3aed;color:white;" onclick="fusionarDocenteUI(${g.docentes[1].id},${g.docentes[0].id},'${escapeHTML(g.docentes[1].nombre)}','${escapeHTML(g.docentes[0].nombre)}')">
                        🔄 Fusionar B → A
                    </button>
                </div>`;
            } else if (g.docentes.length > 2) {
                html += `<div style="margin-top:10px;font-size:.85em;color:var(--texto-suave);">
                    <i>Más de 2 candidatos: fusionalos de a pares manualmente.</i>
                </div>`;
            }
            html += '</div>';
        });
    }
    if (dupE) {
        html += '<h5 style="color:var(--azul-oscuro);margin:18px 0 10px;">📧 Por email duplicado</h5>';
        d.duplicados_por_email.forEach(g => {
            html += `<div class="card" style="background:#fef2f2;border-left:4px solid #dc2626;margin-bottom:10px;">
                <div style="font-weight:700;color:#991b1b;margin-bottom:8px;">
                    📧 Email: <code>${escapeHTML(g.email)}</code>
                </div>`;
            g.docentes.forEach(doc => {
                html += `<div style="background:white;padding:8px;border-radius:6px;border:1px solid #fecaca;margin-bottom:6px;">
                    <b>${escapeHTML(doc.nombre)}</b> <small style="color:#94a3b8;">#${doc.id}</small> · DNI ${escapeHTML(doc.dni)}
                </div>`;
            });
            html += '</div>';
        });
    }
    cont.innerHTML = html;
}

async function fusionarDocenteUI(id_origen, id_destino, nom_o, nom_d) {
    if (!confirm(`¿Fusionar?\n\n  Origen:   ${nom_o} (#${id_origen})\n  Destino:  ${nom_d} (#${id_destino})\n\nTODAS las firmas y justificaciones del origen pasarán al destino.\nEl origen se eliminará.\n\n¿Continuar?`)) return;
    try {
        const r = await fetch('/api/su/fusionar_docente', {
            method:'POST',
            headers:{ 'Content-Type':'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify({ id_origen, id_destino }),
        });
        const d = await r.json();
        if (d.ok) {
            mostrarToast(`✅ ${d.msj} (firmas: ${d.firmas_movidas}, justif: ${d.justif_movidas})`, 'success');
            analizarSaludDB();
        } else {
            mostrarToast(`❌ ${d.error}`, 'error');
        }
    } catch (e) {
        mostrarToast(`❌ ${e.message}`, 'error');
    }
}

function renderHuerfanos(h) {
    const cont = document.getElementById('huer-resultados');
    if (!cont) return;
    const t = h.total_hallazgos || 0;
    if (t === 0) {
        cont.innerHTML = '<div class="bd-ok-banner">✅ Base de datos sin huérfanos detectados.</div>';
        return;
    }
    let html = `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px;margin-bottom:14px;">`;
    // Cards de resumen
    const items = [
        { key: 'firmas_sin_cuenta',           label: 'Firmas sin cuenta',         ico: '✍️', tipo: 'list', sev: 'warn' },
        { key: 'aspirantes_sin_cronograma',   label: 'Aspirantes sin cronograma', ico: '🎓', tipo: 'list', sev: 'warn' },
        { key: 'cronograma_sin_aspirantes',   label: 'Cronograma sin aspirantes', ico: '📅', tipo: 'list', sev: 'warn' },
        { key: 'justif_sin_docente',          label: 'Justif. sin docente',       ico: '📋', tipo: 'list', sev: 'warn' },
        { key: 'docentes_cronograma_sin_cuenta', label: 'Docentes cronograma SIN cuenta', ico: '👤', tipo: 'list', sev: 'info' },
        { key: 'tokens_caducos',              label: 'Tokens caducos',            ico: '🎫', tipo: 'num',  sev: 'auto' },
        { key: 'recordatorios_viejos',        label: 'Recordatorios enviados >30d',ico: '⏰', tipo: 'num',  sev: 'auto' },
        { key: 'system_log_viejo',            label: 'system_log >90 días',       ico: '📜', tipo: 'num',  sev: 'auto' },
        { key: 'failed_logins_viejo',         label: 'failed_logins >90 días',    ico: '🔐', tipo: 'num',  sev: 'auto' },
    ];
    items.forEach(it => {
        const val = h[it.key];
        const n   = it.tipo === 'list' ? (Array.isArray(val) ? val.length : 0) : (val || 0);
        if (n === 0) return;
        const color = it.sev === 'warn' ? '#f59e0b' : it.sev === 'info' ? '#6366f1' : '#0ea5e9';
        html += `<div class="card" style="text-align:center;padding:12px;border-top:3px solid ${color};margin:0;">
            <div style="font-size:1.4em;">${it.ico}</div>
            <div style="font-size:.74em;color:var(--texto-suave);margin-top:4px;">${it.label}</div>
            <div style="font-size:1.6em;font-weight:800;color:${color};font-family:'Barlow Condensed';">${n}</div>
        </div>`;
    });
    html += '</div>';

    // Detalle expandible de las listas críticas
    if ((h.firmas_sin_cuenta || []).length) {
        html += `<details style="margin-bottom:12px;"><summary style="cursor:pointer;font-weight:700;color:#92400e;">
            ✍️ ${h.firmas_sin_cuenta.length} docentes que firmaron pero no tienen cuenta (clic)
        </summary><ul style="margin-top:8px;">`;
        h.firmas_sin_cuenta.slice(0, 20).forEach(d => {
            html += `<li><b>${escapeHTML(d.docente)}</b> — <code>${d.firmas}</code> firmas</li>`;
        });
        html += '</ul><small style="color:var(--texto-suave);"><i>Estos pueden ser docentes nuevos o que cambiaron de nombre. NO se eliminan automáticamente.</i></small></details>';
    }
    if ((h.docentes_cronograma_sin_cuenta || []).length) {
        html += `<details style="margin-bottom:12px;"><summary style="cursor:pointer;font-weight:700;color:#4f46e5;">
            👤 ${h.docentes_cronograma_sin_cuenta.length} docentes en cronograma sin cuenta (clic)
        </summary><ul style="margin-top:8px;">`;
        h.docentes_cronograma_sin_cuenta.slice(0, 20).forEach(d => {
            html += `<li><b>${escapeHTML(d.docente)}</b> — <code>${d.bloques}</code> bloques</li>`;
        });
        html += '</ul><small style="color:var(--texto-suave);"><i>Hay que crearles cuenta para que puedan firmar.</i></small></details>';
    }
    if ((h.aspirantes_sin_cronograma || []).length) {
        html += `<details style="margin-bottom:12px;"><summary style="cursor:pointer;font-weight:700;color:#92400e;">
            🎓 Aulas con aspirantes pero SIN cronograma
        </summary><ul style="margin-top:8px;">`;
        h.aspirantes_sin_cronograma.forEach(d => {
            html += `<li>Aula <b>${escapeHTML(d.aula)}</b> (${escapeHTML(d.turno)}) — ${d.aspirantes} aspirantes</li>`;
        });
        html += '</ul></details>';
    }
    if ((h.cronograma_sin_aspirantes || []).length) {
        html += `<details style="margin-bottom:12px;"><summary style="cursor:pointer;font-weight:700;color:#92400e;">
            📅 Cronogramas SIN aspirantes cargados
        </summary><ul style="margin-top:8px;">`;
        h.cronograma_sin_aspirantes.forEach(d => {
            html += `<li>Aula <b>${escapeHTML(d.aula)}</b> (${escapeHTML(d.turno)})</li>`;
        });
        html += '</ul></details>';
    }

    // Botones de limpieza automática para cosas seguras
    const limpiables = [
        ['tokens_caducos',       'Tokens caducos',       h.tokens_caducos],
        ['recordatorios_viejos', 'Recordatorios viejos', h.recordatorios_viejos],
        ['system_log',           'system_log >90 días',  h.system_log_viejo],
        ['failed_logins',        'failed_logins >90 días', h.failed_logins_viejo],
    ].filter(([k, l, n]) => n > 0);
    if (limpiables.length) {
        html += `<div class="card" style="background:#f0fdf4;border-left:4px solid #16a34a;margin-top:14px;">
            <h5 style="margin-top:0;color:#15803d;">🧼 Limpieza segura (datos no críticos)</h5>
            <p style="font-size:.88em;color:var(--texto-suave);margin-bottom:10px;">
                Elegí qué borrar. Solo se eliminan datos que ya no son útiles operativamente.
            </p>`;
        limpiables.forEach(([k, l, n]) => {
            html += `<label style="display:flex;align-items:center;gap:8px;padding:5px 0;cursor:pointer;">
                <input type="checkbox" id="limp-${k}" data-key="${k}" checked>
                <b>${l}</b> <code style="color:var(--texto-tenue);">(${n} registros)</code>
            </label>`;
        });
        html += `<button class="btn btn-danger" style="margin-top:10px;" onclick="ejecutarLimpiezaHuerfanos()">
            🗑️ Eliminar seleccionados
        </button></div>`;
    }

    cont.innerHTML = html;
}

// Helper para copiar URLs públicas (TV, Status)
function copiarUrl(path) {
    const url = window.location.origin + path;
    if (navigator.clipboard?.writeText) {
        navigator.clipboard.writeText(url)
            .then(() => mostrarToast(`✅ URL copiada: ${url}`, 'success'))
            .catch(() => mostrarToast(`URL: ${url}`, 'info'));
    } else {
        prompt('Copiá esta URL:', url);
    }
}

async function ejecutarLimpiezaHuerfanos() {
    const opts = {};
    document.querySelectorAll('[id^=limp-]').forEach(el => {
        opts[el.dataset.key] = el.checked;
    });
    if (!confirm('¿Confirmás la eliminación de los registros seleccionados?\n\nSe registra en el audit_log.')) return;
    try {
        const r = await fetch('/api/su/limpiar_huerfanos', {
            method:'POST',
            headers:{ 'Content-Type':'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify(opts),
        });
        const d = await r.json();
        if (d.ok) {
            mostrarToast(`✅ ${d.msj}`, 'success');
            analizarSaludDB();
        } else {
            mostrarToast(`❌ ${d.error}`, 'error');
        }
    } catch (e) {
        mostrarToast(`❌ ${e.message}`, 'error');
    }
}

// ══════════════════════════════════════════════════════════════
// INGRESO ADMIN (Plana Mayor) — validación contra hash SHA-256+salt en backend
// ══════════════════════════════════════════════════════════════
async function ingresarAdmin(codigo_2fa = '') {
    const inp  = document.getElementById('pass-admin');
    const userInp = document.getElementById('user-admin');
    const pass = inp.value;
    const usuario = (userInp?.value || '').trim();
    if (!pass) return mostrarToast('Ingrese la clave.', 'warning');
    try {
        const r = await fetch('/api/admin/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ usuario, password: pass, codigo_2fa }),
        });
        const d = await r.json();
        if (r.ok && d.token) {
            window.SIPA.adminToken = d.token;
            window.SIPA.adminUsuario = d.usuario || 'admin';
            window.SIPA.adminNombre  = d.nombre  || 'Plana Mayor';
            localStorage.setItem('sipa_admin_token', d.token);
            document.getElementById('login-admin').style.display = 'none';
            document.getElementById('panel-admin').style.display = 'block';
            inp.value = '';
            // Header de sesión
            const elU = document.getElementById('admin-usuario-info');
            if (elU) elU.textContent = `🛡️ ${d.nombre || 'Plana Mayor'}`;
            const elM = document.getElementById('admin-sesion-info');
            if (elM) elM.textContent = `${d.usuario || 'admin'} · Sesión iniciada ${new Date().toLocaleString('es-AR',{day:'2-digit',month:'2-digit',year:'numeric',hour:'2-digit',minute:'2-digit'})}`;

            mostrarToast(`Acceso autorizado — ${d.nombre || 'Plana Mayor'}`, 'success');
            cargarPinesOperativos();
            cargarFirmasTardiasPendientes();
            loadServicio();
            iniciarSSE();  // Stream de eventos en vivo
            // Auto-refresh del monitor cada 60s SOLO si el usuario está en ese tab
            _monitorInterval = setInterval(() => {
                if (document.getElementById('admin-registro')?.classList.contains('active')) {
                    refrescarMonitor(true);
                }
                if (document.getElementById('panel-admin')?.style.display !== 'none') {
                    cargarFirmasTardiasPendientes(true);
                }
            }, 60000);
            if (_aulasDiaInterval) clearInterval(_aulasDiaInterval);
            _aulasDiaInterval = setInterval(() => {
                const tableroActivo = document.getElementById('panel-admin')?.style.display !== 'none'
                    && document.getElementById('admin-registro')?.classList.contains('active')
                    && document.getElementById('mon-aulas-dia')?.classList.contains('active')
                    && !document.hidden;
                if (tableroActivo) cargarAulasDia(true);
            }, 30000);
        } else if (d.requiere_2fa) {
            // Pedir código TOTP y reintentar
            const codigo = prompt('🔐 Esta cuenta tiene 2FA activado.\nIngrese el código de 6 dígitos de su autenticador:');
            if (codigo && /^\d{6}$/.test(codigo.trim())) {
                return ingresarAdmin(codigo.trim());
            }
            mostrarToast('Código 2FA requerido.', 'warning');
        } else {
            mostrarToast(d.error || 'Clave incorrecta.', 'error');
            inp.classList.add('shake-error');
            setTimeout(() => inp.classList.remove('shake-error'), 500);
        }
    } catch (e) {
        mostrarToast('Error de conexión: ' + e.message, 'error');
    }
}

// ══════════════════════════════════════════════════════════════
// CERRAR SESIÓN DE PLANA MAYOR
// ══════════════════════════════════════════════════════════════
async function cerrarSesionAdmin() {
    if (!confirm('¿Cerrar la sesión de Plana Mayor?')) return;
    if (typeof detenerSSE === 'function') detenerSSE();
    const tok = window.SIPA.adminToken;
    // Avisar al backend para revocar el token (best-effort, no falla si no llega)
    try {
        await fetch('/api/admin/logout', {
            method: 'POST',
            headers: { 'X-Admin-Token': tok || '' },
        });
    } catch {}
    // Limpiar estado local
    window.SIPA.adminToken = null;
    window.SIPA.adminUsuario = null;
    window.SIPA.adminNombre = null;
    localStorage.removeItem('sipa_admin_token');
    // Detener el interval del monitor si está activo
    if (typeof _monitorInterval !== 'undefined' && _monitorInterval) {
        clearInterval(_monitorInterval);
        _monitorInterval = null;
    }
    if (_aulasDiaInterval) {
        clearInterval(_aulasDiaInterval);
        _aulasDiaInterval = null;
    }
    // Volver al login (flex para que la card quede centrada por .login-wrapper)
    document.getElementById('panel-admin').style.display = 'none';
    document.getElementById('login-admin').style.display = 'flex';
    const inp = document.getElementById('pass-admin');
    if (inp) inp.value = '';
    const usrInp = document.getElementById('user-admin');
    if (usrInp) usrInp.value = '';
    mostrarToast('🚪 Sesión de Plana Mayor cerrada', 'info');
}


// ══════════════════════════════════════════════════════════════
// DIAGNÓSTICO / BASE DE DATOS
// ══════════════════════════════════════════════════════════════
async function verificarConexionBD() {
    const btn    = document.getElementById('btn-verificar-bd');
    const status = document.getElementById('bd-status');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spin">🔄</span> Verificando…'; }
    try {
        const res  = await fetch('/api/diagnostico');
        const data = await res.json();
        if (data.estado === 'conectado') {
            const tablas = data.tablas || {};
            // Agrupar por categoría para que se lea bien con 12+ tablas
            const grupos = {
                '📚 Datos académicos': ['cronograma_maestro','cronograma_versiones','aspirantes','docentes','aula_catalogo'],
                '📋 Operatividad diaria': ['minutas','firmas_docentes','justificaciones_ausencia','pin_overrides'],
                '🔒 Seguridad y auditoría': ['usuarios_admin','audit_log','failed_logins','system_log'],
                '⚙️ Configuración': ['config_sistema','tipos_novedad'],
                '🤖 Telegram / Bot': ['bedeles_telegram','bedel_link_tokens','recordatorios_telegram','bot_comando_log'],
                '📦 Archivado': ['minutas_archivo','firmas_archivo'],
            };
            const filaTpl = (nombre, info) => {
                if (info.pendiente) {
                    return `<tr>
                        <td style="opacity:.6;">⏳ <strong style="font-family:'DM Mono',monospace;font-size:.92em;color:var(--texto-suave);">${nombre}</strong></td>
                        <td style="color:var(--texto-tenue);font-weight:500;text-align:right;font-style:italic;font-size:.85em;">
                            ${info.mensaje || 'Pendiente de crear'}
                        </td>
                    </tr>`;
                }
                return `<tr>
                    <td>${info.ok ? '✅' : '❌'} <strong style="font-family:'DM Mono',monospace;font-size:.92em;">${nombre}</strong></td>
                    <td style="color:${info.ok?'var(--exito-cl)':'var(--peligro)'};font-weight:600;text-align:right;">
                        ${info.ok ? info.filas + ' filas' : (info.error||'').substring(0,60)}
                    </td>
                </tr>`;
            };
            // Contadores globales (excluyendo pendientes)
            const operativas = Object.values(tablas).filter(t => !t.pendiente);
            const total = operativas.length;
            const okCnt = operativas.filter(t => t.ok).length;
            const sumFilas = operativas.filter(t => t.ok).reduce((a,t) => a + (t.filas || 0), 0);
            const pendientes = Object.values(tablas).filter(t => t.pendiente).length;

            const tablasHtml = Object.entries(grupos).map(([titulo, lista]) => {
                const filas = lista.filter(n => n in tablas).map(n => filaTpl(n, tablas[n])).join('');
                if (!filas) return '';
                return `<tr><td colspan="2" style="background:#ecfdf5;padding:6px 10px;font-size:.76em;font-weight:700;color:var(--verde-inst);text-transform:uppercase;letter-spacing:.5px;">${titulo}</td></tr>${filas}`;
            }).join('');

            const subTxt = pendientes
                ? `${okCnt}/${total} tablas operativas · ${sumFilas} filas · ${pendientes} de archivo pendientes de crear`
                : `${okCnt}/${total} tablas verificadas · ${sumFilas} filas totales`;
            if (status) status.innerHTML = `
                <div class="bd-ok-banner">
                    <div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;flex-wrap:wrap;">
                        <span style="font-size:1.6em;">🟢</span>
                        <div style="flex:1;min-width:200px;">
                            <strong style="color:var(--exito);">PostgreSQL Conectado</strong>
                            <div style="font-size:.82em;color:var(--texto-suave);">${subTxt}</div>
                        </div>
                    </div>
                    <div class="table-responsive"><table style="width:100%;border-collapse:collapse;font-size:.86em;">
                        <thead><tr>
                            <th style="text-align:left;padding:6px 10px;background:#f0fdf4;color:var(--verde-inst);">Tabla</th>
                            <th style="text-align:right;padding:6px 10px;background:#f0fdf4;color:var(--verde-inst);">Estado</th>
                        </tr></thead>
                        <tbody>${tablasHtml}</tbody>
                    </table></div>
                </div>`;
            mostrarToast('✅ Base de datos conectada.', 'success');
        } else { throw new Error(data.detalle || 'Error de conexión'); }
    } catch (e) {
        if (status) status.innerHTML = `<div class="bd-error-banner">
            <span style="font-size:1.4em;">🔴</span>
            <div><strong style="color:var(--peligro);">Error de Conexión</strong>
            <div style="font-size:.82em;margin-top:4px;">${e.message}</div></div>
        </div>`;
        mostrarToast('Error conectando a la BD.', 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '🔌 Verificar Conexión'; }
    }
}

// ══════════════════════════════════════════════════════════════
// CONEXIÓN A BASE DE DATOS REMOTA
// ══════════════════════════════════════════════════════════════
async function cargarConexionActual() {
    const cont = document.getElementById('conexion-actual');
    if (!cont) return;
    if (!window.SIPA.suToken) {
        cont.innerHTML = `<span style="color:var(--peligro);">⚠️ Requiere sesión TIC activa para ver la conexión.</span>`;
        return;
    }
    try {
        const r = await fetch('/api/db_connection', { headers: { 'X-SU-Token': window.SIPA.suToken } });
        const c = await r.json();
        const tag = c.es_personalizada
            ? '<span style="background:#6366f1;color:white;padding:2px 8px;border-radius:4px;font-size:.78em;font-weight:700;">PERSONALIZADA</span>'
            : '<span style="background:#64748b;color:white;padding:2px 8px;border-radius:4px;font-size:.78em;font-weight:700;">DEFAULT (.env)</span>';
        cont.innerHTML = `
            ${tag}
            &nbsp;Conectado a <strong>${c.host}:${c.port}</strong>
            &nbsp;·&nbsp; BD <code>${c.dbname}</code>
            &nbsp;·&nbsp; usuario <code>${c.user}</code>`;
    } catch (e) {
        cont.innerHTML = `<span style="color:var(--peligro);">No se pudo leer la conexión actual.</span>`;
    }
}

function _leerCamposConexion() {
    return {
        host:     document.getElementById('db-host').value.trim(),
        port:     document.getElementById('db-port').value.trim() || '5432',
        dbname:   document.getElementById('db-name').value.trim(),
        user:     document.getElementById('db-user').value.trim(),
        password: document.getElementById('db-pass').value,
    };
}

async function probarConexionRemota() {
    if (!window.SIPA.suToken) return mostrarToast('Requiere sesión TIC.', 'warning');
    const datos = _leerCamposConexion();
    const out   = document.getElementById('db-test-result');
    if (!datos.host || !datos.dbname || !datos.user) {
        return mostrarToast('Complete host, base de datos y usuario.', 'warning');
    }
    out.innerHTML = `<div style="padding:10px 14px;color:var(--texto-suave);"><span class="spin">🔄</span> Probando conexión a ${datos.host}:${datos.port}…</div>`;
    try {
        const r = await fetch('/api/db_connection/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify(datos),
        });
        const d = await r.json();
        if (r.ok && d.ok) {
            out.innerHTML = `<div class="bd-ok-banner">
                <strong style="color:var(--exito);">✅ Conexión exitosa</strong>
                <div style="font-size:.82em;margin-top:6px;color:var(--texto-suave);">${d.version || ''}</div>
            </div>`;
            mostrarToast('Conexión exitosa.', 'success');
        } else {
            out.innerHTML = `<div class="bd-error-banner">
                <span style="font-size:1.4em;">🔴</span>
                <div><strong style="color:var(--peligro);">No se pudo conectar</strong>
                <div style="font-size:.85em;margin-top:4px;color:var(--texto-suave);">${d.error || 'Error desconocido'}</div></div>
            </div>`;
            mostrarToast('Falló la prueba.', 'error');
        }
    } catch (e) {
        out.innerHTML = `<div class="bd-error-banner">
            <span style="font-size:1.4em;">🔴</span>
            <div><strong style="color:var(--peligro);">Error de red</strong>
            <div style="font-size:.85em;margin-top:4px;">${e.message}</div></div>
        </div>`;
    }
}

async function guardarConexionRemota() {
    if (!window.SIPA.suToken) return mostrarToast('Requiere sesión TIC.', 'warning');
    const datos = _leerCamposConexion();
    if (!datos.host || !datos.dbname || !datos.user) {
        return mostrarToast('Complete host, base de datos y usuario.', 'warning');
    }
    if (!confirm(`⚠️ Va a cambiar la conexión activa a:\n\n${datos.host}:${datos.port} / ${datos.dbname}\n\nEsto reemplaza la BD actual. ¿Continúa?`)) return;

    const out = document.getElementById('db-test-result');
    out.innerHTML = `<div style="padding:10px 14px;color:var(--texto-suave);"><span class="spin">🔄</span> Conectando y creando tablas…</div>`;
    try {
        const r = await fetch('/api/db_connection', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify(datos),
        });
        const d = await r.json();
        if (r.ok) {
            out.innerHTML = `<div class="bd-ok-banner"><strong style="color:var(--exito);">✅ ${d.msj}</strong></div>`;
            mostrarToast('Conexión activada.', 'success');
            document.getElementById('db-pass').value = '';
            await cargarConexionActual();
            await verificarConexionBD();
        } else {
            out.innerHTML = `<div class="bd-error-banner">
                <span style="font-size:1.4em;">🔴</span>
                <div><strong style="color:var(--peligro);">No se pudo guardar</strong>
                <div style="font-size:.85em;margin-top:4px;">${d.error || 'Error desconocido'}</div></div>
            </div>`;
            mostrarToast(d.error || 'Error.', 'error');
        }
    } catch (e) {
        out.innerHTML = `<div class="bd-error-banner"><strong>${e.message}</strong></div>`;
        mostrarToast('Error de red.', 'error');
    }
}

async function restaurarConexionDefault() {
    if (!window.SIPA.suToken) return mostrarToast('Requiere sesión TIC.', 'warning');
    if (!confirm('Volver a la conexión original definida en .env / default. ¿Confirma?')) return;
    try {
        const r = await fetch('/api/db_connection/reset', {
            method: 'POST',
            headers: { 'X-SU-Token': window.SIPA.suToken },
        });
        const d = await r.json();
        if (r.ok) {
            mostrarToast('✅ ' + d.msj, 'success');
            await cargarConexionActual();
            await verificarConexionBD();
        } else {
            mostrarToast(d.error || 'Error.', 'error');
        }
    } catch {
        mostrarToast('Error de red.', 'error');
    }
}


async function inicializarTablas() {
    const btn = document.getElementById('btn-init-tablas');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spin">🔄</span> Creando tablas…'; }
    try {
        const res  = await fetch('/api/init_db', { method: 'POST' });
        const data = await res.json();
        if (res.ok) { mostrarToast('✅ ' + data.msj, 'success'); await verificarConexionBD(); }
        else mostrarToast(data.error || 'Error.', 'error');
    } catch { mostrarToast('Error de red.', 'error'); }
    finally { if (btn) { btn.disabled = false; btn.innerHTML = '🗄️ Inicializar Tablas'; } }
}

// ══════════════════════════════════════════════════════════════
// PINes OPERATIVOS
// ══════════════════════════════════════════════════════════════
async function cargarPinesOperativos() {
    try {
        const pines   = await (await fetch('/api/pines_operativos')).json();
        const tbodyTM = document.getElementById('body-pines-tm');
        const tbodyTT = document.getElementById('body-pines-tt');
        tbodyTM.innerHTML = ''; tbodyTT.innerHTML = '';
        let cTM = 0, cTT = 0;
        pines.forEach(p => {
            const color = _colorGrado(p.grado);
            const badge = `<span style="background:${color};color:white;padding:4px 10px;border-radius:12px;font-size:11px;font-weight:bold;display:inline-block;">${p.grado || '—'}</span>`;
            const row   = `<tr>
                <td style="font-weight:600;color:var(--azul-oscuro);">AULA ${p.aula}</td>
                <td>${badge}</td>
                <td><span class="pin-display">${p.pin}</span></td>
            </tr>`;
            if (p.turno === 'TM') { tbodyTM.innerHTML += row; cTM++; }
            else                  { tbodyTT.innerHTML += row; cTT++; }
        });
        const vacio = `<tr><td colspan="3" style="text-align:center;padding:20px;color:var(--texto-tenue);">Sin configuraciones.</td></tr>`;
        if (!cTM) tbodyTM.innerHTML = vacio;
        if (!cTT) tbodyTT.innerHTML = vacio;
    } catch (e) { console.error('Error PINes:', e); }
}

function _colorGrado(g = '') {
    const gu = g.toUpperCase();
    if (gu.includes('III'))     return '#22c55e';
    if (gu.includes('II'))      return '#3b82f6';
    if (gu.includes('I AÑO'))   return '#f59e0b';
    if (gu.includes('ASPIGEN')) return '#a855f7';
    return '#94a3b8';
}

// ══════════════════════════════════════════════════════════════
// DATOS GENERALES
// ══════════════════════════════════════════════════════════════
async function loadServicio() {
    try {
        const [rMin, rAulas] = await Promise.all([fetch('/api/minutas'), fetch('/api/config_aula')]);
        const minutas = await rMin.json();
        const aulas = await rAulas.json();
        if (!rMin.ok) throw new Error(minutas.error || `Error cargando minutas (${rMin.status})`);
        if (!rAulas.ok) throw new Error(aulas.error || `Error cargando cronogramas (${rAulas.status})`);
        window.SIPA.globalMinutas      = Array.isArray(minutas) ? minutas : [];
        window.SIPA.configuracionAulas = Array.isArray(aulas) ? aulas : [];
        document.getElementById('f-mes').value   = '';
        document.getElementById('f-turno').value = '';
        actualizarAulasFiltro();
        filtrarHistorial();
    } catch (e) {
        window.SIPA.globalMinutas = [];
        window.SIPA.configuracionAulas = [];
        const historial = document.getElementById('historial-list');
        if (historial) historial.innerHTML = `<div class="empty-state" style="color:var(--peligro);">⚠️ No se pudieron cargar los datos: ${escapeHTML(e.message)}</div>`;
        mostrarToast(`Fallo al cargar datos: ${e.message}`, 'error');
        console.error('[loadServicio]', e);
    }
}
function cargarDatosServicio() { loadServicio(); }

// ══════════════════════════════════════════════════════════════
// FILTROS
// ══════════════════════════════════════════════════════════════
function actualizarAulasFiltro() {
    const turno  = document.getElementById('f-turno').value;
    const select = document.getElementById('f-aula');
    const actual = select.value;
    const aulas  = new Set();
    window.SIPA.configuracionAulas.forEach(c => { if (!turno || c.turno === turno) aulas.add(c.aula); });
    window.SIPA.globalMinutas.forEach(m     => { if (!turno || m.turno === turno) aulas.add(m.aula); });
    select.innerHTML = '<option value="">Todas las Aulas</option>';
    Array.from(aulas).sort().forEach(a => {
        select.innerHTML += `<option value="${a}" ${a===actual?'selected':''}>Aula ${a}</option>`;
    });
}

async function cargarAspirantesFiltro() {
    const aula  = document.getElementById('f-aula').value;
    const turno = document.getElementById('f-turno').value || 'TM';
    const sel   = document.getElementById('f-asp');
    sel.innerHTML = '<option value="">Padrón Completo</option>';
    if (!aula) return;
    try {
        const asp = await (await fetch(`/api/aspirantes?aula=${aula}&turno=${turno}`)).json();
        if (Array.isArray(asp)) {
            asp.forEach(a => { sel.innerHTML += `<option value="${a.nombre}">${a.grado} ${a.nombre}</option>`; });
        }
    } catch {}
}

function alSeleccionarAspirante() {
    if (document.getElementById('f-asp').value !== '') mostrarFojaAspirante();
    else document.getElementById('panel-reportes').style.display = 'none';
    filtrarHistorial();
}

// ══════════════════════════════════════════════════════════════
// ██  MONITOR TÁCTICO — GRILLA DE AULAS  ██
// ══════════════════════════════════════════════════════════════
function _docenteKey(docente, aula, turno) {
    const base = String(docente || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase();
    const tokens = base
        .replace(/[.\-/()]/g, ' ')
        .split(/[\s,]+/)
        .map(t => t.trim())
        .filter(Boolean)
        .sort();
    const limpio = tokens.join(' ');
    return `${limpio}|${String(aula || '').trim().toUpperCase()}|${String(turno || '').trim().toUpperCase()}`;
}

async function _leerRespuestaAulasDia(response) {
    const contentType = response.headers.get('content-type') || '';
    if (!contentType.toLowerCase().includes('application/json')) {
        if (response.status === 404) {
            throw new Error(
                'El servidor activo no tiene cargada la ruta del tablero. Reinicie SIPA con la versión actualizada y recargue la página (Ctrl+F5).'
            );
        }
        throw new Error(
            `El servidor respondió HTTP ${response.status} con una página HTML en vez de datos del tablero. Verifique que SIPA esté actualizado y que la sesión siga activa.`
        );
    }
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
}

async function cargarAulasDia(silencioso = false) {
    const grid = document.getElementById('aulas-dia-grid');
    if (!grid) return;
    if (_aulasDiaCargando) {
        _aulasDiaRecargar = true;
        return;
    }
    if (!window.SIPA?.suToken && !window.SIPA?.adminToken) {
        grid.innerHTML = '<div class="bd-error-banner">Inicie sesión en Plana Mayor o TIC para consultar las aulas.</div>';
        return;
    }
    _aulasDiaCargando = true;
    if (!silencioso) grid.innerHTML = '<div class="empty-state">Cargando estado operativo de las aulas…</div>';
    const fechaInput = document.getElementById('aulas-dia-fecha');
    const fecha = fechaInput?.value || obtenerFechaHoyLocal();
    if (fechaInput && !fechaInput.value) fechaInput.value = fecha;
    try {
        const response = await fetch(`/api/monitor/aulas-dia?fecha=${encodeURIComponent(fecha)}`, {
            headers: _headersCalendario(),
        });
        const data = await _leerRespuestaAulasDia(response);
        if ((fechaInput?.value || obtenerFechaHoyLocal()) !== fecha) {
            _aulasDiaRecargar = true;
            return;
        }
        window.SIPA.aulasDia = data;
        renderAulasDia();
        const actualizacion = document.getElementById('aulas-dia-actualizacion');
        if (actualizacion) {
            actualizacion.textContent = `📡 ${data.dia} ${data.fecha} · Actualizado ${new Date().toLocaleTimeString('es-AR', {hour:'2-digit',minute:'2-digit',second:'2-digit'})} · actualización automática cada 30 s`;
        }
        const seleccion = window.SIPA.aulaDiaSeleccionada;
        if (seleccion) await abrirDetalleAulaDia(seleccion.aula, seleccion.turno, true);
    } catch (error) {
        if (!silencioso || !window.SIPA?.aulasDia) {
            grid.innerHTML = `<div class="bd-error-banner">No se pudo cargar el tablero de aulas: ${_esc(error.message)}</div>`;
        }
        console.error('[cargarAulasDia]', error);
    } finally {
        _aulasDiaCargando = false;
        if (_aulasDiaRecargar) {
            _aulasDiaRecargar = false;
            cargarAulasDia(true);
        }
    }
}

function renderAulasDia() {
    const data = window.SIPA?.aulasDia;
    const grid = document.getElementById('aulas-dia-grid');
    if (!data || !grid) return;
    const aulas = Array.isArray(data.aulas) ? data.aulas : [];
    const turnFilter = document.getElementById('aulas-dia-turno')?.value || '';
    const stateFilter = document.getElementById('aulas-dia-estado')?.value || '';
    const firmas = aulas.reduce((total, aula) =>
        total + aula.clases.filter(clase => clase.estado === 'firmado').length, 0);
    const ausencias = aulas.reduce((total, aula) =>
        total + aula.clases.filter(clase => clase.estado === 'ausente').length, 0);
    const setKpi = (id, value) => {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    };
    setKpi('aulas-dia-kpi-activas', aulas.length);
    setKpi('aulas-dia-kpi-minutas', aulas.filter(aula => aula.minuta).length);
    setKpi('aulas-dia-kpi-firmas', firmas);
    setKpi('aulas-dia-kpi-ausencias', ausencias);

    const cierres = document.getElementById('aulas-dia-cierres');
    if (cierres) {
        cierres.innerHTML = data.cierres?.length
            ? `<div class="nota-info">📅 Cierres confirmados del día: ${data.cierres.map(c => {
                const alcance = c.alcance === 'institucion' ? 'Institución'
                    : c.alcance === 'turno' ? `Turno ${_esc(c.turno || '')}`
                        : `Aula ${_esc(c.aula || '')} · ${_esc(c.turno || '')}`;
                return `${alcance} — ${_esc(c.motivo || 'Sin motivo indicado')}`;
            }).join(' · ')}${aulas.length ? '' : ' · No hay clases activas'}</div>`
            : '';
    }
    const filtradas = aulas.filter(aula => {
        if (turnFilter && aula.turno !== turnFilter) return false;
        if (stateFilter === 'pendiente' && aula.minuta) return false;
        if (stateFilter === 'ausente' && !aula.clases.some(clase => clase.estado === 'ausente')) return false;
        if (stateFilter === 'firmado' && !aula.clases.some(clase => clase.estado === 'firmado')) return false;
        return true;
    });
    if (!filtradas.length) {
        grid.innerHTML = `<div class="empty-state"><span class="empty-state-icon">🏫</span><span class="empty-state-text">${aulas.length ? 'No hay aulas para los filtros seleccionados.' : 'No hay clases programadas para esta fecha.'}</span></div>`;
        return;
    }
    grid.innerHTML = filtradas.map(aula => {
        const clasesAusentes = aula.clases.filter(clase => clase.estado === 'ausente').length;
        const docentesFirmados = aula.clases.filter(clase => clase.estado === 'firmado').length;
        const docentesPendientes = aula.clases.filter(clase => clase.estado === 'pendiente').length;
        const estadoClass = clasesAusentes ? 'aulas-dia-card--alerta'
            : !aula.minuta ? 'aulas-dia-card--pendiente'
                : 'aulas-dia-card--ok';
        const etiqueta = clasesAusentes ? `${clasesAusentes} ausencia${clasesAusentes === 1 ? '' : 's'} informada${clasesAusentes === 1 ? '' : 's'}`
            : aula.minuta ? 'Minuta enviada' : 'Minuta pendiente';
        const docentes = aula.clases.map(clase => clase.docente).filter(Boolean);
        const resumenDocentes = [...new Set(docentes)];
        const estadoDocentes = docentesFirmados
            ? `${docentesFirmados} con firma${docentesFirmados === 1 ? '' : 's'}`
            : docentesPendientes ? `${docentesPendientes} pendiente${docentesPendientes === 1 ? '' : 's'}`
                : 'Sin firmas registradas';
        return `<button type="button" class="aulas-dia-card ${estadoClass}"
            data-aula="${_esc(aula.aula)}" data-turno="${_esc(aula.turno)}"
            onclick="abrirDetalleAulaDia(this.dataset.aula,this.dataset.turno)">
            <span class="aulas-dia-card-top"><strong>Aula ${_esc(aula.aula)}</strong><span>${_esc(aula.turno)}</span></span>
            <span class="aulas-dia-card-counts">
                <span><small>FE</small><b>${aula.fe ?? '—'}</b></span>
                <span><small>P</small><b>${aula.presentes ?? '—'}</b></span>
                <span><small>A</small><b>${aula.ausentes ?? '—'}</b></span>
            </span>
            <span class="aulas-dia-card-subjects">${aula.clases.length} clases programadas · ${_esc(estadoDocentes)}</span>
            <span class="aulas-dia-card-teachers">${resumenDocentes.length
                ? _esc(resumenDocentes.slice(0, 2).join(' · ')) + (resumenDocentes.length > 2 ? ` +${resumenDocentes.length - 2}` : '')
                : 'Sin docente asignado en cronograma'}</span>
            <span class="aulas-dia-card-status">${etiqueta}</span>
            <span class="aulas-dia-card-action">Ver cronograma, aspirantes y minuta →</span>
        </button>`;
    }).join('');
}

async function abrirDetalleAulaDia(aula, turno, silencioso = false) {
    const cont = document.getElementById('aulas-dia-detalle');
    if (!cont) return;
    window.SIPA.aulaDiaSeleccionada = { aula, turno };
    cont.style.display = '';
    cont.innerHTML = '<div class="empty-state">Cargando detalle del aula…</div>';
    const fecha = document.getElementById('aulas-dia-fecha')?.value || obtenerFechaHoyLocal();
    try {
        const params = new URLSearchParams({fecha, aula, turno});
        const response = await fetch(`/api/monitor/aulas-dia?${params}`, {
            headers: _headersCalendario(),
        });
        const data = await _leerRespuestaAulasDia(response);
        const detalle = data.aulas[0];
        if (!detalle) throw new Error('No hay cronograma activo para esta aula en la fecha seleccionada.');
        cont.innerHTML = _renderDetalleAulaDia(detalle, data.fecha);
        if (!silencioso) cont.scrollIntoView({behavior:'smooth', block:'start'});
    } catch (error) {
        cont.innerHTML = `<div class="bd-error-banner">No se pudo abrir el detalle: ${_esc(error.message)}</div>`;
        console.error('[abrirDetalleAulaDia]', error);
    }
}

function _renderDetalleAulaDia(aula, fecha) {
    const minuta = aula.minuta;
    const coberturas = aula.coberturas || [];
    const claseHtml = aula.clases.map(clase => {
        const cobertura = coberturas.find(item =>
            _docenteKey(item.titular, aula.aula, aula.turno) === _docenteKey(clase.docente, aula.aula, aula.turno)
            && _normalizarHoraVista(item.hora) === _normalizarHoraVista(clase.hora)
            && String(item.materia || '').toLowerCase() === String(clase.materia || '').toLowerCase()
        );
        const badge = clase.estado === 'firmado'
            ? `<span class="aulas-dia-state aulas-dia-state--ok">✅ Firmó ${_esc(clase.hora_firma)}</span>`
            : clase.estado === 'ausente'
                ? '<span class="aulas-dia-state aulas-dia-state--alerta">❌ Ausente informado en minuta</span>'
                : clase.estado === 'presente'
                    ? '<span class="aulas-dia-state aulas-dia-state--ok">✅ Presente en minuta</span>'
                    : '<span class="aulas-dia-state aulas-dia-state--pendiente">⏳ Firma pendiente</span>';
        const accionPgnp = clase.estado === 'ausente' && !cobertura
            ? `<button class="btn btn-primary btn-small"
                data-titular="${_esc(clase.docente)}" data-materia="${_esc(clase.materia)}"
                data-hora="${_esc(clase.hora)}" data-aula="${_esc(aula.aula)}"
                data-turno="${_esc(aula.turno)}" data-fecha="${_esc(fecha)}"
                onclick="prepararCoberturaDesdeAula(this)">👨‍🏫 Gestionar PGNP</button>`
            : cobertura
                ? `<span class="aulas-dia-state">${_esc(cobertura.estado)}${cobertura.pgnp ? ` · ${_esc(cobertura.pgnp)}` : ''}</span>`
                : '';
        return `<tr><td>${_esc(clase.hora)}</td><td>${_esc(clase.materia)}</td>
            <td>${_esc(clase.docente || 'Sin asignar')}</td><td>${badge}</td><td>${accionPgnp}</td></tr>`;
    }).join('');
    const aspirantes = aula.aspirantes || [];
    const ausentes = minuta?.ausentes || [];
    const ausentesHtml = ausentes.length
        ? `<ul class="aulas-dia-ausentes">${ausentes.map(item =>
            `<li><strong>${_esc(item.nombre || 'Sin nombre')}</strong> · ${_esc(item.causa || 'Sin causa')}${item.es_justificada === true ? ' · Justificada' : item.es_justificada === false ? ' · No justificada' : ''}</li>`
        ).join('')}</ul>`
        : '<p class="aulas-dia-muted">Sin aspirantes ausentes registrados en la minuta.</p>';
    return `<div class="aulas-dia-detail-header">
        <div><h3>Aula ${_esc(aula.aula)} · ${_esc(aula.turno)} · ${_esc(fecha)}</h3>
            <p>${minuta ? `Minuta enviada por ${_esc(minuta.bedel || 'Bedelía')} · ${_esc(minuta.fecha_carga || '')}` : 'Todavía no se envió la minuta de esta aula.'}</p>
        </div>
        <button class="btn btn-secondary btn-small" onclick="cerrarDetalleAulaDia()">Cerrar detalle</button>
    </div>
    <div class="aulas-dia-detail-kpis">
        <span><b>FE:</b> ${aula.fe ?? '—'}</span><span><b>P:</b> ${aula.presentes ?? '—'}</span>
        <span><b>A:</b> ${aula.ausentes ?? '—'}</span><span><b>Aspirantes:</b> ${aspirantes.length}</span>
    </div>
    <h4>📚 Cronograma y asistencia docente</h4>
    <div class="table-responsive"><table class="aulas-dia-detail-table">
        <thead><tr><th>Horario</th><th>Materia</th><th>Docente</th><th>Estado</th><th>Acción</th></tr></thead>
        <tbody>${claseHtml || '<tr><td colspan="5">Sin clases registradas.</td></tr>'}</tbody>
    </table></div>
    <div class="aulas-dia-detail-columns">
        <article><h4>🎓 Aspirantes del aula (${aspirantes.length})</h4>
            ${aspirantes.length ? `<ul>${aspirantes.map(item => `<li>${_esc(item.grado || '')} ${_esc(item.nombre)}</li>`).join('')}</ul>` : '<p class="aulas-dia-muted">No hay aspirantes cargados en el padrón.</p>'}
        </article>
        <article><h4>🚫 Ausencias de aspirantes</h4>${ausentesHtml}</article>
    </div>
    <article class="aulas-dia-novedades"><h4>📝 Novedades completas de la minuta</h4>
        <p>${minuta?.novedades ? _esc(minuta.novedades) : 'Sin novedades registradas.'}</p>
    </article>
    ${coberturas.length ? `<article class="aulas-dia-novedades"><h4>👨‍🏫 Coberturas PGNP</h4><ul>
        ${coberturas.map(item => `<li>${_esc(item.hora)} · ${_esc(item.materia)} · ${_esc(item.estado)}${item.pgnp ? ` · PGNP ${_esc(item.pgnp)}` : ''}${item.motivo ? ` · ${_esc(item.motivo)}` : ''}</li>`).join('')}
    </ul></article>` : ''}`;
}

function _normalizarHoraVista(hora) {
    return String(hora || '').replace(/\s/g, '').replace(/[–—]/g, '-').replace(/:/g, '').toLowerCase();
}

function cerrarDetalleAulaDia() {
    const cont = document.getElementById('aulas-dia-detalle');
    if (cont) {
        cont.style.display = 'none';
        cont.innerHTML = '';
    }
    window.SIPA.aulaDiaSeleccionada = null;
}

function prepararCoberturaDesdeAula(boton) {
    const nav = document.querySelector('#panel-admin > .sub-nav-container .sub-nav[onclick*="admin-coberturas"]');
    if (!nav) return mostrarToast('No se encontró el apartado de Coberturas PGNP.', 'error');
    mostrarPestanaAdmin('admin-coberturas', nav);
    document.getElementById('cob-fecha').value = boton.dataset.fecha;
    document.getElementById('cob-aula').value = boton.dataset.aula;
    document.getElementById('cob-turno').value = boton.dataset.turno;
    document.getElementById('cob-titular').value = boton.dataset.titular;
    document.getElementById('cob-materia').value = boton.dataset.materia;
    document.getElementById('cob-hora').value = boton.dataset.hora;
    cargarCoberturasDocente();
    document.getElementById('admin-coberturas')?.scrollIntoView({behavior:'smooth', block:'start'});
    mostrarToast('Complete el PGNP y envíe la solicitud de autorización.', 'info');
}

async function cargarAdelantosHorarioAdmin() {
    const lista = document.getElementById('admin-adelantos-horario-lista');
    const estado = document.getElementById('admin-adelantos-horario-estado');
    const boton = document.getElementById('btn-toggle-adelantos-horario');
    if (!lista) return;
    lista.innerHTML = '<div class="empty-state">Cargando historial de adelantos…</div>';
    try {
        const response = await fetch('/api/plana_mayor/adelantos-horario', {
            headers: _headersCalendario(),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        window.SIPA.adelantosHorarioActivo = !!data.activo;
        if (estado) {
            estado.innerHTML = data.activo
                ? '<span class="badge-verde">✅ Adelantos automáticos ACTIVADOS</span><p>Las nuevas solicitudes se aplican sin autorización previa y quedan disponibles en este historial.</p>'
                : '<span class="badge-mini">🔒 Adelantos DESACTIVADOS</span><p>Los docentes no pueden enviar nuevos adelantos. Los ya aplicados mantienen su horario hasta que sean revocados.</p>';
        }
        if (boton) {
            boton.style.display = window.SIPA?.suToken ? '' : 'none';
            boton.className = data.activo ? 'btn btn-danger' : 'btn btn-success';
            boton.textContent = data.activo ? '⏸️ Desactivar adelantos' : '▶️ Activar adelantos automáticos';
        }
        const casos = Array.isArray(data.casos) ? data.casos : [];
        lista.innerHTML = casos.length ? `<div style="display:grid;gap:10px;">${casos.map(caso => {
            const puedeRevocar = caso.estado === 'aplicado' && caso.fecha_original >= obtenerFechaHoyLocal()
                && caso.fecha_nueva >= obtenerFechaHoyLocal();
            const estadoCaso = caso.estado === 'aplicado'
                ? '<span class="badge-verde">Aplicado automáticamente</span>'
                : `<span class="badge-mini">Revocado por ${_esc(caso.revocado_por || 'Plana Mayor')}</span>`;
            return `<article class="card" style="margin:0;padding:14px;border:1px solid var(--borde);">
                <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start;flex-wrap:wrap;">
                    <strong>${_esc(caso.docente)} · Aula ${_esc(caso.aula)} (${_esc(caso.turno)})</strong>${estadoCaso}
                </div>
                <div style="margin-top:7px;"><strong>${_esc(caso.materia)}</strong></div>
                <div style="font-size:.9em;color:var(--texto-suave);margin-top:4px;">
                    Original: ${_esc(caso.fecha_original)} · ${_esc(caso.hora_original)}
                    → Adelantada: ${_esc(caso.fecha_nueva)} · ${_esc(caso.hora_nueva)}
                </div>
                <div style="font-size:.82em;color:var(--texto-tenue);margin-top:4px;">
                    Aplicado: ${_esc(caso.creado_en || '')}${caso.revocado_en ? ` · Revocado: ${_esc(caso.revocado_en)}` : ''}
                </div>
                ${puedeRevocar ? `<button class="btn btn-warning btn-small" style="margin-top:10px;" onclick="revocarAdelantoHorario(${Number(caso.id)})">↩️ Revocar cambio</button>` : ''}
            </article>`;
        }).join('')}</div>` : '<div class="empty-state">Todavía no hay adelantos registrados.</div>';
    } catch (error) {
        lista.innerHTML = `<div class="bd-error-banner">No se pudo cargar el historial: ${_esc(error.message)}</div>`;
        console.error('[cargarAdelantosHorarioAdmin]', error);
    }
}

async function toggleAdelantosHorario() {
    if (!window.SIPA?.suToken) {
        return mostrarToast('Solo TIC puede activar o desactivar los adelantos automáticos.', 'error');
    }
    const activo = !window.SIPA.adelantosHorarioActivo;
    const mensaje = activo
        ? 'Al activar, las solicitudes nuevas se aplicarán automáticamente sin autorización previa y quedarán registradas para revisión. ¿Continuar?'
        : 'Al desactivar, se bloquearán nuevas solicitudes. Los adelantos ya aplicados no se revertirán automáticamente. ¿Continuar?';
    if (!confirm(mensaje)) return;
    try {
        const response = await fetch('/api/su/adelantos-horario', {
            method: 'POST',
            headers: _headersCalendario(true),
            body: JSON.stringify({activo}),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        mostrarToast(data.msj, 'success');
        await cargarAdelantosHorarioAdmin();
    } catch (error) {
        mostrarToast(error.message, 'error');
    }
}

async function revocarAdelantoHorario(id) {
    if (!confirm('¿Revocar este cambio? El horario original volverá a regir si todavía no hay minutas ni firmas en las fechas afectadas.')) return;
    try {
        const response = await fetch(`/api/plana_mayor/adelantos-horario/${Number(id)}/revocar`, {
            method: 'POST',
            headers: _headersCalendario(true),
            body: JSON.stringify({}),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        mostrarToast(data.msj, 'success');
        await cargarAdelantosHorarioAdmin();
    } catch (error) {
        mostrarToast(error.message, 'error');
    }
}

async function refrescarMonitor(silencioso = false) {
    const btn    = document.getElementById('btn-refrescar');
    const monEl  = document.getElementById('monitor-firmas');
    const ultAct = document.getElementById('monitor-ult-act');
    const orig   = btn ? btn.innerHTML : '';

    if (!silencioso && btn) {
        btn.disabled  = true;
        btn.innerHTML = '<span class="spin">🔄</span> Actualizando…';
    }

    try {
        const hoy  = obtenerFechaHoyLocal();
        const turnoFiltro = document.getElementById('monitor-filtro-turno')?.value || '';
        const estadoFiltro = document.getElementById('monitor-filtro-estado')?.value || '';

        const [resConfig, resFirmas, resInasis] = await Promise.all([
            fetch('/api/config_aula'),
            fetch(`/api/firmas_docentes?fecha=${hoy}`, { headers: _headersCalendario() }),
            fetch(`/api/inasistencias?desde=${hoy}&hasta=${hoy}&incluir_justificadas=1`),
        ]);

        const config = resConfig.ok ? await resConfig.json() : [];
        const firmas = resFirmas.ok ? await resFirmas.json() : [];
        const inasis = resInasis.ok ? await resInasis.json() : [];

        // Mapa firma: "docente|aula|turno" → firma
        const mapaFirmas = {};
        firmas.forEach(f => {
            mapaFirmas[_docenteKey(f.docente, f.aula, f.turno)] = f;
        });
        // Mapa de justificaciones pendientes: "docente|aula|turno" → motivo
        const mapaJustifPendientes = {};
        inasis.forEach(i => {
            if (i.estado === 'pendiente_aprobacion') {
                mapaJustifPendientes[_docenteKey(i.docente, i.aula, i.turno)] = i;
            }
        });
        window._mapaJustifPendientes = mapaJustifPendientes; // accesible desde _renderTarjetaAula

        const now             = new Date();
        const diaSem          = ['Domingo','Lunes','Martes','Miércoles','Jueves','Viernes','Sábado'][now.getDay()];
        const ocultarVencidos = document.getElementById('monitor-ocultar-finalizados')?.checked ?? true;

        // Filtrar solo bloques de hoy
        const bloquesDelDia = config.filter(b => b.dia === diaSem && b.doc);

        // Filtro temporal: descartar bloques cuyo plazo de firma venció hace más de 45 min
        const bloquesHoy = ocultarVencidos
            ? bloquesDelDia.filter(b => !_estaFinalizado(b, now))
            : bloquesDelDia;
        const ocultados  = bloquesDelDia.length - bloquesHoy.length;

        // Aplicar filtros del panel (turno/estado)
        const bloquesFiltrados = bloquesHoy.filter(b => {
            if (turnoFiltro && b.turno !== turnoFiltro) return false;
            if (estadoFiltro) {
                const estado = _estadoBloque(b, mapaFirmas, now);
                if (estado !== estadoFiltro) return false;
            }
            return true;
        });

        // ── KPIs (sobre la ventana operativa, no sobre todo el día) ─
        let kPuntuales = 0, kTardios = 0, kAlertas = 0, kSinDatos = 0;
        bloquesHoy.forEach(b => {
            const e = _estadoBloque(b, mapaFirmas, now);
            if (e === 'verde')    kPuntuales++;
            else if (e === 'amarillo') kTardios++;
            else if (e === 'rojo' || e === 'pendiente_justif') kAlertas++;
            else                       kSinDatos++;
        });

        _actualizarKPI('kpi-total',      bloquesHoy.length);
        _actualizarKPI('kpi-puntuales',  kPuntuales);
        _actualizarKPI('kpi-tardios',    kTardios);
        _actualizarKPI('kpi-alertas',    kAlertas);

        // ── Grilla ────────────────────────────────────────────
        if (!bloquesFiltrados.length) {
            const mensaje = bloquesDelDia.length === 0
                ? 'Sin clases configuradas para hoy. Cargue cronogramas en Configuración.'
                : (bloquesHoy.length === 0
                    ? `Todos los bloques de hoy ya finalizaron (${ocultados} ocultos). Desactive el switch para verlos.`
                    : 'Sin resultados para los filtros seleccionados.');
            monEl.innerHTML = `
                <div class="empty-state" style="padding:40px;">
                    <span class="empty-state-icon">📡</span>
                    <span class="empty-state-text">${mensaje}</span>
                </div>`;
        } else {
            const aviso = ocultados > 0
                ? `<div class="monitor-aviso-ocultos">⏰ ${ocultados} bloque(s) ocultos por estar finalizados hace más de 45 min. <a href="javascript:void(0)" onclick="document.getElementById('monitor-ocultar-finalizados').checked=false;refrescarMonitor();">Mostrar todos</a>.</div>`
                : '';
            monEl.innerHTML = aviso + `<div class="monitor-grid">${
                bloquesFiltrados.map(b => _renderTarjetaAula(b, mapaFirmas, now)).join('')
            }</div>`;
        }

        // Timestamp
        if (ultAct) {
            ultAct.textContent = `Últ. Act: ${now.toLocaleTimeString('es-AR', {hour:'2-digit', minute:'2-digit'})}`;
        }

        // Registro de firmas
        await _renderRegistroFirmas(firmas, hoy);

    } catch (e) {
        if (!silencioso) {
            monEl.innerHTML = `<div class="empty-state" style="padding:30px;color:var(--peligro);">Error: ${e.message}</div>`;
        }
    } finally {
        if (btn) { btn.disabled = false; btn.innerHTML = orig; }
    }
}

function _estadoBloque(b, mapaFirmas, now) {
    const key   = _docenteKey(b.doc, b.aula, b.turno);
    const firma = mapaFirmas[key];
    const justifPend = (window._mapaJustifPendientes || {})[key];
    const ini   = _parseHoraInicio(b.hora, now);
    const finT  = _parseFinConTolerancia(b.hora, now, 10);   // fin de clase + 10 min

    if (justifPend && !firma) {
        return 'pendiente_justif';
    }

    if (firma) {
        const firmaMs = _firmaAMs(firma.hora_firma, now);
        if (!finT || !firmaMs) return 'verde';
        // 🟢 Firmó dentro de la materia o dentro de la tolerancia (fin + 10 min)
        // 🟡 Firmó después de la tolerancia
        return firmaMs > finT ? 'amarillo' : 'verde';
    }

    // Sin firma
    if (!ini || !finT) return 'sin-datos';
    if (now < ini)     return 'sin-datos';   // clase no empezó
    if (now > finT)    return 'rojo';        // pasó la tolerancia → no firmó
    return 'sin-datos';                       // en curso, esperando firma
}

function _parseHoraAMs(horaStr, offsetMin, base) {
    if (!horaStr) return null;
    // Acepta "0720", "07:20", "7:20", "07.20" — extrae sólo dígitos
    const norm = String(horaStr).replace(/[^\d]/g, '');
    if (norm.length < 3) return null;
    const padded = norm.padStart(4, '0');
    const hh = parseInt(padded.substring(0,2));
    const mm = parseInt(padded.substring(2,4));
    if (isNaN(hh) || isNaN(mm)) return null;
    const d = new Date(base);
    d.setHours(hh, mm + offsetMin, 0, 0);
    return d;
}

/** Hora de inicio de la clase como Date. */
function _parseHoraInicio(hora, base) {
    const ini = (hora || '').split('-')[0] || '';
    return _parseHoraAMs(ini, 0, base);
}

/** Hora de fin de la clase + N minutos de tolerancia. */
function _parseFinConTolerancia(hora, base, tolMin = 10) {
    const fin = (hora || '').split('-')[1] || '';
    return _parseHoraAMs(fin, tolMin, base);
}

/**
 * Bloque "finalizado": pasaron más de 45 minutos desde el fin de la tolerancia
 * (fin de clase + 10 min). Se usa para ocultar clases ya consumadas del Turno
 * Mañana cuando estamos operativos en el Turno Tarde, etc.
 */
function _estaFinalizado(b, now) {
    const finT = _parseFinConTolerancia(b.hora, now, 10);
    if (!finT) return false;
    return (now - finT) > 45 * 60 * 1000; // 45 min después de la tolerancia
}

function _firmaAMs(horaFirma, base) {
    if (!horaFirma) return null;
    const partes = horaFirma.split(':');
    const d = new Date(base);
    d.setHours(parseInt(partes[0]||0), parseInt(partes[1]||0), parseInt(partes[2]||0), 0);
    return d;
}

function _renderTarjetaAula(b, mapaFirmas, now) {
    const key    = _docenteKey(b.doc, b.aula, b.turno);
    const firma  = mapaFirmas[key];
    let   estado = _estadoBloque(b, mapaFirmas, now);

    // Si hay una justificación pendiente del docente → estado especial "pendiente_justif"
    const justifPend = (window._mapaJustifPendientes || {})[key];
    if (justifPend && !firma) {
        estado = 'pendiente_justif';
    }

    const horaDisplay  = (b.hora || '').replace('-', ' – ').replace(/(\d{2}):(\d{2})/g, '$1:$2');
    const horaFirmaStr = firma?.hora_firma ? firma.hora_firma.substring(0,5) : null;

    const estilos = {
        'verde':             { borde: '#16a34a', bg: '#f0fdf4', badge: '🟢 A TIEMPO',           badgeCls: 'monitor-badge--verde' },
        'amarillo':          { borde: '#d97706', bg: '#fffbeb', badge: '🟡 TARDÍO',             badgeCls: 'monitor-badge--amarillo' },
        'rojo':              { borde: '#dc2626', bg: '#fef2f2', badge: '🔴 NO FIRMÓ',           badgeCls: 'monitor-badge--rojo parpadeante' },
        'pendiente_justif':  { borde: '#f59e0b', bg: '#fffbeb', badge: '⏳ JUSTIF. PENDIENTE',  badgeCls: 'monitor-badge--amarillo parpadeante' },
        'sin-datos':         { borde: '#94a3b8', bg: '#f8fafc', badge: '⬜ PENDIENTE',          badgeCls: 'monitor-badge--gris' },
    };
    const st = estilos[estado] || estilos['sin-datos'];

    let infoFirma = '';
    if (firma) {
        infoFirma = `<div class="monitor-firma-hora">Firmó ${horaFirmaStr}</div>`;
    } else if (estado === 'pendiente_justif') {
        infoFirma = `<div class="monitor-firma-hora" style="color:var(--advertencia);" title="${_esc(justifPend.comentario||'')}">📋 ${_esc(justifPend.motivo||'')}</div>`;
    } else if (estado === 'rojo') {
        const lim = _parseFinConTolerancia(b.hora, now, 10);
        const limStr = lim ? `${String(lim.getHours()).padStart(2,'0')}:${String(lim.getMinutes()).padStart(2,'0')}` : '--:--';
        infoFirma = `<div class="monitor-firma-hora" style="color:var(--peligro);">Vencido a las ${limStr}</div>`;
    }

    // Apellido del docente para mostrar compacto, pero conservamos el completo en el tooltip
    const docFull  = b.doc || '—';
    const docCorto = docFull.split(',')[0] || docFull;
    const asigFull = b.asig || '—';

    // Tooltip resumido al hacer hover sobre la tarjeta entera
    const tooltipCard = `Aula ${b.aula} (${b.turno}) — ${horaDisplay}\n${asigFull}\n${docFull}`;

    return `
    <div class="monitor-aula-card has-tooltip" style="border-color:${st.borde};background:${st.bg};"
         title="${_esc(tooltipCard)}">
        <div class="monitor-aula-header">
            <div>
                <div class="monitor-aula-num">Aula ${b.aula}</div>
                <div class="monitor-aula-turno">${b.turno}</div>
            </div>
            <div class="monitor-hora-chip">${horaDisplay}</div>
        </div>
        <div class="monitor-aula-materia" title="${_esc(asigFull)}">${asigFull}</div>
        <div class="monitor-aula-doc"     title="${_esc(docFull)}">👤 ${docCorto}</div>
        <div class="monitor-aula-footer">
            <span class="monitor-badge ${st.badgeCls}">${st.badge}</span>
            ${infoFirma}
        </div>
    </div>`;
}

// Escapa comillas y caracteres especiales para uso seguro en atributos HTML
function _esc(s) {
    return String(s)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

function _actualizarKPI(id, valor) {
    const el = document.getElementById(id);
    if (el) {
        el.textContent = valor;
        el.classList.add('kpi-pulse');
        setTimeout(() => el.classList.remove('kpi-pulse'), 400);
    }
}

async function _renderRegistroFirmas(firmas, hoy) {
    const cont = document.getElementById('registro-firmas-hoy');
    if (!cont) return;
    if (!firmas.length) {
        cont.innerHTML = `<div style="text-align:center;padding:24px;color:var(--texto-tenue);">Sin firmas registradas hoy.</div>`;
        return;
    }
    const rows = firmas.map(f => `
        <tr>
            <td style="font-weight:600;color:var(--azul-oscuro);">${_esc(f.docente)}</td>
            <td><span class="chip">Aula ${_esc(f.aula)} · ${_esc(f.turno)}</span></td>
            <td><span class="puntualidad-verde">✅ Presente</span></td>
            <td style="font-family:'DM Mono',monospace;color:var(--verde-inst);font-weight:600;">${(f.hora_firma||'--:--').substring(0,5)}</td>
            <td>${_renderGeolocalizacionFirma(f)}</td>
        </tr>`).join('');
    cont.innerHTML = `<div class="table-responsive" style="margin-top:0;"><table>
        <thead><tr><th>Docente</th><th>Aula</th><th>Estado</th><th>Hora Firma</th><th>Geolocalización</th></tr></thead>
        <tbody>${rows}</tbody>
    </table></div>`;
}

function _renderGeolocalizacionFirma(firma) {
    if (firma.lat === null || firma.lat === undefined || firma.lat === ''
        || firma.lng === null || firma.lng === undefined || firma.lng === '') {
        return '<span style="color:var(--texto-tenue);">No disponible</span>';
    }
    const lat = Number(firma.lat);
    const lng = Number(firma.lng);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
        return '<span style="color:var(--texto-tenue);">No disponible</span>';
    }
    const coords = `${lat.toFixed(6)}, ${lng.toFixed(6)}`;
    const mapa = `https://www.google.com/maps?q=${encodeURIComponent(`${lat},${lng}`)}`;
    const precision = Number.isFinite(Number(firma.precision_m))
        ? ` ±${Math.round(Number(firma.precision_m))} m` : '';
    const geoEstado = {
        dentro: '<span style="color:#15803d;font-weight:700;">🟢 Dentro del radio</span>',
        fuera: '<span style="color:#b91c1c;font-weight:700;">🔴 Fuera del radio</span>',
        sin_configurar: '<span style="color:#a16207;font-weight:700;">🟡 Radio sin configurar</span>',
        invalida: '<span style="color:#b91c1c;font-weight:700;">⚠️ Coordenada inválida</span>',
    }[firma.geo_estado] || '';
    return `<span style="font-family:'DM Mono',monospace;font-size:.82em;">📍 ${coords}${precision}</span>
        <span style="display:block;font-size:.78em;margin-top:3px;">${geoEstado}</span>
        <a class="btn btn-info btn-small" href="${mapa}" target="_blank" rel="noopener noreferrer"
           style="margin-left:6px;padding:4px 8px;">Mapa</a>`;
}

async function cargarRegistroFirmasHoy() {
    const cont = document.getElementById('registro-firmas-hoy');
    if (!cont) return;
    cont.innerHTML = `<p style="text-align:center;color:var(--texto-tenue);padding:16px;"><span class="spin">🔄</span> Cargando…</p>`;
    const fecha = document.getElementById('reg-fecha')?.value  || obtenerFechaHoyLocal();
    const aula  = document.getElementById('reg-aula')?.value.trim()   || '';
    const turno = document.getElementById('reg-turno')?.value  || '';
    const docente = document.getElementById('reg-docente')?.value.trim() || '';
    let url = `/api/firmas_docentes?fecha=${encodeURIComponent(fecha)}`;
    if (aula)  url += `&aula=${encodeURIComponent(aula)}`;
    if (turno) url += `&turno=${encodeURIComponent(turno)}`;
    if (docente) url += `&docente=${encodeURIComponent(docente)}`;

    const filtroTxt = [
        formatearFechaElegante(fecha),
        aula  ? `Aula ${aula.toUpperCase()}` : null,
        turno ? `Turno ${turno}`             : null,
    ].filter(Boolean).join(' · ');

    try {
        const r = await fetch(url, { headers: _headersCalendario() });
        if (!r.ok) {
            let detalle = `HTTP ${r.status}`;
            try { const j = await r.json(); detalle = j.error || detalle; } catch {}
            cont.innerHTML = `<div class="empty-state" style="border-color:var(--peligro-cl);color:var(--peligro);">
                <span class="empty-state-icon">⚠️</span>
                <span class="empty-state-text">No se pudo obtener el registro: ${detalle}</span></div>`;
            console.error('[firmas_docentes] respuesta no OK:', r.status, detalle);
            return;
        }

        const firmas = await r.json();
        if (!Array.isArray(firmas) || firmas.length === 0) {
            cont.innerHTML = `<div class="empty-state">
                <span class="empty-state-icon">📋</span>
                <span class="empty-state-text">Sin firmas registradas para los filtros seleccionados.</span>
                <div style="font-size:.82em;color:var(--texto-tenue);margin-top:8px;">${filtroTxt}</div>
            </div>`;
            return;
        }
        await _renderRegistroFirmas(firmas, fecha);
    } catch (e) {
        console.error('[cargarRegistroFirmasHoy]', e);
        cont.innerHTML = `<div class="empty-state" style="border-color:var(--peligro-cl);color:var(--peligro);">
            <span class="empty-state-icon">⚠️</span>
            <span class="empty-state-text">Error de conexión: ${e.message}</span></div>`;
    }
}

async function cargarUbicacionesFirmasTIC() {
    const cont = document.getElementById('geo-firmas-resultados');
    if (!cont) return;
    if (!window.SIPA?.suToken) {
        cont.innerHTML = '<div class="bd-error-banner">Esta consulta requiere una sesión TIC activa.</div>';
        return;
    }
    const hoy = obtenerFechaHoyLocal();
    const desde = document.getElementById('geo-firmas-desde');
    const hasta = document.getElementById('geo-firmas-hasta');
    if (desde && !desde.value) desde.value = hoy;
    if (hasta && !hasta.value) hasta.value = hoy;
    const params = new URLSearchParams({
        desde: desde?.value || hoy,
        hasta: hasta?.value || hoy,
    });
    const aula = document.getElementById('geo-firmas-aula')?.value.trim() || '';
    const turno = document.getElementById('geo-firmas-turno')?.value || '';
    const docente = document.getElementById('geo-firmas-docente')?.value.trim() || '';
    if (aula) params.set('aula', aula);
    if (turno) params.set('turno', turno);
    if (docente) params.set('docente', docente);
    cont.innerHTML = '<div class="empty-state">Consultando firmas…</div>';
    try {
        const response = await fetch(`/api/su/firmas/ubicaciones?${params}`, {
            headers: { 'X-SU-Token': window.SIPA.suToken },
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        if (!data.firmas.length) {
            cont.innerHTML = '<div class="empty-state"><span class="empty-state-icon">📭</span><span class="empty-state-text">No hay firmas para los filtros seleccionados.</span></div>';
            return;
        }
        const filas = data.firmas.map(firma => {
            const hayCoordenadas = firma.lat !== null && firma.lat !== undefined
                && firma.lng !== null && firma.lng !== undefined;
            const ubicacion = hayCoordenadas
                ? `<a href="https://www.google.com/maps?q=${encodeURIComponent(`${firma.lat},${firma.lng}`)}" target="_blank" rel="noopener noreferrer">📍 ${Number(firma.lat).toFixed(6)}, ${Number(firma.lng).toFixed(6)}</a>
                    ${firma.precision_m !== null && firma.precision_m !== undefined
                        ? `<small style="display:block;color:var(--texto-suave);">Precisión ±${Math.round(Number(firma.precision_m))} m</small>` : ''}`
                : '<span style="color:var(--texto-tenue);">Ubicación no disponible</span>';
            return `<tr>
                <td>${_esc(firma.fecha)}</td>
                <td style="font-family:'DM Mono',monospace;">${_esc(firma.hora_firma || '--:--')}</td>
                <td><strong>${_esc(firma.docente)}</strong></td>
                <td>Aula ${_esc(firma.aula)} · ${_esc(firma.turno)}</td>
                <td>${ubicacion}</td>
            </tr>`;
        }).join('');
        cont.innerHTML = `${data.limite_alcanzado
            ? '<div class="nota-info" style="margin-bottom:10px;">Se muestran las 500 firmas más recientes. Reduzca el rango para consultar más específicamente.</div>' : ''}
            <div class="table-responsive"><table>
                <thead><tr><th>Fecha</th><th>Hora</th><th>Docente</th><th>Aula / Turno</th><th>Ubicación</th></tr></thead>
                <tbody>${filas}</tbody>
            </table></div>`;
    } catch (error) {
        cont.innerHTML = `<div class="bd-error-banner">No se pudieron consultar las ubicaciones: ${_esc(error.message)}</div>`;
        console.error('[cargarUbicacionesFirmasTIC]', error);
    }
}

function exportarFirmasDocentes() {
    const fecha = document.getElementById('reg-fecha')?.value || obtenerFechaHoyLocal();
    const aula = document.getElementById('reg-aula')?.value.trim() || '';
    const turno = document.getElementById('reg-turno')?.value || '';
    const docente = document.getElementById('reg-docente')?.value.trim() || '';
    const params = new URLSearchParams({desde: fecha, hasta: fecha});
    if (aula) params.set('aula', aula);
    if (turno) params.set('turno', turno);
    if (docente) params.set('docente', docente);
    const token = window.SIPA?.suToken || window.SIPA?.adminToken || '';
    const header = window.SIPA?.suToken ? 'X-SU-Token' : 'X-Admin-Token';
    fetch(`/api/firmas_docentes/export?${params}`, {headers: {[header]: token}})
        .then(async r => {
            if (!r.ok) {
                const detalle = await r.json().catch(() => ({}));
                throw new Error(detalle.error || 'No se pudo exportar');
            }
            return r.blob();
        })
        .then(blob => {
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `firmas_docentes_${fecha}.csv`;
            a.click();
            URL.revokeObjectURL(url);
            mostrarToast('✅ Exportación generada.', 'success');
        })
        .catch(e => mostrarToast(`❌ ${e.message}`, 'error'));
}

function exportarReporteOperativo() {
    const mes = document.getElementById('f-mes')?.value || obtenerFechaHoyLocal().slice(0, 7);
    const turno = document.getElementById('f-turno')?.value || '';
    const aula = document.getElementById('f-aula')?.value || '';
    const [anio, mesNumero] = mes.split('-').map(Number);
    const desde = `${mes}-01`;
    const ultimoDia = new Date(anio, mesNumero, 0).getDate();
    const hasta = `${mes}-${String(ultimoDia).padStart(2, '0')}`;
    const params = new URLSearchParams({desde, hasta});
    if (turno) params.set('turno', turno);
    if (aula) params.set('aula', aula);
    const token = window.SIPA?.suToken || window.SIPA?.adminToken || '';
    const header = window.SIPA?.suToken ? 'X-SU-Token' : 'X-Admin-Token';
    fetch(`/api/reporte_operativo/export?${params}`, {headers: {[header]: token}})
        .then(async r => {
            if (!r.ok) {
                const detalle = await r.json().catch(() => ({}));
                throw new Error(detalle.error || 'No se pudo generar el reporte');
            }
            return r.blob();
        })
        .then(blob => {
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `reporte_operativo_${desde}_${hasta}.csv`;
            a.click();
            URL.revokeObjectURL(url);
            mostrarToast('✅ Reporte operativo generado.', 'success');
        })
        .catch(e => mostrarToast(`❌ ${e.message}`, 'error'));
}

function imprimirReporteOperativo() {
    const mes = document.getElementById('f-mes')?.value || obtenerFechaHoyLocal().slice(0, 7);
    const turno = document.getElementById('f-turno')?.value || '';
    const aula = document.getElementById('f-aula')?.value || '';
    const [anio, mesNumero] = mes.split('-').map(Number);
    const desde = `${mes}-01`;
    const hasta = `${mes}-${String(new Date(anio, mesNumero, 0).getDate()).padStart(2, '0')}`;
    const params = new URLSearchParams({desde, hasta});
    if (turno) params.set('turno', turno);
    if (aula) params.set('aula', aula);
    const token = window.SIPA?.suToken || window.SIPA?.adminToken || '';
    const header = window.SIPA?.suToken ? 'X-SU-Token' : 'X-Admin-Token';
    fetch(`/api/reporte_operativo/print?${params}`, {headers: {[header]: token}})
        .then(async r => {
            if (!r.ok) {
                const detalle = await r.json().catch(() => ({}));
                throw new Error(detalle.error || 'No se pudo preparar el documento');
            }
            return r.text();
        })
        .then(documento => {
            const ventana = window.open('', '_blank');
            if (!ventana) throw new Error('El navegador bloqueó la ventana. Permita ventanas emergentes.');
            ventana.document.open();
            ventana.document.write(documento);
            ventana.document.close();
        })
        .catch(e => mostrarToast(`❌ ${e.message}`, 'error'));
}

// ══════════════════════════════════════════════════════════════
// HISTORIAL
// ══════════════════════════════════════════════════════════════
function filtrarHistorial() {
    const mes   = document.getElementById('f-mes').value;
    const aula  = document.getElementById('f-aula').value.toUpperCase();
    const asp   = document.getElementById('f-asp').value.toUpperCase();
    const turno = document.getElementById('f-turno').value;
    const cont  = document.getElementById('historial-list');
    cont.innerHTML = '';

    const filtradas = window.SIPA.globalMinutas.filter(m =>
        (!mes   || m.fecha.substring(0,7) === mes) &&
        (!aula  || m.aula  === aula)  &&
        (!turno || m.turno === turno) &&
        (!asp   || (m.ausentes && m.ausentes.some(a => a.nombre?.toUpperCase().includes(asp))))
    );

    const map = {};
    filtradas.forEach(m => {
        const k = `${m.aula}-${m.turno}`;
        if (!map[k]) map[k] = [];
        map[k].push(m);
    });

    Object.keys(map).sort().forEach(k => {
        const lista = map[k];
        const divId = `hist-${k.replace(/\s+/g,'-')}`;
        let html = `<div class="card" style="border-top:4px solid var(--azul-primario);background:white;">`;
        html += `<h4 style="margin-top:0;color:var(--azul-oscuro);font-size:1.1em;">Última Actualización</h4>`;
        html += generarTarjetaMinuta(lista[0],'VIGENTE','var(--exito-cl)');
        if (lista.length > 1) {
            html += `<button class="btn btn-secondary btn-full" style="margin-top:10px;"
                onclick="const d=document.getElementById('${divId}');d.style.display=d.style.display==='none'?'block':'none'">
                Explorar Archivo (${lista.length-1} planillas) ▼</button>`;
            html += `<div id="${divId}" style="display:none;margin-top:15px;padding-top:15px;border-top:2px dashed var(--borde);">`;
            lista.slice(1).forEach(ant => { html += generarTarjetaMinuta(ant,'ARCHIVO','var(--texto-tenue)'); });
            html += `</div>`;
        }
        html += `</div>`;
        cont.innerHTML += html;
    });

    if (!Object.keys(map).length) {
        cont.innerHTML = `<div class="empty-state"><span class="empty-state-icon">🗂️</span><span class="empty-state-text">Sin registros para los filtros seleccionados.</span></div>`;
    }
}

function generarTarjetaMinuta(m, etiqueta, colorEtiq) {
    const jsonStr = encodeURIComponent(JSON.stringify(m));
    const ausText = (m.ausentes && m.ausentes.length > 0)
        ? m.ausentes.map(a => `${a.tipo||''} ${a.nombre} (${a.causa||'S/C'})`).join(' | ')
        : '✅ Sin Novedad';
    return `
    <div style="border:1px solid #e2e8f0;padding:18px;border-radius:8px;margin-bottom:12px;background:#f8fafc;">
        <div style="display:flex;justify-content:space-between;flex-wrap:wrap;gap:10px;margin-bottom:12px;border-bottom:1px solid #e2e8f0;padding-bottom:12px;">
            <div style="display:flex;align-items:center;gap:10px;">
                <span style="background:${colorEtiq};color:white;padding:3px 8px;border-radius:4px;font-size:.74em;font-weight:bold;">${etiqueta}</span>
                <strong style="color:var(--azul-oscuro);">Aula ${m.aula} (${m.turno})</strong>
            </div>
            <div style="display:flex;gap:12px;align-items:center;">
                <span style="color:var(--texto-suave);font-size:.9em;">${formatearFechaElegante(m.fecha)}</span>
                <button class="btn btn-whatsapp" style="padding:5px 10px;font-size:1em;box-shadow:none;"
                    onclick="enviarMensajeWhatsApp(JSON.parse(decodeURIComponent('${jsonStr}')))">💬</button>
            </div>
        </div>
        <div style="font-size:.9em;margin-bottom:12px;color:var(--texto-suave);display:flex;gap:18px;flex-wrap:wrap;">
            <span>👤 <b>Bedel:</b> ${m.bedel||'—'}</span>
            <span>👤 <b>Sub:</b> ${m.sub_bedel||'—'}</span>
        </div>
        <div class="grid-small" style="background:white;padding:12px;border-radius:8px;text-align:center;margin-bottom:12px;border:1px solid #e2e8f0;">
            <div><span style="color:#94a3b8;font-size:.82em;text-transform:uppercase;font-weight:600;display:block;margin-bottom:4px;">F.E.</span><b style="font-size:1.4em;color:var(--azul-primario);">${m.fe}</b></div>
            <div style="border-left:1px solid #e2e8f0;border-right:1px solid #e2e8f0;"><span style="color:#94a3b8;font-size:.82em;text-transform:uppercase;font-weight:600;display:block;margin-bottom:4px;">Presentes</span><b style="font-size:1.4em;color:var(--exito-cl);">${m.presentes}</b></div>
            <div><span style="color:#94a3b8;font-size:.82em;text-transform:uppercase;font-weight:600;display:block;margin-bottom:4px;">Ausentes</span><b style="font-size:1.4em;color:var(--peligro-cl);">${m.cant_ausentes}</b></div>
        </div>
        <div style="font-size:.88em;background:white;padding:10px;border-radius:6px;border:1px solid #fee2e2;margin-bottom:10px;">
            <b style="color:var(--peligro);display:block;margin-bottom:4px;">Nómina de Ausentes:</b>
            <span style="color:var(--texto-suave);">${ausText}</span>
        </div>
        <div style="font-size:.88em;background:white;padding:10px;border-radius:6px;border:1px solid ${(m.novedades||'').trim() ? '#fed7aa' : '#e2e8f0'};">
            <b style="color:${(m.novedades||'').trim() ? 'var(--advertencia)' : 'var(--texto-suave)'};display:block;margin-bottom:4px;">📝 Novedades Generales:</b>
            <span style="color:var(--texto);white-space:pre-wrap;">${(m.novedades||'').trim() || '<span style="color:var(--texto-tenue);font-style:italic;">Sin novedades.</span>'}</span>
        </div>
    </div>`;
}

// ══════════════════════════════════════════════════════════════
// REPORTES
// ══════════════════════════════════════════════════════════════
async function mostrarDetallesAula() {
    const aula  = document.getElementById('f-aula').value.trim();
    const turno = document.getElementById('f-turno').value || 'TM';
    if (!aula) return mostrarToast('Defina un aula en los filtros.', 'warning');
    let asp = [], cron = [];
    try { asp  = await (await fetch(`/api/aspirantes?aula=${aula}&turno=${turno}`)).json(); } catch {}
    try { cron = await (await fetch(`/api/config_aula/${aula}/${turno}`)).json(); }           catch {}
    const htmlA = asp.length
        ? `<div class="table-responsive table-modal" style="margin:0;"><table><thead><tr><th>Grado</th><th>Nombre</th></tr></thead><tbody>${asp.map(a=>`<tr><td style="font-weight:600;">${a.grado}</td><td>${a.nombre}</td></tr>`).join('')}</tbody></table></div>`
        : '<p style="text-align:center;color:#94a3b8;padding:20px;">Sin padrón.</p>';
    const htmlC = cron.length
        ? `<div class="table-responsive table-modal" style="margin:0;"><table><thead><tr><th>Día</th><th>Hora</th><th>Asig / Docente</th></tr></thead><tbody>${cron.map(c=>`<tr><td style="font-weight:600;">${c.dia}</td><td><span class="chip">${c.hora}</span></td><td>${c.asig}<br><small style="color:#64748b;">${c.doc}</small></td></tr>`).join('')}</tbody></table></div>`
        : '<p style="text-align:center;color:#94a3b8;padding:20px;">Sin cronograma.</p>';
    _mostrarPanel(`<div class="card" style="border-top:4px solid #0ea5e9;background:white;">
        <h3 style="color:#0ea5e9;margin-top:0;">Aula ${aula} (${turno})</h3>
        <div class="grid"><div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:14px;"><h4 style="margin-top:0;">👥 Padrón (${asp.length})</h4><div style="max-height:360px;overflow-y:auto;">${htmlA}</div></div>
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:14px;"><h4 style="margin-top:0;">📅 Cronograma</h4><div style="max-height:360px;overflow-y:auto;">${htmlC}</div></div></div>
        <button class="btn btn-secondary btn-full" style="margin-top:16px;" onclick="document.getElementById('panel-reportes').style.display='none'">Cerrar</button>
    </div>`);
}

async function mostrarParteDiario() {
    window.SIPA.globalMinutas = await (await fetch('/api/minutas')).json();
    const hoy   = obtenerFechaHoyLocal();
    const aulaF = document.getElementById('f-aula').value.toUpperCase();
    const turnoF = document.getElementById('f-turno').value;
    const mHoy  = window.SIPA.globalMinutas.filter(m =>
        m.fecha === hoy &&
        (!aulaF || m.aula === aulaF) &&
        (!turnoF || m.turno === turnoF));

    // Deduplicar por (aula+turno) — quedarnos con la planilla más reciente
    // (mayor id = guardado más reciente). Si un bedel guardó dos veces, contamos una sola.
    const ultimaPorAula = new Map();
    mHoy.forEach(m => {
        const k = `${m.aula}|${m.turno}`;
        const prev = ultimaPorAula.get(k);
        if (!prev || (m.id || 0) > (prev.id || 0)) ultimaPorAula.set(k, m);
    });
    const mHoyDedup = Array.from(ultimaPorAula.values());

    let fe=0,pres=0,aus=0,docs='';
    mHoyDedup.forEach(m=>{fe+=parseInt(m.fe)||0;pres+=parseInt(m.presentes)||0;aus+=parseInt(m.cant_ausentes)||0;(m.schedule||[]).forEach(s=>{if(!s.doc)return;const b=s.estado==='P'?`<span style="background:#dcfce7;color:#166534;padding:3px 8px;border-radius:4px;font-weight:bold;font-size:.78em;">ASISTIÓ</span>`:`<span style="background:#fee2e2;color:#991b1b;padding:3px 8px;border-radius:4px;font-weight:bold;font-size:.78em;">AUSENTE</span>`;docs+=`<li style="margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid #f1f5f9;display:flex;align-items:center;gap:8px;">${b}<span><strong>Aula ${m.aula}(${m.turno}) ${s.hora}:</strong> ${s.doc} <span style="color:#64748b;">(${s.asig})</span></span></li>`;});});
    if(!docs)docs=`<li style="color:#94a3b8;padding:20px;text-align:center;">Sin registros docentes hoy.</li>`;
    _mostrarPanel(`<div class="card" style="border-top:4px solid #8b5cf6;background:white;">
        <h3 style="margin-top:0;color:#8b5cf6;">📈 Parte Diario — ${formatearFechaElegante(hoy)}</h3>
        <div class="grid" style="text-align:center;margin-top:20px;">
            <div style="background:#f8fafc;padding:18px;border-radius:12px;border:1px solid #e2e8f0;"><div style="font-size:2.2em;font-weight:800;color:var(--azul-oscuro);">${mHoyDedup.length}</div><strong style="color:#64748b;font-size:.85em;">Aulas Op.</strong></div>
            <div style="background:#eff6ff;padding:18px;border-radius:12px;border:1px solid #bfdbfe;"><div style="font-size:2.2em;font-weight:800;color:#3b82f6;">${fe}</div><strong style="color:#64748b;font-size:.85em;">F.E. Global</strong></div>
            <div style="background:#f0fdf4;padding:18px;border-radius:12px;border:1px solid #bbf7d0;"><div style="font-size:2.2em;font-weight:800;color:#22c55e;">${pres}</div><strong style="color:#64748b;font-size:.85em;">Presentes</strong></div>
            <div style="background:#fef2f2;padding:18px;border-radius:12px;border:1px solid #fecaca;"><div style="font-size:2.2em;font-weight:800;color:#ef4444;">${aus}</div><strong style="color:#64748b;font-size:.85em;">Ausentes</strong></div>
        </div>
        <h4 style="margin:24px 0 10px;color:var(--azul-oscuro);">📋 Asistencia Docente</h4>
        <ul style="list-style:none;padding:12px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;max-height:260px;overflow-y:auto;">${docs}</ul>
        <button class="btn btn-secondary btn-full" style="margin-top:16px;" onclick="document.getElementById('panel-reportes').style.display='none'">Cerrar</button>
    </div>`);
}

async function mostrarReporteSemanal() {
    window.SIPA.globalMinutas=await(await fetch('/api/minutas')).json();
    const aulaF=document.getElementById('f-aula').value.toUpperCase(),turnoF=document.getElementById('f-turno').value;
    const hoy=new Date(),hace7=new Date();hace7.setDate(hoy.getDate()-7);

    // Deduplicar por (fecha+aula+turno) — quedarnos con la última planilla guardada de cada combinación
    const ultimaPorClave = new Map();
    window.SIPA.globalMinutas.forEach(m => {
        if (aulaF && m.aula !== aulaF) return;
        if (turnoF && m.turno !== turnoF) return;
        if (!m.fecha) return;
        const [y,mes,d] = m.fecha.split('-');
        const fd = new Date(parseInt(y), parseInt(mes)-1, parseInt(d));
        if (fd < hace7 || fd > hoy) return;
        const k = `${m.fecha}|${m.aula}|${m.turno}`;
        const prev = ultimaPorClave.get(k);
        if (!prev || (m.id || 0) > (prev.id || 0)) ultimaPorClave.set(k, m);
    });
    const minutasSemana = Array.from(ultimaPorClave.values());

    let tot=0,pres=0,aus=0;const f={};
    minutasSemana.forEach(m=>{tot++;pres+=parseInt(m.presentes)||0;aus+=parseInt(m.cant_ausentes)||0;(m.schedule||[]).forEach(s=>{if(s.doc&&s.estado==='A'){const k=`${s.doc}(Aula${m.aula}-${m.turno})`;if(!f[k])f[k]=[];const e=`${formatearFechaElegante(m.fecha)},${s.hora}hs`;if(!f[k].includes(e))f[k].push(e);}});});
    let rank=Object.entries(f).map(([p,d])=>`<li style="margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid #e2e8f0;"><strong style="color:var(--azul-oscuro);display:block;">${p}</strong><span style="color:#ef4444;font-size:.88em;">⚠️ ${d.join(' | ')}</span></li>`).join('');
    if(!rank)rank=`<li style="text-align:center;padding:18px;"><span style="background:#dcfce7;color:#166534;padding:8px 14px;border-radius:8px;font-weight:bold;">✅ Sin ausencias en 7 días.</span></li>`;
    _mostrarPanel(`<div class="card" style="border-top:4px solid #f59e0b;background:white;">
        <h3 style="margin-top:0;color:#d97706;">📅 Resumen Semanal</h3>
        <div class="grid" style="text-align:center;margin-top:20px;">
            <div style="background:#f8fafc;padding:18px;border-radius:12px;border:1px solid #e2e8f0;"><div style="font-size:2.2em;color:var(--azul-oscuro);font-weight:800;">${tot}</div><strong style="color:#64748b;font-size:.85em;">Planillas</strong></div>
            <div style="background:#f0fdf4;padding:18px;border-radius:12px;border:1px solid #bbf7d0;"><div style="font-size:2.2em;color:#22c55e;font-weight:800;">${pres}</div><strong style="color:#64748b;font-size:.85em;">Presentes</strong></div>
            <div style="background:#fef2f2;padding:18px;border-radius:12px;border:1px solid #fecaca;"><div style="font-size:2.2em;color:#ef4444;font-weight:800;">${aus}</div><strong style="color:#64748b;font-size:.85em;">Ausencias</strong></div>
        </div>
        <h4 style="margin:24px 0 10px;color:var(--azul-oscuro);">📋 Docentes con Faltas</h4>
        <ul style="background:#f8fafc;padding:12px;border-radius:8px;border:1px solid #e2e8f0;list-style:none;max-height:260px;overflow-y:auto;">${rank}</ul>
        <button class="btn btn-secondary btn-full" style="margin-top:16px;" onclick="document.getElementById('panel-reportes').style.display='none'">Cerrar</button>
    </div>`);
}

async function mostrarAsistenciaDocentes() {
    window.SIPA.globalMinutas=await(await fetch('/api/minutas')).json();
    const aulaF=document.getElementById('f-aula').value.toUpperCase(),turnoF=document.getElementById('f-turno').value,hoy=obtenerFechaHoyLocal();
    let h='',c=0;
    window.SIPA.globalMinutas.forEach(m=>{if(m.fecha!==hoy)return;if(aulaF&&m.aula!==aulaF)return;if(turnoF&&m.turno!==turnoF)return;(m.schedule||[]).forEach(s=>{if(s.doc&&s.estado==='A'){c++;h+=`<li style="margin-bottom:10px;padding-bottom:10px;border-bottom:1px solid #e2e8f0;"><div style="display:flex;justify-content:space-between;align-items:center;"><strong>${s.doc}</strong><span style="background:#fee2e2;color:#991b1b;padding:2px 8px;border-radius:4px;font-weight:bold;font-size:.78em;">AUSENTE</span></div><div style="color:#64748b;font-size:.88em;">Aula ${m.aula}(${m.turno}) | ${s.asig} | ${s.hora}</div></li>`;}});});
    if(!c)h=`<li style="text-align:center;padding:20px;"><span style="background:#dcfce7;color:#166534;padding:8px 14px;border-radius:8px;font-weight:bold;">✅ Sin ausentes hoy.</span></li>`;
    _mostrarPanel(`<div class="card" style="border-top:4px solid #10b981;background:white;">
        <h3 style="margin-top:0;color:#059669;">👨‍🏫 Docentes Ausentes — ${formatearFechaElegante(hoy)}</h3>
        <ul style="list-style:none;padding:12px;background:#f8fafc;border-radius:8px;border:1px solid #e2e8f0;max-height:280px;overflow-y:auto;">${h}</ul>
        <div style="margin-top:16px;text-align:center;background:#fef2f2;border:1px solid #fecaca;padding:12px;border-radius:8px;"><span style="color:#ef4444;font-weight:bold;">Total: ${c}</span></div>
        <button class="btn btn-secondary btn-full" style="margin-top:16px;" onclick="document.getElementById('panel-reportes').style.display='none'">Cerrar</button>
    </div>`);
}

function mostrarFojaAspirante() {
    const asp=document.getElementById('f-asp').value.toUpperCase();
    if(!asp)return mostrarToast('Seleccione un aspirante.','warning');
    let f=0,r='';
    window.SIPA.globalMinutas.forEach(m=>{(m.ausentes||[]).forEach(a=>{if(a.nombre?.toUpperCase().includes(asp)){f++;r+=`<li style="margin-bottom:8px;padding-bottom:8px;border-bottom:1px solid #e2e8f0;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px;"><div><strong style="color:var(--azul-primario);display:block;">${formatearFechaElegante(m.fecha)}</strong><span style="color:#64748b;font-size:.88em;">Aula ${m.aula}(${m.turno})</span></div><div style="background:#fef2f2;color:#ef4444;border:1px solid #fecaca;padding:5px 10px;border-radius:6px;font-size:.88em;font-weight:600;">${a.causa||'Sin causa'}</div></li>`;}});});
    _mostrarPanel(`<div class="card" style="border-top:4px solid #334155;background:white;">
        <h3 style="margin-top:0;color:#334155;">🕵️ Foja: <span style="color:var(--azul-primario);">${asp}</span></h3>
        <div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:18px;text-align:center;margin:16px 0;"><span style="display:block;color:#64748b;font-size:.85em;text-transform:uppercase;font-weight:600;margin-bottom:4px;">Total Inasistencias</span><span style="font-size:2.8em;font-weight:800;color:#ef4444;">${f}</span></div>
        <ul style="max-height:260px;overflow-y:auto;padding:0;list-style:none;">${r||'<li style="text-align:center;padding:18px;"><span style="background:#dcfce7;color:#166534;padding:8px 14px;border-radius:8px;font-weight:bold;">✅ Asistencia perfecta.</span></li>'}</ul>
        <button class="btn btn-secondary btn-full" style="margin-top:16px;" onclick="document.getElementById('panel-reportes').style.display='none'">Cerrar</button>
    </div>`);
}

async function mostrarHorasCatedra() {
    const desde = prompt('Fecha desde (AAAA-MM-DD):', `${new Date().getFullYear()}-01-01`);
    if (!desde) return;
    const hasta = prompt('Fecha hasta (AAAA-MM-DD):', obtenerFechaHoyLocal());
    if (!hasta) return;
    const aula = document.getElementById('f-aula')?.value || '';
    const turno = document.getElementById('f-turno')?.value || '';
    const aspirante = document.getElementById('f-asp')?.value || '';
    const materia = prompt('Materia (opcional; parte del nombre):', '');
    if (materia === null) return;
    const params = new URLSearchParams({ desde, hasta, aula, turno, aspirante, materia });
    const cont = document.getElementById('panel-reportes');
    _mostrarPanel('<div class="card"><p style="text-align:center;"><span class="spin">🔄</span> Calculando horas cátedra…</p></div>');
    try {
        const r = await fetch(`/api/plana_mayor/horas_catedra?${params}`, {
            headers: {
                'X-Admin-Token': window.SIPA.adminToken || '',
                'X-SU-Token': window.SIPA.suToken || '',
            },
        });
        const d = await r.json();
        if (!r.ok) throw new Error(d.error || 'No se pudo calcular');
        const s = d.resumen || {};
        const money = n => Number(n || 0).toFixed(2).replace('.', ',');
        const rows = (d.detalle || []).map(x => `<tr>
            <td>${escapeHTML(x.aspirante)}</td><td>Aula ${escapeHTML(x.aula)} · ${escapeHTML(x.turno)}</td>
            <td>${escapeHTML(x.materia)}</td><td>${money(x.horas_totales)}</td>
            <td>${money(x.horas_asistidas)}</td><td>${money(x.horas_justificadas)}</td>
            <td>${money(x.horas_no_justificadas)}</td><td>${money(x.porcentaje_asistencia)}%</td>
            <td><span class="${x.estado === 'OBSERVADO' ? 'badge-rojo' : x.estado === 'SIN CLASIFICAR' ? 'badge-amarillo' : 'badge-verde'}">${x.estado}</span></td>
        </tr>`).join('');
        cont.innerHTML = `<div class="card" style="border-top:4px solid #7c3aed;">
            <h3 style="margin-top:0;color:#6d28d9;">📚 Horas Cátedra por Aspirante y Materia</h3>
            <p style="color:var(--texto-suave);font-size:.86em;">Período: ${escapeHTML(desde)} a ${escapeHTML(hasta)}. Las horas sin criterio administrativo quedan clasificadas aparte.</p>
            <div class="grid">
                <div><strong>Total</strong><br>${money(s.horas_totales)} h</div>
                <div><strong>Asistidas</strong><br>${money(s.horas_asistidas)} h</div>
                <div><strong>Justificadas</strong><br>${money(s.horas_justificadas)} h</div>
                <div><strong>No justificadas</strong><br>${money(s.horas_no_justificadas)} h</div>
                <div><strong>Asistencia</strong><br>${money(s.porcentaje_asistencia)}%</div>
            </div>
            <div class="table-responsive" style="margin-top:14px;"><table>
                <thead><tr><th>Aspirante</th><th>Aula</th><th>Materia</th><th>Total</th><th>Asistidas</th><th>Justificadas</th><th>No justificadas</th><th>% Asistencia</th><th>Estado</th></tr></thead>
                <tbody>${rows || '<tr><td colspan="9" style="text-align:center;">Sin datos para los filtros seleccionados.</td></tr>'}</tbody>
            </table></div>
            <button class="btn btn-secondary btn-full" style="margin-top:16px;" onclick="document.getElementById('panel-reportes').style.display='none'">Cerrar</button>
        </div>`;
    } catch (e) {
        cont.innerHTML = `<div class="empty-state" style="color:var(--peligro);">❌ ${escapeHTML(e.message)}</div>`;
    }
}

async function cargarTiposNovedad() {
    const body = document.getElementById('body-tipos-novedad');
    if (!body) return;
    body.innerHTML = '<tr><td colspan="5">Cargando…</td></tr>';
    const data = await _fetchSU('/api/tipos_novedad');
    if (!data) return;
    body.innerHTML = data.length ? data.map(t => `<tr>
        <td><strong>${escapeHTML(t.nombre)}</strong></td>
        <td>${t.permite_justificacion ? 'Sí' : 'No'}</td>
        <td>${t.justificada_por_defecto === true ? 'Justificada' : t.justificada_por_defecto === false ? 'No justificada' : 'Sin valor'}</td>
        <td><span class="${t.activo === false ? 'badge-rojo' : 'badge-verde'}">${t.activo === false ? 'Inactivo' : 'Activo'}</span></td>
        <td><button class="btn btn-danger btn-small" onclick="desactivarTipoNovedad(${t.id})">Desactivar</button></td>
    </tr>`).join('') : '<tr><td colspan="5">No hay novedades configuradas.</td></tr>';
}

async function crearTipoNovedad() {
    const nombre = document.getElementById('novedad-nombre')?.value.trim();
    if (!nombre) return mostrarToast('Ingrese el nombre de la novedad.', 'warning');
    const defecto = document.getElementById('novedad-defecto')?.value;
    const payload = {
        nombre,
        permite_justificacion: document.getElementById('novedad-permite')?.value === 'true',
        justificada_por_defecto: defecto === '' ? null : defecto === 'true',
    };
    const r = await fetch('/api/tipos_novedad', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-SU-Token': window.SIPA.suToken || ''},
        body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (!r.ok) return mostrarToast(d.error || 'No se pudo crear.', 'error');
    document.getElementById('novedad-nombre').value = '';
    mostrarToast('Tipo de novedad creado.', 'success');
    cargarTiposNovedad();
}

async function desactivarTipoNovedad(id) {
    if (!confirm('¿Desactivar este tipo de novedad?')) return;
    const r = await fetch(`/api/tipos_novedad/${id}`, {
        method: 'DELETE',
        headers: {'X-SU-Token': window.SIPA.suToken || ''},
    });
    const d = await r.json();
    if (!r.ok) return mostrarToast(d.error || 'No se pudo desactivar.', 'error');
    mostrarToast('Tipo de novedad desactivado.', 'success');
    cargarTiposNovedad();
}

function _mostrarPanel(html) {
    const p=document.getElementById('panel-reportes');
    p.innerHTML=html; p.style.display='block';
    p.scrollIntoView({behavior:'smooth',block:'nearest'});
}

// ── SISTEMA ──
// ══════════════════════════════════════════════════════════════
// CUENTAS DE PLANA MAYOR (multi-admin)
// ══════════════════════════════════════════════════════════════
async function cargarUsuariosAdmin() {
    const cont = document.getElementById('ua-tabla');
    cont.innerHTML = `<p style="text-align:center;padding:20px;color:var(--texto-tenue);"><span class="spin">🔄</span> Cargando…</p>`;
    const data = await _fetchSU('/api/su/usuarios_admin');
    if (!data) { cont.innerHTML = ''; return; }
    if (!data.length) { cont.innerHTML = `<div class="empty-state">Sin cuentas registradas. Use el formulario de arriba para crear la primera.</div>`; return; }
    cont.innerHTML = `<div class="table-responsive"><table>
        <thead><tr><th>Usuario</th><th>Nombre</th><th>Activo</th><th>Último login</th><th>Acciones</th></tr></thead>
        <tbody>${data.map(u => {
            const dAttrs = `data-uid="${u.id}" data-usuario="${_esc(u.usuario)}"`;
            return `<tr style="${u.activo ? '' : 'opacity:.55;'}">
            <td><code>${_esc(u.usuario)}</code></td>
            <td><strong>${_esc(u.nombre)}</strong></td>
            <td>${u.activo ? '<span class="badge-verde">✓ Activo</span>' : '<span class="badge-rojo">✗ Bloqueado</span>'}</td>
            <td style="font-size:.82em;font-family:'DM Mono',monospace;color:var(--texto-suave);">${(u.ultimo_login||'—').substring(0,19)}</td>
            <td style="display:flex;gap:5px;flex-wrap:wrap;">
                <button class="btn btn-warning btn-small" style="margin:0;padding:4px 9px;font-size:.76em;" ${dAttrs} onclick="_resetPwdAdmin(this)">🔓 Reset</button>
                <button class="btn btn-info btn-small" style="margin:0;padding:4px 9px;font-size:.76em;" ${dAttrs} onclick="_toggleAdmin(this)">${u.activo ? '⏸ Bloquear' : '▶️ Activar'}</button>
                <button class="btn btn-danger btn-small" style="margin:0;padding:4px 9px;font-size:.76em;" ${dAttrs} onclick="_eliminarAdmin(this)">🗑</button>
            </td>
        </tr>`;
        }).join('')}</tbody></table></div>`;
}

async function crearUsuarioAdmin() {
    const usuario  = document.getElementById('ua-usuario').value.trim().toLowerCase();
    const nombre   = document.getElementById('ua-nombre').value.trim();
    const password = document.getElementById('ua-password').value;
    if (!usuario || !nombre) return mostrarToast('Usuario y nombre requeridos.', 'warning');
    try {
        const r = await fetch('/api/su/usuarios_admin', {
            method:'POST',
            headers:{'Content-Type':'application/json','X-SU-Token':window.SIPA.suToken},
            body: JSON.stringify({ usuario, nombre, password: password || undefined }),
        });
        const d = await r.json();
        if (r.ok) {
            alert(`✅ Cuenta creada\n\nUsuario: ${usuario}\nClave inicial: ${d.password_inicial}\n\nEntréguesela en persona.`);
            ['ua-usuario','ua-nombre','ua-password'].forEach(id => document.getElementById(id).value = '');
            cargarUsuariosAdmin();
        } else mostrarToast(d.error || 'Error.', 'error');
    } catch (e) { mostrarToast('Error: '+e.message, 'error'); }
}

async function _resetPwdAdmin(btn) {
    const id = btn.dataset.uid, usuario = btn.dataset.usuario;
    const nueva = prompt(`Nueva clave para "${usuario}" (vacío = autogenerar):`,'');
    if (nueva === null) return;
    try {
        const r = await fetch(`/api/su/usuarios_admin/${id}/reset_pass`, {
            method:'POST',
            headers:{'Content-Type':'application/json','X-SU-Token':window.SIPA.suToken},
            body: JSON.stringify({ password: nueva || undefined }),
        });
        const d = await r.json();
        if (r.ok) alert(`✅ ${d.msj}\n\nNueva clave: ${d.nueva_password}\n\nEntréguesela en persona.`);
        else mostrarToast(d.error || 'Error.', 'error');
    } catch (e) { mostrarToast('Error: '+e.message, 'error'); }
}

async function _toggleAdmin(btn) {
    const id = btn.dataset.uid, usuario = btn.dataset.usuario;
    if (!confirm(`Cambiar estado de "${usuario}"?`)) return;
    try {
        const r = await fetch(`/api/su/usuarios_admin/${id}/toggle`, {
            method:'POST', headers:{'X-SU-Token':window.SIPA.suToken},
        });
        const d = await r.json();
        if (r.ok) { mostrarToast(d.msj, 'success'); cargarUsuariosAdmin(); }
        else mostrarToast(d.error || 'Error.', 'error');
    } catch (e) { mostrarToast('Error: '+e.message, 'error'); }
}

async function _eliminarAdmin(btn) {
    const id = btn.dataset.uid, usuario = btn.dataset.usuario;
    if (!confirm(`⚠️ ELIMINAR la cuenta "${usuario}"?\nEsta operación es irreversible.`)) return;
    try {
        const r = await fetch(`/api/su/usuarios_admin/${id}`, {
            method:'DELETE', headers:{'X-SU-Token':window.SIPA.suToken},
        });
        const d = await r.json();
        if (r.ok) { mostrarToast('🗑 ' + d.msj, 'success'); cargarUsuariosAdmin(); }
        else mostrarToast(d.error || 'Error.', 'error');
    } catch (e) { mostrarToast('Error: '+e.message, 'error'); }
}

// ══════════════════════════════════════════════════════════════
// IMPERSONACIÓN ("MODO DIOS")
// ══════════════════════════════════════════════════════════════
async function iniciarImpersonacion() {
    const rol     = document.getElementById('imp-rol').value;
    const sujeto  = document.getElementById('imp-sujeto').value.trim();
    const motivo  = document.getElementById('imp-motivo').value.trim();
    if (!sujeto) return mostrarToast('Indique a quién impersonar.', 'warning');
    if (motivo.length < 5) return mostrarToast('El motivo debe tener al menos 5 caracteres.', 'warning');
    if (!confirm(`⚠️ Está a punto de iniciar sesión COMO si fuera otra persona.\n\nRol: ${rol}\nSujeto: ${sujeto}\nMotivo: ${motivo}\n\nTODA la actividad queda registrada en el Audit Log a tu nombre (TIC).\n\n¿Continuar?`)) return;
    try {
        const r = await fetch('/api/su/impersonar', {
            method:'POST',
            headers:{'Content-Type':'application/json','X-SU-Token':window.SIPA.suToken},
            body: JSON.stringify({ rol, sujeto, motivo }),
        });
        const d = await r.json();
        const out = document.getElementById('imp-result');
        if (r.ok) {
            // Construir URL para abrir en pestaña nueva con sesión pre-cargada
            const params = new URLSearchParams({
                imp_token:   d.token,
                imp_rol:     d.rol,
                imp_persona: d.persona,
                imp_sujeto:  d.sujeto,
            });
            const url = `${location.origin}/?${params.toString()}`;
            out.innerHTML = `<div class="bd-ok-banner">
                <strong style="color:var(--exito);">🎭 ${d.msj}</strong>
                <div style="margin-top:11px;display:flex;gap:8px;flex-wrap:wrap;">
                    <button class="btn btn-primary" onclick="window.open('${url}', '_blank')">
                        🪟 Abrir nueva pestaña como ${d.persona}
                    </button>
                    <button class="btn btn-secondary btn-small" onclick="_terminarImp('${d.token}')">⏹ Terminar ahora</button>
                </div>
                <div style="margin-top:8px;font-size:.78em;color:var(--texto-suave);">
                    Duración máxima: ${d.duracion_min} min. Token: <code style="font-size:.92em;">${d.token.substring(0,12)}…</code>
                </div>
            </div>`;
        } else {
            out.innerHTML = `<div class="bd-error-banner"><strong>${d.error || 'Error'}</strong></div>`;
        }
    } catch (e) { mostrarToast('Error: '+e.message, 'error'); }
}

async function _terminarImp(token) {
    try {
        await fetch('/api/su/impersonar_fin', {
            method:'POST',
            headers:{'Content-Type':'application/json','X-SU-Token':window.SIPA.suToken},
            body: JSON.stringify({ token }),
        });
        document.getElementById('imp-result').innerHTML = '<div class="empty-state">✅ Sesión de impersonación cerrada.</div>';
    } catch {}
}

// ══════════════════════════════════════════════════════════════
// ARCHIVO HISTÓRICO DE CICLOS — Consulta y Export
// ══════════════════════════════════════════════════════════════
async function cargarResumenArchivo() {
    const cont = document.getElementById('archivo-resumen');
    if (!cont) return;
    cont.innerHTML = `<p style="color:var(--texto-tenue);text-align:center;padding:10px;"><span class="spin">🔄</span> Cargando…</p>`;
    const d = await _fetchSU('/api/su/archivo_resumen');
    if (!d) { cont.innerHTML = ''; return; }

    // Llenar select de años (unión de ambas tablas)
    const setAnios = new Set();
    (d.minutas_archivo.anios || []).forEach(x => setAnios.add(x.anio));
    (d.firmas_archivo.anios  || []).forEach(x => setAnios.add(x.anio));
    const aniosOrdenados = Array.from(setAnios).sort((a,b) => b - a);
    const sel = document.getElementById('arch-anio');
    if (sel) {
        const valActual = sel.value;
        sel.innerHTML = '<option value="">Todos</option>' +
            aniosOrdenados.map(a => `<option value="${a}">${a}</option>`).join('');
        if (aniosOrdenados.includes(parseInt(valActual))) sel.value = valActual;
    }

    // Mostrar el toggle de docente solo si tipo=firmas
    const tipo = document.getElementById('arch-tipo')?.value;
    const docWrap = document.getElementById('arch-docente-wrap');
    if (docWrap) docWrap.style.display = (tipo === 'firmas') ? '' : 'none';

    if (!d.minutas_archivo.existe && !d.firmas_archivo.existe) {
        cont.innerHTML = `<div class="empty-state" style="padding:24px;">
            <span class="empty-state-icon">📭</span>
            <span class="empty-state-text">
                <strong>Aún no hay ciclos archivados.</strong>
                Para crear el archivo histórico, vaya a
                <em>Configuración → Peligro → Archivar Año</em>.
            </span>
        </div>`;
        return;
    }

    cont.innerHTML = `<div class="archivo-stats">
        ${_renderArchivoStat('📋 Minutas archivadas', d.minutas_archivo)}
        ${_renderArchivoStat('✍️ Firmas archivadas',  d.firmas_archivo)}
    </div>`;
}

function _renderArchivoStat(titulo, info) {
    if (!info.existe) {
        return `<div class="archivo-stat archivo-stat--vacio">
            <div class="archivo-stat-titulo">${titulo}</div>
            <div class="archivo-stat-vacio">Sin datos archivados aún</div>
        </div>`;
    }
    const total = info.anios.reduce((a,x) => a + parseInt(x.filas), 0);
    const aniosTxt = info.anios.map(x =>
        `<span class="archivo-anio-chip">${x.anio} · <b>${x.filas}</b></span>`
    ).join('');
    return `<div class="archivo-stat">
        <div class="archivo-stat-titulo">${titulo} · <strong>${total}</strong> filas totales</div>
        <div class="archivo-stat-anios">${aniosTxt || '<em>Sin años cargados</em>'}</div>
    </div>`;
}

async function consultarArchivo() {
    const out = document.getElementById('archivo-resultado');
    if (!out) return;
    out.innerHTML = `<p style="color:var(--texto-tenue);text-align:center;padding:20px;"><span class="spin">🔄</span> Consultando archivo…</p>`;

    const tipo  = document.getElementById('arch-tipo').value;
    const anio  = document.getElementById('arch-anio').value;
    const aula  = document.getElementById('arch-aula').value.trim();
    const turno = document.getElementById('arch-turno').value;
    const docente = document.getElementById('arch-docente')?.value.trim() || '';

    // Mostrar/ocultar campo docente según tipo
    document.getElementById('arch-docente-wrap').style.display = (tipo === 'firmas') ? '' : 'none';

    const qs = new URLSearchParams({tipo, limit: '200'});
    if (anio)  qs.set('anio', anio);
    if (aula)  qs.set('aula', aula);
    if (turno) qs.set('turno', turno);
    if (docente && tipo === 'firmas') qs.set('docente', docente);

    const d = await _fetchSU(`/api/su/archivo_consultar?${qs.toString()}`);
    if (!d) { out.innerHTML = ''; return; }
    if (d.mensaje) {
        out.innerHTML = `<div class="empty-state"><span class="empty-state-icon">📭</span><span class="empty-state-text">${d.mensaje}</span></div>`;
        return;
    }
    if (!d.filas || !d.filas.length) {
        out.innerHTML = `<div class="empty-state"><span class="empty-state-icon">📭</span><span class="empty-state-text">Sin resultados para los filtros seleccionados.</span></div>`;
        return;
    }

    const cabeceras = tipo === 'minutas'
        ? ['Fecha','Aula','Turno','Bedel','Sub-Bedel','F.E.','Presentes','Ausentes','Novedades']
        : ['Fecha','Docente','Aula','Turno','Hora Firma','PIN'];

    const filasTr = d.filas.map(r => {
        if (tipo === 'minutas') {
            return `<tr>
                <td style="font-family:'DM Mono',monospace;font-size:.85em;">${r.fecha || ''}</td>
                <td><strong>${r.aula || ''}</strong></td>
                <td><span class="chip">${r.turno || ''}</span></td>
                <td style="font-size:.85em;">${_esc(r.bedel || '—')}</td>
                <td style="font-size:.85em;">${_esc(r.sub_bedel || '—')}</td>
                <td style="text-align:center;color:var(--azul-primario);font-weight:700;">${r.fe ?? '—'}</td>
                <td style="text-align:center;color:var(--exito);font-weight:700;">${r.presentes ?? '—'}</td>
                <td style="text-align:center;color:var(--peligro);font-weight:700;">${r.cant_ausentes ?? '—'}</td>
                <td style="font-size:.82em;color:var(--texto-suave);">${_esc((r.novedades || '').substring(0,80))}</td>
            </tr>`;
        }
        return `<tr>
            <td style="font-family:'DM Mono',monospace;font-size:.85em;">${r.fecha || ''}</td>
            <td><strong>${_esc(r.docente || '—')}</strong></td>
            <td>${r.aula || ''}</td>
            <td><span class="chip">${r.turno || ''}</span></td>
            <td style="font-family:'DM Mono',monospace;color:var(--verde-inst);font-weight:600;">${(r.hora_firma || '').substring(0,5)}</td>
            <td style="font-family:'DM Mono',monospace;font-size:.82em;color:var(--texto-tenue);">${r.pin_usado || '—'}</td>
        </tr>`;
    }).join('');

    out.innerHTML = `
        <div class="archivo-cabecera">
            Mostrando <strong>${d.filas.length}</strong> resultados
            ${d.filas.length === d.limit ? ` (límite ${d.limit} — afine filtros para ver más)` : ''}
        </div>
        <div class="table-responsive">
            <table>
                <thead><tr>${cabeceras.map(h => `<th>${h}</th>`).join('')}</tr></thead>
                <tbody>${filasTr}</tbody>
            </table>
        </div>`;
}

async function exportarArchivo() {
    if (!window.SIPA.suToken) return mostrarToast('Requiere TIC.', 'warning');
    const tipo = document.getElementById('arch-tipo').value;
    const anio = document.getElementById('arch-anio').value;
    const qs = new URLSearchParams({tipo});
    if (anio) qs.set('anio', anio);
    // Como necesitamos enviar header X-SU-Token, hacemos fetch y luego download del blob
    try {
        const r = await fetch(`/api/su/archivo_export?${qs.toString()}`, {
            headers: { 'X-SU-Token': window.SIPA.suToken },
        });
        if (!r.ok) {
            const e = await r.json().catch(()=>({}));
            return mostrarToast(e.error || `HTTP ${r.status}`, 'error');
        }
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = `archivo_${tipo}${anio ? '_'+anio : ''}.csv`;
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
        mostrarToast('📥 Descarga iniciada.', 'success');
    } catch (e) {
        mostrarToast('Error: '+e.message, 'error');
    }
}

// ══════════════════════════════════════════════════════════════
// BACKUPS AUTOMÁTICOS + RESTAURACIÓN + ARCHIVADO
// ══════════════════════════════════════════════════════════════
async function cargarBackupsAuto() {
    const cont = document.getElementById('su-backups-auto-lista');
    cont.innerHTML = `<p style="text-align:center;padding:20px;color:var(--texto-tenue);"><span class="spin">🔄</span> Cargando…</p>`;
    const d = await _fetchSU('/api/su/backups_listado');
    if (!d) { cont.innerHTML = ''; return; }
    const ult = d.ultimo_auto ? `<div style="font-size:.82em;color:var(--texto-suave);margin-bottom:8px;">🕐 Último backup automático: ${d.ultimo_auto.substring(0,19)}</div>` : '';
    const hint = `<div style="font-size:.78em;color:var(--texto-tenue);margin-bottom:8px;">📂 ${d.directorio}</div>`;
    if (!d.archivos.length) { cont.innerHTML = ult + hint + '<div class="empty-state">Sin backups generados aún. Configure la hora en Parámetros (<code>backup_hora_diaria</code> en formato HH:MM) para activar el backup automático.</div>'; return; }
    cont.innerHTML = ult + hint + `<div class="table-responsive"><table>
        <thead><tr><th>Archivo</th><th>Fecha</th><th>Tamaño</th><th></th></tr></thead>
        <tbody>${d.archivos.map(a => `<tr>
            <td><code style="font-size:.82em;">${a.nombre}</code></td>
            <td style="font-family:'DM Mono',monospace;font-size:.8em;">${a.fecha.substring(0,19)}</td>
            <td style="font-family:'DM Mono',monospace;font-size:.82em;">${a.tamano_kb} KB</td>
            <td><a href="javascript:void(0)" onclick="_descargarBackupAuto('${a.nombre}')" style="color:var(--azul-primario);font-size:.85em;">📥 Descargar</a></td>
        </tr>`).join('')}</tbody></table></div>`;
}

async function _descargarBackupAuto(nombre) {
    try {
        const r = await fetch(`/api/su/backup_descargar/${encodeURIComponent(nombre)}`, {
            headers: { 'X-SU-Token': window.SIPA.suToken },
        });
        if (!r.ok) return mostrarToast('Error al descargar.', 'error');
        const blob = await r.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = nombre;
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
    } catch (e) { mostrarToast('Error: '+e.message, 'error'); }
}

async function restaurarBackup() {
    const fileInput = document.getElementById('restore-file');
    const f = fileInput.files[0];
    if (!f) return mostrarToast('Seleccione un archivo .json de backup.', 'warning');
    if (!confirm('⚠️ Esta operación BORRA TODAS las tablas actuales antes de restaurar.\n\n¿Estás seguro de continuar?')) return;
    const fd = new FormData();
    fd.append('file', f);
    const out = document.getElementById('restore-result');
    out.innerHTML = `<p style="color:var(--texto-tenue);"><span class="spin">🔄</span> Restaurando…</p>`;
    try {
        const r = await fetch('/api/su/restore_backup', {
            method: 'POST',
            headers: { 'X-SU-Token': window.SIPA.suToken },
            body: fd,
        });
        const d = await r.json();
        if (r.ok) {
            out.innerHTML = `<div class="bd-ok-banner"><strong style="color:var(--exito);">✅ ${d.msj}</strong>
                <ul style="margin:8px 0 0;padding-left:20px;font-size:.85em;">${d.resumen.map(x=>`<li>${x}</li>`).join('')}</ul></div>`;
            mostrarToast('♻️ Restauración completada.', 'success');
        } else {
            out.innerHTML = `<div class="bd-error-banner"><strong>${d.error}</strong></div>`;
        }
    } catch (e) {
        out.innerHTML = `<div class="bd-error-banner"><strong>${e.message}</strong></div>`;
    }
}

async function archivarCiclo() {
    const anio = parseInt(document.getElementById('archivar-anio').value);
    if (!anio || anio < 2020) return mostrarToast('Ingrese un año válido.', 'warning');
    if (!confirm(`⚠️ Archivar todas las minutas y firmas del año ${anio}?\nSe moverán a tablas _archivo (solo lectura).`)) return;
    const out = document.getElementById('archivar-result');
    out.innerHTML = `<p style="color:var(--texto-tenue);"><span class="spin">🔄</span> Archivando…</p>`;
    try {
        const r = await fetch('/api/su/archivar_ciclo', {
            method:'POST',
            headers:{'Content-Type':'application/json','X-SU-Token':window.SIPA.suToken},
            body: JSON.stringify({ anio }),
        });
        const d = await r.json();
        if (r.ok) {
            out.innerHTML = `<div class="bd-ok-banner"><strong style="color:var(--exito);">📦 ${d.msj}</strong>
                <div style="margin-top:6px;font-size:.85em;color:var(--texto-suave);">
                    Minutas archivadas: ${d.minutas_archivadas} · Firmas archivadas: ${d.firmas_archivadas}
                </div></div>`;
        } else {
            out.innerHTML = `<div class="bd-error-banner"><strong>${d.error}</strong></div>`;
        }
    } catch (e) {
        out.innerHTML = `<div class="bd-error-banner"><strong>${e.message}</strong></div>`;
    }
}

// ══════════════════════════════════════════════════════════════
// MONITOR EN TIEMPO REAL (SSE — Server-Sent Events)
// Push del backend → toast + refresh incremental sin polling.
// ══════════════════════════════════════════════════════════════
let _sseConexion = null;
let _sseIndicador = null;
let _sseUltimoEvento = null;

function iniciarSSE() {
    const tok = window.SIPA.adminToken || window.SIPA.suToken;
    if (!tok) return;
    if (_sseConexion) try { _sseConexion.close(); } catch {}

    _sseConexion = new EventSource(`/api/sse/monitor?token=${encodeURIComponent(tok)}`);

    _sseConexion.addEventListener('conectado', (e) => {
        _actualizarIndicadorSSE('on');
        console.log('[SSE] Conectado al stream:', e.data);
    });

    _sseConexion.addEventListener('firma', (e) => {
        const d = JSON.parse(e.data);
        _sseUltimoEvento = d;
        const tag = d.tiene_geo ? '📍' : '✍️';
        mostrarToast(`${tag} ${d.docente} firmó · Aula ${d.aula} (${d.turno}) ${d.hora_firma}`, 'success');
        // Refrescar monitor en silencio si está activo
        if (typeof refrescarMonitor === 'function') {
            const monActivo = document.getElementById('mon-tiempo-real')?.classList.contains('active');
            if (monActivo) refrescarMonitor(true);
        }
        _flashIndicadorSSE();
    });

    _sseConexion.addEventListener('justificacion', (e) => {
        const d = JSON.parse(e.data);
        mostrarToast(`📋 Justificación cargada: ${d.docente} (${d.fecha}) · ${d.motivo}`, 'info');
        _flashIndicadorSSE();
    });

    _sseConexion.addEventListener('mantenimiento', (e) => {
        const d = JSON.parse(e.data);
        mostrarToast(d.activo ? '🛠️ Modo mantenimiento ACTIVADO por TIC' : '✅ Modo mantenimiento DESACTIVADO', d.activo ? 'warning' : 'success');
    });

    _sseConexion.onerror = () => {
        _actualizarIndicadorSSE('off');
        // EventSource reintenta automáticamente solo
    };
}

function detenerSSE() {
    if (_sseConexion) { try { _sseConexion.close(); } catch {} _sseConexion = null; }
    _actualizarIndicadorSSE('off');
}

function _actualizarIndicadorSSE(estado) {
    if (!_sseIndicador) {
        _sseIndicador = document.createElement('div');
        _sseIndicador.id = 'sse-indicador';
        _sseIndicador.className = 'sse-indicador';
        document.body.appendChild(_sseIndicador);
    }
    if (estado === 'on') {
        _sseIndicador.className = 'sse-indicador sse-on';
        _sseIndicador.innerHTML = '<span class="sse-dot"></span> EN VIVO';
        _sseIndicador.title = 'Recibiendo eventos en tiempo real (SSE)';
    } else {
        _sseIndicador.className = 'sse-indicador sse-off';
        _sseIndicador.innerHTML = '<span class="sse-dot"></span> RECONECTANDO…';
        _sseIndicador.title = 'Sin conexión al stream — reintentando';
    }
}

function _flashIndicadorSSE() {
    if (!_sseIndicador) return;
    _sseIndicador.classList.add('sse-flash');
    setTimeout(() => _sseIndicador?.classList.remove('sse-flash'), 700);
}


// ══════════════════════════════════════════════════════════════
// VERSIONADO DE CRONOGRAMAS — listar y restaurar
// ══════════════════════════════════════════════════════════════
async function cargarVersionesCronograma() {
    const aula  = document.getElementById('ver-aula').value.trim().toUpperCase();
    const turno = document.getElementById('ver-turno').value;
    const cont  = document.getElementById('versiones-resultado');
    cont.innerHTML = `<p style="text-align:center;padding:20px;color:var(--texto-tenue);"><span class="spin">🔄</span> Cargando…</p>`;
    let url = '/api/su/cronograma_versiones';
    const q = [];
    if (aula)  q.push(`aula=${encodeURIComponent(aula)}`);
    if (turno) q.push(`turno=${encodeURIComponent(turno)}`);
    if (q.length) url += '?' + q.join('&');
    const data = await _fetchSU(url);
    if (!data) { cont.innerHTML = ''; return; }
    if (!data.length) {
        cont.innerHTML = `<div class="empty-state"><span class="empty-state-icon">📭</span><span class="empty-state-text">Sin versiones guardadas todavía. Al editar o re-importar un cronograma, las versiones anteriores quedarán acá.</span></div>`;
        return;
    }
    cont.innerHTML = `<div class="table-responsive"><table>
        <thead><tr><th>Fecha</th><th>Aula</th><th>Turno</th><th>Motivo</th><th>Por</th><th>Bloques</th><th>Acción</th></tr></thead>
        <tbody>${data.map(v => `<tr>
            <td style="font-family:'DM Mono',monospace;font-size:.82em;">${(v.creado_en||'').substring(0,19).replace('T',' ')}</td>
            <td><strong>${v.aula}</strong></td>
            <td><span class="chip">${v.turno}</span></td>
            <td>${v.motivo || '—'}</td>
            <td style="font-size:.85em;color:var(--texto-suave);">${v.creado_por || '—'}</td>
            <td style="font-family:'DM Mono',monospace;font-weight:700;color:var(--azul-primario);">${v.bloques_cnt || 0}</td>
            <td><button class="btn btn-warning btn-small" style="margin:0;padding:5px 11px;font-size:.78em;"
                onclick="_restaurarVersion(${v.id},'${v.aula}','${v.turno}','${(v.creado_en||'').substring(0,16)}')">⏪ Restaurar</button></td>
        </tr>`).join('')}</tbody></table></div>`;
}

async function _restaurarVersion(vid, aula, turno, fecha) {
    if (!confirm(`⚠️ Restaurar el cronograma de Aula ${aula} (${turno}) a la versión del ${fecha}?\n\nEl cronograma actual se guardará como una nueva versión (para poder deshacer).`)) return;
    try {
        const r = await fetch(`/api/su/cronograma_versiones/${vid}/restaurar`, {
            method:'POST',
            headers:{'X-SU-Token':window.SIPA.suToken},
        });
        const d = await r.json();
        if (r.ok) { mostrarToast('⏪ ' + d.msj, 'success'); cargarVersionesCronograma(); }
        else mostrarToast(d.error || 'Error.', 'error');
    } catch (e) { mostrarToast('Error: '+e.message, 'error'); }
}


// ══════════════════════════════════════════════════════════════
// CONSOLA SQL READ-ONLY (TIC)
// ══════════════════════════════════════════════════════════════
function _setSql(btn) {
    const q = btn.dataset.sql || '';
    const ta = document.getElementById('sql-query');
    if (ta) {
        ta.value = q;
        ta.focus();
        // Scroll al textarea para que el usuario vea lo que cargó
        ta.scrollIntoView({behavior:'smooth', block:'center'});
    }
}

async function ejecutarSQLConsole() {
    const query = document.getElementById('sql-query').value.trim();
    const out   = document.getElementById('sql-result');
    if (!query) return mostrarToast('Ingrese una query', 'warning');
    out.innerHTML = `<p style="text-align:center;padding:18px;color:var(--texto-tenue);"><span class="spin">🔄</span> Ejecutando…</p>`;
    try {
        const r = await fetch('/api/su/sql', {
            method:'POST',
            headers:{'Content-Type':'application/json','X-SU-Token':window.SIPA.suToken},
            body: JSON.stringify({ query }),
        });
        const d = await r.json();
        if (!r.ok) {
            out.innerHTML = `<div class="bd-error-banner">
                <span style="font-size:1.4em;">🔴</span>
                <div><strong>Error en SQL</strong><pre style="margin:6px 0 0;font-size:.85em;white-space:pre-wrap;">${(d.error||'').substring(0,500)}</pre></div>
            </div>`;
            return;
        }
        if (!d.cols.length || !d.rows.length) {
            out.innerHTML = `<div class="empty-state">Query OK — sin filas devueltas.</div>`;
            return;
        }
        const trunc = d.truncated ? '<div style="font-size:.82em;color:var(--advertencia);margin-bottom:6px;">⚠️ Resultado truncado a 500 filas.</div>' : '';
        out.innerHTML = trunc + `<div style="font-size:.82em;color:var(--texto-suave);margin-bottom:6px;">${d.count} fila(s) — ${d.cols.length} columna(s)</div>
            <div class="table-responsive"><table>
                <thead><tr>${d.cols.map(c => `<th style="font-family:'DM Mono',monospace;">${c}</th>`).join('')}</tr></thead>
                <tbody>${d.rows.map(row => `<tr>${row.map(v =>
                    `<td style="font-family:'DM Mono',monospace;font-size:.85em;">${v === null ? '<em style="color:var(--texto-tenue);">NULL</em>' : String(v).substring(0,200)}</td>`
                ).join('')}</tr>`).join('')}</tbody>
            </table></div>`;
    } catch (e) {
        out.innerHTML = `<div class="bd-error-banner">${e.message}</div>`;
    }
}

// Ctrl+Enter dispara la query
document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
        const ta = document.getElementById('sql-query');
        if (ta && document.activeElement === ta) {
            e.preventDefault();
            ejecutarSQLConsole();
        }
    }
});

// ── Consola SQL: botones dinámicos "Ver contenido" de TODAS las tablas ──
// Se generan desde la BD en vivo (no hardcodeado), así nunca queda desactualizado.
let _sqlTablasCargadas = false;
async function _sqlCargarTablasDinamicas(forzar = false) {
    const cont = document.getElementById('sql-tablas-dinamicas');
    if (!cont) return;
    if (_sqlTablasCargadas && !forzar) return;
    try {
        const r = await fetch('/api/su/sql', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-SU-Token': window.SIPA.suToken || '' },
            body: JSON.stringify({ query: "SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE' ORDER BY table_name" }),
        });
        const d = await r.json();
        if (!r.ok || !Array.isArray(d.rows)) throw new Error(d.error || 'sin datos');
        // Validar identificadores (alfanumérico/underscore) antes de armar el SELECT
        const tablas = d.rows.map(row => String(row[0])).filter(t => /^[a-z_][a-z0-9_]*$/.test(t));
        const botones = tablas.map(t =>
            `<button class="sql-ej-btn" onclick="_setSql(this)" data-sql="SELECT * FROM ${t} LIMIT 100">📄 ${t}</button>`
        ).join('');
        cont.innerHTML = `<div class="sql-ej-grupo-titulo">📂 Ver contenido de tablas (${tablas.length}) — SELECT *</div>${botones}`;
        _sqlTablasCargadas = true;
    } catch (e) {
        cont.innerHTML = `<div class="sql-ej-grupo-titulo">📂 Ver contenido de tablas</div>
            <button class="sql-ej-btn" onclick="_sqlCargarTablasDinamicas(true)">🔄 Cargar lista de tablas</button>`;
    }
}


// ══════════════════════════════════════════════════════════════
// DASHBOARD DEL SU — KPIs y gráficos con Chart.js
// ══════════════════════════════════════════════════════════════
let _dashCharts = {};
function renderResumenEjecutivo(resumen) {
    const cont = document.getElementById('dash-resumen-ejecutivo');
    if (!cont) return;
    const r = resumen || {};
    const cards = [
        { ic: '📝', label: 'Minutas', value: r.total_minutas ?? 0 },
        { ic: '📋', label: 'Firmas', value: r.total_firmas ?? 0 },
        { ic: '✅', label: 'Justificadas', value: r.justificaciones_aprobadas ?? 0 },
        { ic: '⏳', label: 'Pendientes', value: r.justificaciones_pendientes ?? 0 },
        { ic: '🏫', label: 'Aula más activa', value: r.aula_mas_activa?.aula || '—' },
        { ic: '📊', label: 'Promedio/día', value: r.promedio_firmas_por_dia ?? 0 },
    ];
    const aulaMasActiva = r.aula_mas_activa && r.aula_mas_activa.aula !== '—'
        ? `<div style="margin-top:8px;color:var(--texto-suave);font-size:.82em;">${r.aula_mas_activa.cnt} firmas en el período</div>`
        : '';
    const docentes = (r.top_docentes_firmas || []).slice(0, 3).map(x =>
        `<div style="display:flex;justify-content:space-between;gap:10px;padding:5px 0;border-bottom:1px solid rgba(148,163,184,.18);"><span>${escapeHTML(x.docente || '—')}</span><strong>${x.cnt}</strong></div>`
    ).join('') || '<div style="color:var(--texto-tenue);padding:6px 0;">Sin datos.</div>';
    const alertas = (r.alertas_operativas || []).slice(0, 3).map(x =>
        `<div style="padding:6px 0;border-bottom:1px solid rgba(148,163,184,.18);">${escapeHTML(x.fecha)} · ${escapeHTML(x.docente)} · Aula ${escapeHTML(x.aula)} (${escapeHTML(x.turno)}) · ${x.distancia_m ?? '—'} m</div>`
    ).join('') || '<div style="color:var(--texto-tenue);padding:6px 0;">Sin alertas fuera del radio.</div>';

    cont.innerHTML = `
        <div class="card" style="border-top:4px solid #0ea5e9; background:linear-gradient(135deg, rgba(14,165,233,.05), rgba(59,130,246,.02));">
            <h4 style="margin:0 0 12px;color:var(--azul-oscuro);">📊 Resumen ejecutivo institucional</h4>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:10px;">
                ${cards.map(c => `
                    <div style="padding:12px;border:1px solid var(--borde);border-radius:10px;background:rgba(255,255,255,.45);">
                        <div style="font-size:1.2em;">${c.ic}</div>
                        <div style="font-size:1.35em;font-weight:800;margin:6px 0 2px;">${c.value}</div>
                        <div style="font-size:.8em;color:var(--texto-suave);">${c.label}</div>
                    </div>
                `).join('')}
            </div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin-top:14px;">
                <div style="padding:12px;border:1px solid var(--borde);border-radius:10px;background:rgba(255,255,255,.03);">
                    <div style="font-weight:700;color:var(--azul-oscuro);margin-bottom:8px;">🏫 Aula más activa</div>
                    <div style="font-size:1.15em;font-weight:800;">${escapeHTML(r.aula_mas_activa?.aula || '—')}</div>
                    ${aulaMasActiva}
                </div>
                <div style="padding:12px;border:1px solid var(--borde);border-radius:10px;background:rgba(255,255,255,.03);">
                    <div style="font-weight:700;color:var(--azul-oscuro);margin-bottom:8px;">👨‍🏫 Top docentes</div>
                    <div>${docentes}</div>
                </div>
                <div style="padding:12px;border:1px solid var(--borde);border-radius:10px;background:rgba(255,255,255,.03);">
                    <div style="font-weight:700;color:var(--azul-oscuro);margin-bottom:8px;">🚨 Alertas operativas</div>
                    <div>${alertas}</div>
                </div>
            </div>
        </div>
    `;
}

function exportarDashboardSU() {
    const rango = document.getElementById('dash-rango')?.value || '7';
    if (!window.SIPA?.suToken) {
        mostrarToast('Requiere sesión TIC activa.', 'warning');
        return;
    }
    const url = `/api/su/dashboard/export?rango=${encodeURIComponent(rango)}`;
    fetch(url, { headers: { 'X-SU-Token': window.SIPA.suToken } })
        .then(async r => {
            if (!r.ok) {
                const d = await r.json().catch(() => ({}));
                throw new Error(d.error || 'No se pudo exportar el dashboard');
            }
            const blob = await r.blob();
            const a = document.createElement('a');
            const href = URL.createObjectURL(blob);
            a.href = href;
            a.download = `resumen_ejecutivo_${rango}_dias.csv`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(() => URL.revokeObjectURL(href), 1000);
            mostrarToast('✅ CSV exportado.', 'success');
        })
        .catch(e => mostrarToast(e.message, 'error'));
}

function imprimirDashboardSU() {
    const rango = document.getElementById('dash-rango')?.value || '7';
    if (!window.SIPA?.suToken) {
        mostrarToast('Requiere sesión TIC activa.', 'warning');
        return;
    }
    const url = `/api/su/dashboard/print?rango=${encodeURIComponent(rango)}&token=${encodeURIComponent(window.SIPA.suToken)}&_=${Date.now()}`;
    fetch(url)
        .then(async r => {
            if (!r.ok) {
                const d = await r.json().catch(() => ({}));
                throw new Error(d.error || 'No se pudo generar el PDF');
            }
            return r.text();
        })
        .then(html => {
            const win = window.open('', '_blank');
            if (!win) throw new Error('El navegador bloqueó la ventana del PDF. Permita ventanas emergentes para SIPA.');
            win.document.open();
            win.document.write(html);
            win.document.close();
            win.focus();
            setTimeout(() => win.print(), 500);
            mostrarToast('✅ Vista PDF lista para imprimir o guardar.', 'success');
        })
        .catch(e => mostrarToast(e.message, 'error'));
}

async function cargarDashboardSU() {
    const rango = document.getElementById('dash-rango')?.value || '7';
    const d = await _fetchSU('/api/su/dashboard?rango=' + rango);
    if (!d) return;

    const k = d.kpis;
    const kpis = [
        { ic:'📋', val:k.firmas_hoy,    lbl:'Firmas hoy',         col:'verde' },
        { ic:'🏫', val:k.aulas_op_hoy,  lbl:'Aulas operativas',   col:'azul' },
        { ic:'📝', val:k.justifs_hoy,   lbl:'Justificaciones',    col:'naranja' },
        { ic:'🚫', val:k.falls_hoy,     lbl:'Logins fallidos',    col:'rojo' },
        { ic:'👤', val:k.sesiones_admin,lbl:'Sesiones Admin',     col:'gris' },
        { ic:'⚙️', val:k.sesiones_su,   lbl:'Sesiones TIC',       col:'morado' },
        { ic:'🟢', val:k.firmas_dentro ?? 0, lbl:'Firmas dentro de zona', col:'verde' },
        { ic:'🔴', val:k.firmas_fuera ?? 0,  lbl:'Firmas fuera de zona',  col:'rojo' },
        { ic:'📍', val:k.firmas_sin_geo ?? 0, lbl:'Firmas sin GPS',       col:'naranja' },
    ];
    document.getElementById('dash-kpis').innerHTML = kpis.map(x =>
        `<div class="dash-kpi dash-kpi-${x.col}">
            <span class="dash-kpi-ic">${x.ic}</span>
            <span class="dash-kpi-val">${x.val}</span>
            <span class="dash-kpi-lbl">${x.lbl}</span>
        </div>`
    ).join('');

    const alertasGeo = document.getElementById('dash-alertas-geo');
    if (alertasGeo) {
        const lista = d.geo_alertas || [];
        alertasGeo.innerHTML = lista.length
            ? `<div style="border-left:4px solid #dc2626;background:#fef2f2;padding:10px 12px;border-radius:6px;">
                <strong style="color:#991b1b;">🔴 Firmas fuera del radio institucional</strong>
                <div style="margin-top:6px;font-size:.86em;">${lista.slice(0, 5).map(x =>
                    `<div>${escapeHTML(x.fecha)} ${escapeHTML(x.hora)} · ${escapeHTML(x.docente)} · Aula ${escapeHTML(x.aula)} (${escapeHTML(x.turno)}) · ${x.distancia_m ?? '—'} m</div>`
                ).join('')}</div>
                ${lista.length > 5 ? `<small>Se muestran 5 de ${lista.length} alertas.</small>` : ''}
              </div>`
            : '<div style="color:#15803d;font-size:.86em;">🟢 No hay firmas fuera del radio en el período seleccionado.</div>';
    }

    renderResumenEjecutivo(d.resumen_ejecutivo || {});

    // Comparación con período anterior
    const comp = d.comparacion || {};
    const compEl = document.getElementById('dash-comparacion');
    if (compEl && comp.variacion_pct !== undefined) {
        const pct = comp.variacion_pct;
        const flecha = pct > 0 ? '↑' : pct < 0 ? '↓' : '→';
        const color = pct > 0 ? '#10b981' : pct < 0 ? '#ef4444' : '#94a3b8';
        compEl.innerHTML = `<span style="color:${color};font-weight:600;">${flecha} ${Math.abs(pct)}%</span> <span style="color:var(--texto-tenue);">vs periodo anterior (${comp.firmas_actual} vs ${comp.firmas_anterior} firmas)</span>`;
    }

    // Actualizar títulos de gráficos con el rango
    const rangoTxt = rango + ' dias';
    const tF = document.getElementById('dash-titulo-firmas');
    const tA = document.getElementById('dash-titulo-audit');
    if (tF) tF.textContent = '📈 Firmas registradas — ' + rangoTxt;
    if (tA) tA.textContent = '🛡️ Actividad de auditoria — ' + rangoTxt;

    document.getElementById('dash-generado').textContent =
        `Rango: ${d.desde || ''} a ${d.hasta || ''} | Generado: ${(d.generado_en || '').substring(0,19).replace('T',' ')}`;

    // Esperar a que Chart.js esté cargado (con timeout 5s para no colgar la UI)
    if (typeof Chart === 'undefined') {
        const cargado = await new Promise(resolve => {
            const t0 = Date.now();
            const intv = setInterval(() => {
                if (typeof Chart !== 'undefined') { clearInterval(intv); resolve(true); }
                else if (Date.now() - t0 > 5000) { clearInterval(intv); resolve(false); }
            }, 80);
        });
        if (!cargado) {
            document.querySelectorAll('.dash-chart-card canvas').forEach(c => {
                c.outerHTML = '<div class="empty-state" style="margin:0;border-color:var(--peligro-cl);color:var(--peligro);"><span class="empty-state-icon">⚠️</span><span class="empty-state-text">No se pudo cargar Chart.js (red bloqueada). Los KPIs siguen disponibles arriba.</span></div>';
            });
            return;
        }
    }

    // Destruir charts viejos
    Object.values(_dashCharts).forEach(c => { try { c.destroy(); } catch {} });
    _dashCharts = {};

    // Determinar colores por tema
    const dark = document.documentElement.getAttribute('data-theme') === 'dark';
    const colorEjes = dark ? '#94a3b8' : '#4a6178';
    const gridColor = dark ? 'rgba(255,255,255,.08)' : 'rgba(0,0,0,.08)';
    Chart.defaults.color = colorEjes;
    Chart.defaults.borderColor = gridColor;

    // Para rangos > 30 dias, usar line en vez de bar (más legible)
    const tipoFirmas = parseInt(rango) > 30 ? 'line' : 'bar';

    // 1. Firmas
    _dashCharts.firmas = new Chart(document.getElementById('chart-firmas'), {
        type: tipoFirmas,
        data: {
            labels: d.firmas_semanal.labels,
            datasets: [{ label:'Firmas', data: d.firmas_semanal.data,
                         backgroundColor:'rgba(39,174,96,.7)', borderColor:'#1a8a4a', borderWidth:1, borderRadius:6,
                         tension:.3, fill: tipoFirmas==='line', pointRadius: tipoFirmas==='line' ? 2 : 0 }]
        },
        options: { plugins:{legend:{display:false}}, scales:{y:{beginAtZero:true,grid:{color:gridColor}},x:{grid:{display:false}, ticks:{maxTicksLimit:15}}} }
    });

    // 2. Auditoria
    _dashCharts.audit = new Chart(document.getElementById('chart-audit'), {
        type: 'line',
        data: {
            labels: d.audit_semanal.labels,
            datasets: [{ label:'Acciones', data: d.audit_semanal.data,
                         borderColor:'#8b5cf6', backgroundColor:'rgba(139,92,246,.2)',
                         tension:.35, fill:true, pointRadius: parseInt(rango) > 30 ? 1 : 4, pointBackgroundColor:'#8b5cf6' }]
        },
        options: { plugins:{legend:{display:false}}, scales:{y:{beginAtZero:true,grid:{color:gridColor}},x:{grid:{display:false}, ticks:{maxTicksLimit:15}}} }
    });

    // 3. Top ausentes (horizontal bar)
    _dashCharts.ausentes = new Chart(document.getElementById('chart-ausentes'), {
        type: 'bar',
        data: {
            labels: d.top_ausentes.map(x => x.docente),
            datasets: [{ label:'Justificaciones', data: d.top_ausentes.map(x => x.cnt),
                         backgroundColor:'rgba(239,68,68,.65)', borderColor:'#dc2626', borderWidth:1, borderRadius:5 }]
        },
        options: { indexAxis:'y', plugins:{legend:{display:false}},
                   scales:{x:{beginAtZero:true,grid:{color:gridColor}},y:{grid:{display:false}}} }
    });

    // 4. Por rol (donut)
    _dashCharts.roles = new Chart(document.getElementById('chart-roles'), {
        type: 'doughnut',
        data: {
            labels: d.por_rol.map(x => x.rol),
            datasets: [{ data: d.por_rol.map(x => x.cnt),
                         backgroundColor:['#3b82f6','#8b5cf6','#10b981','#f59e0b','#ef4444','#64748b'] }]
        },
        options: { plugins:{legend:{position:'bottom'}} }
    });
}


// ══════════════════════════════════════════════════════════════
// MÓDULO AUDITORÍA & LOGS (Super Usuario)
// ══════════════════════════════════════════════════════════════
function _mostrarLogTab(id, el) {
    document.querySelectorAll('#cfg-auditoria .log-section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('#cfg-auditoria .sub-nav').forEach(n => n.classList.remove('active'));
    document.getElementById(id)?.classList.add('active');
    el.classList.add('active');
    if (id === 'log-audit')  cargarAuditLog();
    if (id === 'log-failed') cargarFailedLogins();
    if (id === 'log-system') cargarSystemLog();
}

async function _fetchSU(url) {
    if (!window.SIPA.suToken) { mostrarToast('Requiere SU.', 'warning'); return null; }
    try {
        const r = await fetch(url, { headers: { 'X-SU-Token': window.SIPA.suToken } });
        if (!r.ok) { const e = await r.json().catch(()=>({})); mostrarToast(e.error || `HTTP ${r.status}`, 'error'); return null; }
        return await r.json();
    } catch (e) { mostrarToast('Error: '+e.message, 'error'); return null; }
}

async function cargarAuditLog() {
    const cont = document.getElementById('audit-log-tabla');
    cont.innerHTML = `<p style="text-align:center;padding:20px;color:var(--texto-tenue);"><span class="spin">🔄</span> Cargando…</p>`;
    const data = await _fetchSU('/api/su/audit_log?limit=200');
    if (!data) { cont.innerHTML = ''; return; }
    if (!data.length) { cont.innerHTML = `<div class="empty-state">Sin eventos registrados.</div>`; return; }
    cont.innerHTML = `<div class="table-responsive"><table>
        <thead><tr><th>Fecha</th><th>Usuario</th><th>Rol</th><th>Acción</th><th>Detalle</th><th>IP</th></tr></thead>
        <tbody>${data.map(r => `<tr>
            <td style="font-family:'DM Mono',monospace;font-size:.78em;white-space:nowrap;">${(r.fecha||'').substring(0,19)}</td>
            <td><strong>${r.usuario || '?'}</strong></td>
            <td><span class="chip">${r.rol || '?'}</span></td>
            <td style="font-weight:600;">${r.accion}</td>
            <td style="font-size:.84em;">${r.tabla ? `<code>${r.tabla}</code> · ` : ''}${r.registro_ref || ''}${r.detalle ? `<br><span style="color:var(--texto-tenue);">${r.detalle}</span>` : ''}</td>
            <td style="font-family:'DM Mono',monospace;font-size:.78em;">${r.ip || '?'}</td>
        </tr>`).join('')}</tbody>
    </table></div>`;
}

async function cargarFailedLogins() {
    const cont = document.getElementById('failed-log-tabla');
    cont.innerHTML = `<p style="text-align:center;padding:20px;color:var(--texto-tenue);"><span class="spin">🔄</span> Cargando…</p>`;
    const data = await _fetchSU('/api/su/failed_logins?limit=200');
    if (!data) { cont.innerHTML = ''; return; }
    if (!data.length) { cont.innerHTML = `<div class="empty-state">🎉 Sin intentos fallidos. Sin alertas.</div>`; return; }
    cont.innerHTML = `<div class="table-responsive"><table>
        <thead><tr><th>Fecha</th><th>Tipo</th><th>Detalle</th><th>IP</th></tr></thead>
        <tbody>${data.map(r => `<tr style="background:#fef9f9;">
            <td style="font-family:'DM Mono',monospace;font-size:.78em;">${(r.fecha||'').substring(0,19)}</td>
            <td><span class="badge-rojo">${r.tipo}</span></td>
            <td>${r.detalle || ''}</td>
            <td style="font-family:'DM Mono',monospace;font-size:.78em;">${r.ip || '?'}</td>
        </tr>`).join('')}</tbody>
    </table></div>`;
}

async function cargarSystemLog() {
    const cont = document.getElementById('system-log-tabla');
    cont.innerHTML = `<p style="text-align:center;padding:20px;color:var(--texto-tenue);"><span class="spin">🔄</span> Cargando…</p>`;
    const data = await _fetchSU('/api/su/system_log?limit=100');
    if (!data) { cont.innerHTML = ''; return; }
    if (!data.length) { cont.innerHTML = `<div class="empty-state">🎉 Sin errores recientes.</div>`; return; }
    cont.innerHTML = data.map(r => `
        <details class="syslog-item">
            <summary>
                <span class="syslog-nivel syslog-nivel-${(r.nivel||'').toLowerCase()}">${r.nivel}</span>
                <span style="font-family:'DM Mono',monospace;font-size:.78em;color:var(--texto-tenue);">${(r.fecha||'').substring(0,19)}</span>
                <code style="font-size:.82em;">${r.endpoint || '?'}</code>
                <span style="font-size:.85em;color:var(--texto);">${(r.mensaje||'').substring(0,100)}</span>
            </summary>
            <pre style="background:#1e293b;color:#cbd5e1;padding:11px;border-radius:6px;overflow-x:auto;font-size:.78em;margin-top:8px;">${r.traceback || r.mensaje || ''}</pre>
        </details>
    `).join('');
}

// ══════════════════════════════════════════════════════════════
// MÓDULO SALUD / MANTENIMIENTO (Super Usuario)
// ══════════════════════════════════════════════════════════════
async function toggleMantenimiento(activo) {
    if (!window.SIPA.suToken) return mostrarToast('Requiere SU.', 'warning');
    if (activo && !confirm('⚠️ Activar Modo Mantenimiento BLOQUEARÁ a TODA la Plana Mayor, Bedeles y Docentes hasta que lo desactives. ¿Confirmás?')) {
        document.getElementById('maint-toggle').checked = false;
        return;
    }
    try {
        const r = await fetch('/api/su/maintenance', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify({ activo: !!activo }),
        });
        const d = await r.json();
        if (r.ok) {
            mostrarToast((activo ? '🔧 ' : '✅ ') + d.msj, activo ? 'warning' : 'success');
            document.getElementById('maint-card').classList.toggle('maint-card-activa', !!activo);
            document.getElementById('maint-toggle-label').textContent = activo ? 'ACTIVO' : 'Activar';
        } else {
            mostrarToast(d.error || 'Error.', 'error');
            document.getElementById('maint-toggle').checked = !activo;
        }
    } catch (e) {
        mostrarToast('Error: '+e.message, 'error');
        document.getElementById('maint-toggle').checked = !activo;
    }
}

async function cargarHealthCheck() {
    const cont = document.getElementById('health-result');
    cont.innerHTML = `<p style="text-align:center;padding:20px;color:var(--texto-tenue);"><span class="spin">🔄</span> Verificando…</p>`;
    const s = await _fetchSU('/api/su/health');
    if (!s) { cont.innerHTML = ''; return; }

    const uptime = _formatUptime(s.uptime_seg);
    const dbOk   = s.db_ok;
    const maintenance = s.modo_mantenimiento;

    // Sincronizar toggle con estado real
    const t = document.getElementById('maint-toggle');
    if (t) {
        t.checked = !!maintenance;
        document.getElementById('maint-card').classList.toggle('maint-card-activa', !!maintenance);
        document.getElementById('maint-toggle-label').textContent = maintenance ? 'ACTIVO' : 'Activar';
    }

    cont.innerHTML = `
        <div class="health-grid">
            <div class="health-card ${dbOk ? 'health-ok' : 'health-err'}">
                <div class="health-icon">${dbOk ? '🟢' : '🔴'}</div>
                <div class="health-label">PostgreSQL</div>
                <div class="health-valor">${dbOk ? 'Conectado' : 'ERROR'}</div>
                <div class="health-detalle">${s.pg_version || s.db_error || ''}</div>
            </div>
            <div class="health-card">
                <div class="health-icon">⏱️</div>
                <div class="health-label">Uptime</div>
                <div class="health-valor">${uptime}</div>
                <div class="health-detalle">Desde: ${(s.ahora||'').substring(0,19)}</div>
            </div>
            <div class="health-card">
                <div class="health-icon">👥</div>
                <div class="health-label">Sesiones Activas</div>
                <div class="health-valor">${s.sesiones_admin} + ${s.sesiones_su}</div>
                <div class="health-detalle">Admin · TIC</div>
            </div>
            <div class="health-card ${maintenance ? 'health-warn' : ''}">
                <div class="health-icon">${maintenance ? '🛠️' : '✅'}</div>
                <div class="health-label">Modo</div>
                <div class="health-valor">${maintenance ? 'MANTENIMIENTO' : 'Normal'}</div>
            </div>
        </div>
        <h4 style="margin:18px 0 8px;color:var(--azul-oscuro);">📊 Conteo de Filas por Tabla</h4>
        <div class="table-responsive"><table>
            <thead><tr><th>Tabla</th><th style="text-align:right;">Filas</th></tr></thead>
            <tbody>${Object.entries(s.tablas_filas).map(([t, n]) => {
                let color, valor, opacity = '1';
                if (n === null) {
                    color = 'var(--peligro)'; valor = 'ERROR';
                } else if (n === '—') {
                    color = 'var(--texto-tenue)'; valor = 'pendiente'; opacity = '.55';
                } else {
                    color = 'var(--azul-primario)'; valor = n;
                }
                return `<tr style="opacity:${opacity};">
                    <td><code>${t}</code></td>
                    <td style="font-family:'DM Mono',monospace;font-weight:700;color:${color};text-align:right;">
                        ${valor}
                    </td></tr>`;
            }).join('')}
            </tbody>
        </table></div>`;
}

function _formatUptime(seg) {
    if (seg < 60) return `${seg}s`;
    if (seg < 3600) return `${Math.floor(seg/60)}m ${seg%60}s`;
    if (seg < 86400) return `${Math.floor(seg/3600)}h ${Math.floor((seg%3600)/60)}m`;
    return `${Math.floor(seg/86400)}d ${Math.floor((seg%86400)/3600)}h`;
}

// ══════════════════════════════════════════════════════════════
// GESTIÓN DE USUARIOS (Super Usuario)
// ══════════════════════════════════════════════════════════════
async function cargarDocentesParaReset() {
    const cont = document.getElementById('su-docentes-lista');
    cont.innerHTML = `<p style="text-align:center;padding:20px;color:var(--texto-tenue);"><span class="spin">🔄</span> Cargando…</p>`;
    const data = await _fetchSU('/api/su/listar_docentes');
    if (!data) { cont.innerHTML = ''; return; }
    if (!data.length) { cont.innerHTML = `<div class="empty-state">Sin docentes registrados aún.</div>`; return; }
    cont.innerHTML = `<div class="table-responsive"><table>
        <thead><tr><th>Nombre</th><th>Email</th><th>DNI</th><th>Acción</th></tr></thead>
        <tbody>${data.map(d => `<tr>
            <td><strong>${d.nombre}</strong></td>
            <td style="font-size:.85em;">${d.email}</td>
            <td style="font-family:'DM Mono',monospace;font-size:.85em;">${d.dni}</td>
            <td><button class="btn btn-warning btn-small" style="margin:0;padding:5px 10px;font-size:.78em;"
                onclick="_resetPwdDocente('${d.email.replace(/'/g,"\\'")}','${d.nombre.replace(/'/g,"\\'")}')">🔓 Resetear Clave</button></td>
        </tr>`).join('')}</tbody></table></div>`;
}

async function _resetPwdDocente(email, nombre) {
    const nueva = prompt(`Nueva clave para ${nombre} (dejá vacío para autogenerar):`, '');
    if (nueva === null) return;
    try {
        const r = await fetch('/api/su/reset_docente_password', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify({ email, new_password: nueva || undefined }),
        });
        const d = await r.json();
        if (r.ok) {
            alert(`✅ Password reseteado para ${nombre}\n\nNueva clave: ${d.nueva_password}\n\nEntréguesela en persona.`);
        } else {
            mostrarToast(d.error || 'Error.', 'error');
        }
    } catch (e) {
        mostrarToast('Error: '+e.message, 'error');
    }
}

async function revocarTokens(scope) {
    const msj = scope === 'all'
        ? '⚠️ Cerrar TODAS las sesiones (Plana Mayor y otras sesiones TIC). Tu sesión actual queda activa. ¿Confirmás?'
        : '⚠️ Cerrar TODAS las sesiones de Plana Mayor. ¿Confirmás?';
    if (!confirm(msj)) return;
    try {
        const r = await fetch('/api/su/revoke_tokens', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify({ scope }),
        });
        const d = await r.json();
        if (r.ok) mostrarToast('🚪 ' + d.msj, 'success');
        else mostrarToast(d.error || 'Error.', 'error');
    } catch (e) {
        mostrarToast('Error: '+e.message, 'error');
    }
}

// ══════════════════════════════════════════════════════════════
// HARD RESET CRONOGRAMA
// ══════════════════════════════════════════════════════════════
function _chequearPurgaCronograma() {
    const inp = document.getElementById('confirmar-purga-cronograma');
    const btn = document.getElementById('btn-purgar-cronograma');
    if (!inp || !btn) return;
    btn.disabled = inp.value.trim() !== 'PURGAR CRONOGRAMA';
}

async function purgarCronograma() {
    if (!window.SIPA.suToken) return mostrarToast('Requiere SU.', 'warning');
    const frase = document.getElementById('confirmar-purga-cronograma').value.trim();
    if (frase !== 'PURGAR CRONOGRAMA') return mostrarToast('Tipee: PURGAR CRONOGRAMA', 'error');
    if (!confirm('Esto elimina la tabla cronograma_maestro completa.\n(Las firmas, padrones y minutas se conservan.)\n\n¿Continuar?')) return;
    try {
        const r = await fetch('/api/su/hard_reset_cronograma', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify({ confirmacion: frase }),
        });
        const d = await r.json();
        if (r.ok) {
            mostrarToast('♻️ ' + d.msj, 'success');
            document.getElementById('confirmar-purga-cronograma').value = '';
            document.getElementById('btn-purgar-cronograma').disabled = true;
        } else {
            mostrarToast(d.error || 'Error.', 'error');
        }
    } catch (e) {
        mostrarToast('Error: '+e.message, 'error');
    }
}

// ══════════════════════════════════════════════════════════════
// MÓDULO PELIGRO (Super Usuario): Backup + Formateo
// ══════════════════════════════════════════════════════════════
function _chequearConfirmacionFormateo() {
    const inp = document.getElementById('confirmar-formateo-input');
    const btn = document.getElementById('btn-formatear-su');
    if (!inp || !btn) return;
    btn.disabled = inp.value.trim() !== 'CONFIRMAR FORMATEO INSTITUCIONAL';
}

async function restaurarSistema() {
    if (!window.SIPA.suToken) {
        return mostrarToast('Esta operación requiere autenticación de Super Usuario (TIC).', 'warning');
    }
    const inp = document.getElementById('confirmar-formateo-input');
    const frase = inp ? inp.value.trim() : '';
    if (frase !== 'CONFIRMAR FORMATEO INSTITUCIONAL') {
        return mostrarToast('Tipee EXACTAMENTE: CONFIRMAR FORMATEO INSTITUCIONAL', 'error');
    }
    if (!confirm('⚠️ ÚLTIMA CONFIRMACIÓN\n\nEsto vacía TODAS las tablas del sistema: firmas, minutas, padrones, cronogramas, justificaciones, cuentas docentes y overrides de PIN.\n\nNo se puede deshacer. ¿Continuar?')) return;
    try {
        const res = await fetch('/api/limpiar_sistema', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-SU-Token':   window.SIPA.suToken,
            },
            body: JSON.stringify({ confirmacion: frase }),
        });
        const d = await res.json();
        if (res.ok) {
            mostrarToast('🗑️ ' + d.msj, 'success');
            setTimeout(() => location.reload(), 2200);
        } else {
            mostrarToast(d.error || 'Error.', 'error');
        }
    } catch (e) {
        mostrarToast('Error: ' + e.message, 'error');
    }
}

// ══════════════════════════════════════════════════════════════
// TELEGRAM — config, prueba y reenvío manual
// ══════════════════════════════════════════════════════════════
async function copiarInstruccionesTelegram() {
    const comandosBotFather = document.getElementById('tg-botfather-commands')?.textContent
        .trim().split(/\r?\n/) || [];
    if (!comandosBotFather.length) {
        return mostrarToast('No se encontró el bloque de comandos para BotFather.', 'error');
    }
    const instrucciones = [
        'GUIA COMPLETA: CREAR Y CONFIGURAR EL BOT DE S.I.P.A.',
        '',
        '1) Crear el bot y obtener el token',
        '• En Telegram, abrí el chat oficial @BotFather y enviá /newbot.',
        '• Elegí un nombre visible para el bot (por ejemplo: SIPA Escuela).',
        '• Elegí un username único que termine en bot (por ejemplo: sipa_cuello_bot).',
        '• BotFather enviará un token. Guardalo de forma privada y pegalo en “Token del bot” en S.I.P.A.',
        '',
        '2) Cargar el menu de comandos en @BotFather',
        '• Enviá /setcommands a @BotFather y seleccioná tu bot.',
        '• Copiá y pegá TODO el bloque siguiente como mensaje (sin agregar barras antes de los comandos):',
        '',
        ...comandosBotFather,
        '',
        '3) Crear el grupo de Plana Mayor',
        '• Creá un grupo privado de Telegram para Plana Mayor y agregá el bot.',
        '• Para que el bot reciba comandos escritos en el grupo, enviá /setprivacy a @BotFather, seleccioná el bot y elegí Disable.',
        '• Enviá un mensaje nuevo al grupo luego de cambiar la privacidad.',
        '',
        '4) Obtener el chat_id del grupo',
        '• Abrí en un navegador esta dirección y reemplazá <TU_TOKEN> por el token del bot:',
        '  https://api.telegram.org/bot<TU_TOKEN>/getUpdates',
        '• Buscá el mensaje que enviaste y copiá el valor de "chat":{"id":...}. Para grupos, conservá el signo menos (normalmente comienza con -100).',
        '• Pegá ese número en “Chat ID del grupo” en S.I.P.A.',
        '',
        '5) Guardar y probar en S.I.P.A.',
        '• En TIC > Telegram, ingresá el token y el chat_id, configurá las opciones y presioná Guardar.',
        '• Usá el botón de prueba y verificá que el mensaje llegue al grupo.',
        '• Para que el bot procese comandos, activá “Bot interactivo”.',
        '• El acceso de Telegram para Bedelía se controla por separado en la misma pestaña; el PIN diario sigue disponible.',
        '',
        'SEGURIDAD',
        '• No publiques ni reenvíes el token. Permite controlar el bot.',
        '• Si el token se expone, pedí uno nuevo a @BotFather con /revoke y actualizalo en S.I.P.A.',
    ].join('\n');
    try {
        if (navigator.clipboard?.writeText) {
            await navigator.clipboard.writeText(instrucciones);
        } else {
            const temporal = document.createElement('textarea');
            temporal.value = instrucciones;
            temporal.setAttribute('readonly', '');
            temporal.style.position = 'fixed';
            temporal.style.opacity = '0';
            document.body.appendChild(temporal);
            temporal.select();
            const copiado = document.execCommand('copy');
            temporal.remove();
            if (!copiado) throw new Error('El navegador no permitió copiar al portapapeles.');
        }
        mostrarToast('✅ Guía y comandos para @BotFather copiados.', 'success');
    } catch (error) {
        console.error('[copiarInstruccionesTelegram]', error);
        mostrarToast(`No se pudieron copiar las instrucciones: ${error.message}`, 'error');
    }
}

async function cargarTelegramConfig() {
    if (!window.SIPA.suToken) return mostrarToast('Requiere autenticación SU.', 'warning');
    cargarEstadoAccesoTelegramBedelia();
    try {
        const r = await fetch('/api/su/telegram/config', { headers: { 'X-SU-Token': window.SIPA.suToken } });
        const d = await r.json();
        if (!r.ok) return mostrarToast(d.error || 'Error', 'error');
        // El input de token va vacío (placeholder muestra los 4 últimos chars si existe)
        const inputToken = document.getElementById('tg-token');
        if (inputToken) {
            inputToken.value = '';
            inputToken.placeholder = d.token_configurado
                ? `••••••${d.token_mask.slice(-4)} (dejar vacío para conservar)`
                : '123456:ABCdefGHIjklMNOpqrSTU-vwxYZ';
        }
        const inputChat   = document.getElementById('tg-chat-id');         if (inputChat)   inputChat.value   = d.chat_id || '';
        const inputActivo = document.getElementById('tg-activo');          if (inputActivo) inputActivo.checked = !!d.activo;
        const inputBot    = document.getElementById('tg-bot-interactivo'); if (inputBot)    inputBot.checked    = !!d.bot_interactivo;
        // Toggles de alertas
        const alerts = d.alerts || {};
        const mapAlerts = {
            'tg-al-resumen-diario':       'telegram_alert_resumen_diario',
            'tg-al-minutas-tardias':      'telegram_alert_minutas_tardias',
            'tg-al-docentes-no-firman':   'telegram_alert_docentes_no_firman',
            'tg-al-ausentismo':           'telegram_alert_ausentismo',
            'tg-al-baja-asistencia':      'telegram_alert_baja_asistencia',
            'tg-al-login-sospechoso':     'telegram_alert_login_sospechoso',
            'tg-al-pins-dia':             'telegram_alert_pins_dia',
            'tg-al-justif-pend':          'telegram_alert_justif_pend',
            'tg-al-cronograma':           'telegram_alert_cronograma',
            'tg-al-backup':               'telegram_alert_backup',
            'tg-al-status-diario':        'telegram_alert_status_diario',
        };
        Object.entries(mapAlerts).forEach(([id, key]) => {
            const el = document.getElementById(id);
            if (el) el.checked = !!alerts[key];
        });
        // Cargar estadísticas en paralelo
        cargarTelegramStats();
        const out = document.getElementById('tg-resultado');
        if (out) {
            out.innerHTML = `<div class="nota-info" style="background:#f0f9ff;border-left:3px solid #0088cc;color:var(--texto);">
                ${d.token_configurado ? '✅ Token configurado' : '⚠️ Token NO configurado'}
                · ${d.chat_id ? '✅ chat_id: <code>' + d.chat_id + '</code>' : '⚠️ chat_id NO configurado'}
                <br>📨 Envío de minutas: <strong>${d.activo ? 'ACTIVO 🟢' : 'INACTIVO 🔴'}</strong>
                · 🤖 Bot interactivo: <strong>${d.bot_interactivo ? 'ACTIVO 🟢' : 'INACTIVO 🔴'}</strong>
            </div>`;
        }
    } catch (e) {
        mostrarToast('Error al cargar: ' + e.message, 'error');
    }
}

async function cargarEstadoAccesoTelegramBedelia() {
    const estado = document.getElementById('tg-bedel-acceso-estado');
    const boton = document.getElementById('btn-tg-bedel-acceso');
    if (!estado || !boton) return;
    boton.disabled = true;
    try {
        const response = await fetch('/api/su/telegram/acceso_bedelia', {
            headers: { 'X-SU-Token': window.SIPA.suToken },
        });
        const datos = await response.json();
        if (!response.ok) throw new Error(datos.error || `HTTP ${response.status}`);
        window.SIPA.telegramBedelAccesoActivo = !!datos.activo;
        estado.innerHTML = `${datos.activo
            ? '<span class="badge-verde">🟢 ACTIVADO</span> — vinculación, comandos y acceso disponibles; PIN vigente.'
            : '<span class="badge-mini">🔒 DESACTIVADO</span> — funciones Telegram de Bedelía ocultas y bloqueadas.'}
            <br><small>${Number(datos.bedeles_vinculados) || 0} bedel(es) vinculado(s) a Telegram</small>`;
        boton.className = datos.activo ? 'btn btn-warning' : 'btn btn-primary';
        boton.textContent = datos.activo
            ? '⏸️ Desactivar Telegram de Bedelía'
            : '▶️ Activar Telegram de Bedelía';
    } catch (error) {
        estado.textContent = `No se pudo consultar el estado: ${error.message}`;
        boton.textContent = 'No disponible';
        console.error('[cargarEstadoAccesoTelegramBedelia]', error);
    } finally {
        boton.disabled = false;
    }
}

async function toggleAccesoTelegramBedelia() {
    if (!window.SIPA?.suToken) return mostrarToast('Requiere autenticación TIC.', 'warning');
    const activo = !window.SIPA.telegramBedelAccesoActivo;
    const mensaje = activo
        ? '¿Activar toda la integración de Telegram para Bedelía? Se habilitarán vinculación, comandos del bot y enlace de acceso. El PIN diario seguirá vigente.'
        : '¿Desactivar por completo Telegram para Bedelía? Se ocultará la vinculación y se bloquearán sus comandos y enlaces. Los bedeles ingresarán con el PIN diario. Se conservarán los vínculos guardados.';
    if (!confirm(mensaje)) return;
    const boton = document.getElementById('btn-tg-bedel-acceso');
    if (boton) boton.disabled = true;
    try {
        const response = await fetch('/api/su/telegram/acceso_bedelia', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-SU-Token': window.SIPA.suToken,
            },
            body: JSON.stringify({ activo }),
        });
        const datos = await response.json();
        if (!response.ok) throw new Error(datos.error || `HTTP ${response.status}`);
        window.SIPA.telegramBedelAccesoActivo = datos.activo;
        mostrarToast(datos.msj, 'success');
        await cargarEstadoAccesoTelegramBedelia();
    } catch (error) {
        mostrarToast(`No se pudo cambiar el acceso: ${error.message}`, 'error');
    } finally {
        if (boton) boton.disabled = false;
    }
}

async function guardarTelegramConfig() {
    if (!window.SIPA.suToken) return mostrarToast('Requiere autenticación SU.', 'warning');
    const token           = (document.getElementById('tg-token').value || '').trim();
    const chat_id         = (document.getElementById('tg-chat-id').value || '').trim();
    const activo          = document.getElementById('tg-activo').checked;
    const bot_interactivo = (document.getElementById('tg-bot-interactivo') || {}).checked || false;
    // Recopilar el estado de los 11 toggles de alertas
    const mapAlerts = {
        'tg-al-resumen-diario':       'telegram_alert_resumen_diario',
        'tg-al-minutas-tardias':      'telegram_alert_minutas_tardias',
        'tg-al-docentes-no-firman':   'telegram_alert_docentes_no_firman',
        'tg-al-ausentismo':           'telegram_alert_ausentismo',
        'tg-al-baja-asistencia':      'telegram_alert_baja_asistencia',
        'tg-al-login-sospechoso':     'telegram_alert_login_sospechoso',
        'tg-al-pins-dia':             'telegram_alert_pins_dia',
        'tg-al-justif-pend':          'telegram_alert_justif_pend',
        'tg-al-cronograma':           'telegram_alert_cronograma',
        'tg-al-backup':               'telegram_alert_backup',
        'tg-al-status-diario':        'telegram_alert_status_diario',
    };
    const alerts = {};
    Object.entries(mapAlerts).forEach(([id, key]) => {
        const el = document.getElementById(id);
        alerts[key] = el ? el.checked : false;
    });
    if (!chat_id) return mostrarToast('Falta chat_id del grupo.', 'warning');
    try {
        const r = await fetch('/api/su/telegram/config', {
            method:'POST',
            headers:{ 'Content-Type':'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify({ token, chat_id, activo, bot_interactivo, alerts }),
        });
        const d = await r.json();
        if (r.ok) {
            mostrarToast('✅ ' + d.msj, 'success');
            cargarTelegramConfig();
        } else {
            mostrarToast(d.error || 'Error', 'error');
        }
    } catch (e) {
        mostrarToast('Error: ' + e.message, 'error');
    }
}

async function probarTelegram() {
    if (!window.SIPA.suToken) return mostrarToast('Requiere autenticación SU.', 'warning');
    const out = document.getElementById('tg-resultado');
    if (out) out.innerHTML = '<div class="nota-info">🔄 Enviando mensaje de prueba...</div>';
    try {
        const r = await fetch('/api/su/telegram/test', {
            method:'POST',
            headers:{ 'Content-Type':'application/json', 'X-SU-Token': window.SIPA.suToken },
        });
        const d = await r.json();
        if (d.ok) {
            if (out) out.innerHTML = `<div class="bd-ok-banner">✅ Mensaje de prueba enviado correctamente al grupo.</div>`;
            mostrarToast('✅ Prueba enviada al grupo', 'success');
        } else {
            if (out) out.innerHTML = `<div class="bd-error-banner"><strong>❌ Falló:</strong> ${d.msj || 'sin detalle'}</div>`;
            mostrarToast('❌ ' + (d.msj || 'Error al probar'), 'error');
        }
    } catch (e) {
        if (out) out.innerHTML = `<div class="bd-error-banner"><strong>❌ Error:</strong> ${e.message}</div>`;
    }
}

async function reenviarMinutaTelegram() {
    if (!window.SIPA.suToken) return mostrarToast('Requiere autenticación SU.', 'warning');
    const aula  = (document.getElementById('tg-re-aula').value || '').trim().toUpperCase();
    const turno = document.getElementById('tg-re-turno').value;
    const fecha = document.getElementById('tg-re-fecha').value;
    if (!aula || !fecha) return mostrarToast('Completá aula y fecha.', 'warning');
    const out = document.getElementById('tg-reenvio-resultado');
    if (out) out.innerHTML = '<div class="nota-info">🔄 Reenviando minuta...</div>';
    try {
        const r = await fetch('/api/su/telegram/reenviar', {
            method:'POST',
            headers:{ 'Content-Type':'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify({ aula, turno, fecha }),
        });
        const d = await r.json();
        if (d.ok) {
            if (out) out.innerHTML = `<div class="bd-ok-banner">✅ Minuta reenviada al grupo (${aula}/${turno}/${fecha}).</div>`;
            mostrarToast('✅ Reenviado', 'success');
        } else {
            if (out) out.innerHTML = `<div class="bd-error-banner"><strong>❌ Falló:</strong> ${d.msj || 'sin detalle'}</div>`;
            mostrarToast('❌ ' + (d.msj || 'Error'), 'error');
        }
    } catch (e) {
        if (out) out.innerHTML = `<div class="bd-error-banner"><strong>❌ Error:</strong> ${e.message}</div>`;
    }
}


async function enviarManualTG(tipo) {
    if (!window.SIPA.suToken) return mostrarToast('Requiere autenticación SU.', 'warning');
    const out = document.getElementById('tg-manual-resultado');
    if (out) out.innerHTML = `<div class="nota-info">🔄 Generando y enviando "${tipo}"...</div>`;
    try {
        const r = await fetch('/api/su/telegram/enviar_manual', {
            method:'POST',
            headers:{ 'Content-Type':'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify({ tipo }),
        });
        const d = await r.json();
        if (d.ok) {
            if (out) out.innerHTML = `<div class="bd-ok-banner">✅ Enviado al grupo: <code>${tipo}</code></div>`;
            mostrarToast('✅ Enviado al grupo', 'success');
            // Refrescar stats
            setTimeout(cargarTelegramStats, 1000);
        } else {
            if (out) out.innerHTML = `<div class="bd-error-banner"><strong>❌ Falló:</strong> ${d.msj || 'sin detalle'}</div>`;
            mostrarToast('❌ ' + (d.msj || 'Error'), 'error');
        }
    } catch (e) {
        if (out) out.innerHTML = `<div class="bd-error-banner"><strong>❌ Error:</strong> ${e.message}</div>`;
    }
}

async function cargarTelegramStats() {
    if (!window.SIPA.suToken) return;
    try {
        const r = await fetch('/api/su/telegram/stats', { headers: { 'X-SU-Token': window.SIPA.suToken } });
        const d = await r.json();
        if (!d.ok) return;
        const setVal = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
        setVal('tg-stat-ok',   d.exitos_7d);
        setVal('tg-stat-warn', d.warnings_7d);
        setVal('tg-stat-err',  d.errores_7d);
        const cont = document.getElementById('tg-stats-recientes');
        if (cont) {
            if (!(d.recientes || []).length) {
                cont.innerHTML = '<i>Sin eventos registrados todavía.</i>';
            } else {
                cont.innerHTML = d.recientes.map(ev => {
                    const cls = ev.mensaje.startsWith('[telegram] Excep') ? 'color:#b91c1c;'
                              : ev.mensaje.includes('enviado') ? 'color:#16a34a;'
                              : 'color:#64748b;';
                    return `<div style="${cls}padding:3px 0;border-bottom:1px solid #e2e8f0;">
                        <small>${ev.fecha.substring(0,19).replace('T',' ')}</small><br>
                        ${ev.mensaje}
                    </div>`;
                }).join('');
            }
        }
    } catch (e) {}
}


async function descargarBackup() {
    if (!window.SIPA.suToken) {
        return mostrarToast('Requiere autenticación SU.', 'warning');
    }
    try {
        const r = await fetch('/api/su/backup', {
            headers: { 'X-SU-Token': window.SIPA.suToken },
        });
        if (!r.ok) {
            const d = await r.json().catch(() => ({}));
            return mostrarToast(d.error || `HTTP ${r.status}`, 'error');
        }
        const blob = await r.blob();
        const url  = URL.createObjectURL(blob);
        const a    = document.createElement('a');
        a.href = url;
        a.download = `sipa_backup_${new Date().toISOString().substring(0,19).replace(/[:T]/g,'-')}.json`;
        document.body.appendChild(a); a.click(); a.remove();
        URL.revokeObjectURL(url);
        mostrarToast('💾 Backup descargado.', 'success');
    } catch (e) {
        mostrarToast('Error: ' + e.message, 'error');
    }
}

// ══════════════════════════════════════════════════════════════
// MÓDULO SEGURIDAD / PINES (Super Usuario)
// ══════════════════════════════════════════════════════════════
async function cargarMapaPines() {
    const cont = document.getElementById('su-pines-tabla');
    if (!cont) return;
    if (!window.SIPA.suToken) return mostrarToast('Requiere SU.', 'warning');
    cont.innerHTML = `<p style="color:var(--texto-tenue);text-align:center;padding:20px;"><span class="spin">🔄</span> Cargando…</p>`;
    try {
        const r = await fetch('/api/su/pines_hoy', {
            headers: { 'X-SU-Token': window.SIPA.suToken },
        });
        const data = await r.json();
        if (!r.ok) return cont.innerHTML = `<div class="empty-state" style="color:var(--peligro);">${data.error || 'Error'}</div>`;
        if (!data.length) return cont.innerHTML = `<div class="empty-state">Sin aulas configuradas.</div>`;

        cont.innerHTML = `<div class="table-responsive">
            <table>
                <thead><tr><th>Aula</th><th>Turno</th><th>PIN</th><th>Origen</th><th>Acción</th></tr></thead>
                <tbody>${data.map(p => `
                    <tr>
                        <td><strong>${p.aula}</strong></td>
                        <td><span class="chip">${p.turno}</span></td>
                        <td><span class="pin-display">${p.pin}</span></td>
                        <td>${p.override
                            ? `<span class="badge-mini badge-mini-verde">BLANQUEADO</span>${p.motivo ? `<div style="font-size:.78em;color:var(--texto-suave);margin-top:3px;">${p.motivo}</div>` : ''}`
                            : `<span class="badge-mini badge-mini-gris">HASH AUTO</span>`}</td>
                        <td>
                            <button class="btn btn-warning btn-small" style="margin:0;padding:5px 10px;font-size:.78em;"
                                    onclick="_blanquearPin('${p.aula}','${p.turno}')">🔓 Blanquear</button>
                            ${p.override ? `<button class="btn btn-secondary btn-small" style="margin:0;padding:5px 10px;font-size:.78em;"
                                    onclick="_restaurarPin('${p.aula}','${p.turno}')">↩️ Restaurar</button>` : ''}
                        </td>
                    </tr>`).join('')}</tbody>
            </table>
        </div>`;
    } catch (e) {
        cont.innerHTML = `<div class="empty-state" style="color:var(--peligro);">Error: ${e.message}</div>`;
    }
}

async function _blanquearPin(aula, turno) {
    const motivo = prompt(`Motivo del blanqueo para Aula ${aula} (${turno}):`, 'Bloqueo de terminal — solicitud Bedelía');
    if (motivo === null) return;
    try {
        const r = await fetch('/api/su/pin_blanquear', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify({ aula, turno, motivo }),
        });
        const d = await r.json();
        if (r.ok) { mostrarToast('🔓 ' + d.msj, 'success'); cargarMapaPines(); }
        else mostrarToast(d.error || 'Error.', 'error');
    } catch (e) {
        mostrarToast('Error: ' + e.message, 'error');
    }
}

async function _restaurarPin(aula, turno) {
    if (!confirm(`Volver al PIN calculado por hash para Aula ${aula} (${turno})?`)) return;
    try {
        const r = await fetch('/api/su/pin_restaurar', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify({ aula, turno }),
        });
        const d = await r.json();
        if (r.ok) { mostrarToast('↩️ ' + d.msj, 'success'); cargarMapaPines(); }
        else mostrarToast(d.error || 'Error.', 'error');
    } catch (e) {
        mostrarToast('Error: ' + e.message, 'error');
    }
}

// ══════════════════════════════════════════════════════════════
// MÓDULO PARÁMETROS (Super Usuario)
// ══════════════════════════════════════════════════════════════
async function cargarParametrosSU() {
    const cont = document.getElementById('su-params-form');
    if (!cont || !window.SIPA.suToken) return;
    try {
        const r = await fetch('/api/su/parametros', {
            headers: { 'X-SU-Token': window.SIPA.suToken },
        });
        const params = await r.json();
        if (!r.ok) return cont.innerHTML = `<div class="empty-state" style="color:var(--peligro);">${params.error || 'Error'}</div>`;

        cont.innerHTML = Object.entries(params).map(([k, v]) => `
            <div class="param-row">
                <div class="param-info">
                    <div class="param-clave">${k}</div>
                    <div class="param-desc">${v.descripcion || ''}</div>
                </div>
                <input type="text" class="param-input" data-clave="${k}"
                       value="${v.valor}" style="width:100px;text-align:center;font-family:'DM Mono',monospace;font-weight:700;">
            </div>`).join('') + `
            <div style="margin-top:18px;display:flex;gap:9px;flex-wrap:wrap;">
                <button class="btn btn-primary" onclick="guardarParametrosSU()">💾 Guardar Cambios</button>
                <button class="btn btn-secondary" onclick="cargarParametrosSU()">↩️ Descartar</button>
            </div>`;
    } catch (e) {
        cont.innerHTML = `<div class="empty-state" style="color:var(--peligro);">Error: ${e.message}</div>`;
    }
}

async function guardarParametrosSU() {
    if (!window.SIPA.suToken) return mostrarToast('Requiere SU.', 'warning');
    const inputs = document.querySelectorAll('#su-params-form .param-input');
    const cambios = {};
    inputs.forEach(i => { cambios[i.dataset.clave] = i.value.trim(); });
    try {
        const r = await fetch('/api/su/parametros', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify({ parametros: cambios }),
        });
        const d = await r.json();
        if (r.ok) mostrarToast('✅ ' + d.msj, 'success');
        else mostrarToast(d.error || 'Error.', 'error');
    } catch (e) {
        mostrarToast('Error: ' + e.message, 'error');
    }
}

async function subirPadron() {
    const f=document.getElementById('excel-file').files[0],t=document.getElementById('excel-turno').value;
    if(!f)return mostrarToast('Seleccione un archivo.','warning');
    const btn=document.querySelector('#cfg-padron .btn-success');
    if(btn){btn.disabled=true;btn.innerHTML='<span class="spin">🔄</span> Procesando…';}
    const fd=new FormData();fd.append('file',f);fd.append('turno',t);
    try{const r=await fetch('/api/upload_padron',{method:'POST',body:fd});if(r.ok)mostrarToast('✅ Padrón importado.','success');else{const e=await r.json();mostrarToast(e.error||'Error.','error');}}
    catch{mostrarToast('Error.','error');}
    finally{if(btn){btn.disabled=false;btn.textContent='Procesar e Importar Padrón';}}
}

async function subirWord() {
    const f=document.getElementById('word-file').files[0],t=document.getElementById('word-turno').value;
    if(!f)return mostrarToast('Seleccione un documento.','warning');
    const btn=document.querySelector('#cfg-cronograma .btn-primary');
    if(btn){btn.disabled=true;btn.innerHTML='<span class="spin">🔄</span> Extrayendo…';}
    const fd=new FormData();fd.append('file',f);fd.append('turno',t);
    const resBox=document.getElementById('word-resultado');
    if(resBox)resBox.innerHTML='';
    try{
        const r=await fetch('/api/upload_word_schedule',{method:'POST',body:fd});
        const d=await r.json();
        if(r.ok){
            mostrarToast(d.msj,'success');
            _mostrarResumenWord(d);
            // Si ya hay un aula seleccionada en el editor manual, refrescarla
            if(document.getElementById('c-aula')?.value.trim()) cargarConfigParaEditar();
        }else{
            mostrarToast(d.error||'Error procesando el archivo.','error');
            _mostrarDiagWord(d);
        }
    }catch(e){mostrarToast('Error de conexión: '+e.message,'error');}
    finally{if(btn){btn.disabled=false;btn.textContent='📤 Extraer Cronograma';}}
}

function _mostrarResumenWord(d){
    const box=document.getElementById('word-resultado');
    if(!box)return;
    const aulas=d.resumen_aulas||[];
    const warns=d.advertencias||[];
    let html=`<div class="card" style="margin-top:16px;border-top:3px solid var(--exito-cl);">
        <h4 style="margin:0 0 12px;color:var(--exito-cl);">✅ Importación completada</h4>
        <p style="margin:0 0 12px;color:var(--texto-suave);">${d.msj}</p>`;
    if(aulas.length){
        html+=`<div class="table-responsive" style="margin:0 0 12px;"><table style="font-size:.92em;min-width:0;">
            <thead><tr style="background:var(--azul-primario);color:#fff;">
                <th style="padding:7px 12px;text-align:left;">Aula</th>
                <th style="padding:7px 12px;text-align:left;">Turno</th>
                <th style="padding:7px 12px;text-align:right;">Bloques</th>
            </tr></thead><tbody>`;
        html+=`<tr style="background:#f8fafc;font-size:.82em;">
            <th style="padding:4px 12px;text-align:left;font-weight:500;color:var(--texto-suave);" colspan="3">Toque una fila para editar esa aula</th></tr>`;
        aulas.forEach(a=>{
            html+=`<tr style="border-bottom:1px solid var(--borde-suave);cursor:pointer;"
                onclick="cargarAulaDesdeImport('${a.aula}','${a.turno}')">
                <td style="padding:6px 12px;font-weight:600;">${a.aula}</td>
                <td style="padding:6px 12px;">${a.turno}</td>
                <td style="padding:6px 12px;text-align:right;">${a.bloques} ✏️</td>
            </tr>`;
        });
        html+=`</tbody></table></div>`;
    }
    if(warns.length){
        html+=`<details style="margin-top:12px;"><summary style="cursor:pointer;color:var(--alerta-cl);font-size:.9em;">⚠️ ${warns.length} advertencia(s)</summary>
            <ul style="margin:8px 0 0;padding-left:20px;font-size:.85em;color:var(--texto-suave);">`;
        warns.forEach(w=>{ html+=`<li>${w}</li>`; });
        html+=`</ul></details>`;
    }
    html+=`</div>`;
    box.innerHTML=html;
}

function _mostrarDiagWord(d){
    const box=document.getElementById('word-resultado');
    if(!box)return;
    const errs=d.errores_detalle||[];
    const diag=d.diagnostico||{};
    let html=`<div class="card" style="margin-top:16px;border-top:3px solid var(--peligro-cl);">
        <h4 style="margin:0 0 8px;color:var(--peligro-cl);">❌ ${d.error||'Error'}</h4>`;
    if(diag.tablas_total!==undefined){
        html+=`<p style="font-size:.9em;color:var(--texto-suave);margin:0 0 8px;">
            Tablas en el documento: <b>${diag.tablas_total}</b> &nbsp;|&nbsp;
            Con columna HORA: <b>${diag.tablas_horario}</b> &nbsp;|&nbsp;
            Saltadas: <b>${diag.tablas_saltadas}</b></p>`;
    }
    if(errs.length){
        html+=`<ul style="margin:8px 0 0;padding-left:20px;font-size:.85em;color:var(--texto-suave);">`;
        errs.forEach(e=>{ html+=`<li>${e}</li>`; });
        html+=`</ul>`;
    }
    html+=`</div>`;
    box.innerHTML=html;
}

function addConfigRow(data={}) {
    const t=document.getElementById('body-config');
    const ops=['Lunes','Martes','Miércoles','Jueves','Viernes'].map(d=>`<option ${d===data.dia?'selected':''}>${d}</option>`).join('');
    const tr=document.createElement('tr');
    tr.innerHTML=`<td><select class="c-dia">${ops}</select></td><td><input type="text" class="c-hora" value="${data.hora||''}" placeholder="07:20-08:20"></td><td><input type="text" class="c-asig" value="${data.asig||''}" placeholder="Materia"></td><td><input type="text" class="c-doc" value="${data.doc||''}" placeholder="Profesor"></td><td><button class="btn btn-danger btn-small" style="padding:8px 12px;" onclick="this.closest('tr').remove()">✖</button></td>`;
    t.appendChild(tr);
}

async function cargarAulasCronograma() {
    const select = document.getElementById('c-aula');
    if (!select) return;
    const turno = document.getElementById('c-turno')?.value || '';
    const seleccionado = select.value;
    try {
        const [catalogoResp, configResp] = await Promise.all([
            fetch('/api/aulas_catalogo'),
            fetch('/api/config_aula'),
        ]);
        if (!catalogoResp.ok || !configResp.ok) throw new Error('No se pudo cargar el listado de aulas');
        const catalogo = await catalogoResp.json();
        const configuraciones = await configResp.json();
        const aulas = new Map();
        (Array.isArray(catalogo) ? catalogo : []).forEach(a => {
            if (!turno || a.turno === turno) aulas.set(`${a.aula}|${a.turno}`, a);
        });
        (Array.isArray(configuraciones) ? configuraciones : []).forEach(b => {
            if (!turno || b.turno === turno) {
                const key = `${b.aula}|${b.turno}`;
                if (!aulas.has(key)) aulas.set(key, {
                    aula: b.aula, turno: b.turno, nombre: `Aula ${b.aula}`,
                });
            }
        });
        const opciones = Array.from(aulas.values()).sort((a, b) =>
            `${a.turno}-${a.aula}`.localeCompare(`${b.turno}-${b.aula}`, 'es', {numeric: true})
        );
        select.innerHTML = '<option value="">— Seleccione un aula —</option>' +
            opciones.map(a => `<option value="${escapeHTML(a.aula)}" data-turno="${escapeHTML(a.turno)}" data-nombre="${escapeHTML(a.nombre || '')}">Aula ${escapeHTML(a.aula)} — ${escapeHTML(a.nombre || 'Sin nombre')} (${escapeHTML(a.turno)})</option>`).join('');
        if (opciones.some(a => a.aula === seleccionado)) select.value = seleccionado;
        if (!select.value && opciones.length) select.value = opciones[0].aula;
        await cargarConfigParaEditar();
    } catch (e) {
        select.innerHTML = '<option value="">No se pudieron cargar las aulas</option>';
        mostrarToast(`Error cargando aulas: ${e.message}`, 'error');
    }
}

function cargarAulaDesdeImport(aula, turno) {
    const inputAula  = document.getElementById('c-aula');
    const selectTurno = document.getElementById('c-turno');
    if(inputAula)  inputAula.value  = aula;
    if(selectTurno) selectTurno.value = turno;
    cargarConfigParaEditar();
    // Scroll al editor
    const editor = document.getElementById('body-config');
    if(editor) editor.closest('table')?.scrollIntoView({behavior:'smooth', block:'start'});
}

// ══════════════════════════════════════════════════════════════
// MONITOR & FIRMAS — SUB-TABS
// ══════════════════════════════════════════════════════════════
function mostrarMonitorTab(id, el) {
    document.querySelectorAll('#admin-registro > .admin-section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('#admin-registro > .sub-nav-container .sub-nav').forEach(n => n.classList.remove('active'));
    const target = document.getElementById(id);
    if (target) target.classList.add('active');
    el.classList.add('active');
    if (id === 'mon-aulas-dia') cargarAulasDia();
    if (id === 'mon-tiempo-real') refrescarMonitor();
    if (id === 'mon-inasistencias') {
        // Asegurarnos de inicializar el rango por defecto
        if (!document.getElementById('inasis-desde').value) _setRangoInasis(
            document.querySelector('.inasis-rango-btn.active'), 'hoy');
        cargarInasistencias();
    }
}

// ══════════════════════════════════════════════════════════════
// AUDITORÍA INDIVIDUAL DE ASISTENCIA
// ══════════════════════════════════════════════════════════════
let _audSearchTimer = null;
let _audDocenteActual = null;

function _buscarDocenteDebounced() {
    clearTimeout(_audSearchTimer);
    _audSearchTimer = setTimeout(_buscarDocente, 250);
}

async function _buscarDocente() {
    const q   = document.getElementById('aud-buscar').value.trim();
    const sug = document.getElementById('aud-sugerencias');
    if (!q || q.length < 2) { sug.innerHTML = ''; sug.style.display = 'none'; return; }
    try {
        const r = await fetch(`/api/docentes/buscar?q=${encodeURIComponent(q)}`);
        const docs = r.ok ? await r.json() : [];
        if (!docs.length) {
            sug.innerHTML = `<div class="aud-sug-item aud-sug-vacio">Sin coincidencias.</div>`;
        } else {
            sug.innerHTML = docs.map(d => `
                <div class="aud-sug-item" onclick="_seleccionarDocenteAud('${d.nombre.replace(/'/g,"\\'")}')">
                    <strong>${d.nombre}</strong>
                    ${d.registrado ? `<span class="badge-mini badge-mini-verde">DNI ${d.dni || '—'}</span>` : `<span class="badge-mini badge-mini-gris">Sin cuenta</span>`}
                </div>`).join('');
        }
        sug.style.display = 'block';
    } catch (e) {
        sug.innerHTML = `<div class="aud-sug-vacio" style="color:var(--peligro);">Error: ${e.message}</div>`;
        sug.style.display = 'block';
    }
}

function _seleccionarDocenteAud(nombre) {
    _audDocenteActual = nombre;
    document.getElementById('aud-buscar').value = nombre;
    document.getElementById('aud-sugerencias').style.display = 'none';
    document.getElementById('aud-filtros').style.display = 'flex';
    // Default: último mes (en fechas LOCALES, no UTC)
    const hoy = new Date();
    const hace30 = new Date(hoy); hace30.setDate(hoy.getDate() - 30);
    document.getElementById('aud-desde').value = _fechaLocalISO(hace30);
    document.getElementById('aud-hasta').value = _fechaLocalISO(hoy);
    auditarDocente();
}

/** Convierte un Date a 'YYYY-MM-DD' usando la zona horaria LOCAL (no UTC). */
function _fechaLocalISO(d) {
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const dd = String(d.getDate()).padStart(2, '0');
    return `${y}-${m}-${dd}`;
}

async function auditarDocente() {
    if (!_audDocenteActual) return;
    const desde  = document.getElementById('aud-desde').value;
    const hasta  = document.getElementById('aud-hasta').value;
    const out    = document.getElementById('aud-resultado');
    out.innerHTML = `<p style="color:var(--texto-tenue);text-align:center;padding:24px;"><span class="spin">🔄</span> Cargando legajo…</p>`;
    try {
        const url = `/api/firmas_docentes/historial?docente=${encodeURIComponent(_audDocenteActual)}&desde=${desde}&hasta=${hasta}`;
        const r   = await fetch(url, { headers: _headersCalendario() });
        const respuesta = await r.json();
        if (!r.ok) throw new Error(respuesta.error || `HTTP ${r.status}`);
        const registros = respuesta;

        // Métricas
        const presentes = registros.filter(x => x.estado === 'presente').length;
        const ausentes  = registros.filter(x => x.estado === 'ausente').length;
        const total     = registros.length;

        let html = `
        <div class="aud-card">
            <div class="aud-header">
                <div>
                    <div class="aud-nombre">${_audDocenteActual}</div>
                    <div class="aud-rango">${formatearFechaElegante(desde)} → ${formatearFechaElegante(hasta)}</div>
                </div>
                <div class="aud-metricas">
                    <div class="aud-metrica aud-met-verde"><span>${presentes}</span><small>✅ Presentes</small></div>
                    <div class="aud-metrica aud-met-rojo"><span>${ausentes}</span><small>❌ No Firmó</small></div>
                    <div class="aud-metrica aud-met-azul"><span>${total}</span><small>📚 Clases</small></div>
                </div>
            </div>`;

        if (!total) {
            html += `<div class="empty-state" style="margin-top:14px;"><span class="empty-state-icon">📭</span><span class="empty-state-text">Sin clases programadas en este rango.</span></div>`;
        } else {
            // Agrupar por fecha
            const porFecha = {};
            registros.forEach(r => { (porFecha[r.fecha] = porFecha[r.fecha] || []).push(r); });

            html += '<div class="aud-timeline">';
            Object.keys(porFecha).sort().reverse().forEach(fecha => {
                const items = porFecha[fecha];
                html += `<div class="aud-dia">
                    <div class="aud-dia-fecha">${formatearFechaElegante(fecha)}</div>
                    ${items.map(_renderAudItem).join('')}
                </div>`;
            });
            html += '</div>';
        }

        html += '</div>';
        out.innerHTML = html;
    } catch (e) {
        out.innerHTML = `<div class="empty-state" style="border-color:var(--peligro-cl);color:var(--peligro);"><span class="empty-state-icon">⚠️</span><span class="empty-state-text">Error: ${e.message}</span></div>`;
        console.error('[auditarDocente]', e);
    }
}

function _renderAudItem(r) {
    if (r.estado === 'ausente') {
        return `<div class="aud-item aud-item-ausente">
            <span class="aud-item-hora">${r.hora_clase || '--:--'}</span>
            <span class="aud-item-info"><strong>Aula ${r.aula}</strong> · ${r.turno}${r.materia ? ' · '+r.materia : ''}</span>
            <span class="badge-rojo">❌ No Firmó</span>
        </div>`;
    }
    return `<div class="aud-item aud-item-presente">
        <span class="aud-item-hora">${(r.hora_firma||'--:--').substring(0,5)}</span>
        <span class="aud-item-info"><strong>Aula ${r.aula}</strong> · ${r.turno}</span>
        <span class="badge-verde">✅ Presente</span>
    </div>`;
}

// ══════════════════════════════════════════════════════════════
// REGISTRO DE INASISTENCIAS (¿CUÁNDO FALTÓ?)
// ══════════════════════════════════════════════════════════════
function _setRangoInasis(btn, modo) {
    document.querySelectorAll('.inasis-rango-btn').forEach(b => b.classList.remove('active'));
    if (btn) btn.classList.add('active');
    const hoy = new Date();
    let desde = new Date(hoy);
    let hasta = new Date(hoy);
    if (modo === 'semana') {
        // Lunes de esta semana
        const dow = hoy.getDay(); // 0=domingo
        const diff = dow === 0 ? -6 : 1 - dow;
        desde.setDate(hoy.getDate() + diff);
    } else if (modo === 'mes') {
        desde = new Date(hoy.getFullYear(), hoy.getMonth(), 1);
    } else if (modo === 'custom') {
        document.getElementById('inasis-rango-custom').style.display = 'flex';
        return; // no autocarga
    }
    document.getElementById('inasis-rango-custom').style.display =
        modo === 'custom' ? 'flex' : 'none';
    document.getElementById('inasis-desde').value = _fechaLocalISO(desde);
    document.getElementById('inasis-hasta').value = _fechaLocalISO(hasta);
    cargarInasistencias();
}

async function cargarInasistencias() {
    const out   = document.getElementById('inasis-listado');
    const sum   = document.getElementById('inasis-resumen');
    out.innerHTML = `<p style="color:var(--texto-tenue);text-align:center;padding:24px;"><span class="spin">🔄</span> Cargando inasistencias…</p>`;
    sum.innerHTML = '';

    const desde   = document.getElementById('inasis-desde').value;
    const hasta   = document.getElementById('inasis-hasta').value;
    const turno   = document.getElementById('inasis-turno').value;
    const incJust = document.getElementById('inasis-incluir-just').checked ? '1' : '0';

    if (!desde || !hasta) { out.innerHTML = '<div class="empty-state"><span class="empty-state-text">Seleccione rango.</span></div>'; return; }

    try {
        const url = `/api/inasistencias?desde=${desde}&hasta=${hasta}&turno=${turno}&incluir_justificadas=${incJust}`;
        const r   = await fetch(url);
        const data = r.ok ? await r.json() : [];

        const totalAus  = data.filter(x => x.estado === 'ausente').length;
        const totalJust = data.filter(x => x.estado === 'justificado').length;
        const totalPend = data.filter(x => x.estado === 'pendiente_aprobacion').length;

        sum.innerHTML = `
            <div class="inasis-kpi inasis-kpi-rojo">
                <span class="inasis-kpi-valor">${totalAus}</span>
                <span class="inasis-kpi-lbl">Sin justificar</span>
            </div>
            ${totalPend > 0 ? `<div class="inasis-kpi inasis-kpi-naranja">
                <span class="inasis-kpi-valor">${totalPend}</span>
                <span class="inasis-kpi-lbl">⏳ Pendientes de revisión</span>
            </div>` : ''}
            <div class="inasis-kpi inasis-kpi-verde">
                <span class="inasis-kpi-valor">${totalJust}</span>
                <span class="inasis-kpi-lbl">Justificadas</span>
            </div>
            <div class="inasis-kpi inasis-kpi-gris">
                <span class="inasis-kpi-valor">${data.length}</span>
                <span class="inasis-kpi-lbl">Total inasistencias</span>
            </div>`;

        if (!data.length) {
            out.innerHTML = `<div class="empty-state" style="padding:36px;">
                <span class="empty-state-icon">🎉</span>
                <span class="empty-state-text"><strong>Sin inasistencias detectadas en el período.</strong></span>
            </div>`;
            return;
        }

        out.innerHTML = `<div class="inasis-tabla-wrap"><table class="inasis-tabla">
            <thead><tr>
                <th>Fecha</th><th>Hora</th><th>Turno</th><th>Aula</th>
                <th>Docente</th><th>Materia</th><th>Estado</th><th>Acción</th>
            </tr></thead>
            <tbody>${data.map(_renderInasisRow).join('')}</tbody>
        </table></div>`;
    } catch (e) {
        out.innerHTML = `<div class="empty-state" style="border-color:var(--peligro-cl);color:var(--peligro);"><span class="empty-state-icon">⚠️</span><span class="empty-state-text">Error: ${e.message}</span></div>`;
        console.error('[cargarInasistencias]', e);
    }
}

async function cargarFirmasTardiasPendientes(silencioso = false) {
    const lista = document.getElementById('firmas-tardias-pendientes-lista');
    const badge = document.getElementById('firmas-tardias-pendientes-badge');
    const filtro = document.getElementById('firmas-tardias-filtro')?.value || 'pendiente';
    if (!lista || !badge) return;
    const token = window.SIPA?.suToken || window.SIPA?.adminToken || '';
    const authHeader = window.SIPA?.suToken ? 'X-SU-Token' : 'X-Admin-Token';
    if (!token) return;
    if (!silencioso) {
        lista.innerHTML = '<div class="empty-state"><span class="empty-state-icon">⏳</span><span class="empty-state-text">Cargando solicitudes…</span></div>';
    }
    try {
        const r = await fetch(`/api/justificacion/pendientes?estado=${encodeURIComponent(filtro)}`, {
            headers: { [authHeader]: token },
        });
        const data = await r.json();
        if (!r.ok) throw new Error(data.error || `HTTP ${r.status}`);
        const items = Array.isArray(data.items) ? data.items : [];
        const total = Number(data.pendientes) || 0;
        badge.textContent = total > 99 ? '99+' : String(total);
        badge.style.display = total ? 'inline-block' : 'none';
        const sidebarBadge = document.getElementById('firmas-tardias-pendientes-sidebar');
        if (sidebarBadge) {
            sidebarBadge.textContent = total > 99 ? '99+' : String(total);
            sidebarBadge.style.display = total ? 'inline-block' : 'none';
        }
        if (silencioso && !document.getElementById('admin-firmas-tardias')?.classList.contains('active')) return;
        if (!items.length) {
            lista.innerHTML = filtro === 'pendiente'
                ? '<div class="empty-state"><span class="empty-state-icon">✅</span><span class="empty-state-text">No hay firmas tardías pendientes de revisión.</span></div>'
                : '<div class="empty-state"><span class="empty-state-icon">📋</span><span class="empty-state-text">Todavía no hay solicitudes revisadas.</span></div>';
            return;
        }
        lista.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));gap:14px;">${
            items.map(_renderFirmaTardiaPendiente).join('')
        }</div>`;
    } catch (e) {
        lista.innerHTML = `<div class="empty-state" style="border-color:var(--peligro-cl);color:var(--peligro);"><span class="empty-state-icon">⚠️</span><span class="empty-state-text">No se pudieron cargar las solicitudes: ${_esc(e.message)}</span></div>`;
        console.error('[cargarFirmasTardiasPendientes]', e);
    }
}

function _renderFirmaTardiaPendiente(item) {
    const attrs = `data-docente="${_esc(item.docente)}" data-aula="${_esc(item.aula)}" data-turno="${_esc(item.turno)}" data-fecha="${_esc(item.fecha)}"`;
    const pendiente = item.estado === 'pendiente';
    const estado = item.estado === 'aprobada'
        ? '<span class="badge-mini badge-mini-verde">✅ Aprobada</span>'
        : item.estado === 'rechazada'
            ? '<span class="badge-rojo">❌ Rechazada</span>'
            : '<span class="badge-mini badge-mini-naranja">⏳ Pendiente</span>';
    const remitente = String(item.registrado_por || '').replace(/^AUTO:/, '');
    const revision = pendiente ? '' : `
        <div style="margin-top:10px;padding-top:9px;border-top:1px solid var(--borde-suave);font-size:.86em;color:var(--texto-suave);">
            Revisada por <strong>${_esc(item.revisado_por || 'Plana Mayor')}</strong>
            ${item.revisado_en ? ` · ${_esc(item.revisado_en)}` : ''}
            ${item.observacion_revision ? `<div style="margin-top:5px;"><strong>Observación:</strong> ${_esc(item.observacion_revision)}</div>` : ''}
        </div>`;
    return `<article class="card" style="margin:0;border:1px solid var(--borde);box-shadow:var(--sombra-xs);">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start;">
            <strong style="color:var(--azul-oscuro);">${_esc(item.docente)}</strong>${estado}
        </div>
        <div style="margin-top:8px;font-size:.88em;color:var(--texto-suave);">
            Aula <strong>${_esc(item.aula)}</strong> · ${_esc(item.turno)} · ${_esc(item.fecha)}
            ${item.creado_en ? `<div>Solicitada: ${_esc(item.creado_en)}</div>` : ''}
            ${remitente ? `<div>Enviada por: ${_esc(remitente)}</div>` : ''}
        </div>
        <div style="margin-top:10px;"><strong>Motivo:</strong> ${_esc(item.motivo || '—')}</div>
        ${item.comentario ? `<p style="margin:6px 0 0;color:var(--texto-suave);white-space:pre-wrap;">${_esc(item.comentario)}</p>` : ''}
        ${item.adjunto_nombre ? `<div style="margin-top:8px;font-size:.84em;">📎 ${_esc(item.adjunto_nombre)}</div>` : ''}
        ${pendiente ? `<label style="display:block;margin-top:12px;">Observación de revisión (opcional)
            <textarea class="firma-tardia-observacion" rows="2" maxlength="1000" placeholder="Anotá el motivo de la decisión, si corresponde." style="width:100%;margin-top:4px;"></textarea>
        </label>
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:10px;">
            <button class="btn btn-success btn-small" ${attrs} onclick="_aprobarJustif(this)">✅ Aprobar</button>
            <button class="btn btn-danger btn-small" ${attrs} onclick="_rechazarJustif(this)">❌ Rechazar</button>
        </div>` : revision}
    </article>`;
}

function _headersCalendario(json = false) {
    const headers = {};
    if (json) headers['Content-Type'] = 'application/json';
    if (window.SIPA?.suToken) headers['X-SU-Token'] = window.SIPA.suToken;
    if (window.SIPA?.adminToken) headers['X-Admin-Token'] = window.SIPA.adminToken;
    return headers;
}

function actualizarCamposCalendario() {
    const alcance = document.getElementById('cal-alcance')?.value;
    const turno = document.getElementById('cal-turno-wrap');
    const aula = document.getElementById('cal-aula-wrap');
    if (turno) turno.style.display = alcance === 'institucion' ? 'none' : '';
    if (aula) aula.style.display = alcance === 'aula' ? '' : 'none';
}

async function cargarCalendarioNoActividad() {
    const lista = document.getElementById('calendario-no-actividad-lista');
    const formulario = document.getElementById('calendario-formulario');
    if (!lista) return;
    const tieneTIC = !!window.SIPA?.suToken;
    const tieneSesion = tieneTIC || !!window.SIPA?.adminToken;
    if (formulario) formulario.style.display = tieneTIC ? '' : 'none';
    if (!tieneSesion) {
        lista.innerHTML = '<div class="empty-state"><span class="empty-state-icon">🔒</span><span class="empty-state-text">Inicie sesión en Plana Mayor o TIC para consultar el calendario.</span></div>';
        return;
    }
    lista.innerHTML = '<div class="empty-state"><span class="empty-state-icon">⏳</span><span class="empty-state-text">Cargando calendario…</span></div>';
    try {
        const response = await fetch('/api/calendario/no_actividad', {
            headers: _headersCalendario(),
        });
        const items = await response.json();
        if (!response.ok) throw new Error(items.error || `HTTP ${response.status}`);
        if (!Array.isArray(items) || !items.length) {
            lista.innerHTML = '<div class="empty-state"><span class="empty-state-icon">✅</span><span class="empty-state-text">No hay días sin actividad programados.</span></div>';
            return;
        }
        lista.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,380px),1fr));gap:14px;">${
            items.map(item => _renderDiaSinActividad(item, tieneTIC, tieneSesion)).join('')
        }</div>`;
    } catch (error) {
        lista.innerHTML = `<div class="empty-state" style="border-color:var(--peligro-cl);color:var(--peligro);"><span class="empty-state-icon">⚠️</span><span class="empty-state-text">No se pudo cargar el calendario: ${_esc(error.message)}</span></div>`;
        console.error('[cargarCalendarioNoActividad]', error);
    }
}

function _renderDiaSinActividad(item, tieneTIC, tieneSesion) {
    const id = Number(item.id);
    const alcance = item.alcance === 'institucion' ? 'Toda la institución'
        : item.alcance === 'turno' ? `Turno ${_esc(item.turno)}`
            : `Aula ${_esc(item.aula)} · ${_esc(item.turno)}`;
    const confirmado = item.estado === 'confirmado';
    const estado = confirmado
        ? '<span class="badge-mini badge-mini-verde">✅ Confirmado</span>'
        : '<span class="badge-mini badge-mini-naranja">⏳ Pendiente de confirmación</span>';
    const excepciones = Array.isArray(item.excepciones) ? item.excepciones : [];
    const excepcionesHtml = excepciones.length
        ? `<div style="margin-top:9px;font-size:.86em;"><strong>Excepciones autorizadas</strong><ul style="margin:4px 0 0;padding-left:20px;">${
            excepciones.map(ex => `<li>${_esc(ex.aula)} (${_esc(ex.turno)}) — ${_esc(ex.motivo || 'Sin motivo')} ${
                tieneSesion ? `<button class="btn btn-danger btn-small" style="padding:2px 7px;margin-left:5px;" data-aula="${_esc(ex.aula)}" data-turno="${_esc(ex.turno)}" onclick="quitarExcepcionCalendario(${id},this)">Quitar</button>` : ''
            }</li>`).join('')
        }</ul></div>`
        : '';
    const editar = !confirmado && tieneTIC ? `
        <details style="margin-top:10px;">
            <summary style="cursor:pointer;color:var(--azul-oscuro);">Editar programación</summary>
            <div class="grid" style="align-items:end;margin-top:8px;">
                <div><label>Fecha</label><input type="date" id="cal-ed-fecha-${id}" value="${_esc(item.fecha)}"></div>
                <div><label>Alcance</label><select id="cal-ed-alcance-${id}">
                    <option value="institucion" ${item.alcance === 'institucion' ? 'selected' : ''}>Institución</option>
                    <option value="turno" ${item.alcance === 'turno' ? 'selected' : ''}>Turno</option>
                    <option value="aula" ${item.alcance === 'aula' ? 'selected' : ''}>Aula</option>
                </select></div>
                <div><label>Turno</label><select id="cal-ed-turno-${id}">
                    <option value="TM" ${item.turno === 'TM' ? 'selected' : ''}>Mañana</option>
                    <option value="TT" ${item.turno === 'TT' ? 'selected' : ''}>Tarde</option>
                </select></div>
                <div><label>Aula</label><input id="cal-ed-aula-${id}" maxlength="50" value="${_esc(item.aula || '')}"></div>
                <div><label>Motivo</label><input id="cal-ed-motivo-${id}" maxlength="200" value="${_esc(item.motivo)}"></div>
            </div>
            <button class="btn btn-primary btn-small" style="margin-top:8px;" onclick="editarDiaSinActividad(${id})">Guardar cambios</button>
        </details>` : '';
    const accionesEstado = confirmado
        ? `<button class="btn btn-small" onclick="reabrirDiaSinActividad(${id})">↩️ Reabrir</button>`
        : `<button class="btn btn-success btn-small" onclick="confirmarDiaSinActividad(${id})">✅ Confirmar cierre</button>`;
    const accionesTIC = !confirmado && tieneTIC
        ? `<button class="btn btn-danger btn-small" onclick="eliminarDiaSinActividad(${id})">🗑️ Eliminar</button>`
        : '';
    const exceptionForm = confirmado && item.alcance !== 'aula' && tieneSesion ? `
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:7px;margin-top:10px;align-items:end;">
            <div><label>Aula con actividad</label><input id="cal-ex-aula-${id}" maxlength="50" placeholder="Ej.: 1° A"></div>
            <div><label>Turno</label><select id="cal-ex-turno-${id}">${
                item.alcance === 'turno'
                    ? `<option value="${_esc(item.turno)}">${item.turno === 'TM' ? 'Mañana' : 'Tarde'}</option>`
                    : '<option value="TM">Mañana</option><option value="TT">Tarde</option>'
            }</select></div>
            <div><label>Motivo</label><input id="cal-ex-motivo-${id}" maxlength="200" placeholder="Actividad autorizada"></div>
            <button class="btn btn-primary btn-small" onclick="agregarExcepcionCalendario(${id})">➕ Autorizar aula</button>
        </div>` : '';
    return `<article class="card" style="margin:0;border:1px solid var(--borde);box-shadow:var(--sombra-xs);">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start;">
            <strong style="color:var(--azul-oscuro);">${_esc(item.fecha)} · ${alcance}</strong>${estado}
        </div>
        <div style="margin-top:8px;"><strong>Motivo:</strong> ${_esc(item.motivo)}</div>
        <div style="margin-top:6px;font-size:.84em;color:var(--texto-suave);">
            Programado por ${_esc(item.creado_por || 'TIC')}
            ${item.confirmado_por ? ` · Confirmado por ${_esc(item.confirmado_por)} ${_esc(item.confirmado_en || '')}` : ''}
        </div>
        ${excepcionesHtml}${exceptionForm}${editar}
        <div style="display:flex;gap:7px;flex-wrap:wrap;margin-top:12px;">${accionesEstado}${accionesTIC}</div>
    </article>`;
}

async function _enviarAccionCalendario(url, method, body, mensaje, refrescar = cargarCalendarioNoActividad) {
    const response = await fetch(url, {
        method,
        headers: _headersCalendario(body !== undefined),
        ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    mostrarToast(data.msj || mensaje, 'success');
    if (refrescar) await refrescar();
}

async function crearDiaSinActividad() {
    const alcance = document.getElementById('cal-alcance').value;
    const payload = {
        fecha: document.getElementById('cal-fecha').value,
        alcance,
        turno: document.getElementById('cal-turno').value,
        aula: document.getElementById('cal-aula').value.trim(),
        motivo: document.getElementById('cal-motivo').value.trim(),
    };
    try {
        await _enviarAccionCalendario('/api/calendario/no_actividad', 'POST', payload, 'Cierre programado.');
        document.getElementById('cal-motivo').value = '';
        document.getElementById('cal-aula').value = '';
    } catch (error) {
        mostrarToast(error.message, 'error');
    }
}

async function editarDiaSinActividad(id) {
    const payload = {
        fecha: document.getElementById(`cal-ed-fecha-${id}`).value,
        alcance: document.getElementById(`cal-ed-alcance-${id}`).value,
        turno: document.getElementById(`cal-ed-turno-${id}`).value,
        aula: document.getElementById(`cal-ed-aula-${id}`).value.trim(),
        motivo: document.getElementById(`cal-ed-motivo-${id}`).value.trim(),
    };
    try {
        await _enviarAccionCalendario(`/api/calendario/no_actividad/${id}`, 'PUT', payload, 'Programación actualizada.');
    } catch (error) {
        mostrarToast(error.message, 'error');
    }
}

async function eliminarDiaSinActividad(id) {
    if (!confirm('¿Eliminar este cierre programado?')) return;
    try {
        await _enviarAccionCalendario(`/api/calendario/no_actividad/${id}`, 'DELETE', undefined, 'Cierre eliminado.');
    } catch (error) {
        mostrarToast(error.message, 'error');
    }
}

async function confirmarDiaSinActividad(id) {
    if (!confirm('Al confirmar, no se generarán faltas para el alcance de este cierre. ¿Continuar?')) return;
    try {
        await _enviarAccionCalendario(`/api/calendario/no_actividad/${id}/confirmar`, 'POST', undefined, 'Cierre confirmado.');
    } catch (error) {
        mostrarToast(error.message, 'error');
    }
}

async function reabrirDiaSinActividad(id) {
    if (!confirm('Al reabrir, las clases volverán a contar en la asistencia. ¿Continuar?')) return;
    try {
        await _enviarAccionCalendario(`/api/calendario/no_actividad/${id}/reabrir`, 'POST', undefined, 'Cierre reabierto.');
    } catch (error) {
        mostrarToast(error.message, 'error');
    }
}

async function agregarExcepcionCalendario(id) {
    const payload = {
        aula: document.getElementById(`cal-ex-aula-${id}`).value.trim(),
        turno: document.getElementById(`cal-ex-turno-${id}`).value,
        motivo: document.getElementById(`cal-ex-motivo-${id}`).value.trim(),
        accion: 'agregar',
    };
    try {
        await _enviarAccionCalendario(`/api/calendario/no_actividad/${id}/excepciones`, 'POST', payload, 'Excepción autorizada.');
    } catch (error) {
        mostrarToast(error.message, 'error');
    }
}

async function quitarExcepcionCalendario(id, boton) {
    try {
        await _enviarAccionCalendario(`/api/calendario/no_actividad/${id}/excepciones`, 'POST', {
            aula: boton.dataset.aula, turno: boton.dataset.turno, accion: 'quitar',
        }, 'Excepción quitada.');
    } catch (error) {
        mostrarToast(error.message, 'error');
    }
}

async function cargarCoberturasDocente() {
    const lista = document.getElementById('coberturas-lista');
    const selector = document.getElementById('cob-pgnp');
    if (!lista || !selector) return;
    const fecha = document.getElementById('cob-fecha');
    if (fecha && !fecha.value) fecha.value = obtenerFechaHoyLocal();
    const filtro = document.getElementById('cob-filtro-estado')?.value || '';
    lista.innerHTML = '<div class="empty-state">Cargando solicitudes de cobertura…</div>';
    try {
        const [response, pgnpResponse] = await Promise.all([
            fetch(`/api/plana_mayor/coberturas?estado=${encodeURIComponent(filtro)}`, {
                headers: _headersCalendario(),
            }),
            fetch('/api/plana_mayor/pgnp', { headers: _headersCalendario() }),
        ]);
        const [items, pgnp] = await Promise.all([response.json(), pgnpResponse.json()]);
        if (!response.ok) throw new Error(items.error || `HTTP ${response.status}`);
        if (!pgnpResponse.ok) throw new Error(pgnp.error || `HTTP ${pgnpResponse.status}`);
        selector.innerHTML = pgnp.length
            ? '<option value="">— Seleccione PGNP —</option>' +
                pgnp.map(persona => `<option value="${Number(persona.id)}">${_esc(persona.nombre)}</option>`).join('')
            : '<option value="">TIC aún no habilitó cuentas PGNP</option>';
        if (!items.length) {
            lista.innerHTML = '<div class="empty-state"><span class="empty-state-icon">📋</span><span class="empty-state-text">No hay coberturas para mostrar.</span></div>';
            return;
        }
        lista.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));gap:12px;">${
            items.map(item => _renderCoberturaDocente(item, selector.innerHTML)).join('')
        }</div>`;
    } catch (error) {
        lista.innerHTML = `<div class="bd-error-banner">No se pudieron cargar las coberturas: ${_esc(error.message)}</div>`;
        console.error('[cargarCoberturasDocente]', error);
    }
}

function _renderCoberturaDocente(item, pgnpOptions) {
    const estadoTexto = {
        pendiente: '⏳ Pendiente de autorización',
        solicitada: '📨 Solicitud de Bedelía',
        aprobada: '✅ Aprobada · pendiente de firma',
        completada: '✍️ Firmada por el PGNP',
        rechazada: '❌ Rechazada',
        cancelada: '🚫 Cancelada por TIC',
    }[item.estado] || _esc(item.estado);
    const revision = item.revisada_por
        ? `<div style="font-size:.84em;color:var(--texto-suave);margin-top:6px;">Revisada por ${_esc(item.revisada_por)} · ${_esc(item.revisada_en || '')}</div>`
        : '';
    const selectorPgnp = item.estado === 'solicitada' ? `
        <div style="margin-top:10px;">
            <label for="cob-revisar-pgnp-${Number(item.id)}">Asignar PGNP al aprobar</label>
            <select id="cob-revisar-pgnp-${Number(item.id)}">${pgnpOptions}</select>
        </div>` : '';
    const acciones = ['pendiente', 'solicitada'].includes(item.estado) ? `
        ${selectorPgnp}
        <div style="display:flex;gap:8px;margin-top:10px;">
            <button class="btn btn-success btn-small" onclick="revisarCoberturaDocente(${Number(item.id)},'aprobar')">✅ Autorizar</button>
            <button class="btn btn-danger btn-small" onclick="revisarCoberturaDocente(${Number(item.id)},'rechazar')">❌ Rechazar</button>
        </div>` : '';
    const firma = item.firmado_en
        ? `<div style="margin-top:7px;color:var(--exito);">Firma del PGNP: ${_esc(item.firmado_en)}</div>` : '';
    return `<article class="card" style="margin:0;border:1px solid var(--borde);">
        <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start;">
            <strong>${_esc(item.fecha)} · Aula ${_esc(item.aula)} (${_esc(item.turno)})</strong>
            <span class="badge-mini">${estadoTexto}</span>
        </div>
        <div style="margin-top:8px;"><strong>${_esc(item.materia)}</strong> · ${_esc(item.hora)}</div>
        <div style="font-size:.88em;color:var(--texto-suave);">
            Titular: <strong>${_esc(item.titular)}</strong><br>
            PGNP asignado: <strong>${_esc(item.pgnp)}</strong><br>
            Solicitó: ${_esc(item.solicitada_por || 'Plana Mayor')} · ${_esc(item.solicitada_en || '')}
        </div>${item.motivo_solicitud ? `<div style="margin-top:7px;"><strong>Motivo:</strong> ${_esc(item.motivo_solicitud)}</div>` : ''}${revision}${firma}${acciones}
    </article>`;
}

async function crearCoberturaDocente() {
    const payload = {
        fecha: document.getElementById('cob-fecha').value,
        aula: document.getElementById('cob-aula').value.trim(),
        turno: document.getElementById('cob-turno').value,
        titular: document.getElementById('cob-titular').value.trim(),
        materia: document.getElementById('cob-materia').value.trim(),
        hora: document.getElementById('cob-hora').value.trim(),
        pgnp_id: document.getElementById('cob-pgnp').value,
    };
    try {
        await _enviarAccionCalendario(
            '/api/plana_mayor/coberturas', 'POST', payload,
            'Solicitud de cobertura enviada a Plana Mayor.', cargarCoberturasDocente
        );
    } catch (error) {
        mostrarToast(error.message, 'error');
    }
}

async function revisarCoberturaDocente(id, decision) {
    const texto = decision === 'aprobar' ? 'autorizar esta cobertura' : 'rechazar esta solicitud';
    if (!confirm(`¿Confirma que desea ${texto}?`)) return;
    const pgnp = document.getElementById(`cob-revisar-pgnp-${Number(id)}`);
    if (decision === 'aprobar' && pgnp && !pgnp.value) {
        mostrarToast('Seleccione una cuenta PGNP para autorizar esta solicitud.', 'warning');
        return;
    }
    try {
        const payload = { decision };
        if (decision === 'aprobar' && pgnp) payload.pgnp_id = pgnp.value;
        await _enviarAccionCalendario(
            `/api/plana_mayor/coberturas/${id}/revisar`,
            'POST',
            payload,
            `Solicitud ${decision === 'aprobar' ? 'aprobada' : 'rechazada'}.`,
            cargarCoberturasDocente
        );
    } catch (error) {
        mostrarToast(error.message, 'error');
    }
}

async function cargarCuentasPgnp() {
    const lista = document.getElementById('cuentas-pgnp-lista');
    if (!lista) return;
    if (!window.SIPA?.suToken) {
        lista.innerHTML = '<div class="bd-error-banner">Esta administración requiere sesión TIC.</div>';
        return;
    }
    lista.innerHTML = '<div class="empty-state">Cargando cuentas docentes…</div>';
    try {
        const response = await fetch('/api/su/docentes_pgnp', {
            headers: { 'X-SU-Token': window.SIPA.suToken },
        });
        const items = await response.json();
        if (!response.ok) throw new Error(items.error || `HTTP ${response.status}`);
        if (!items.length) {
            lista.innerHTML = '<div class="empty-state">No hay cuentas docentes registradas.</div>';
            return;
        }
        lista.innerHTML = `<div class="table-responsive"><table><thead><tr><th>Docente</th><th>Email</th><th>Habilitación PGNP</th></tr></thead><tbody>${
            items.map(item => `<tr>
                <td>${_esc(item.nombre)}</td><td>${_esc(item.email)}</td>
                <td><label style="display:flex;align-items:center;gap:8px;">
                    <input type="checkbox" ${item.es_pgnp ? 'checked' : ''} onchange="actualizarCuentaPgnp(${Number(item.id)},this.checked)">
                    ${item.es_pgnp ? 'Habilitado' : 'No habilitado'}
                </label></td>
            </tr>`).join('')
        }</tbody></table></div>`;
    } catch (error) {
        lista.innerHTML = `<div class="bd-error-banner">No se pudieron cargar las cuentas: ${_esc(error.message)}</div>`;
        console.error('[cargarCuentasPgnp]', error);
    }
}

async function actualizarCuentaPgnp(id, es_pgnp) {
    try {
        const response = await fetch(`/api/su/docentes_pgnp/${id}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json', 'X-SU-Token': window.SIPA.suToken },
            body: JSON.stringify({ es_pgnp }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        mostrarToast(data.es_pgnp ? 'Cuenta habilitada como PGNP.' : 'Cuenta PGNP deshabilitada.', 'success');
        await cargarCuentasPgnp();
        await cargarCoberturasDocente();
    } catch (error) {
        mostrarToast(error.message, 'error');
        await cargarCuentasPgnp();
    }
}

function _renderInasisRow(r) {
    const dAttrs = `data-docente="${_esc(r.docente)}" data-aula="${_esc(r.aula)}" data-turno="${_esc(r.turno)}" data-fecha="${_esc(r.fecha)}" data-hora="${_esc(r.hora_clase||'')}" data-materia="${_esc(r.materia||'')}"`;

    let estadoBadge, accion, filaCls;

    if (r.estado === 'justificado') {
        estadoBadge = '<span class="badge-verde">✓ JUSTIFICADO</span>';
        filaCls     = 'inasis-fila-just';
        accion = `<div style="font-size:.82em;">
            <span class="badge-mini badge-mini-verde">✓ Aprobada</span>
            <div style="color:var(--texto-suave);margin-top:3px;font-size:.92em;">
                <strong>${_esc(r.motivo||'')}</strong>${r.comentario ? ' — '+_esc(r.comentario) : ''}
            </div>
            <a href="javascript:void(0)" ${dAttrs} onclick="_eliminarJustif(this)" style="font-size:.82em;color:var(--peligro);">eliminar</a>
        </div>`;
    } else if (r.estado === 'pendiente_aprobacion') {
        estadoBadge = '<span class="badge-mini badge-mini-naranja">⏳ PENDIENTE</span>';
        filaCls     = 'inasis-fila-pendiente';
        accion = `<div style="font-size:.82em;">
            <div style="color:var(--texto);margin-bottom:5px;font-size:.92em;">
                <strong>${_esc(r.motivo||'')}</strong>${r.comentario ? '<br><span style="color:var(--texto-suave);">'+_esc(r.comentario)+'</span>' : ''}
                ${r.registrado_por ? `<div style="font-size:.85em;color:var(--texto-tenue);margin-top:3px;">Enviado por: ${_esc(r.registrado_por.replace('AUTO:', '👤 '))}</div>` : ''}
            </div>
            <div style="display:flex;gap:5px;">
                <button class="btn btn-success btn-small" style="padding:5px 9px;font-size:.78em;" ${dAttrs} onclick="_aprobarJustif(this)">✅ Aprobar</button>
                <button class="btn btn-danger btn-small" style="padding:5px 9px;font-size:.78em;" ${dAttrs} onclick="_rechazarJustif(this)">❌ Rechazar</button>
            </div>
        </div>`;
    } else {
        // Ausente puro o rechazado (estado='ausente')
        const esRechazada = r.estado_justif === 'rechazada';
        estadoBadge = esRechazada
            ? '<span class="badge-rojo">❌ NO FIRMÓ <span style="font-size:.85em;">(just. rechazada)</span></span>'
            : '<span class="badge-rojo">❌ NO FIRMÓ</span>';
        filaCls = 'inasis-fila-aus';
        accion = `<button class="btn btn-warning btn-small" style="margin-top:0;padding:6px 11px;font-size:.82em;"
                          ${dAttrs}
                          onclick="abrirModalJustif(this)">📋 Justificar</button>`;
    }

    return `<tr class="${filaCls}">
        <td>${formatearFechaElegante(r.fecha)}</td>
        <td class="inasis-hora">${r.hora_clase || '--:--'}</td>
        <td><span class="chip">${_esc(r.turno)}</span></td>
        <td><strong>${_esc(r.aula)}</strong></td>
        <td>${_esc(r.docente)}</td>
        <td style="font-size:.86em;color:var(--texto-suave);">${_esc(r.materia || '—')}</td>
        <td>${estadoBadge}</td>
        <td>${accion}</td>
    </tr>`;
}

async function _aprobarJustif(btn) {
    const d = {docente: btn.dataset.docente, aula: btn.dataset.aula,
               turno: btn.dataset.turno, fecha: btn.dataset.fecha,
               revisado_por: (window.SIPA.adminUsuario || 'Plana Mayor')};
    d.observacion_revision = btn.closest('.card')
        ?.querySelector('.firma-tardia-observacion')?.value.trim() || '';
    const token = window.SIPA?.suToken || window.SIPA?.adminToken || '';
    const authHeader = window.SIPA?.suToken ? 'X-SU-Token' : 'X-Admin-Token';
    try {
        const r = await fetch('/api/justificacion/aprobar', {
            method:'POST', headers:{'Content-Type':'application/json', [authHeader]: token},
            body: JSON.stringify(d),
        });
        const dr = await r.json();
        if (r.ok) {
            mostrarToast(dr.msj, 'success');
            cargarInasistencias();
            cargarFirmasTardiasPendientes();
        }
        else mostrarToast(dr.error || 'Error.', 'error');
    } catch (e) {
        mostrarToast('Error de red: ' + e.message, 'error');
    }
}

async function _rechazarJustif(btn) {
    const observacion = btn.closest('.card')?.querySelector('.firma-tardia-observacion')?.value.trim() || '';
    if (!confirm(`Rechazar la justificación de ${btn.dataset.docente} del ${btn.dataset.fecha}?\nLa decisión quedará registrada en S.I.P.A..`)) return;
    const d = {docente: btn.dataset.docente, aula: btn.dataset.aula,
               turno: btn.dataset.turno, fecha: btn.dataset.fecha,
               revisado_por: (window.SIPA.adminUsuario || 'Plana Mayor'),
               observacion_revision: observacion};
    const token = window.SIPA?.suToken || window.SIPA?.adminToken || '';
    const authHeader = window.SIPA?.suToken ? 'X-SU-Token' : 'X-Admin-Token';
    try {
        const r = await fetch('/api/justificacion/rechazar', {
            method:'POST', headers:{'Content-Type':'application/json', [authHeader]: token},
            body: JSON.stringify(d),
        });
        const dr = await r.json();
        if (r.ok) {
            mostrarToast(dr.msj, 'success');
            cargarInasistencias();
            cargarFirmasTardiasPendientes();
        }
        else mostrarToast(dr.error || 'Error.', 'error');
    } catch (e) {
        mostrarToast('Error de red: ' + e.message, 'error');
    }
}

let _justifData = null;
function abrirModalJustif(btn) {
    _justifData = {
        docente:    btn.dataset.docente,
        aula:       btn.dataset.aula,
        turno:      btn.dataset.turno,
        fecha:      btn.dataset.fecha,
        hora_clase: btn.dataset.hora,
        materia:    btn.dataset.materia,
    };
    document.getElementById('justif-info').innerHTML = `
        <strong>${_esc(_justifData.docente)}</strong><br>
        <span style="color:var(--texto-suave);">Aula ${_esc(_justifData.aula)} · ${_esc(_justifData.turno)} · ${formatearFechaElegante(_justifData.fecha)} · ${_esc(_justifData.hora_clase || '--:--')}</span>
        ${_justifData.materia ? `<div style="margin-top:6px;color:var(--texto-suave);font-size:.92em;">📖 ${_esc(_justifData.materia)}</div>` : ''}`;
    document.getElementById('justif-motivo').value = '';
    document.getElementById('justif-comentario').value = '';
    document.getElementById('justif-modal-overlay').classList.add('justif-modal--visible');
    document.body.style.overflow = 'hidden';
}

function cerrarModalJustif() {
    document.getElementById('justif-modal-overlay').classList.remove('justif-modal--visible');
    document.body.style.overflow = '';
    _justifData = null;
}

async function confirmarJustificacion() {
    if (!_justifData) return;
    const motivo  = document.getElementById('justif-motivo').value.trim();
    const coment  = document.getElementById('justif-comentario').value.trim();
    if (!motivo) return mostrarToast('Seleccione un motivo.', 'warning');
    try {
        const r = await fetch('/api/justificacion_ausencia', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({
                docente:    _justifData.docente,
                aula:       _justifData.aula,
                turno:      _justifData.turno,
                fecha:      _justifData.fecha,
                motivo, comentario: coment,
                registrado_por: (window.SIPA.adminUsuario || 'Plana Mayor'),
            }),
        });
        const d = await r.json();
        if (r.ok) {
            mostrarToast('✅ ' + d.msj, 'success');
            cerrarModalJustif();
            cargarInasistencias();
        } else {
            mostrarToast(d.error || 'Error.', 'error');
        }
    } catch (e) {
        mostrarToast('Error de red: ' + e.message, 'error');
    }
}

async function _eliminarJustif(link) {
    const d = {
        docente: link.dataset.docente,
        aula:    link.dataset.aula,
        turno:   link.dataset.turno,
        fecha:   link.dataset.fecha,
    };
    if (!confirm(`Eliminar la justificación de ${d.docente} del ${d.fecha}?`)) return;
    try {
        const r = await fetch('/api/justificacion_ausencia', {
            method: 'DELETE',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify(d),
        });
        const dr = await r.json();
        if (r.ok) { mostrarToast('🗑️ ' + dr.msj, 'success'); cargarInasistencias(); }
        else mostrarToast(dr.error || 'Error.', 'error');
    } catch (e) {
        mostrarToast('Error: ' + e.message, 'error');
    }
}

function exportarInasistencias() {
    const desde = document.getElementById('inasis-desde').value;
    const hasta = document.getElementById('inasis-hasta').value;
    const turno = document.getElementById('inasis-turno').value;
    const incJ  = document.getElementById('inasis-incluir-just').checked ? '1' : '0';
    if (!desde || !hasta) return mostrarToast('Defina rango primero.', 'warning');
    const url = `/api/inasistencias/export?desde=${desde}&hasta=${hasta}&turno=${turno}&incluir_justificadas=${incJ}`;
    const a = document.createElement('a');
    a.href = url; a.download = ''; a.target = '_blank';
    document.body.appendChild(a); a.click(); a.remove();
}

function abrirPartePDF() {
    const fecha = document.getElementById('inasis-desde')?.value || new Date().toISOString().slice(0,10);
    const turno = document.getElementById('inasis-turno')?.value || '';
    const tok = window.SIPA.adminToken || window.SIPA.suToken || '';
    let url = `/api/parte_pdf?fecha=${fecha}`;
    if (turno) url += `&turno=${turno}`;
    // Abrir en nueva pestana con token en header no es posible con window.open,
    // asi que usamos fetch + blob
    fetch(url, { headers: { 'X-Admin-Token': window.SIPA.adminToken || '', 'X-SU-Token': window.SIPA.suToken || '' } })
        .then(r => { if (!r.ok) throw new Error('No autorizado'); return r.text(); })
        .then(html => {
            const w = window.open('', '_blank');
            if (w) { w.document.write(html); w.document.close(); }
            else mostrarToast('Habilite popups para ver el PDF.', 'warning');
        })
        .catch(e => mostrarToast('Error: ' + e.message, 'error'));
}


// ══════════════════════════════════════════════════════════════
// EDICIÓN MANUAL DE PADRÓN
// ══════════════════════════════════════════════════════════════
async function cargarPadronParaEditar() {
    const a = document.getElementById('p-aula').value.trim().toUpperCase();
    const t = document.getElementById('p-turno').value;
    if (!a) return;
    const tb = document.getElementById('body-padron');
    try {
        const r = await fetch(`/api/aspirantes?aula=${encodeURIComponent(a)}&turno=${encodeURIComponent(t)}`);
        if (!r.ok) {
            mostrarToast(`Error cargando padrón de Aula ${a}: HTTP ${r.status}`, 'error');
            return;
        }
        const d = await r.json();
        tb.innerHTML = '';
        if (Array.isArray(d) && d.length) {
            d.forEach(asp => addPadronRow(asp));
        } else {
            addPadronRow();
        }
    } catch (e) {
        mostrarToast('Error cargando padrón: ' + e.message, 'error');
        console.error('[cargarPadronParaEditar]', e);
    }
}

function addPadronRow(asp = {}) {
    const tb = document.getElementById('body-padron');
    if (!tb) return;
    const tr = document.createElement('tr');
    tr.innerHTML = `
        <td><input type="text" class="p-grado"  value="${(asp.grado || '').replace(/"/g,'&quot;')}"  placeholder="ASP III"></td>
        <td><input type="text" class="p-nombre" value="${(asp.nombre || '').replace(/"/g,'&quot;')}" placeholder="APELLIDO NOMBRE"></td>
        <td><button class="btn btn-danger btn-small" style="padding:8px 12px;" onclick="this.closest('tr').remove()">✖</button></td>`;
    tb.appendChild(tr);
}

async function guardarPadronManual() {
    const aula  = document.getElementById('p-aula').value.trim().toUpperCase();
    const turno = document.getElementById('p-turno').value;
    if (!aula) return mostrarToast('Ingrese un aula primero.', 'warning');

    const aspirantes = [];
    document.querySelectorAll('#body-padron tr').forEach(tr => {
        const grado  = tr.querySelector('.p-grado')?.value.trim()  || '';
        const nombre = tr.querySelector('.p-nombre')?.value.trim() || '';
        if (nombre) aspirantes.push({ grado, nombre: nombre.toUpperCase() });
    });

    if (!aspirantes.length) {
        if (!confirm('No hay aspirantes cargados. ¿Confirma vaciar el padrón de esta aula?')) return;
    }

    try {
        const r = await fetch('/api/aspirantes', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ aula, turno, aspirantes }),
        });
        const d = await r.json();
        if (r.ok) {
            mostrarToast('✅ ' + (d.msj || 'Padrón guardado.'), 'success');
        } else {
            mostrarToast(d.error || 'Error al guardar', 'error');
        }
    } catch (e) {
        mostrarToast('Error de red: ' + e.message, 'error');
        console.error('[guardarPadronManual]', e);
    }
}


async function cargarConfigParaEditar() {
    const a=document.getElementById('c-aula').value.trim().toUpperCase();
    const t=document.getElementById('c-turno').value;
    if(!a) return;
    const tb=document.getElementById('body-config');
    try {
        const r = await fetch(`/api/config_aula/${a}/${t}`);
        if(!r.ok){ mostrarToast(`Error cargando aula ${a}: HTTP ${r.status}`,'error'); return; }
        const d = await r.json();
        tb.innerHTML='';
        if(Array.isArray(d) && d.length){
            d.forEach(b => addConfigRow(b));
        } else {
            addConfigRow();
        }
    } catch(e) {
        mostrarToast('Error cargando configuración: '+e.message,'error');
        console.error('[cargarConfigParaEditar]', e);
    }
}

async function guardarCronogramaManual() {
    const a=document.getElementById('c-aula').value.trim().toUpperCase(),t=document.getElementById('c-turno').value;
    if(!a)return mostrarToast('Ingrese número de aula.','warning');
    const config=Array.from(document.querySelectorAll('#body-config tr')).map(tr=>({
        dia:tr.querySelector('.c-dia')?.value||'',hora:tr.querySelector('.c-hora')?.value||'',
        asig:tr.querySelector('.c-asig')?.value||'',doc:tr.querySelector('.c-doc')?.value||''
    })).filter(r=>r.dia&&r.asig);
    const btn=document.querySelector('#cfg-cronograma .btn-success');
    if(btn){btn.disabled=true;btn.innerHTML='<span class="spin">🔄</span>';}
    try{const r=await fetch('/api/config_aula',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({aula:a,turno:t,config})});if(r.ok)mostrarToast('✅ Cuadrícula guardada.','success');else {const d=await r.json().catch(()=>({}));mostrarToast(d.error||'Error.','error');}}
    catch{mostrarToast('Error.','error');}
    finally{if(btn){btn.disabled=false;btn.textContent='💾 Registrar Cuadrícula';}}
}
