/* ============================================================
   main.js — S.I.P.A. · GNA 2026
   Utilidades globales: reloj, navegación, toast, fecha
   ============================================================ */
'use strict';

// ── PWA: Service Worker + prompt de instalación ──────────────
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/service-worker.js', { scope: '/' })
            .then(reg => console.log('[SIPA] Service Worker activo. scope:', reg.scope))
            .catch(err => console.warn('[SIPA] Service Worker no registrado:', err));
    });
}

let _sipaDeferredInstallPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {
    // Evitar el prompt automático del navegador, lo controlamos manualmente
    e.preventDefault();
    _sipaDeferredInstallPrompt = e;
    _mostrarBotonInstalar();
});
window.addEventListener('appinstalled', () => {
    _sipaDeferredInstallPrompt = null;
    _ocultarBotonInstalar();
    if (typeof mostrarToast === 'function')
        mostrarToast('✅ SIPA instalado en este dispositivo.', 'success');
});

function _mostrarBotonInstalar() {
    if (document.getElementById('pwa-install-btn')) return;
    const btn = document.createElement('button');
    btn.id = 'pwa-install-btn';
    btn.className = 'pwa-install-btn';
    btn.innerHTML = '📲 Instalar SIPA';
    btn.title = 'Instalar SIPA como aplicación en este dispositivo';
    btn.onclick = async () => {
        if (!_sipaDeferredInstallPrompt) return;
        _sipaDeferredInstallPrompt.prompt();
        const choice = await _sipaDeferredInstallPrompt.userChoice;
        if (choice.outcome === 'accepted') _ocultarBotonInstalar();
        _sipaDeferredInstallPrompt = null;
    };
    document.body.appendChild(btn);
}
function _ocultarBotonInstalar() {
    document.getElementById('pwa-install-btn')?.remove();
}

// ── TEMA CLARO / OSCURO ──────────────────────────────────────
// Preferencia guardada en localStorage (por defecto claro).
function aplicarTema(modo) {
    const root = document.documentElement;
    if (modo !== 'dark') modo = 'light';
    if (modo === 'dark') root.setAttribute('data-theme', 'dark');
    else                 root.removeAttribute('data-theme');
    localStorage.setItem('sipa_theme', modo);
    _actualizarBotonTema(modo);
}

function _actualizarBotonTema(modo) {
    const btn = document.getElementById('theme-toggle-btn');
    if (!btn) return;
    btn.textContent = modo === 'dark' ? '🌙' : '☀️';
    btn.title = `Tema: ${modo === 'dark' ? 'oscuro' : 'claro'} (click para cambiar)`;
}

function _toggleTema() {
    aplicarTema(localStorage.getItem('sipa_theme') === 'dark' ? 'light' : 'dark');
}

function _instalarBotonTema() {
    if (document.getElementById('theme-toggle-btn')) return;
    const btn = document.createElement('button');
    btn.id = 'theme-toggle-btn';
    btn.className = 'theme-toggle';
    btn.onclick = _toggleTema;
    // Preferir el slot dentro de la top-bar; sino fallback al body
    const slot = document.getElementById('theme-toggle-slot');
    if (slot) slot.appendChild(btn);
    else      document.body.appendChild(btn);
    aplicarTema(localStorage.getItem('sipa_theme'));
}

// ── ESTADO GLOBAL (reemplaza variables sueltas del HTML original) ──
window.SIPA = {
    globalMinutas:      [],
    aspirantesDelAula:  [],
    configuracionAulas: [],
    docenteLogName:     '',
    suToken:            localStorage.getItem('sipa_su_token')    || null,
    adminToken:         localStorage.getItem('sipa_admin_token') || null,
};

