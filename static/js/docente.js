/* ============================================================
   docente.js — S.I.P.A. · GNA 2026
   Portal Docente: enfoque móvil, Mi Jornada, teclado PIN modal
   ============================================================ */
'use strict';

// ── ESTADO INTERNO ────────────────────────────────────────
let _pinModalTarget = null;   // { aula, turno } o null (firma directa)
let _pinBuffer      = '';

// ── NAVEGACIÓN ────────────────────────────────────────────
function mostrarRegistroDoc() {
    document.getElementById('login-docente').style.display     = 'none';
    document.getElementById('recuperar-docente').style.display = 'none';
    document.getElementById('panel-docente').style.display     = 'none';
    document.getElementById('registro-docente').style.display  = 'flex';
    cargarListaDocentesOficial();
}
function mostrarRecuperarDoc() {
    document.getElementById('login-docente').style.display     = 'none';
    document.getElementById('registro-docente').style.display  = 'none';
    document.getElementById('panel-docente').style.display     = 'none';
    document.getElementById('recuperar-docente').style.display = 'flex';
}
function volverLoginDoc() {
    if (window.SIPA.docenteLogName &&
        !confirm('¿Cerrar la sesión del Portal Docente?')) return;
    const token = window.SIPA.docenteToken;
    if (token) {
        fetch('/api/docente/logout', {
            method: 'POST',
            headers: { 'X-Docente-Token': token },
        }).catch(error => console.error('[docenteLogout]', error));
    }
    ['registro-docente','recuperar-docente','panel-docente'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
    });
    document.getElementById('login-docente').style.display = 'flex';
    cerrarPinModal();
    // Limpiar formulario de login para que el próximo usuario arranque vacío
    ['doc-email','doc-pass'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = '';
    });
    if (window.SIPA.docenteLogName) {
        mostrarToast('🚪 Sesión cerrada', 'info');
    }
    window.SIPA.docenteLogName = '';
    window.SIPA.docenteToken = '';
    window.SIPA.docenteEsPgnp = false;
}

// ── LISTA OFICIAL ─────────────────────────────────────────
async function cargarListaDocentesOficial() {
    const sel = document.getElementById('reg-nombre');
    if (!sel) return;
    sel.innerHTML = '<option value="">Cargando…</option>';
    try {
        const res = await fetch('/api/docentes/nombres-cronograma');
        const nombres = await res.json();
        if (!res.ok) throw new Error(nombres.error || `HTTP ${res.status}`);
        sel.innerHTML = nombres.length === 0
            ? '<option value="">(Sin cronogramas cargados)</option>'
            : '<option value="">— Seleccione exactamente su nombre y aula —</option>' +
              nombres.map(item => `<option value="${_esc(item.nombre)}">${_esc(item.nombre)} · ${item.bloques} bloques · ${_esc(item.aulas.join(', '))}</option>`).join('');
    } catch (error) {
        console.error('[cargarListaDocentesOficial]', error);
        mostrarToast('No se pudo cargar la lista.', 'error');
        sel.innerHTML = '<option value="">Error</option>';
    }
}

function cambiarTipoCuentaDocente() {
    const esPgnp = document.getElementById('reg-tipo-cuenta')?.value === 'pgnp';
    const oficial = document.getElementById('reg-nombre-oficial-wrap');
    const pgnp = document.getElementById('reg-nombre-pgnp-wrap');
    if (oficial) oficial.style.display = esPgnp ? 'none' : '';
    if (pgnp) pgnp.style.display = esPgnp ? '' : 'none';
}

// ── REGISTRO ──────────────────────────────────────────────
async function docenteRegistrar() {
    const esPgnp   = document.getElementById('reg-tipo-cuenta').value === 'pgnp';
    const nombre   = esPgnp
        ? document.getElementById('reg-nombre-pgnp').value.trim()
        : document.getElementById('reg-nombre').value;
    const dni      = document.getElementById('reg-dni').value.trim();
    const email    = document.getElementById('reg-email').value.trim();
    const password = document.getElementById('reg-pass').value;
    if (!nombre || !dni || !email || !password)
        return mostrarToast('Complete todos los campos.', 'warning');
    const btn = document.querySelector('#registro-docente .btn-primary');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spin">🔄</span> Registrando…'; }
    try {
        const res  = await fetch('/api/docente/registro', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ nombre, dni, email, password, es_pgnp: esPgnp })
        });
        const data = await res.json();
        if (res.ok) { mostrarToast('✅ Cuenta creada.', 'success'); volverLoginDoc(); }
        else mostrarToast(data.error || 'Error al registrar.', 'error');
    } catch { mostrarToast('Error de conexión.', 'error'); }
    finally { if (btn) { btn.disabled = false; btn.innerHTML = '✓ Crear Cuenta'; } }
}

// ── RECUPERAR ─────────────────────────────────────────────
async function docenteRecuperar() {
    const email = document.getElementById('rec-email').value.trim();
    const dni   = document.getElementById('rec-dni').value.trim();
    const npass = document.getElementById('rec-pass').value;
    if (!email || !dni || !npass) return mostrarToast('Complete todos los campos.', 'warning');
    const btn = document.querySelector('#recuperar-docente .btn-warning');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spin">🔄</span>'; }
    try {
        const res  = await fetch('/api/docente/recuperar', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ email, dni, nueva_password: npass })
        });
        const data = await res.json();
        if (res.ok) { mostrarToast('✅ Contraseña actualizada.', 'success'); volverLoginDoc(); }
        else mostrarToast(data.error || 'Error.', 'error');
    } catch { mostrarToast('Error de conexión.', 'error'); }
    finally { if (btn) { btn.disabled = false; btn.innerHTML = '🔄 Cambiar Contraseña'; } }
}

