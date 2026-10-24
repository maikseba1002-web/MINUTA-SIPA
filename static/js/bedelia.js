/* ============================================================
   bedelia.js — S.I.P.A. · GNA 2026
   Módulo: Gestión de Bedelía
   ============================================================ */
'use strict';

let _tiposNovedadPromise = null;
let _telegramBedelStatusInterval = null;

function cargarTiposNovedadBedelia() {
    if (!_tiposNovedadPromise) {
        _tiposNovedadPromise = fetch('/api/tipos_novedad')
            .then(r => r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`)))
            .then(data => Array.isArray(data) ? data : [])
            .catch(e => {
                console.error('[tipos_novedad]', e);
                return [];
            });
    }
    return _tiposNovedadPromise;
}

function configurarCausaAusencia(div, causaInicial = '') {
    const select = div.querySelector('.a-causa-select');
    const manual = div.querySelector('.a-causa-otro');
    if (!select || !manual) return;
    const existe = Array.from(select.options).some(o => o.value === causaInicial);
    select.value = causaInicial && existe ? causaInicial : 'OTRO';
    manual.value = !existe && causaInicial ? causaInicial : '';
    manual.style.display = select.value === 'OTRO' ? 'block' : 'none';
    actualizarEstadoJustificacion(div);
}

function actualizarEstadoJustificacion(div) {
    const select = div.querySelector('.a-causa-select');
    const estado = div.querySelector('.a-justificacion-estado');
    if (!select || !estado) return;
    const opcion = select.options[select.selectedIndex];
    let justificada;
    if (div.dataset.justificacionHistorica === 'true') {
        justificada = div.dataset.justificacionHistoricaValor === 'true'
            ? true : div.dataset.justificacionHistoricaValor === 'false' ? false : null;
    } else if (opcion?.dataset.permite === 'false') {
        justificada = false;
    } else {
        justificada = opcion?.dataset.justificada === 'true'
            ? true : opcion?.dataset.justificada === 'false' ? false : null;
    }
    estado.textContent = justificada === true
        ? 'Justificada' : justificada === false ? 'No justificada' : 'Sin definir';
    estado.title = div.dataset.justificacionHistorica === 'true'
        ? 'Clasificación histórica conservada'
        : 'Clasificación automática según la configuración de TIC';
}

async function cargarCausasEnFila(div, causaInicial = '') {
    const select = div.querySelector('.a-causa-select');
    if (!select) return;
    const tipos = await cargarTiposNovedadBedelia();
    select.innerHTML = '<option value="">— Seleccionar motivo —</option>' +
        tipos.map(t => `<option value="${_esc(t.nombre)}" data-permite="${t.permite_justificacion !== false}" data-justificada="${t.justificada_por_defecto === true ? 'true' : t.justificada_por_defecto === false ? 'false' : ''}">${_esc(t.nombre)}</option>`).join('') +
        '<option value="OTRO" data-permite="true" data-justificada="">Otro motivo</option>';
    configurarCausaAusencia(div, causaInicial);
}

function _textoIdentidadAula(aula, turno, info) {
    const base = `📝 Aula ${aula} · ${turno}`;
    if (!info || !info.nombre) return base;
    const detalle = [info.nombre, info.especialidad, info.curso].filter(Boolean).join(' · ');
    return detalle ? `${base} · ${detalle}` : base;
}

async function actualizarVisibilidadTelegramBedel() {
    const panel = document.getElementById('bedel-telegram-vinculacion');
    if (!panel) return;
    panel.style.display = 'none';
    if (!_telegramBedelStatusInterval && window.SIPA?.bedelSesion) {
        _telegramBedelStatusInterval = setInterval(() => {
            if (window.SIPA?.bedelSesion) actualizarVisibilidadTelegramBedel();
        }, 30000);
    }
    try {
        const response = await fetch('/api/bedel/telegram/status');
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        panel.style.display = data.activo ? '' : 'none';
    } catch (error) {
        console.error('[actualizarVisibilidadTelegramBedel]', error);
        panel.style.display = 'none';
    }
}

async function actualizarEstadoCierreBedel() {
    const aviso = document.getElementById('bedel-cierre-aviso');
    const formulario = document.getElementById('bedel-formulario-operativo');
    if (!aviso || !formulario) return;
    const params = new URLSearchParams({
        fecha: document.getElementById('b-fecha').value,
        aula: document.getElementById('b-aula').value,
        turno: document.getElementById('b-turno').value,
    });
    try {
        const response = await fetch(`/api/calendario/estado?${params}`);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        if (data.sin_actividad) {
            aviso.textContent = `📅 ${data.mensaje} No es necesario cargar una minuta ni registrar ausencias de aspirantes o docentes.`;
            aviso.style.display = 'block';
            formulario.style.display = 'none';
        } else {
            aviso.style.display = 'none';
            formulario.style.display = '';
        }
    } catch (error) {
        console.error('[actualizarEstadoCierreBedel]', error);
        aviso.textContent = `⚠️ No se pudo verificar el calendario (${error.message}). Por seguridad, la carga de la planilla queda deshabilitada.`;
        aviso.style.display = 'block';
        formulario.style.display = 'none';
    }
}

// ── VINCULACIÓN TELEGRAM (Bloque 3) ─────────────────────────
async function vincularTelegramBedel() {
    const codigo = (document.getElementById('bedel-tg-codigo').value || '').trim();
    const out    = document.getElementById('bedel-tg-result');
    if (!/^\d{6}$/.test(codigo)) {
        out.innerHTML = '<div class="bd-error-banner">⚠️ Ingresá los 6 dígitos del código.</div>';
        return;
    }
    const sesion = window.SIPA?.bedelSesion;
    if (!sesion?.aula) {
        out.innerHTML = '<div class="bd-error-banner">⚠️ Iniciá sesión primero con tu PIN.</div>';
        return;
    }
    try {
        const r = await fetch('/api/bedel/vincular_telegram', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ codigo, aula: sesion.aula, turno: sesion.turno }),
        });
        const d = await r.json();
        if (d.ok) {
            out.innerHTML = `<div class="bd-ok-banner">✅ ${d.msj}<br><small>Recibí confirmación en tu Telegram.</small></div>`;
            document.getElementById('bedel-tg-codigo').value = '';
            mostrarToast('✅ Telegram vinculado', 'success');
        } else {
            out.innerHTML = `<div class="bd-error-banner">❌ ${d.error}</div>`;
        }
    } catch (e) {
        out.innerHTML = `<div class="bd-error-banner">❌ ${e.message}</div>`;
    }
}

// ── LOGIN MÁGICO (token desde URL) ──────────────────────────
async function intentarLoginMagicoBedel() {
    const params = new URLSearchParams(window.location.search);
    const tok    = params.get('bedel_token');
    if (!tok) return false;
    try {
        const r = await fetch('/api/bedel/login_magic', {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify({ token: tok }),
        });
        const d = await r.json();
        if (d.status === 'ok') {
            // Limpiar URL
            window.history.replaceState({}, '', window.location.pathname);
            // Simular login como bedel
            document.getElementById('login-bedel').style.display = 'none';
            document.getElementById('panel-bedel').style.display  = 'block';
            const hoy = obtenerFechaHoyLocal();
            const fechaEl = document.getElementById('b-fecha');
            fechaEl.value = hoy; fechaEl.min = hoy; fechaEl.max = hoy;
            document.getElementById('b-turno').value = d.turno;
            document.getElementById('b-aula').value  = d.aula;
            const elAula = document.getElementById('bedel-aula-info');
            if (elAula) elAula.textContent = _textoIdentidadAula(d.aula, d.turno, d.aula_info);
            window.SIPA = window.SIPA || {};
            window.SIPA.bedelSesion = { aula: d.aula, turno: d.turno };
            await actualizarVisibilidadTelegramBedel();
            mostrarToast(`🔗 Login mágico OK: Aula ${d.aula} (${d.turno})`, 'success');
            await cargarAspirantesAula(d.aula, d.turno);
            await cargarMaster(d.aula, d.turno);
            await actualizarEstadoCierreBedel();
            return true;
        }
    } catch (e) {
        console.warn('Login mágico falló:', e);
    }
    return false;
}
// Auto-ejecutar al cargar la página si hay token en URL
if (typeof window !== 'undefined') {
    document.addEventListener('DOMContentLoaded', intentarLoginMagicoBedel);
}

// ── LOGIN CON PIN ─────────────────────────────────────────
async function ingresarBedel() {
    const pin = document.getElementById('pass-bedel').value.trim();
    if (!pin) return mostrarToast('Ingrese el PIN de seguridad.', 'warning');

    const btn = document.querySelector('#login-bedel .btn-primary');
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spin">🔄</span> Verificando…'; }

    try {
        const res = await fetch('/api/validar_pin', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ pin }),
        });
        if (res.ok) {
            const data = await res.json();
            document.getElementById('login-bedel').style.display = 'none';
            document.getElementById('panel-bedel').style.display  = 'block';
            // Fecha bloqueada al día actual: value + min + max iguales para que ni
            // siquiera se pueda cambiar desde el picker del celular
            const hoy = obtenerFechaHoyLocal();
            const fechaEl = document.getElementById('b-fecha');
            fechaEl.value = hoy;
            fechaEl.min   = hoy;
            fechaEl.max   = hoy;
            document.getElementById('b-turno').value = data.turno;
            document.getElementById('b-aula').value  = data.aula;
            document.getElementById('pass-bedel').value = '';
            // Header de sesión
            const elAula = document.getElementById('bedel-aula-info');
            if (elAula) elAula.textContent = _textoIdentidadAula(data.aula, data.turno, data.aula_info);
            const elFecha = document.getElementById('bedel-fecha-info');
            if (elFecha) elFecha.textContent = `Sesión iniciada · ${new Date().toLocaleString('es-AR', {weekday:'long', day:'2-digit', month:'2-digit', year:'numeric', hour:'2-digit', minute:'2-digit'})}`;
            // Guardar info de aula para cerrar sesión
            window.SIPA.bedelSesion = { aula: data.aula, turno: data.turno, pin };

            await actualizarVisibilidadTelegramBedel();
            mostrarToast(`Autenticado: Aula ${data.aula} (${data.turno})`, 'success');
            await cargarAspirantesAula(data.aula, data.turno);
            await cargarMaster(data.aula, data.turno);
            await actualizarEstadoCierreBedel();
            const cod = document.getElementById('bedel-tg-codigo');
            if (cod) cod.value = '';
        } else {
            const err = await res.json();
            mostrarToast(err.error || 'PIN no válido', 'error');
        }
    } catch { mostrarToast('Error de red con el servidor.', 'error'); }
    finally {
        if (btn) { btn.disabled = false; btn.innerHTML = '🔓 Desbloquear Planilla'; }
    }
}

// ── CERRAR SESIÓN DE BEDELÍA ─────────────────────────────────
function _cerrarSesionBedelSilent() {
    // Versión sin confirm/toast — usada cuando "Volver al Inicio" ya confirmó
    document.getElementById('panel-bedel').style.display = 'none';
    document.getElementById('login-bedel').style.display  = 'block';
    ['b-fecha','b-turno','b-aula','b-fe','b-pres','b-aus-cant','b-nov'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = el.type === 'number' ? '0' : '';
    });
    const bd = document.getElementById('body-diario');     if (bd) bd.innerHTML = '';
    const al = document.getElementById('ausentes-list');   if (al) al.innerHTML = '';
    const aviso = document.getElementById('bedel-cierre-aviso');
    const formulario = document.getElementById('bedel-formulario-operativo');
    if (aviso) aviso.style.display = 'none';
    if (formulario) formulario.style.display = '';
    window.SIPA.bedelSesion = null;
    if (_telegramBedelStatusInterval) {
        clearInterval(_telegramBedelStatusInterval);
        _telegramBedelStatusInterval = null;
    }
}

function cerrarSesionBedel() {
    if (!confirm('¿Cerrar la sesión de Bedelía? Se perderán los datos no guardados de la planilla.')) return;
    document.getElementById('panel-bedel').style.display = 'none';
    document.getElementById('login-bedel').style.display  = 'block';
    // Limpiar campos para que la próxima sesión arranque limpia
    ['b-fecha','b-turno','b-aula','b-fe','b-pres','b-aus-cant','b-nov'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.value = el.type === 'number' ? '0' : '';
    });
    document.getElementById('body-diario').innerHTML  = '';
    document.getElementById('ausentes-list').innerHTML = '';
    const aviso = document.getElementById('bedel-cierre-aviso');
    const formulario = document.getElementById('bedel-formulario-operativo');
    if (aviso) aviso.style.display = 'none';
    if (formulario) formulario.style.display = '';
    window.SIPA.bedelSesion = null;
    if (_telegramBedelStatusInterval) {
        clearInterval(_telegramBedelStatusInterval);
        _telegramBedelStatusInterval = null;
    }
    mostrarToast('🚪 Sesión de Bedelía cerrada', 'info');
}

// ── CARGA DE ASPIRANTES ───────────────────────────────────
async function cargarAspirantesAula(aula, turno) {
    if (!aula) return;
    try {
        const res = await fetch(`/api/aspirantes?aula=${encodeURIComponent(aula)}&turno=${encodeURIComponent(turno)}`);
        window.SIPA.aspirantesDelAula = await res.json();
        _renderizarSelectsAutoridades();
        // Actualizar selects de ausentes ya existentes
        document.querySelectorAll('.a-select-container .a-nombre-select').forEach(sel => {
            llenarSelectAspirantes(sel);
        });
        recalcularNumeros();
    } catch { mostrarToast('Error cargando el padrón oficial', 'error'); }
}

function _renderizarSelectsAutoridades() {
    const asp      = window.SIPA.aspirantesDelAula;
    const contBedel = document.getElementById('container-bedel');
    const contSub   = document.getElementById('container-subbedel');

    if (asp.length > 0) {
        const opciones = '<option value="">— Seleccionar Padrón —</option>' +
            asp.map(a => `<option value="${a.grado} ${a.nombre}">${a.grado} ${a.nombre}</option>`).join('');
        contBedel.innerHTML = `<select id="b-bedel-select">${opciones}</select>`;
        contSub.innerHTML   = `<select id="b-subbedel-select">${opciones}</select>`;
    } else {
        const gradoOpts = '<option>ASP III AÑO</option><option>ASP II AÑO</option><option>ASP I AÑO</option>';
        contBedel.innerHTML = `<div style="display:flex;gap:5px;">
            <select id="b-bedel-grado" style="width:36%;">${gradoOpts}</select>
            <input type="text" id="b-bedel-nombre" placeholder="Apellido (Manual)" style="width:64%;">
        </div>`;
        contSub.innerHTML = `<div style="display:flex;gap:5px;">
            <select id="b-subbedel-grado" style="width:36%;">${gradoOpts}</select>
            <input type="text" id="b-subbedel-nombre" placeholder="Apellido (Manual)" style="width:64%;">
        </div>`;
    }
}

// ── CARGA DEL CRONOGRAMA (cargarMaster) ───────────────────
function _mostrarCoberturasBedel(items) {
    const cont = document.getElementById('bedel-coberturas-lista');
    if (!cont) return;
    if (!items.length) {
        cont.innerHTML = '';
        return;
    }
    cont.innerHTML = `<div class="card" style="border-left:4px solid #7c3aed;background:#faf5ff;">
        <strong style="color:#6d28d9;">Solicitudes y coberturas PGNP</strong>
        ${items.map(item => `<div style="margin-top:9px;padding-top:8px;border-top:1px solid #e9d5ff;">
            <strong>${_esc(item.materia)}</strong> · ${_esc(item.hora)}<br>
            Titular: ${_esc(item.titular)}${item.pgnp ? ` · Reemplaza: <strong>PGNP ${_esc(item.pgnp)}</strong>` : ''}<br>
            <span class="badge-mini ${item.estado === 'completada' ? 'badge-mini-verde' : 'badge-mini-naranja'}">
                ${item.estado === 'solicitada'
                    ? 'Enviada a Plana Mayor · pendiente de autorización'
                    : item.estado === 'completada'
                        ? `Firmada ${_esc(item.firmado_en || '')}`
                        : 'Autorizada · firma pendiente'}
            </span>
        </div>`).join('')}
    </div>`;
}

function _prepararSolicitudCoberturaBedel(dataConfig, diaSeleccionado, fecha) {
    const panel = document.getElementById('bedel-solicitar-cobertura');
    const selector = document.getElementById('bedel-cobertura-clase');
    const formulario = document.getElementById('bedel-cobertura-solicitud-formulario');
    const avisoPin = document.getElementById('bedel-cobertura-pin-aviso');
    if (!panel || !selector || !formulario || !avisoPin) return;
    const sesion = window.SIPA?.bedelSesion;
    if (!sesion) {
        panel.style.display = 'none';
        return;
    }
    panel.style.display = '';
    formulario.style.display = sesion.pin ? '' : 'none';
    avisoPin.style.display = sesion.pin ? 'none' : '';
    const clases = (Array.isArray(dataConfig) ? dataConfig : [])
        .filter(b => b && b.dia === diaSeleccionado && b.hora && b.asig && b.doc);
    window.SIPA.clasesCoberturaBedel = clases;
    selector.innerHTML = clases.length
        ? '<option value="">— Seleccione la clase del docente ausente —</option>' +
            clases.map((b, i) => `<option value="${i}">${_esc(b.hora)} · ${_esc(b.asig)} · ${_esc(b.doc)}</option>`).join('')
        : '<option value="">No hay clases oficiales para esta fecha</option>';
    selector.disabled = !clases.length || fecha !== obtenerFechaHoyLocal();
}

async function cargarMaster(aula, turno) {
    const tbody = document.getElementById('body-diario');
    if (tbody) tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;padding:24px;color:var(--texto-tenue);"><span class="spin">🔄</span> Cargando cronograma…</td></tr>`;

    const fecha = document.getElementById('b-fecha').value || obtenerFechaHoyLocal();
    if (!document.getElementById('b-fecha').value) {
        document.getElementById('b-fecha').value = fecha;
    }
    const [y, m, d] = fecha.split('-');
    const dias = ['Domingo','Lunes','Martes','Miércoles','Jueves','Viernes','Sábado'];
    const diaSeleccionado = dias[new Date(parseInt(y), parseInt(m)-1, parseInt(d)).getDay()];

    try {
        const [resConfig, resMinutas, resCoberturas, resAdelantos] = await Promise.all([
            fetch(`/api/config_aula/${encodeURIComponent(aula)}/${encodeURIComponent(turno)}`),
            fetch('/api/minutas'),
            fetch(`/api/coberturas/aula?fecha=${encodeURIComponent(fecha)}&aula=${encodeURIComponent(aula)}&turno=${encodeURIComponent(turno)}`),
            fetch(`/api/adelantos-horario/dia?fecha=${encodeURIComponent(fecha)}&aula=${encodeURIComponent(aula)}&turno=${encodeURIComponent(turno)}`),
        ]);

        if (!resConfig.ok) {
            const er = await resConfig.json().catch(()=>({}));
            mostrarToast('Error cargando cronograma del aula: ' + (er.error || resConfig.status), 'error');
        }
        if (!resMinutas.ok) {
            const er = await resMinutas.json().catch(()=>({}));
            mostrarToast('Error cargando minutas: ' + (er.error || resMinutas.status), 'error');
        }
        if (!resAdelantos.ok) {
            const er = await resAdelantos.json().catch(() => ({}));
            throw new Error(`No se pudieron consultar adelantos de horario: ${er.error || resAdelantos.status}`);
        }

        const dataConfig   = resConfig.ok  ? await resConfig.json()  : [];
        const todasMinutas = resMinutas.ok ? await resMinutas.json() : [];
        const cambiosAdelanto = await resAdelantos.json();
        let coberturas = [];
        if (resCoberturas.ok) {
            coberturas = await resCoberturas.json();
        } else {
            const error = await resCoberturas.json().catch(() => ({}));
            console.error('[cargarMaster] No se pudieron cargar coberturas:', error.error || resCoberturas.status);
            const cont = document.getElementById('bedel-coberturas-lista');
            if (cont) cont.innerHTML = `<div class="bd-error-banner">No se pudieron consultar las coberturas autorizadas (${_esc(error.error || resCoberturas.status)}).</div>`;
        }
        if (resCoberturas.ok) _mostrarCoberturasBedel(Array.isArray(coberturas) ? coberturas : []);
        const minutaExist  = Array.isArray(todasMinutas)
            ? todasMinutas.find(mx => mx.aula === aula && mx.fecha === fecha && mx.turno === turno)
            : null;

        const tbody = document.getElementById('body-diario');
        tbody.innerHTML = '';
        document.getElementById('ausentes-list').innerHTML = '';

        const scheduleGuardado = Array.isArray(minutaExist?.schedule) ? minutaExist.schedule : [];

        if (minutaExist) {
            // Rellenar campos guardados
            document.getElementById('b-pres').value     = minutaExist.presentes    || 0;
            document.getElementById('b-aus-cant').value = minutaExist.cant_ausentes || 0;
            document.getElementById('b-nov').value      = minutaExist.novedades    || '';

            const bSel = document.getElementById('b-bedel-select');
            if (bSel) bSel.value = minutaExist.bedel || '';
            else if (document.getElementById('b-bedel-nombre'))
                document.getElementById('b-bedel-nombre').value = minutaExist.bedel || '';

            const sSel = document.getElementById('b-subbedel-select');
            if (sSel) sSel.value = minutaExist.sub_bedel || '';
            else if (document.getElementById('b-subbedel-nombre'))
                document.getElementById('b-subbedel-nombre').value = minutaExist.sub_bedel || '';

            if (minutaExist.ausentes) {
                minutaExist.ausentes.forEach(a => {
                    const esManual = !window.SIPA.aspirantesDelAula.some(asp => asp.nombre === a.nombre);
                    const justificacion = Object.prototype.hasOwnProperty.call(a, 'es_justificada')
                        ? a.es_justificada : null;
                    addAusenteRow(a.nombre, a.causa, esManual, justificacion);
                });
            }
        } else {
            recalcularNumeros();
        }

        // Materias del día: si la minuta guardada tiene schedule, usar ése.
        // Si no, cargar el cronograma maestro del día (siempre se ve algo).
        const clasesBase = scheduleGuardado.length > 0
            ? scheduleGuardado.map(h => ({...h}))
            : (Array.isArray(dataConfig) ? dataConfig : [])
                .filter(h => h.dia === diaSeleccionado)
                .map(h => ({...h, estado: 'A'}));
        const retiradas = Array.isArray(cambiosAdelanto.retiradas) ? cambiosAdelanto.retiradas : [];
        const incorporadas = Array.isArray(cambiosAdelanto.incorporadas) ? cambiosAdelanto.incorporadas : [];
        const clasesDia = clasesBase.filter(clase => !retiradas.some(cambio =>
            _normalizarTextoClase(clase.doc) === _normalizarTextoClase(cambio.docente)
            && _normalizarTextoClase(clase.asig) === _normalizarTextoClase(cambio.materia)
            && _normalizarHoraClase(clase.hora) === _normalizarHoraClase(cambio.hora)
        ));
        incorporadas.forEach(cambio => {
            clasesDia.push({
                dia: diaSeleccionado, hora: cambio.hora, asig: cambio.materia,
                doc: cambio.docente, estado: 'A', adelanto: true,
            });
        });
        if (clasesDia.length > 0) {
            clasesDia.forEach(h => _appendFilaDiaria(h.hora, h.asig, h.doc, h.estado, h.adelanto));
        } else {
            tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--texto-tenue);padding:30px;">
                Sin materias asignadas para ${diaSeleccionado} en el cronograma. Puede anexar materias manualmente.
            </td></tr>`;
        }
        const clasesCobertura = (Array.isArray(dataConfig) ? dataConfig : [])
            .filter(h => h.dia === diaSeleccionado)
            .filter(h => !retiradas.some(cambio =>
                _normalizarTextoClase(h.doc) === _normalizarTextoClase(cambio.docente)
                && _normalizarTextoClase(h.asig) === _normalizarTextoClase(cambio.materia)
                && _normalizarHoraClase(h.hora) === _normalizarHoraClase(cambio.hora)
            ))
            .concat(incorporadas.map(cambio => ({
                dia: diaSeleccionado, hora: cambio.hora, asig: cambio.materia, doc: cambio.docente,
            })));
        _prepararSolicitudCoberturaBedel(clasesCobertura, diaSeleccionado, fecha);
    } catch (e) {
        console.error('Error en cargarMaster:', e);
        const tb = document.getElementById('body-diario');
        if (tb) tb.innerHTML = `<tr><td colspan="4" style="text-align:center;color:var(--peligro);padding:24px;">
            ⚠️ Error de conexión al cargar: ${e.message}
        </td></tr>`;
        mostrarToast('No se pudo cargar el cronograma: ' + e.message, 'error');
    }
}

async function solicitarCoberturaBedel() {
    const sesion = window.SIPA?.bedelSesion;
    if (!sesion?.pin) {
        mostrarToast('Inicie sesión con el PIN diario para solicitar una cobertura.', 'warning');
        return;
    }
    const selector = document.getElementById('bedel-cobertura-clase');
    const motivoEl = document.getElementById('bedel-cobertura-motivo');
    const clase = selector?.value
        ? window.SIPA.clasesCoberturaBedel?.[Number(selector.value)]
        : null;
    const motivo = motivoEl?.value.trim() || '';
    if (!clase) {
        mostrarToast('Seleccione una clase oficial del cronograma.', 'warning');
        return;
    }
    if (!motivo) {
        mostrarToast('Indique el motivo de la solicitud.', 'warning');
        motivoEl?.focus();
        return;
    }
    try {
        const response = await fetch('/api/bedel/coberturas/solicitar', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pin: sesion.pin,
                aula: sesion.aula,
                turno: sesion.turno,
                fecha: document.getElementById('b-fecha').value,
                titular: clase.doc,
                materia: clase.asig,
                hora: clase.hora,
                motivo,
            }),
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
        mostrarToast(data.msj || 'Solicitud enviada a Plana Mayor.', 'success');
        selector.value = '';
        motivoEl.value = '';
        try {
            const consulta = await fetch(
                `/api/coberturas/aula?fecha=${encodeURIComponent(document.getElementById('b-fecha').value)}&aula=${encodeURIComponent(sesion.aula)}&turno=${encodeURIComponent(sesion.turno)}`
            );
            if (!consulta.ok) {
                const error = await consulta.json().catch(() => ({}));
                throw new Error(error.error || `HTTP ${consulta.status}`);
            }
            _mostrarCoberturasBedel(await consulta.json());
        } catch (error) {
            console.error('[solicitarCoberturaBedel] Solicitud enviada, pero no se pudo actualizar el listado:', error);
        }
    } catch (error) {
        mostrarToast(`No se pudo solicitar la cobertura: ${error.message}`, 'error');
    }
}

// ── TABLA DE MATERIAS ─────────────────────────────────────
function _appendFilaDiaria(hora, asig, doc, estado = 'A', adelanto = false) {
    const tbody = document.getElementById('body-diario');
    const pSel  = estado === 'P' ? 'selected' : '';
    const aSel  = estado === 'A' ? 'selected' : '';
    const tr = document.createElement('tr');
    tr.innerHTML = `
        <td><input type="text" value="${hora}" readonly style="background:transparent;border:none;padding:0;">${adelanto ? '<small class="badge-mini">⏩ Adelantada</small>' : ''}</td>
        <td><input type="text" value="${asig}" readonly style="background:transparent;border:none;padding:0;"></td>
        <td><input type="text" value="${doc}"  readonly style="background:transparent;border:none;padding:0;"></td>
        <td><select class="b-pres inline-select">
            <option value="P" ${pSel}>✅ Presente</option>
            <option value="A" ${aSel}>❌ Ausente</option>
        </select></td>`;
    tbody.appendChild(tr);
}

function _normalizarTextoClase(valor) {
    return String(valor || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim().toLowerCase();
}

function _normalizarHoraClase(valor) {
    const partes = String(valor || '').split(/[-–—]/);
    if (partes.length !== 2) return String(valor || '').replace(/\s/g, '').toLowerCase();
    return partes.map(parte => {
        const digitos = parte.replace(/\D/g, '').padStart(4, '0');
        return digitos.length === 4 ? `${digitos.slice(0, 2)}:${digitos.slice(2)}` : digitos;
    }).join('-');
}

function addFilaExtraDiaria() {
    const tbody = document.getElementById('body-diario');
    if (tbody.querySelector('td[colspan]')) tbody.innerHTML = '';
    const tr = document.createElement('tr');
    tr.innerHTML = `
        <td><input type="text" placeholder="Ej: 0720-0820" style="padding:8px;min-width:110px;"></td>
        <td><input type="text" placeholder="Materia" style="padding:8px;"></td>
        <td><input type="text" placeholder="Docente" style="padding:8px;"></td>
        <td><select class="b-pres inline-select">
            <option value="P">✅ Presente</option>
            <option value="A" selected>❌ Ausente</option>
        </select></td>`;
    tbody.appendChild(tr);
}

// ── GESTIÓN DE AUSENTES ───────────────────────────────────
function llenarSelectAspirantes(selectEl, valorSeleccionado = '') {
    const asp = window.SIPA.aspirantesDelAula;
    if (!asp || asp.length === 0) {
        selectEl.innerHTML = '<option value="">— Sin padrón. Use ingreso manual —</option>';
        selectEl.disabled  = true;
        return;
    }
    selectEl.disabled = false;
    selectEl.innerHTML = '<option value="">— Seleccionar Padrón —</option>' +
        asp.map(a => {
            const val  = `${a.grado} ${a.nombre}`;
            const sel  = (val === valorSeleccionado || a.nombre === valorSeleccionado) ? 'selected' : '';
            return `<option value="${val}" data-grado="${a.grado}" data-nombre="${a.nombre}" ${sel}>${val}</option>`;
        }).join('');
}

/**
 * Añade fila de ausente.
 * @param {string}  nombre   - Nombre a preseleccionar
 * @param {string}  causa    - Causal
 * @param {boolean} isManual - Si true muestra input manual en lugar del select
 * @param {boolean|null|undefined} esJustificada - Clasificación histórica; undefined para una nueva ausencia
 */
function addAusenteRow(nombre = '', causa = '', isManual = false, esJustificada = undefined) {
    const gradoOpts = ['ASP III AÑO','ASP II AÑO','ASP I AÑO','ASPIGEN']
        .map(g => `<option>${g}</option>`).join('');

    const div = document.createElement('div');
    div.className = 'a-select-container grid';
    // compatibilidad con el estilo inline del HTML original
    div.style.cssText = 'background:#f8fafc;padding:15px;border:1px solid #e2e8f0;border-radius:8px;align-items:center;margin-bottom:12px;transition:all 0.2s;';

    div.innerHTML = `
        <div style="display:flex;gap:8px;grid-column:span 1;">
            <select class="a-tipo" style="width:25%;display:${isManual?'block':'none'};">${gradoOpts}</select>
            <select class="a-nombre-select" style="display:${isManual?'none':'block'};flex:1;" onchange="recalcularNumeros()"></select>
            <input  class="a-nombre-input" type="text" value="${_esc(nombre)}" placeholder="Apellido (Manual)"
                    style="display:${isManual?'block':'none'};flex:1;" oninput="recalcularNumeros()">
            <button type="button" class="btn btn-warning toggle-manual-btn" style="padding:10px;" title="Carga Manual">✍️</button>
        </div>
        <div style="display:flex;gap:8px;grid-column:span 1;align-items:center;flex-wrap:wrap;">
            <select class="a-causa-select" style="flex:1;min-width:170px;">
                <option value="">Cargando motivos…</option>
                <option value="OTRO">Otro motivo</option>
            </select>
            <input type="text" class="a-causa-otro" value="" placeholder="Escriba el motivo"
                   style="display:none;flex:1;min-width:170px;">
            <span class="a-justificacion-estado" style="white-space:nowrap;font-size:.84em;color:var(--texto-suave);"></span>
            <button type="button" class="btn btn-danger" style="padding:10px;"
                onclick="this.closest('.a-select-container').remove();recalcularNumeros();">✖</button>
        </div>`;

    document.getElementById('ausentes-list').appendChild(div);

    const selectEl = div.querySelector('.a-nombre-select');
    const inputEl  = div.querySelector('.a-nombre-input');
    const tipoEl   = div.querySelector('.a-tipo');
    if (esJustificada !== undefined) {
        div.dataset.justificacionHistorica = 'true';
        div.dataset.justificacionHistoricaValor = esJustificada === null ? '' : String(esJustificada);
    }

    llenarSelectAspirantes(selectEl, nombre);
    cargarCausasEnFila(div, causa);
    div.querySelector('.a-causa-select').addEventListener('change', () => {
        const manual = div.querySelector('.a-causa-otro');
        manual.style.display = div.querySelector('.a-causa-select').value === 'OTRO' ? 'block' : 'none';
        if (div.querySelector('.a-causa-select').value !== 'OTRO') manual.value = '';
        actualizarEstadoJustificacion(div);
    });

    div.querySelector('.toggle-manual-btn').addEventListener('click', function () {
        if (selectEl.style.display === 'none') {
            selectEl.style.display = 'block';
            inputEl.style.display  = 'none';
            tipoEl.style.display   = 'none';
        } else {
            selectEl.style.display = 'none';
            inputEl.style.display  = 'block';
            tipoEl.style.display   = 'block';
            inputEl.focus();
        }
        recalcularNumeros();
    });

    recalcularNumeros();
}

function _esc(s) {
    return String(s || '')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}

// ── RECALCULAR FE / PRESENTES / AUSENTES ─────────────────
function recalcularNumeros() {
    const feInput   = document.getElementById('b-fe');
    const presInput = document.getElementById('b-pres');
    const ausInput  = document.getElementById('b-aus-cant');
    if (!feInput) return;

    let ausentesTotal = 0, manualesExtra = 0;
    document.querySelectorAll('#ausentes-list .a-select-container').forEach(div => {
        const sel   = div.querySelector('.a-nombre-select');
        const input = div.querySelector('.a-nombre-input');
        if (!sel || !input) return;
        if (sel.style.display !== 'none') {
            if (sel.value && sel.value !== '') ausentesTotal++;
        } else {
            if (input.value.trim() !== '') { ausentesTotal++; manualesExtra++; }
        }
    });

    const asp = window.SIPA.aspirantesDelAula;
    if (asp.length > 0) {
        feInput.readOnly = true;
        const feReal = asp.length + manualesExtra;
        feInput.value   = feReal;
        ausInput.value  = ausentesTotal;
        presInput.value = Math.max(0, feReal - ausentesTotal);
    } else {
        feInput.readOnly = false;
        const fe = parseInt(feInput.value) || 0;
        ausInput.value  = ausentesTotal;
        presInput.value = Math.max(0, fe - ausentesTotal);
    }
}

// ── OBTENER VALOR BEDEL ───────────────────────────────────
function _obtenerValorBedel(tipo) {
    const sel = document.getElementById(`b-${tipo}-select`);
    if (sel) return sel.value;
    const g = document.getElementById(`b-${tipo}-grado`);
    const n = document.getElementById(`b-${tipo}-nombre`);
    const gVal = g ? g.value : '';
    const nVal = n ? n.value.trim() : '';
    return nVal ? `${gVal} ${nVal}` : gVal;
}

// ── ENVÍO DE PLANILLA ─────────────────────────────────────
async function enviarPlanilla(wpp) {
    const tbody  = document.getElementById('body-diario');
    let schedule = [];

    if (!tbody.querySelector('td[colspan]')) {
        schedule = Array.from(document.querySelectorAll('#body-diario tr')).map(tr => {
            const getV = (i) => {
                const inp = tr.cells[i]?.querySelector('input');
                return inp ? inp.value : (tr.cells[i]?.textContent || '');
            };
            return {
                hora:   getV(0),
                asig:   getV(1),
                doc:    getV(2),
                estado: tr.querySelector('.b-pres')?.value || 'A',
            };
        }).filter(s => s.hora || s.asig);
    }

    const ausentes = Array.from(document.querySelectorAll('#ausentes-list div.a-select-container')).map(div => {
        const sel   = div.querySelector('.a-nombre-select');
        let nombre  = '', tipo = 'ASP';
        if (sel && sel.style.display !== 'none') {
            const opt = sel.options[sel.selectedIndex];
            if (opt && opt.value && !opt.text.includes('Sin padrón')) {
                nombre = opt.getAttribute('data-nombre') || opt.text;
                tipo   = opt.getAttribute('data-grado')  || tipo;
            }
        } else {
            nombre = div.querySelector('.a-nombre-input')?.value.trim() || '';
            tipo   = div.querySelector('.a-tipo')?.value || tipo;
        }
        const causaSelect = div.querySelector('.a-causa-select');
        const causaOtro = div.querySelector('.a-causa-otro');
        const causaSeleccionada = causaSelect?.value || '';
        const causaManual = causaOtro?.value.trim() || '';
        return {
            tipo, nombre,
            causa: causaSeleccionada === 'OTRO' ? causaManual : causaSeleccionada,
            causa_tipo: causaSeleccionada,
            causa_detalle: causaSeleccionada === 'OTRO' ? causaManual : '',
        };
    }).filter(a => a.nombre);

    const data = {
        aula:          document.getElementById('b-aula').value.trim(),
        fecha:         document.getElementById('b-fecha').value,
        turno:         document.getElementById('b-turno').value,
        bedel:         _obtenerValorBedel('bedel'),
        sub_bedel:     _obtenerValorBedel('subbedel'),
        fe:            document.getElementById('b-fe').value,
        presentes:     document.getElementById('b-pres').value,
        cant_ausentes: document.getElementById('b-aus-cant').value,
        schedule, ausentes,
        novedades: document.getElementById('b-nov').value,
    };

    if (!data.aula || !data.fecha) return mostrarToast('Error: faltan datos del aula.', 'warning');

    const btns = document.querySelectorAll('#panel-bedel .btn-primary, #panel-bedel .btn-whatsapp');
    btns.forEach(b => b.disabled = true);

    try {
        const res = await fetch('/api/minutas', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        });
        const resp = await res.json();
        if (res.ok) {
            if (wpp) enviarMensajeWhatsApp(data);
            else     mostrarToast('✅ Planilla Oficial Registrada exitosamente.', 'success');
        } else {
            mostrarToast(resp.error || 'Error al guardar la planilla.', 'error');
        }
    } catch { mostrarToast('Fallo al remitir la planilla al servidor.', 'error'); }
    finally  { btns.forEach(b => b.disabled = false); }
}

// ── WHATSAPP ──────────────────────────────────────────────
function enviarMensajeWhatsApp(datos) {
    let texto = `*📌 PARTE DIARIO — AULA ${datos.aula} (${datos.turno})*\n`;
    texto += `📅 *Fecha:* ${formatearFechaElegante(datos.fecha)}\n`;
    texto += `👤 *Bedel:* ${datos.bedel}\n`;
    if (datos.sub_bedel && datos.sub_bedel.trim() && datos.sub_bedel !== 'ASP')
        texto += `👤 *Sub-Bedel:* ${datos.sub_bedel}\n`;
    texto += `━━━━━━━━━━━━━━━━━━━━━━━\n`;
    texto += `📊 *ESTADÍSTICA:*\n• F.E.: ${datos.fe}  |  Presentes: ${datos.presentes}  |  Ausentes: ${datos.cant_ausentes}\n\n`;
    if (datos.ausentes && datos.ausentes.length > 0) {
        texto += `🚫 *NÓMINA DE AUSENTES:*\n`;
        datos.ausentes.forEach(a => { texto += `• ${a.tipo} ${a.nombre} — ${a.causa || 'S/C'}\n`; });
        texto += '\n';
    } else { texto += `✅ *Personal Ausente:* Sin Novedad\n\n`; }
    if (datos.schedule) {
        const pAus = datos.schedule.filter(s => s.estado === 'A' && s.doc && s.doc.trim());
        if (pAus.length > 0) {
            texto += `👨‍🏫 *DOCENTES AUSENTES:*\n`;
            pAus.forEach(p => { texto += `• ${p.doc} (${p.asig})\n`; });
            texto += '\n';
        }
    }
    texto += `📝 *NOVEDADES:*\n${datos.novedades || 'Sin Novedad.'}\n\n`;
    texto += `_Enviado desde S.I.P.A. — Gendarmería Nacional_`;
    window.open('https://api.whatsapp.com/send?text=' + encodeURIComponent(texto), '_blank');
}