// ── SUPER USUARIO (TIC) ──────────────────────────────────
function abrirModalSU() {
    document.getElementById('su-modal-overlay').classList.add('justif-modal--visible');
    document.body.style.overflow = 'hidden';
    setTimeout(() => document.getElementById('su-password')?.focus(), 80);
    const err = document.getElementById('su-error');
    if (err) { err.style.display = 'none'; err.textContent = ''; }
}
function cerrarModalSU() {
    document.getElementById('su-modal-overlay').classList.remove('justif-modal--visible');
    document.body.style.overflow = '';
    const pwd = document.getElementById('su-password');
    if (pwd) pwd.value = '';
}
async function ingresarSU() {
    const pwd = document.getElementById('su-password').value;
    const err = document.getElementById('su-error');
    if (!pwd) {
        err.textContent = 'Ingrese la clave.';
        err.style.display = 'block';
        return;
    }
    try {
        const r = await fetch('/api/su/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ password: pwd }),
        });
        const d = await r.json();
        if (r.ok && d.token) {
            window.SIPA.suToken = d.token;
            localStorage.setItem('sipa_su_token', d.token);
            mostrarToast('🔓 Acceso técnico autorizado. Configuración habilitada.', 'success');
            cerrarModalSU();
            _aplicarPrivilegiosSU(true);
            _mostrarPanelAdminParaSU();
            // Refrescar el sidebar para que aparezca "⚙️ Configuración (TIC)"
            // El rol activo sigue siendo admin pero ahora con suToken
            if (typeof _actualizarSidebarMenu === 'function' && window.SIPA.rolActivo) {
                _actualizarSidebarMenu(window.SIPA.rolActivo);
            }
            // Abrir el sidebar automáticamente para que el usuario vea la nueva opción
            if (typeof abrirSidebar === 'function') {
                setTimeout(abrirSidebar, 350);
            }
            setTimeout(() => {
                document.getElementById('nav-tab-config')?.click();
            }, 100);
            if (typeof iniciarSSE === 'function') iniciarSSE();
        } else {
            err.textContent = d.error || 'Credenciales inválidas.';
            err.style.display = 'block';
        }
    } catch (e) {
        err.textContent = 'Error de red: ' + e.message;
        err.style.display = 'block';
    }
}
async function logoutSU() {
    try {
        await fetch('/api/su/logout', {
            method: 'POST',
            headers: { 'X-SU-Token': window.SIPA.suToken || '' },
        });
    } catch {}
    window.SIPA.suToken = null;
    localStorage.removeItem('sipa_su_token');
    _aplicarPrivilegiosSU(false);
    // Refrescar sidebar para quitar "Configuración (TIC)"
    if (typeof _actualizarSidebarMenu === 'function' && window.SIPA.rolActivo) {
        _actualizarSidebarMenu(window.SIPA.rolActivo);
    }
    // Cerrar el stream SSE para evitar reintentos con token revocado
    if (typeof detenerSSE === 'function') detenerSSE();
    mostrarToast('🔒 Sesión técnica cerrada.', 'info');
}
function _aplicarPrivilegiosSU(activo) {
    const tabConfig = document.getElementById('nav-tab-config');
    if (tabConfig) tabConfig.style.display = activo ? '' : 'none';

    const btnAcceso = document.getElementById('btn-acceso-su');
    if (btnAcceso) {
        // Solo visible con sesión TIC activa (para poder cerrarla)
        btnAcceso.style.display = activo ? '' : 'none';
        if (activo) {
            btnAcceso.classList.add('btn-acceso-su--activo');
            btnAcceso.title = 'Sesión TIC activa — click para cerrar';
            btnAcceso.onclick = () => {
                if (confirm('¿Cerrar la sesión de Super Usuario?')) logoutSU();
            };
            const lbl = btnAcceso.querySelector('.btn-acceso-su-label');
            if (lbl) lbl.textContent = 'TIC activo';
        } else {
            btnAcceso.classList.remove('btn-acceso-su--activo');
            btnAcceso.title = 'Acceso Técnico · Personal de TIC';
            btnAcceso.onclick = abrirModalSU;
            const lbl = btnAcceso.querySelector('.btn-acceso-su-label');
            if (lbl) lbl.textContent = 'Acceso Técnico';
        }
    }
}