// ── LOGIN ─────────────────────────────────────────────────
async function docenteLogin() {
    const email    = document.getElementById('doc-email').value.trim();
    const password = document.getElementById('doc-pass').value;
    if (!email || !password) return mostrarToast('Ingrese correo y contraseña.', 'warning');
    const btn = document.querySelector('#login-docente .btn-info');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spin">🔄</span> Ingresando…'; }
    try {
        const res  = await fetch('/api/docente/login', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ email, password })
        });
        const data = await res.json();
        if (res.ok) {
            window.SIPA.docenteLogName  = data.nombre;
            window.SIPA.docenteLogEmail = email;  // necesario para auto-justificación
            window.SIPA.docenteToken = data.token;
            window.SIPA.docenteEsPgnp = !!data.es_pgnp;
            document.getElementById('login-docente').style.display = 'none';
            document.getElementById('panel-docente').style.display  = 'block';
            const panelPgnp = document.getElementById('panel-coberturas-pgnp');
            if (panelPgnp) panelPgnp.style.display = data.es_pgnp ? '' : 'none';
            const panelAdelantos = document.getElementById('docente-adelantos-horario');
            if (panelAdelantos) panelAdelantos.style.display = data.es_pgnp ? 'none' : '';
            // Saludo personalizado
            _actualizarSaludoDocente(data.nombre);
            mostrarToast(`Bienvenido/a, ${data.nombre}`, 'success');
            if (data.es_pgnp) await cargarCoberturasPgnp();
            await cargarClasesPendientes();
            await cargarHorarioSemanal();
            await cargarHistorialFirmasDocente();
            await cargarJustificacionesDocente();
        } else {
            mostrarToast(data.error || 'Credenciales incorrectas.', 'error');
        }
    } catch { mostrarToast('Error de conexión.', 'error'); }
    finally { if (btn) { btn.disabled = false; btn.innerHTML = '🔓 Ingresar'; } }
}

async function cargarCoberturasPgnp() {
    const lista = document.getElementById('coberturas-pgnp-lista');
    if (!lista || !window.SIPA.docenteToken) return;
    lista.innerHTML = '<div class="empty-state">Cargando coberturas asignadas…</div>';
    try {
        const response = await fetch('/api/docente/coberturas', {
            headers: { 'X-Docente-Token': window.SIPA.docenteToken },
        });
        const items = await response.json();
        if (!response.ok) throw new Error(items.error || `HTTP ${response.status}`);
        if (!items.length) {
            lista.innerHTML = '<div class="empty-state"><span class="empty-state-icon">📋</span><span class="empty-state-text">No tiene coberturas aprobadas.</span></div>';
            return;
        }
        lista.innerHTML = `<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:10px;">${
            items.map(item => {
                const firmada = item.estado === 'completada';
                const hoy = item.fecha === obtenerFechaHoyLocal();
                return `<article class="card" style="margin:0;border:1px solid var(--borde);">
                    <div style="display:flex;justify-content:space-between;gap:8px;align-items:flex-start;">
                        <strong>${_esc(item.fecha)} · Aula ${_esc(item.aula)} (${_esc(item.turno)})</strong>
                        <span class="badge-mini ${firmada ? 'badge-mini-verde' : 'badge-mini-naranja'}">${firmada ? '✅ Firmada' : '⏳ Aprobada'}</span>
                    </div>
                    <div style="margin-top:8px;"><strong>${_esc(item.materia)}</strong> · ${_esc(item.hora)}</div>
                    <div style="font-size:.88em;color:var(--texto-suave);">Titular: ${_esc(item.titular)} · Autorizó: ${_esc(item.revisada_por || 'Plana Mayor')}</div>
                    ${firmada ? `<div style="margin-top:8px;color:var(--exito);">Cobertura firmada: ${_esc(item.firmado_en || '')}</div>` : hoy
                        ? `<button class="btn btn-success btn-small" style="margin-top:10px;" onclick="firmarCoberturaPgnp(${Number(item.id)},this)">✍️ Firmar que cubrí esta clase</button>`
                        : `<div style="margin-top:8px;color:var(--texto-suave);">La firma estará disponible el día asignado.</div>`}
                </article>`;
            }).join('')
        }</div>`;
    } catch (error) {
        lista.innerHTML = `<div class="bd-error-banner">No se pudieron cargar las coberturas: ${_esc(error.message)}</div>`;
        console.error('[cargarCoberturasPgnp]', error);
    }
}