function _mostrarPanelAdminParaSU() {
    const contenedor = document.getElementById('servicio-container');
    const panel = document.getElementById('panel-admin');
    const login = document.getElementById('login-admin');
    if (!panel) return;
    window.SIPA.rolActivo = 'tic';
    if (contenedor) contenedor.classList.add('active');
    if (login) login.style.display = 'none';
    panel.style.display = 'block';
    document.querySelectorAll('.section').forEach(s => {
        if (s.id !== 'servicio-container') s.classList.remove('active');
    });
    _aplicarPrivilegiosSU(true);
    if (typeof loadServicio === 'function') loadServicio();
    if (typeof cargarFirmasTardiasPendientes === 'function') cargarFirmasTardiasPendientes();
    if (typeof _actualizarSidebarMenu === 'function') {
        _actualizarSidebarMenu('tic');
    }
}

async function _validarTokenSUAlInicio() {
    if (!window.SIPA.suToken) return;
    try {
        const r = await fetch('/api/su/validar', {
            headers: { 'X-SU-Token': window.SIPA.suToken },
        });
        const d = await r.json();
        _aplicarPrivilegiosSU(!!d.valido);
        // Si el token sigue válido y ya hay un rol activo, refrescar sidebar
        if (d.valido) {
            _mostrarPanelAdminParaSU();
        }
        if (!d.valido) {
            window.SIPA.suToken = null;
            localStorage.removeItem('sipa_su_token');
        }
    } catch {}
}

// ── RELOJ ─────────────────────────────────────────────────
function actualizarReloj() {
    const ahora   = new Date();
    const opciones = { weekday:'long', year:'numeric', month:'2-digit', day:'2-digit' };
    let fecha     = ahora.toLocaleDateString('es-AR', opciones);
    fecha         = fecha.charAt(0).toUpperCase() + fecha.slice(1);
    const hh = String(ahora.getHours()).padStart(2,'0');
    const mm = String(ahora.getMinutes()).padStart(2,'0');
    const ss = String(ahora.getSeconds()).padStart(2,'0');
    const el = document.getElementById('fecha-reloj');
    if (el) el.textContent = `${fecha}  |  ${hh}:${mm}:${ss}`;
}

// ── TOAST ─────────────────────────────────────────────────
function mostrarToast(mensaje, tipo = 'success') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const icons = { success:'✅', error:'❌', warning:'⚠️', info:'ℹ️' };
    const toast = document.createElement('div');
    toast.className = `toast ${tipo}`;
    toast.innerHTML = `
        <span style="display:flex;align-items:flex-start;gap:9px;line-height:1.5;">
            <span style="flex-shrink:0">${icons[tipo] || 'ℹ️'}</span>
            <span>${mensaje}</span>
        </span>
        <span class="toast-close" onclick="cerrarToast(this.parentElement)">✖</span>`;
    container.appendChild(toast);
    setTimeout(() => cerrarToast(toast), 5500);
}

function cerrarToast(el) {
    if (!el || !el.parentElement) return;
    el.style.animation = 'toastOut .35s ease forwards';
    setTimeout(() => el.remove(), 360);
}

// ── FECHA ─────────────────────────────────────────────────
function obtenerFechaHoyLocal() {
    const f = new Date();
    return `${f.getFullYear()}-${String(f.getMonth()+1).padStart(2,'0')}-${String(f.getDate()).padStart(2,'0')}`;
}

function formatearFechaElegante(fechaString) {
    if (!fechaString) return '';
    const [y, m, d] = fechaString.split('-');
    if (!y || !m || !d) return fechaString;
    const dateObj = new Date(parseInt(y), parseInt(m)-1, parseInt(d));
    let diaNombre = dateObj.toLocaleDateString('es-ES', { weekday:'long' });
    return `${diaNombre.charAt(0).toUpperCase() + diaNombre.slice(1)}, ${d}/${m}/${y}`;
}

// ══════════════════════════════════════════════════════════
// PANTALLA DE BIENVENIDA + NAVEGACIÓN ENTRE PORTALES
// ══════════════════════════════════════════════════════════
function seleccionarPortal(rol) {
    const welcome = document.getElementById('welcome-screen');
    const contMain = document.getElementById('container-principal');
    if (!welcome || !contMain) return;

    welcome.classList.add('welcome-fading-out');
    setTimeout(() => {
        welcome.style.display = 'none';
        welcome.classList.remove('welcome-fading-out');
        document.body.classList.remove('welcome-activo');
        contMain.style.display = 'block';
        contMain.classList.add('fade-in-up');
        setTimeout(() => contMain.classList.remove('fade-in-up'), 350);

        // Activar la sección que corresponda
        document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
        if (rol === 'bedel') {
            document.getElementById('bedel-container')?.classList.add('active');
        } else if (rol === 'docente') {
            document.getElementById('docente-container')?.classList.add('active');
        } else if (rol === 'admin') {
            document.getElementById('servicio-container')?.classList.add('active');
        } else if (rol === 'tic') {
            // TIC abre el modal de SU directamente (sin pasar por panel admin)
            if (typeof abrirModalSU === 'function') abrirModalSU();
            // Mostramos el panel admin igual por si después se logean
            document.getElementById('servicio-container')?.classList.add('active');
        }

        // Mostrar botón hamburguesa
        document.getElementById('btn-hamburguesa').style.display = '';
        window.SIPA.rolActivo = rol;
        _actualizarSidebarMenu(rol);
    }, 280);
}

function volverInicio() {
    // Si hay una sesión activa, avisar al usuario que también la va a cerrar
    const rol = window.SIPA.rolActivo;
    const haySesion = (rol === 'bedel'   && window.SIPA.bedelSesion) ||
                      (rol === 'docente' && window.SIPA.docenteLogName) ||
                      ((rol === 'admin' || rol === 'tic') && window.SIPA.adminToken);
    if (haySesion) {
        if (!confirm('Volver al Inicio cerrará la sesión actual. ¿Continúa?')) return;
        // Cerrar la sesión limpiamente sin volver a llamar a volverInicio
        if (rol === 'bedel'   && typeof _cerrarSesionBedelSilent === 'function') _cerrarSesionBedelSilent();
        if (rol === 'docente') {
            window.SIPA.docenteLogName = '';
        }
        if (rol === 'admin' || rol === 'tic') {
            try {
                const tok = window.SIPA.adminToken;
                if (tok) fetch('/api/admin/logout', { method:'POST', headers:{'X-Admin-Token': tok} });
            } catch {}
            window.SIPA.adminToken = null;
            localStorage.removeItem('sipa_admin_token');
        }
    }
    cerrarSidebar();
    const welcome = document.getElementById('welcome-screen');
    const contMain = document.getElementById('container-principal');
    if (!welcome || !contMain) return;
    contMain.style.display = 'none';
    welcome.style.display = '';
    welcome.classList.add('fade-in-up');
    setTimeout(() => welcome.classList.remove('fade-in-up'), 350);
    document.getElementById('btn-hamburguesa').style.display = 'none';
    document.body.classList.add('welcome-activo');
    window.SIPA.rolActivo = null;
}

// ── SIDEBAR / HAMBURGUESA ─────────────────────────────────
function toggleSidebar() {
    const btn = document.getElementById('btn-hamburguesa');
    const side = document.getElementById('sidebar');
    const over = document.getElementById('sidebar-overlay');
    if (!btn || !side || !over) return;
    const abierto = side.classList.contains('sidebar--open');
    if (abierto) cerrarSidebar();
    else        abrirSidebar();
}