async function firmarCoberturaPgnp(id, boton) {
    if (!window.SIPA.docenteToken) return mostrarToast('Inicie sesión nuevamente para firmar.', 'warning');
    boton.disabled = true;
    try {
        const response = await fetch(`/api/docente/coberturas/${id}/firmar`, {
            method: 'POST',
            headers: { 'X-Docente-Token': window.SIPA.docenteToken },
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        mostrarToast(data.msj, data.ya_firmada ? 'info' : 'success');
        await cargarCoberturasPgnp();
    } catch (error) {
        boton.disabled = false;
        mostrarToast(error.message, 'error');
    }
}

function _actualizarSaludoDocente(nombre) {
    const hora   = new Date().getHours();
    const saludo = hora < 12 ? 'Buenos días' : hora < 19 ? 'Buenas tardes' : 'Buenas noches';
    // Apellido: primer token del nombre
    const apellido = nombre.split(',')[0].split(' ')[0];
    const el = document.getElementById('docente-saludo');
    if (el) el.textContent = `${saludo}, ${apellido}`;
    const e = document.getElementById('docente-logueado');
    if (e) e.textContent = nombre;
}

// ── HORARIO SEMANAL COMPLETO + FIRMA POR AULA ────────────────
async function cargarHorarioSemanal() {
    const cont = document.getElementById('horario-semanal-list');
    if (!cont) return;
    cont.innerHTML = `<p style="color:var(--texto-tenue);text-align:center;padding:20px;"><span class="spin">🔄</span> Cargando horario…</p>`;
    try {
        const r = await fetch(`/api/horario_docente?nombre=${encodeURIComponent(window.SIPA.docenteLogName)}`);
        if (!r.ok) {
            let detalle = `HTTP ${r.status}`;
            try { const j = await r.json(); detalle = j.error || detalle; } catch {}
            throw new Error(detalle);
        }
        const clasesBase = await r.json();
        const resAdelantos = await fetch('/api/docente/adelantos-horario', {
            headers: {'X-Docente-Token': window.SIPA.docenteToken || ''},
        });
        const datosAdelantos = await resAdelantos.json();
        if (!resAdelantos.ok) throw new Error(datosAdelantos.error || `HTTP ${resAdelantos.status}`);
        window.SIPA.docenteHorarioBase = Array.isArray(clasesBase) ? clasesBase : [];
        _renderPanelAdelantosDocente(datosAdelantos, Array.isArray(clasesBase) ? clasesBase : []);
        const hoy = obtenerFechaHoyLocal();
        const adelantos = Array.isArray(datosAdelantos.casos) ? datosAdelantos.casos : [];
        const clases = (Array.isArray(clasesBase) ? clasesBase : []).filter(clase =>
            !(clase.es_hoy && adelantos.some(caso =>
                caso.estado === 'aplicado' && caso.fecha_original === hoy
                && caso.aula === clase.aula && caso.turno === clase.turno
                && _normalizarTextoAdelanto(caso.materia) === _normalizarTextoAdelanto(clase.materia)
                && _normalizarHoraAdelanto(caso.hora_original) === _normalizarHoraAdelanto(clase.hora)
            ))
        );
        adelantos.filter(caso => caso.estado === 'aplicado' && caso.fecha_nueva === hoy)
            .forEach(caso => clases.push({
                aula: caso.aula, turno: caso.turno,
                dia: _diaSemanaDesdeFecha(caso.fecha_nueva),
                hora: caso.hora_nueva, materia: caso.materia,
                es_hoy: true, firmado: !!caso.firmado, adelanto: true,
                fecha_adelanto: caso.fecha_nueva,
            }));
        if (!clases.length) {
            cont.innerHTML = `<div class="empty-state">
                <span class="empty-state-icon">📭</span>
                <span class="empty-state-text">No se encontraron materias asignadas a su nombre en el cronograma cargado.</span>
            </div>`;
            return;
        }

        // Contar cuántos módulos comparten misma (aula+turno) hoy → la firma es única
        const conteoHoyPorAula = {};
        clases.filter(c => c.es_hoy).forEach(c => {
            const k = `${c.aula}|${c.turno}`;
            conteoHoyPorAula[k] = (conteoHoyPorAula[k] || 0) + 1;
        });
        clases.forEach(c => {
            if (c.es_hoy) {
                c._modulosMismaAula = conteoHoyPorAula[`${c.aula}|${c.turno}`] || 1;
            }
        });

        cont.innerHTML = clases.map(c => _crearItemHorario(c)).join('');
    } catch (e) {
        console.error('[cargarHorarioSemanal]', e);
        cont.innerHTML = `<div class="empty-state" style="border-color:var(--peligro-cl);color:var(--peligro);">
            <span class="empty-state-icon">⚠️</span>
            <span class="empty-state-text">Error al cargar el horario: ${e.message}</span>
        </div>`;
    }
}

function _normalizarTextoAdelanto(valor) {
    return String(valor || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim().toLowerCase();
}

function _normalizarHoraAdelanto(valor) {
    const partes = String(valor || '').split(/[-–—]/);
    if (partes.length !== 2) return String(valor || '').replace(/\s/g, '').toLowerCase();
    return partes.map(parte => {
        const digitos = parte.replace(/\D/g, '').padStart(4, '0');
        return digitos.length === 4 ? `${digitos.slice(0, 2)}:${digitos.slice(2)}` : digitos;
    }).join('-');
}

function _diaSemanaDesdeFecha(fecha) {
    const [y, m, d] = String(fecha || '').split('-').map(Number);
    return ['Domingo','Lunes','Martes','Miércoles','Jueves','Viernes','Sábado'][
        new Date(y, m - 1, d).getDay()
    ];
}

function _fechaProximaClase(dia) {
    const dias = ['Domingo','Lunes','Martes','Miércoles','Jueves','Viernes','Sábado'];
    const fecha = new Date();
    fecha.setHours(0, 0, 0, 0);
    for (let intento = 0; intento <= 180; intento++) {
        if (dias[fecha.getDay()] === dia) {
            const y = fecha.getFullYear();
            const m = String(fecha.getMonth() + 1).padStart(2, '0');
            const d = String(fecha.getDate()).padStart(2, '0');
            return `${y}-${m}-${d}`;
        }
        fecha.setDate(fecha.getDate() + 1);
    }
    return obtenerFechaHoyLocal();
}

function _fechaLimiteAdelanto() {
    const fecha = new Date();
    fecha.setDate(fecha.getDate() + 180);
    return `${fecha.getFullYear()}-${String(fecha.getMonth() + 1).padStart(2, '0')}-${String(fecha.getDate()).padStart(2, '0')}`;
}

function _renderPanelAdelantosDocente(datos, clases) {
    const estado = document.getElementById('docente-adelantos-estado');
    const formulario = document.getElementById('docente-adelantos-form');
    const historial = document.getElementById('docente-adelantos-historial');
    const selector = document.getElementById('docente-adelanto-clase');
    const activo = !!datos.activo;
    if (estado) {
        estado.textContent = activo ? '✅ Adelantos automáticos ACTIVADOS' : '🔒 Adelantos DESACTIVADOS por TIC';
        estado.className = activo ? 'badge-verde' : 'badge-mini';
    }
    if (formulario) formulario.style.display = activo ? '' : 'none';
    if (selector && activo) {
        selector.innerHTML = clases.length
            ? '<option value="">— Seleccione la clase del cronograma —</option>' +
                clases.map((clase, indice) =>
                    `<option value="${indice}">${_esc(clase.dia)} · ${_esc(clase.hora)} · ${_esc(clase.materia)} · Aula ${_esc(clase.aula)} (${_esc(clase.turno)})</option>`
                ).join('')
            : '<option value="">No hay clases asignadas en el cronograma</option>';
        selector.onchange = () => {
            const clase = clases[Number(selector.value)];
            if (!clase) return;
            const fechaOrigen = _fechaProximaClase(clase.dia);
            const origen = document.getElementById('docente-adelanto-origen');
            const destino = document.getElementById('docente-adelanto-fecha');
            if (origen) {
                origen.value = fechaOrigen;
                origen.min = obtenerFechaHoyLocal();
                origen.max = _fechaLimiteAdelanto();
            }
            if (destino) {
                destino.min = obtenerFechaHoyLocal();
                destino.max = fechaOrigen;
                destino.value = fechaOrigen;
            }
        };
        document.getElementById('docente-adelanto-origen').onchange = () => {
            const origen = document.getElementById('docente-adelanto-origen');
            const destino = document.getElementById('docente-adelanto-fecha');
            if (!origen || !destino) return;
            destino.max = origen.value;
            if (destino.value > origen.value) destino.value = origen.value;
        };
    }
    const casos = Array.isArray(datos.casos) ? datos.casos : [];
    if (historial) {
        historial.innerHTML = casos.length ? `<h4 style="margin:12px 0 8px;">Mis adelantos registrados</h4>${casos.map(caso => `
            <article class="card" style="margin:8px 0;padding:12px;border:1px solid var(--borde);">
                <strong>${_esc(caso.estado === 'aplicado' ? '✅ Aplicado automáticamente' : '↩️ Revocado')}</strong>
                · ${_esc(caso.materia)} · Aula ${_esc(caso.aula)} (${_esc(caso.turno)})
                <div style="font-size:.88em;color:var(--texto-suave);margin-top:4px;">
                    Original: ${_esc(caso.fecha_original)} · ${_esc(caso.hora_original)}
                    → Adelantada: ${_esc(caso.fecha_nueva)} · ${_esc(caso.hora_nueva)}
                </div>
                <div style="font-size:.8em;color:var(--texto-tenue);">Registrado: ${_esc(caso.creado_en || '')}${caso.revocado_por ? ` · Revocado por ${_esc(caso.revocado_por)}` : ''}</div>
            </article>`).join('')}` : '<p class="aulas-dia-muted">Todavía no hay adelantos registrados.</p>';
    }
}

async function solicitarAdelantoHorario() {
    const clases = window.SIPA?.docenteHorarioBase || [];
    const seleccion = document.getElementById('docente-adelanto-clase')?.value || '';
    if (seleccion === '') return mostrarToast('Seleccione una clase del cronograma.', 'warning');
    const indice = Number(seleccion);
    const clase = clases[indice];
    if (!clase) return mostrarToast('Seleccione una clase del cronograma.', 'warning');
    const payload = {
        aula: clase.aula,
        turno: clase.turno,
        materia: clase.materia,
        hora_original: clase.hora,
        fecha_original: document.getElementById('docente-adelanto-origen')?.value,
        fecha_nueva: document.getElementById('docente-adelanto-fecha')?.value,
        hora_nueva_inicio: document.getElementById('docente-adelanto-hora')?.value,
    };
    if (!payload.fecha_original || !payload.fecha_nueva || !payload.hora_nueva_inicio) {
        return mostrarToast('Complete las fechas y la nueva hora de inicio.', 'warning');
    }
    try {
        const response = await fetch('/api/docente/adelantos-horario', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-Docente-Token': window.SIPA.docenteToken || '',
            },
            body: JSON.stringify(payload),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        mostrarToast(data.msj || 'Adelanto aplicado automáticamente.', 'success');
        document.getElementById('docente-adelanto-hora').value = '';
        await cargarHorarioSemanal();
    } catch (error) {
        mostrarToast(error.message, 'error');
    }
}

function _crearItemHorario(c) {
    const esHoy   = !!c.es_hoy;
    const firmado = !!c.firmado;
    const horaTxt = _formatHora(c.hora);
    const modulos = c._modulosMismaAula || 1;

    // Aviso: una firma cubre varios módulos del mismo día en la misma aula
    const avisoModulos = (esHoy && modulos > 1)
        ? `<div class="aviso-modulos">
            ℹ️ <strong>Esta aula tiene ${modulos} módulos hoy.</strong>
            Con <u>una sola firma</u> queda registrada su asistencia para todos ellos.
           </div>`
        : '';

    // El botón de firma SOLO aparece el día que corresponde, y se habilita
    // únicamente en la ventana operativa: inicio-15min ≤ ahora ≤ fin+10min.
    let accionHtml = '';
    if (esHoy && c.sin_actividad) {
        accionHtml = `<div class="horario-accion">
            <div class="horario-justif-info">
                <span class="badge-mini">📅 Sin actividad</span>
                <div class="horario-justif-detalle">La jornada fue confirmada como día sin actividad. Esta clase no genera falta.</div>
            </div>
        </div>`;
    } else if (esHoy && firmado) {
        const textoCobertura = modulos > 1
            ? `<span class="horario-firmado-cobertura">Cubre los ${modulos} módulos de hoy en esta aula</span>`
            : '';
        accionHtml = `<div class="horario-accion">
            <div class="horario-firmado">
                <span class="horario-firmado-check">✅</span>
                <span class="horario-firmado-txt">Asistencia registrada</span>
                <span class="horario-firmado-hora">${c.hora_firma || '--:--'}</span>
            </div>
            ${textoCobertura}
        </div>`;
    } else if (esHoy && c.justif_estado) {
        // Hay justificación previa (auto o por PM)
        const estado = c.justif_estado;
        const badge = estado === 'aprobada'
            ? `<span class="badge-verde">✓ JUSTIFICADA</span>`
            : estado === 'pendiente'
            ? `<span class="badge-mini badge-mini-naranja">⏳ Pendiente de aprobación</span>`
            : `<span class="badge-rojo">✗ Justificación rechazada</span>`;
        accionHtml = `<div class="horario-accion">
            <div class="horario-justif-info">
                ${badge}
                <div class="horario-justif-detalle">
                    <strong>Motivo:</strong> ${c.justif_motivo || '—'}
                    ${c.justif_coment ? `<div style="margin-top:3px;color:var(--texto-suave);font-size:.88em;">${c.justif_coment}</div>` : ''}
                </div>
            </div>
        </div>`;
    } else if (esHoy) {
        const v = _ventanaFirma(c.hora);
        if (v.enRango) {
            accionHtml = `<div class="horario-accion">
                <button class="btn-firmar btn-firmar--hoy"
                        data-aula="${c.aula}" data-turno="${c.turno}" data-hora="${c.hora || ''}"
                        onclick="abrirPinModal('${c.aula}','${c.turno}')">
                    <span class="btn-firmar-icon">🔐</span>
                    <span class="btn-firmar-txt">Firmar Presentismo</span>
                </button>
            </div>`;
        } else {
            // Determinar si la ventana YA pasó (para ofrecer justificar) o aún no llegó
            const now = new Date();
            const finCierre = _horaToDate((c.hora||'').split('-')[1]||'', 10, now);
            const yaPaso = finCierre && now > finCierre;

            if (yaPaso) {
                // Ventana cerrada → ofrecer auto-justificación
                accionHtml = `<div class="horario-accion">
                    <button class="btn-justif-docente"
                            data-aula="${c.aula}" data-turno="${c.turno}" data-hora="${c.hora || ''}"
                            data-materia="${(c.materia||'').replace(/"/g,'&quot;')}"
                            onclick="abrirAutoJustif(this)">
                        📋 Justificar / Firma Tardía
                    </button>
                    <div class="btn-firmar-hint">El plazo expiró a las ${v.cierreTxt}. Puede enviar una justificación que quedará pendiente de aprobación.</div>
                </div>`;
            } else {
                accionHtml = `<div class="horario-accion">
                    <button class="btn-firmar btn-firmar--bloqueado" disabled
                            title="Habilitado entre ${v.aperturaTxt} y ${v.cierreTxt}">
                        <span class="btn-firmar-icon">🔒</span>
                        <span class="btn-firmar-txt">${v.razon}</span>
                    </button>
                    <div class="btn-firmar-hint">${v.hint}</div>
                </div>`;
            }
        }
    }
    // Días que no son hoy: no se muestra acción (no se puede firmar)

    return `
    <div class="horario-item ${esHoy ? 'horario-item--hoy' : ''}">
        ${c.adelanto ? '<div class="badge-verde" style="display:inline-block;margin-bottom:8px;">⏩ Cambio aplicado automáticamente</div>' : ''}
        <div class="horario-fila">
            <span class="horario-label">Día</span>
            <span class="horario-valor">${c.dia || '—'}${esHoy ? ' <span class="badge-hoy">HOY</span>' : ''}</span>
        </div>
        <div class="horario-fila">
            <span class="horario-label">Horario</span>
            <span class="horario-valor horario-hora">${horaTxt}</span>
        </div>
        <div class="horario-fila">
            <span class="horario-label">Materia</span>
            <span class="horario-valor">${c.materia || '—'}</span>
        </div>
        <div class="horario-fila">
            <span class="horario-label">Aula</span>
            <span class="horario-valor"><strong>${c.aula}</strong> · ${c.turno}${c.orientacion ? ' · '+c.orientacion : ''}</span>
        </div>
        ${avisoModulos}
        ${accionHtml}
    </div>`;
}

// Parámetros operativos cargados desde el backend (configurables por SU)
window._SIPA_PARAMS = window._SIPA_PARAMS || {
    tolerancia_antes_min:  15,
    tolerancia_despues_min: 10,
};

(async function _cargarParametrosSistema() {
    try {
        const r = await fetch('/api/parametros_publicos');
        if (r.ok) {
            const p = await r.json();
            window._SIPA_PARAMS.tolerancia_antes_min   = parseInt(p.tolerancia_antes_min   || 15) || 15;
            window._SIPA_PARAMS.tolerancia_despues_min = parseInt(p.tolerancia_despues_min || 10) || 10;
        }
    } catch {}
})();

/**
 * Determina si la hora actual está dentro de la ventana operativa de firma.
 * Ventana: [inicio_clase - tolAntes, fin_clase + tolDespues] (configurables por SU).
 */
function _ventanaFirma(horaStr) {
    if (!horaStr || !horaStr.includes('-')) {
        return { enRango: false, razon: 'Horario no definido', hint: '', aperturaTxt:'--:--', cierreTxt:'--:--' };
    }
    const now = new Date();
    const [iniStr, finStr] = horaStr.split('-').map(s => s.trim());
    const tolAntes   = window._SIPA_PARAMS.tolerancia_antes_min;
    const tolDespues = window._SIPA_PARAMS.tolerancia_despues_min;
    const apertura = _horaToDate(iniStr, -tolAntes,   now);
    const cierre   = _horaToDate(finStr,  tolDespues, now);
    if (!apertura || !cierre) {
        return { enRango: false, razon: 'Horario no definido', hint: '', aperturaTxt:'--:--', cierreTxt:'--:--' };
    }
    const fmt = d => `${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
    const aperturaTxt = fmt(apertura);
    const cierreTxt   = fmt(cierre);

    if (now < apertura) {
        const diffMin = Math.ceil((apertura - now) / 60000);
        const hint = diffMin >= 60
            ? `Habilita en ${Math.floor(diffMin/60)} h ${diffMin%60} min (a las ${aperturaTxt})`
            : `Habilita en ${diffMin} min (a las ${aperturaTxt})`;
        return { enRango: false, razon: 'Fuera de rango horario', hint, aperturaTxt, cierreTxt };
    }
    if (now > cierre) {
        return { enRango: false, razon: 'Fuera de rango horario',
                 hint: `Plazo cerrado a las ${cierreTxt}`, aperturaTxt, cierreTxt };
    }
    return { enRango: true, razon: '', hint: '', aperturaTxt, cierreTxt };
}

function _horaToDate(horaStr, offsetMin, base) {
    if (!horaStr) return null;
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

function _formatHora(h) {
    if (!h) return '—';
    const partes = h.split('-').map(s => s.trim());
    if (partes.length === 2) return `${partes[0]} h a ${partes[1]} h`;
    return h;
}

// ── TECLADO PIN MODAL ─────────────────────────────────────
function abrirPinModal(aula = null, turno = null) {
    _pinBuffer     = '';
    _pinModalTarget = aula ? { aula, turno } : null;

    // Texto contextual
    const titulo = aula
        ? `Firma · Aula ${aula} (${turno})`
        : 'Firma Manual';

    document.getElementById('pin-modal-titulo').textContent = titulo;
    _actualizarDisplayPin();
    document.getElementById('pin-modal-overlay').classList.add('pin-modal--visible');
    // Prevenir scroll del body
    document.body.style.overflow = 'hidden';
}

function cerrarPinModal() {
    document.getElementById('pin-modal-overlay')?.classList.remove('pin-modal--visible');
    document.body.style.overflow = '';
    _pinBuffer     = '';
    _pinModalTarget = null;
}

function pinTecla(digito) {
    if (_pinBuffer.length >= 6) return;
    _pinBuffer += String(digito);
    _actualizarDisplayPin();
    // Vibración háptica en móvil
    if (navigator.vibrate) navigator.vibrate(30);
    // Auto-enviar si llegó a 4 dígitos
    if (_pinBuffer.length === 4) {
        setTimeout(enviarPinModal, 200);
    }
}

function pinBorrar() {
    if (_pinBuffer.length > 0) {
        _pinBuffer = _pinBuffer.slice(0, -1);
        _actualizarDisplayPin();
    }
}

function _actualizarDisplayPin() {
    const dots = document.querySelectorAll('.pin-dot');
    dots.forEach((dot, i) => {
        dot.classList.toggle('pin-dot--lleno', i < _pinBuffer.length);
    });
}

async function enviarPinModal() {
    if (!_pinBuffer || _pinBuffer.length < 4) {
        return mostrarToast('Ingrese los 4 dígitos del PIN.', 'warning');
    }

    const btnEnviar = document.getElementById('pin-btn-enviar');
    if (btnEnviar) { btnEnviar.disabled = true; btnEnviar.innerHTML = '<span class="spin">🔄</span>'; }

    // Intentar capturar geolocalización de forma no-bloqueante (timeout de 2s)
    const geo = await _capturarUbicacionRapida();

    const firmaPayload = {
        pin: _pinBuffer,
        docente: window.SIPA.docenteLogName,
        lat: geo.lat, lng: geo.lng, precision: geo.precision,
    };

    try {
        const res  = await fetch('/api/docente/firmar', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(firmaPayload)
        });
        const data = await res.json();

        if (res.ok) {
            cerrarPinModal();
            if (data.ya_firmado) {
                mostrarToast(`ℹ️ Ya había firmado en Aula ${data.aula} a las ${data.hora_firma}`, 'info');
            } else {
                mostrarToast(`✅ Presente registrado · Aula ${data.aula} · ${data.hora_firma}`, 'success');
                if (navigator.vibrate) navigator.vibrate([50, 30, 100]);
            }
            // Intentar enviar firmas offline pendientes
            _flushOfflineQueueFromApp();
            await cargarClasesPendientes();
            await cargarHorarioSemanal();
            await cargarHistorialFirmasDocente();
        } else {
            _animarErrorPin();
            mostrarToast(data.error || 'PIN incorrecto.', 'error');
            _pinBuffer = '';
            _actualizarDisplayPin();
        }
    } catch {
        // Sin conexión — encolar firma para enviar cuando vuelva la red
        if (navigator.serviceWorker && navigator.serviceWorker.controller) {
            const mc = new MessageChannel();
            navigator.serviceWorker.controller.postMessage({
                type: 'ENQUEUE_OFFLINE',
                url: '/api/docente/firmar',
                options: {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(firmaPayload)
                }
            }, [mc.port2]);
            cerrarPinModal();
            mostrarToast('📶 Sin conexión — firma guardada. Se enviará automáticamente al reconectar.', 'warning');
            if (navigator.vibrate) navigator.vibrate([30, 50, 30]);
        } else {
            mostrarToast('Error de red. No se pudo guardar la firma.', 'error');
        }
    } finally {
        if (btnEnviar) { btnEnviar.disabled = false; btnEnviar.textContent = 'Firmar ✓'; }
    }
}

function _flushOfflineQueueFromApp() {
    if (!navigator.serviceWorker || !navigator.serviceWorker.controller) return;
    const mc = new MessageChannel();
    mc.port1.onmessage = (evt) => {
        const r = evt.data;
        if (r && r.enviados > 0) {
            mostrarToast(`📶 ${r.enviados} firma(s) offline enviada(s) exitosamente.`, 'success');
        }
    };
    navigator.serviceWorker.controller.postMessage('FLUSH_OFFLINE_QUEUE', [mc.port2]);
}

// Auto-flush al reconectar
window.addEventListener('online', () => {
    _flushOfflineQueueFromApp();
});

function _animarErrorPin() {
    const display = document.getElementById('pin-modal-display');
    if (!display) return;
    display.classList.add('pin-display--error');
    if (navigator.vibrate) navigator.vibrate([100, 50, 100, 50, 100]);
    setTimeout(() => display.classList.remove('pin-display--error'), 600);
}

// ── HISTORIAL DE FIRMAS ───────────────────────────────────
async function cargarHistorialFirmasDocente() {
    const cont = document.getElementById('historial-firmas-docente');
    if (!cont) return;
    cont.innerHTML = `<div class="jornada-loading"><span class="spin">🔄</span><span>Cargando historial…</span></div>`;

    try {
        const desde   = '2024-01-01';
        const res     = await fetch(`/api/firmas_docentes/historial?docente=${encodeURIComponent(window.SIPA.docenteLogName)}&desde=${desde}`, {
            headers: { 'X-Docente-Token': window.SIPA.docenteToken },
        });
        const respuesta = await res.json();
        if (!res.ok) throw new Error(respuesta.error || `HTTP ${res.status}`);
        const firmas = respuesta;

        if (!firmas.length) {
            cont.innerHTML = `<div class="historial-vacio">Aún no se registraron clases en el calendario.</div>`;
            return;
        }

        // Agrupar por fecha
        const porFecha = {};
        firmas.forEach(f => {
            if (!porFecha[f.fecha]) porFecha[f.fecha] = [];
            porFecha[f.fecha].push(f);
        });

        let html = '';
        Object.keys(porFecha).sort().reverse().slice(0, 30).forEach(fecha => {
            const registros = porFecha[fecha];
            // Stats del día
            const presentes = registros.filter(r => r.estado === 'presente').length;
            const ausentes  = registros.filter(r => r.estado === 'ausente').length;
            const resumen = ausentes
                ? `<span class="historial-resumen-ausentes">${ausentes} sin firma</span>`
                : `<span class="historial-resumen-ok">${presentes} firmadas</span>`;

            html += `
            <div class="historial-firma-dia">
                <div class="historial-firma-fecha">
                    ${formatearFechaElegante(fecha)} ${resumen}
                </div>
                ${registros.map(r => _renderHistorialFila(r)).join('')}
            </div>`;
        });
        cont.innerHTML = html;
    } catch (e) {
        console.error('[cargarHistorialFirmasDocente]', e);
        cont.innerHTML = `<div class="historial-vacio" style="color:var(--peligro);">Error cargando historial: ${e.message}</div>`;
    }
}

function _renderHistorialFila(r) {
    const esAusente = r.estado === 'ausente';
    if (esAusente) {
        return `
            <div class="historial-firma-item historial-firma-item--ausente">
                <span class="historial-firma-hora historial-firma-hora--ausente">${_formatHora(r.hora_clase) || '--:--'}</span>
                <span class="historial-firma-aula">
                    <strong>Aula ${r.aula}</strong> · ${r.turno}
                    ${r.materia ? `<span style="color:var(--texto-tenue);font-size:.9em;"> · ${r.materia}</span>` : ''}
                </span>
                <span class="badge-rojo">❌ No Registrado</span>
            </div>`;
    }
    return `
        <div class="historial-firma-item">
            <span class="historial-firma-hora">${(r.hora_firma || '--:--').substring(0,5)}</span>
            <span class="historial-firma-aula"><strong>Aula ${r.aula}</strong> · ${r.turno}</span>
            <span class="badge-verde">✅ Presente</span>
            ${_renderGeolocalizacionDocente(r)}
        </div>`;
}

function _renderGeolocalizacionDocente(firma) {
    if (firma.lat === null || firma.lat === undefined || firma.lat === ''
        || firma.lng === null || firma.lng === undefined || firma.lng === '') {
        return '<span style="color:var(--texto-tenue);font-size:.82em;">📍 Ubicación no registrada</span>';
    }
    const lat = Number(firma.lat);
    const lng = Number(firma.lng);
    if (!Number.isFinite(lat) || !Number.isFinite(lng)) return '';
    const mapa = `https://www.google.com/maps?q=${encodeURIComponent(`${lat},${lng}`)}`;
    return `<a href="${mapa}" target="_blank" rel="noopener noreferrer"
        title="Coordenadas de esta firma">📍 ${lat.toFixed(6)}, ${lng.toFixed(6)}</a>`;
}

async function cargarJustificacionesDocente() {
    const cont = document.getElementById('justificaciones-docente-lista');
    if (!cont || !window.SIPA.docenteToken) return;
    cont.innerHTML = '<div class="historial-vacio">Cargando justificaciones…</div>';

    try {
        const response = await fetch('/api/docente/justificaciones', {
            headers: { 'X-Docente-Token': window.SIPA.docenteToken },
        });
        if (!response.headers.get('content-type')?.includes('application/json')) {
            throw new Error(
                `El servidor respondió con una página en vez de datos (HTTP ${response.status}). ` +
                'Actualice o reinicie el servidor para cargar la ruta de justificaciones.'
            );
        }
        const justificaciones = await response.json();
        if (!response.ok) throw new Error(justificaciones.error || `HTTP ${response.status}`);
        if (!justificaciones.length) {
            cont.innerHTML = '<div class="historial-vacio">Aún no envió solicitudes de justificación.</div>';
            return;
        }

        cont.innerHTML = justificaciones.map(j => {
            const estado = j.estado === 'aprobada'
                ? '<span class="badge-verde">✅ Aprobada · justificación aceptada</span>'
                : j.estado === 'rechazada'
                ? '<span class="badge-rojo">❌ Rechazada</span>'
                : '<span class="badge-mini badge-mini-naranja">⏳ Pendiente de aprobación</span>';
            const observacion = j.observacion_revision
                ? `<div style="margin-top:6px;"><strong>Respuesta de Plana Mayor:</strong> ${_escaparTextoHtml(j.observacion_revision)}</div>`
                : '';
            const comentario = j.comentario
                ? `<div style="margin-top:4px;color:var(--texto-suave);">${_escaparTextoHtml(j.comentario)}</div>`
                : '';
            const nuevaSolicitud = j.estado === 'rechazada'
                ? `<button class="btn-justif-docente" style="margin-top:8px;"
                    data-aula="${_escaparTextoHtml(j.aula)}"
                    data-turno="${_escaparTextoHtml(j.turno)}"
                    data-fecha="${_escaparTextoHtml(j.fecha)}"
                    data-materia="Justificación de ausencia"
                    onclick="abrirAutoJustif(this)">📋 Enviar nueva justificación</button>`
                : '';
            return `<article class="historial-firma-item" style="align-items:flex-start;">
                <div style="flex:1;min-width:220px;">
                    <strong>${_escaparTextoHtml(formatearFechaElegante(j.fecha))}</strong>
                    <div style="color:var(--texto-suave);margin:4px 0;">Aula ${_escaparTextoHtml(j.aula)} · ${_escaparTextoHtml(j.turno)} · ${_escaparTextoHtml(j.motivo)}</div>
                    ${comentario}${observacion}
                    ${j.revisado_en ? `<small style="display:block;margin-top:5px;color:var(--texto-tenue);">Resuelta: ${_escaparTextoHtml(j.revisado_en)}</small>` : ''}
                    ${nuevaSolicitud}
                </div>
                ${estado}
            </article>`;
        }).join('');
    } catch (error) {
        console.error('[cargarJustificacionesDocente]', error);
        cont.innerHTML = `<div class="historial-vacio" style="color:var(--peligro);">Error cargando justificaciones: ${_escaparTextoHtml(error.message)}</div>`;
    }
}

function _escaparTextoHtml(valor) {
    return String(valor ?? '').replace(/[&<>"']/g, caracter => ({
        '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    })[caracter]);
}

// ── GEOLOCALIZACIÓN para firmas (opcional, no bloqueante) ──
function _capturarUbicacionRapida() {
    return new Promise(resolve => {
        if (!('geolocation' in navigator)) {
            resolve({ lat: null, lng: null, precision: null });
            return;
        }
        let resuelto = false;
        const finish = (datos) => { if (!resuelto) { resuelto = true; resolve(datos); } };
        // Timeout corto de 2.5s para no bloquear la firma si el usuario tarda en aceptar
        setTimeout(() => finish({ lat: null, lng: null, precision: null }), 2500);
        navigator.geolocation.getCurrentPosition(
            (pos) => finish({
                lat: pos.coords.latitude,
                lng: pos.coords.longitude,
                precision: pos.coords.accuracy,
            }),
            () => finish({ lat: null, lng: null, precision: null }),
            { timeout: 2000, maximumAge: 60000, enableHighAccuracy: false }
        );
    });
}

// Teclado físico para el PIN modal
document.addEventListener('keydown', function(e) {
    const modal = document.getElementById('pin-modal-overlay');
    if (!modal || !modal.classList.contains('pin-modal--visible')) return;
    if (e.key >= '0' && e.key <= '9') pinTecla(e.key);
    else if (e.key === 'Backspace') pinBorrar();
    else if (e.key === 'Enter') enviarPinModal();
    else if (e.key === 'Escape') cerrarPinModal();
});

// Reevaluar cada minuto el estado de los botones Firmar para que se habiliten/bloqueen
// automáticamente al entrar/salir del rango horario, sin recargar.
setInterval(() => {
    const panel = document.getElementById('panel-docente');
    if (!panel || panel.style.display === 'none') return;
    const cont = document.getElementById('horario-semanal-list');
    if (!cont || !cont.querySelector('.btn-firmar')) return;
    cargarHorarioSemanal();
}, 60 * 1000);


// ══════════════════════════════════════════════════════════════
// CLASES PENDIENTES DE REGULARIZAR (últimos 7 días sin firma ni justif)
// ══════════════════════════════════════════════════════════════
async function cargarClasesPendientes() {
    const cont = document.getElementById('alerta-pendientes');
    if (!cont) return;
    try {
        const r = await fetch(`/api/docente/pendientes?nombre=${encodeURIComponent(window.SIPA.docenteLogName)}&dias=7`);
        const pendientes = r.ok ? await r.json() : [];
        if (!pendientes.length) { cont.innerHTML = ''; return; }

        const titulo = pendientes.length === 1
            ? `⚠️ Tiene <strong>1 clase</strong> sin registrar`
            : `⚠️ Tiene <strong>${pendientes.length} clases</strong> sin registrar`;

        cont.innerHTML = `
        <div class="alerta-pendientes-card">
            <div class="alerta-pendientes-header">
                <span class="alerta-pendientes-titulo">${titulo} en los últimos 7 días</span>
                <span class="alerta-pendientes-sub">Justifíquelas para regularizar su situación.</span>
            </div>
            <div class="alerta-pendientes-lista">
                ${pendientes.map(_renderClasePendiente).join('')}
            </div>
        </div>`;
    } catch (e) {
        console.error('[cargarClasesPendientes]', e);
        cont.innerHTML = '';
    }
}

function _renderClasePendiente(p) {
    const fechaStr = formatearFechaElegante(p.fecha);
    const horaTxt  = (p.hora_clase || '').replace('-', ' h a ') + ' h';
    const advRech  = p.justif_rechazada
        ? `<div class="pend-rechazada">⚠️ Justificación previa rechazada — debe enviarse una nueva.</div>`
        : '';
    const materiaHtml = (p.materia || '').replace(/"/g,'&quot;');
    return `
    <div class="pend-item">
        <div class="pend-fecha-chip">${p.dia}<br><small>${p.fecha.substring(8,10)}/${p.fecha.substring(5,7)}</small></div>
        <div class="pend-info">
            <div class="pend-materia">${p.materia || '—'}</div>
            <div class="pend-meta">
                <span>🕐 ${horaTxt}</span>
                <span>🏫 Aula <strong>${p.aula}</strong> · ${p.turno}</span>
            </div>
            ${advRech}
        </div>
        <button class="btn-justif-docente pend-btn-justif"
                data-aula="${p.aula}" data-turno="${p.turno}" data-hora="${p.hora_clase||''}"
                data-fecha="${p.fecha}" data-materia="${materiaHtml}"
                onclick="abrirAutoJustif(this)">
            📋 Justificar Ahora
        </button>
    </div>`;
}


// ══════════════════════════════════════════════════════════════
// AUTO-JUSTIFICACIÓN DEL DOCENTE
// ══════════════════════════════════════════════════════════════
let _autoJustifData = null;

function abrirAutoJustif(btn) {
    _autoJustifData = {
        aula:    btn.dataset.aula,
        turno:   btn.dataset.turno,
        hora:    btn.dataset.hora,
        materia: btn.dataset.materia,
        // Si el botón trae data-fecha (de "clases pendientes") la usamos; sino HOY
        fecha:   btn.dataset.fecha || obtenerFechaHoyLocal(),
    };

    const info = document.getElementById('auto-justif-info');
    if (info) {
        info.innerHTML = `
            <strong>${_autoJustifData.materia || 'Clase'}</strong><br>
            Aula ${_autoJustifData.aula} · ${_autoJustifData.turno} · ${formatearFechaElegante(_autoJustifData.fecha)} · ${_autoJustifData.hora}`;
    }
    document.getElementById('auto-justif-motivo').value     = '';
    document.getElementById('auto-justif-comentario').value = '';
    document.getElementById('auto-justif-pass').value       = '';
    document.getElementById('auto-justif-modal').classList.add('justif-modal--visible');
    document.body.style.overflow = 'hidden';
}

function cerrarAutoJustif() {
    document.getElementById('auto-justif-modal').classList.remove('justif-modal--visible');
    document.body.style.overflow = '';
    _autoJustifData = null;
}

async function enviarAutoJustif() {
    if (!_autoJustifData) return;
    const motivo = document.getElementById('auto-justif-motivo').value.trim();
    const coment = document.getElementById('auto-justif-comentario').value.trim();
    const pass   = document.getElementById('auto-justif-pass').value;

    if (!motivo) return mostrarToast('Seleccione un motivo.', 'warning');
    if (!coment) return mostrarToast('El comentario es obligatorio.', 'warning');
    if (!pass)   return mostrarToast('Reingrese su contraseña como firma digital.', 'warning');

    const btn = document.getElementById('auto-justif-btn-enviar');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spin">🔄</span> Enviando…'; }

    try {
        const r = await fetch('/api/docente/justificar', {
            method: 'POST',
            headers: {'Content-Type':'application/json'},
            body: JSON.stringify({
                email:      window.SIPA.docenteLogEmail,
                password:   pass,
                aula:       _autoJustifData.aula,
                turno:      _autoJustifData.turno,
                fecha:      _autoJustifData.fecha,
                motivo, comentario: coment,
            }),
        });
        const d = await r.json();
        if (r.ok) {
            mostrarToast('✅ ' + d.msj, 'success');
            cerrarAutoJustif();
            await cargarClasesPendientes();
            await cargarHorarioSemanal();
            await cargarHistorialFirmasDocente();
            await cargarJustificacionesDocente();
        } else {
            mostrarToast(d.error || 'Error al enviar.', 'error');
        }
    } catch (e) {
        mostrarToast('Error de red: ' + e.message, 'error');
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = '📋 Enviar Justificación'; }
    }
}