function abrirSidebar() {
    document.getElementById('btn-hamburguesa').classList.add('hamburger--abierto');
    document.getElementById('sidebar').classList.add('sidebar--open');
    document.getElementById('sidebar').setAttribute('aria-hidden','false');
    document.getElementById('sidebar-overlay').classList.add('sidebar-overlay--visible');
    document.body.style.overflow = 'hidden';
}
function cerrarSidebar() {
    document.getElementById('btn-hamburguesa')?.classList.remove('hamburger--abierto');
    document.getElementById('sidebar')?.classList.remove('sidebar--open');
    document.getElementById('sidebar')?.setAttribute('aria-hidden','true');
    document.getElementById('sidebar-overlay')?.classList.remove('sidebar-overlay--visible');
    document.body.style.overflow = '';
}

function _actualizarSidebarMenu(rol) {
    const icon = document.getElementById('sidebar-rol-icon');
    const titulo = document.getElementById('sidebar-rol-nombre');
    const sub = document.getElementById('sidebar-rol-sub');
    const menu = document.getElementById('sidebar-menu');
    if (!icon || !menu) return;

    const roles = {
        bedel:   { icon:'📝', titulo:'Bedelía',         sub:'Carga del Parte Diario' },
        docente: { icon:'🖋️', titulo:'Portal Docente',  sub:'Firma y horario' },
        admin:   { icon:'🛡️', titulo:'Plana Mayor',     sub:'Monitor Táctico' },
        tic:     { icon:'⚙️', titulo:'Soporte TIC',     sub:'Acceso restringido' },
    };
    const info = roles[rol] || roles.bedel;
    icon.textContent = info.icon;
    titulo.textContent = info.titulo;
    sub.textContent = info.sub;

    // Pintar el sidebar de rojo si está en modo TIC (después de login SU)
    document.getElementById('sidebar').classList.toggle('sidebar--tic', !!window.SIPA.suToken);

    // Menú dinámico
    let items = [];
    if (rol === 'admin' || rol === 'tic') {
        items = [
            { ic:'🗂️', txt:'Archivo Histórico', fn:"_navAdmin('admin-reportes')" },
            { ic:'🔑', txt:'PINes Diarios',     fn:"_navAdmin('admin-pines')" },
            { ic:'⏳', txt:'Firmas tardías',     fn:"_navAdmin('admin-firmas-tardias')", badge:'firmas-tardias-pendientes-sidebar' },
            { ic:'📅', txt:'Días sin actividad', fn:"_navAdmin('admin-calendario')" },
            { ic:'👨‍🏫', txt:'Coberturas PGNP',  fn:"_navAdmin('admin-coberturas')" },
            { ic:'⏩', txt:'Adelantos de horario', fn:"_navAdmin('admin-adelantos-horario')" },
            { ic:'📡', txt:'Monitor & Firmas',  fn:"_navAdmin('admin-registro')" },
        ];
        if (window.SIPA.suToken) {
            items.push({ ic:'⚙️', txt:'Configuración (TIC)', fn:"_navAdmin('admin-config')", clase:'sidebar-item-su' });
        }
    } else if (rol === 'docente') {
        items = [
            { ic:'📚', txt:'Mis Materias', fn:"_scrollA('horario-semanal-list')" },
            { ic:'📝', txt:'Mis justificaciones', fn:"_scrollA('justificaciones-docente-lista')" },
            { ic:'📋', txt:'Mi Historial', fn:"_scrollA('historial-firmas-docente')" },
        ];
    } else if (rol === 'bedel') {
        items = [
            { ic:'📝', txt:'Parte Diario', fn:"_scrollA('panel-bedel')" },
        ];
    }

    menu.innerHTML = items.map(it =>
        `<button class="sidebar-item ${it.clase || ''}" onclick="${it.fn};cerrarSidebar();">
            ${it.ic} <span>${it.txt}</span>
            ${it.badge ? `<span id="${it.badge}" class="badge-mini badge-mini-naranja" style="display:none;margin-left:auto;">0</span>` : ''}
        </button>`
    ).join('');
}

function _navAdmin(id) {
    const el = Array.from(document.querySelectorAll('#panel-admin > .sub-nav-container .sub-nav'))
        .find(n => n.getAttribute('onclick')?.includes(`'${id}'`));
    if (el) el.click();
}
function _scrollA(id) {
    document.getElementById(id)?.scrollIntoView({behavior:'smooth', block:'start'});
}

function cerrarSesionUniversal() {
    const rol = window.SIPA.rolActivo;
    if (rol === 'bedel'    && typeof cerrarSesionBedel === 'function') cerrarSesionBedel();
    if (rol === 'docente'  && typeof volverLoginDoc   === 'function') volverLoginDoc();
    if (rol === 'admin' || rol === 'tic') {
        if (typeof cerrarSesionAdmin === 'function') cerrarSesionAdmin();
    }
    cerrarSidebar();
    // Después de cerrar, volver al welcome
    setTimeout(() => volverInicio(), 300);
}

// ── NAVEGACIÓN PRINCIPAL ──────────────────────────────────
function mostrarPestanaPrincipal(id, elemento) {
    document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('.nav-item').forEach(n => {
        n.classList.remove('active','active-admin');
        n.style.background = '';
        n.style.color = '';
    });
    const target = document.getElementById(id);
    if (target) target.classList.add('active');
    if (elemento) {
        if (id === 'servicio-container') elemento.classList.add('active-admin');
        else elemento.classList.add('active');
    }
}

function mostrarPestanaAdmin(id, el) {
    document.querySelectorAll('#panel-admin > .admin-section').forEach(s => s.classList.remove('active'));
    // Solo afectar los sub-navs del primer nivel del panel-admin
    const firstSubnav = document.querySelector('#panel-admin .sub-nav-container');
    if (firstSubnav) firstSubnav.querySelectorAll('.sub-nav').forEach(n => n.classList.remove('active'));
    const target = document.getElementById(id);
    if (target) target.classList.add('active');
    el.classList.add('active');
    if (id === 'admin-pines')    cargarPinesOperativos();
    if (id === 'admin-firmas-tardias') cargarFirmasTardiasPendientes();
    if (id === 'admin-calendario' && typeof cargarCalendarioNoActividad === 'function') cargarCalendarioNoActividad();
    if (id === 'admin-coberturas' && typeof cargarCoberturasDocente === 'function') cargarCoberturasDocente();
    if (id === 'admin-adelantos-horario' && typeof cargarAdelantosHorarioAdmin === 'function') cargarAdelantosHorarioAdmin();
    if (id === 'admin-registro') {
        if (document.getElementById('mon-aulas-dia')?.classList.contains('active')) cargarAulasDia();
        else refrescarMonitor();
    }
    if (id === 'admin-config') {
        const aulaInput = document.getElementById('c-aula');
        if (aulaInput && aulaInput.value.trim()) cargarConfigParaEditar();
    }
}

function mostrarCfgTab(id, el) {
    document.querySelectorAll('#admin-config .admin-section').forEach(s => s.classList.remove('active'));
    document.querySelectorAll('#admin-config .sub-nav').forEach(n => n.classList.remove('active'));
    const target = document.getElementById(id);
    if (target) target.classList.add('active');
    el.classList.add('active');
    if (id === 'cfg-bd'         && typeof cargarConexionActual === 'function') cargarConexionActual();
    if (id === 'cfg-aulas'      && typeof cargarCatalogoAulas === 'function') cargarCatalogoAulas();
    if (id === 'cfg-novedades' && typeof cargarTiposNovedad === 'function') cargarTiposNovedad();
    if (id === 'cfg-pgnp' && typeof cargarCuentasPgnp === 'function') cargarCuentasPgnp();
    if (id === 'cfg-cronograma' && typeof cargarAulasCronograma === 'function') cargarAulasCronograma();
    if (id === 'cfg-seguridad'  && typeof cargarMapaPines      === 'function') cargarMapaPines();
    if (id === 'cfg-parametros' && typeof cargarParametrosSU   === 'function') cargarParametrosSU();
    if (id === 'cfg-auditoria'  && typeof cargarAuditLog       === 'function') cargarAuditLog();
    if (id === 'cfg-salud'      && typeof cargarHealthCheck    === 'function') cargarHealthCheck();
    if (id === 'cfg-cuentas'    && typeof cargarUsuariosAdmin  === 'function') cargarUsuariosAdmin();
    if (id === 'cfg-dashboard'  && typeof cargarDashboardSU       === 'function') cargarDashboardSU();
    if (id === 'cfg-ubicaciones'  && typeof cargarUbicacionesFirmasTIC === 'function') cargarUbicacionesFirmasTIC();
    if (id === 'cfg-versiones'  && typeof cargarVersionesCronograma === 'function') cargarVersionesCronograma();
    if (id === 'cfg-limpieza'   && typeof analizarSaludDB === 'function') analizarSaludDB();
    if (id === 'cfg-telegram'   && typeof cargarTelegramConfig    === 'function') cargarTelegramConfig();
    if (id === 'cfg-sql'        && typeof _sqlCargarTablasDinamicas === 'function') _sqlCargarTablasDinamicas();
    if (id === 'cfg-sesiones'   && typeof cargarSesionesActivas   === 'function') {
        cargarSesionesActivas();
        if (typeof toggleSesionesAuto === 'function') toggleSesionesAuto(true);
    }
    if (id === 'cfg-archivo'    && typeof cargarResumenArchivo === 'function') {
        cargarResumenArchivo();
        if (typeof consultarArchivo === 'function') consultarArchivo();
    }
}

// ── FETCH HELPER (compatibilidad con apiFetch del main.js anterior) ──
async function apiFetch(url, options = {}) {
    const response = await fetch(url, options);
    if (!response.ok) {
        let msg = 'Error en la solicitud al servidor';
        try { const d = await response.json(); msg = d.error || msg; } catch {}
        mostrarToast(msg, 'error');
        throw new Error(msg);
    }
    return response.json();
}

// ── INIT ──────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', function () {
    actualizarReloj();
    setInterval(actualizarReloj, 1000);

    // Marcar la pantalla de bienvenida como activa al inicio (oculta el hero)
    document.body.classList.add('welcome-activo');

    // Inicializar selector de tema (☀️/🌙/🖥️)
    _instalarBotonTema();

    // ── EVENT DELEGATION para botones de SQL ejemplos ──
    // Garantiza funcionamiento aunque admin.js tenga problemas de carga
    document.addEventListener('click', function(e) {
        const btn = e.target.closest('.sql-ej-btn');
        if (!btn) return;
        const q = btn.dataset.sql || '';
        if (!q) return;
        const ta = document.getElementById('sql-query');
        if (ta) {
            ta.value = q;
            ta.focus();
            ta.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
    });

    // Enter en inputs de login
    const bindings = [
        ['pass-admin', () => ingresarAdmin()],
        ['pass-bedel', () => ingresarBedel()],
        ['doc-pass',   () => docenteLogin()],
        ['su-password',() => ingresarSU()],
    ];
    bindings.forEach(([id, fn]) => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('keypress', e => { if (e.key === 'Enter') fn(); });
    });

    // Validar token de SU si quedó guardado de una sesión previa
    _validarTokenSUAlInicio();

    // Detectar impersonación por URL (?imp_token=...&imp_rol=...&imp_persona=...)
    _detectarImpersonacionDesdeURL();
});


// ── IMPERSONACIÓN: bootstrap automático desde URL ────────────
function _detectarImpersonacionDesdeURL() {
    const params = new URLSearchParams(location.search);
    const tok     = params.get('imp_token');
    const rol     = params.get('imp_rol');
    const persona = params.get('imp_persona');
    const sujeto  = params.get('imp_sujeto');
    if (!tok || !rol || !persona) return;

    // Limpiar la URL para no exponer el token en la barra
    history.replaceState({}, '', location.pathname);

    // Marcar sesión como impersonada
    window.SIPA.impersonacion = { token: tok, rol, persona, sujeto };

    // Mostrar banner permanente
    _mostrarBannerImpersonacion(rol, persona, sujeto);

    // Salir de la pantalla de bienvenida — si no, queda tapando el portal impersonado
    const _welcome = document.getElementById('welcome-screen');
    if (_welcome) _welcome.style.display = 'none';
    document.body.classList.remove('welcome-activo');
    const _contMain = document.getElementById('container-principal');
    if (_contMain) _contMain.style.display = 'block';
    const _btnHamb = document.getElementById('btn-hamburguesa');
    if (_btnHamb) _btnHamb.style.display = '';

    if (rol === 'docente') {
        // Saltar login y armar el portal docente como si hubiera entrado
        window.SIPA.docenteLogName = persona;
        document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        const cont = document.getElementById('docente-container');
        if (cont) cont.classList.add('active');
        const nav = Array.from(document.querySelectorAll('.nav-item'))
            .find(n => n.textContent.includes('Docente'));
        if (nav) nav.classList.add('active');
        document.getElementById('login-docente').style.display    = 'none';
        document.getElementById('registro-docente').style.display = 'none';
        document.getElementById('recuperar-docente').style.display = 'none';
        document.getElementById('panel-docente').style.display    = 'block';
        if (typeof _actualizarSaludoDocente === 'function') _actualizarSaludoDocente(persona);
        if (typeof cargarClasesPendientes === 'function')   cargarClasesPendientes();
        if (typeof cargarHorarioSemanal === 'function')     cargarHorarioSemanal();
        if (typeof cargarHistorialFirmasDocente === 'function') cargarHistorialFirmasDocente();
    } else if (rol === 'plana_mayor' || rol === 'admin') {
        // Usar el token como sesión admin (ya está registrado en _ADMIN_TOKENS por el backend)
        window.SIPA.adminToken = tok;
        document.querySelectorAll('.section').forEach(s => s.classList.remove('active'));
        document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
        const cont = document.getElementById('servicio-container');
        if (cont) cont.classList.add('active');
        const nav = Array.from(document.querySelectorAll('.nav-item'))
            .find(n => n.textContent.includes('Plana'));
        if (nav) nav.classList.add('active');
        document.getElementById('login-admin').style.display = 'none';
        document.getElementById('panel-admin').style.display = 'block';
        if (typeof cargarPinesOperativos === 'function') cargarPinesOperativos();
        if (typeof loadServicio === 'function')          loadServicio();
    }
    mostrarToast(`🎭 Impersonado como ${persona}`, 'info');
}

function _mostrarBannerImpersonacion(rol, persona, sujeto) {
    const div = document.createElement('div');
    div.className = 'banner-impersonacion';
    div.innerHTML = `
        🎭 <strong>MODO IMPERSONACIÓN ACTIVO</strong> — Visualizando como
        <strong>${persona}</strong> (${rol})
        <button onclick="_terminarImpersonacionLocal()" class="btn-cerrar-imp">
            ⏹ Salir
        </button>`;
    document.body.insertBefore(div, document.body.firstChild);
    // Compatible con navegadores sin :has() — agregamos clase al body
    document.body.classList.add('con-impersonacion');
}

async function _terminarImpersonacionLocal() {
    const info = window.SIPA.impersonacion;
    if (!info) { location.href = '/'; return; }
    try {
        // Si tenemos token SU activo en localStorage, le pedimos al backend que cierre la sesión
        const suTok = localStorage.getItem('sipa_su_token');
        if (suTok) {
            await fetch('/api/su/impersonar_fin', {
                method:'POST',
                headers:{'Content-Type':'application/json','X-SU-Token':suTok},
                body: JSON.stringify({ token: info.token }),
            });
        }
    } catch {}
    // Limpiar la sesión local y volver al inicio sin la query
    window.SIPA.impersonacion = null;
    window.SIPA.docenteLogName = '';
    window.SIPA.adminToken     = null;
    location.href = '/';
}
