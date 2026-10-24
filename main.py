# pyright: reportOptionalIterable=false, reportOptionalSubscript=false, reportOptionalMemberAccess=false, reportPossiblyUnboundVariable=false, reportAttributeAccessIssue=false
"""
main.py — S.I.P.A. · GNA 2026
Backend Flask + PostgreSQL

Parser Word robusto:
  - Horario militar (0720-0820 → 07:20-08:20)
  - Días con espacios entre letras (L U N E S) o abreviaturas (Lun, Mar…)
  - Separación asignatura / docente sin separador explícito
  - Grados militares eliminados del nombre (CBO, STO, ALF, 2DO CTE, …)
  - Canonicalización de variantes truncadas del mismo docente
  - Materias con "/" que separan cuatrimestres dentro de la misma celda

Pragmas de Pylance arriba: psycopg2 no expone type stubs completos, sus cursores
tipan fetchall/fetchone como Optional → falsos positivos en cada query. El código
está verificado y funciona correctamente.
"""

import csv
import html
import io
import json
import smtplib
import ssl
import threading
import time as _time_mod
import hashlib
import math
import os
import re
import secrets
import traceback as _traceback
import unicodedata
from datetime import datetime, date, time, timedelta
from difflib import SequenceMatcher

import psycopg2
from flask import (Flask, request, jsonify, render_template,
                   Response, make_response, send_file,
                   send_from_directory, stream_with_context)
from dotenv import load_dotenv

try:
    import bcrypt  # type: ignore[import-not-found]
    BCRYPT_OK = True
except ImportError:
    bcrypt = None  # type: ignore[assignment]
    BCRYPT_OK = False

try:
    from docx import Document as DocxDocument  # type: ignore[import-not-found]
    DOCX_OK = True
except ImportError:
    DocxDocument = None  # type: ignore[assignment]
    DOCX_OK = False

try:
    import pandas as pd  # type: ignore[import-not-found]
    PANDAS_OK = True
except ImportError:
    pd = None  # type: ignore[assignment]
    PANDAS_OK = False

# ═══════════════════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════════════
load_dotenv()
app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

DB_CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    'db_config.json'
)


def _default_db_config():
    return {
        'host':     os.getenv("DB_HOST", "localhost"),
        'port':     os.getenv("DB_PORT", "5432"),
        'dbname':   os.getenv("DB_NAME", "sistema_escuadron"),
        'user':     os.getenv("DB_USER", "postgres"),
        'password': os.getenv("DB_PASS", "1982"),
    }


def _load_db_config():
    """Lee la conexión activa: archivo JSON si existe, sino .env / default."""
    if os.path.exists(DB_CONFIG_FILE):
        try:
            with open(DB_CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
            base = _default_db_config()
            base.update({k: v for k, v in cfg.items() if v not in (None, '')})
            return base
        except Exception as e:
            print(f"[SIPA] No se pudo leer {DB_CONFIG_FILE}: {e}")
    return _default_db_config()


# ═══════════════════════════════════════════════════════════════════════════
# BASE DE DATOS
# ═══════════════════════════════════════════════════════════════════════════

def get_db():
    c = _load_db_config()
    return psycopg2.connect(
        host=c['host'], port=c['port'], dbname=c['dbname'],
        user=c['user'], password=c['password']
    )


def _catalogo_aulas_oficial() -> list[dict]:
    """Catálogo académico base para resolver aula, curso y especialidad."""
    registros = []

    def agregar(turno, aulas, nombre, anio, especialidad, curso):
        for aula in aulas:
            aliases = [f'AULA {aula}']
            if turno == 'TT':
                aliases.append(f'{aula}T')
            if aula.endswith('T'):
                aliases.append(aula[:-1])
            if aula == '7' and turno == 'TT':
                aliases.append('7 Op. Montadas')
            if aula == '8' and turno == 'TT':
                aliases.append('8 TT')
            registros.append({
                'aula': aula, 'turno': turno, 'nombre': nombre,
                'anio': anio, 'especialidad': especialidad, 'curso': curso,
                'aliases': aliases,
                'fuente': 'Distribución de aulas y horarios oficiales 2026',
            })

    # Turno mañana: ASPIGEN, segundo y tercer año IUGNA.
    agregar('TM', [str(n) for n in range(1, 7)],
            'ASPIGEN', '1°', 'Formación de aspirantes a gendarmes',
            '1° Año IUGNA - ASPIGEN')
    agregar('TM', ['10', '11'], '2° TUSPyC', '2°', 'TUSPyC', '2° Año TUSPyC')
    agregar('TM', ['13', '14'], '2° TUSPyC', '2°', 'TUSPCGC', '2° Año TUSPyC')
    agregar('TM', ['15', '16'], '2° TUSPyC', '2°', 'TUSPCAP', '2° Año TUSPyC')
    agregar('TM', ['7', '8', '9'], '2° TUSPyC', '2°', 'TUSPCIC', '2° Año TUSPyC')
    agregar('TM', ['12'], '2° TUSPyC', '2°', 'TUSPCSV', '2° Año TUSPyC')
    agregar('TM', ['17', '18'], '3° TUSPyC', '3°', 'TUSPyC', '3° Año TUSPyC')
    agregar('TM', ['21', '22'], '3° TUSPyC', '3°', 'TUSPCIC', '3° Año TUSPyC')
    agregar('TM', ['19', '20'], '3° TUSPyC', '3°', 'TUSPCC', '3° Año TUSPyC')
    agregar('TM', ['26', '28'], '3° TUSPyC', '3°', 'TUSPCSV', '3° Año TUSPyC')
    agregar('TM', ['23', '24'], '3° TUSPyC', '3°', 'TUSPCAP', '3° Año TUSPyC')
    agregar('TM', ['25', '29'], '3° TUSPyC', '3°', 'TUSPCGC', '3° Año TUSPyC')

    # Turno tarde: cursos CBFG, CAO, segundo y tercer año TUSPyC.
    agregar('TT', [str(n) for n in range(1, 7)],
            'CBFG', '1°', 'Formación de gendarmes',
            'Curso Básico de Formación de Gendarmes')
    agregar('TT', ['7'], 'CAO Op. Montadas', 'CAO',
            'Operaciones Montadas', 'Curso Auxiliar Operativo Op. Montadas')
    agregar('TT', ['8'], 'CAO Seguridad', 'CAO',
            'Seguridad', 'Curso Auxiliar Operativo - Seguridad')
    agregar('TT', [str(n) for n in range(9, 19)],
            '2° TUSPyC', '2°', 'TUSPyC', '2° Año TUSPyC')
    agregar('TT', [str(n) for n in range(19, 27)],
            '3° TUSPyC', '3°', 'TUSPyC', '3° Año TUSPyC')
    return registros


def _sembrar_catalogo_aulas(conn):
    """Inserta la distribución oficial sin borrar personalizaciones existentes."""
    with conn.cursor() as cur:
        # Las planillas pueden escribir "9" y la documentación "9T": el turno
        # ya desambigua ambos casos, por eso el catálogo usa el número canónico.
        cur.execute("DELETE FROM aula_catalogo WHERE turno='TT' AND aula ~ '^[0-9]+T$'")
        for r in _catalogo_aulas_oficial():
            cur.execute("""
                INSERT INTO aula_catalogo
                    (aula, turno, nombre, anio, especialidad, curso, aliases, fuente, actualizado)
                VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s,CURRENT_TIMESTAMP)
                ON CONFLICT (aula, turno) DO UPDATE SET
                    nombre=CASE WHEN aula_catalogo.fuente = 'Edición manual' THEN aula_catalogo.nombre ELSE EXCLUDED.nombre END,
                    anio=CASE WHEN aula_catalogo.fuente = 'Edición manual' THEN aula_catalogo.anio ELSE EXCLUDED.anio END,
                    especialidad=CASE WHEN aula_catalogo.fuente = 'Edición manual' THEN aula_catalogo.especialidad ELSE EXCLUDED.especialidad END,
                    curso=CASE WHEN aula_catalogo.fuente = 'Edición manual' THEN aula_catalogo.curso ELSE EXCLUDED.curso END,
                    aliases=CASE WHEN aula_catalogo.fuente = 'Edición manual' THEN aula_catalogo.aliases ELSE EXCLUDED.aliases END,
                    fuente=CASE WHEN aula_catalogo.fuente = 'Edición manual' THEN aula_catalogo.fuente ELSE EXCLUDED.fuente END,
                    actualizado=CURRENT_TIMESTAMP
            """, (r['aula'], r['turno'], r['nombre'], r['anio'],
                  r['especialidad'], r['curso'], json.dumps(r['aliases']),
                  r['fuente']))


def _calendario_cubre_aula(item, aula, turno):
    aula = str(aula or '').strip().upper()
    turno = str(turno or '').strip().upper()
    alcance = item.get('alcance')
    cubre = (
        alcance == 'institucion' or
        (alcance == 'turno' and item.get('turno') == turno) or
        (alcance == 'aula' and item.get('aula') == aula and item.get('turno') == turno)
    )
    if not cubre:
        return False
    excepciones = item.get('excepciones') or []
    if isinstance(excepciones, str):
        try:
            excepciones = json.loads(excepciones)
        except (ValueError, TypeError):
            excepciones = []
    return not any(
        isinstance(excepcion, dict)
        and str(excepcion.get('aula', '')).strip().upper() == aula
        and str(excepcion.get('turno', '')).strip().upper() == turno
        for excepcion in excepciones
    )


def _cargar_calendario_no_actividad(cur, desde, hasta):
    cur.execute("""
        SELECT fecha::text, alcance, turno, aula, excepciones
        FROM calendario_no_actividad
        WHERE estado='confirmado' AND fecha BETWEEN %s AND %s
    """, (desde, hasta))
    return [{
        'fecha': row[0],
        'alcance': row[1],
        'turno': row[2],
        'aula': row[3],
        'excepciones': row[4],
    } for row in cur.fetchall()]


def _sin_actividad_en_fecha(calendario, fecha, aula, turno):
    fecha_iso = fecha.isoformat() if hasattr(fecha, 'isoformat') else str(fecha)
    return any(
        item['fecha'] == fecha_iso and _calendario_cubre_aula(item, aula, turno)
        for item in calendario
    )


def _cargar_cierres_fecha(cur, fecha):
    cur.execute("""
        SELECT fecha::text, alcance, turno, aula, excepciones, motivo
        FROM calendario_no_actividad
        WHERE fecha=%s AND estado='confirmado'
    """, (fecha,))
    return [{
        'fecha': row[0], 'alcance': row[1], 'turno': row[2],
        'aula': row[3], 'excepciones': row[4], 'motivo': row[5],
    } for row in cur.fetchall()]


def _usuario_sesion_actual(req):
    tokens = (req.headers.get('X-SU-Token'), req.headers.get('X-Admin-Token'))
    for token in tokens:
        meta = _SESIONES_META.get(token or '')
        if meta:
            return str(meta.get('usuario') or 'Usuario administrativo')
    return 'TIC' if _su_token_valido(req) else 'Plana Mayor'


def _validar_alcance_calendario(d):
    if not isinstance(d, dict):
        return None, 'El cuerpo de la solicitud debe ser un objeto JSON.'
    fecha = str(d.get('fecha') or '').strip()
    try:
        datetime.strptime(fecha, '%Y-%m-%d')
    except ValueError:
        return None, 'La fecha debe tener formato AAAA-MM-DD.'
    alcance = str(d.get('alcance') or '').strip().lower()
    if alcance not in ('institucion', 'turno', 'aula'):
        return None, 'El alcance debe ser institución, turno o aula.'
    turno = str(d.get('turno') or '').strip().upper() or None
    aula = str(d.get('aula') or '').strip().upper() or None
    if alcance == 'institucion':
        turno = aula = None
    elif alcance == 'turno':
        aula = None
        if turno not in ('TM', 'TT'):
            return None, 'Seleccione un turno válido.'
    elif alcance == 'aula':
        if turno not in ('TM', 'TT') or not aula:
            return None, 'Seleccione aula y turno para el alcance por aula.'
        if len(aula) > 50:
            return None, 'El aula no puede superar 50 caracteres.'
    motivo = str(d.get('motivo') or '').strip()
    if not motivo or len(motivo) > 200:
        return None, 'El motivo es obligatorio y no puede superar 200 caracteres.'
    return {
        'fecha': fecha, 'alcance': alcance, 'turno': turno,
        'aula': aula, 'motivo': motivo,
    }, None


def _normalizar_horario_cobertura(valor):
    partes = re.split(r'\s*[-–]\s*', str(valor or '').strip())
    if len(partes) != 2:
        return None
    salida = []
    for parte in partes:
        digitos = re.sub(r'\D', '', parte)
        if len(digitos) not in (3, 4):
            return None
        digitos = digitos.zfill(4)
        hora, minuto = int(digitos[:2]), int(digitos[2:])
        if hora > 23 or minuto > 59:
            return None
        salida.append(f'{hora:02d}:{minuto:02d}')
    return '-'.join(salida)


def _minutos_horario(hora):
    normalizada = _normalizar_horario_cobertura(hora)
    if not normalizada:
        return None
    inicio, fin = normalizada.split('-')
    a = int(inicio[:2]) * 60 + int(inicio[3:])
    b = int(fin[:2]) * 60 + int(fin[3:])
    return (a, b) if b > a else None


def _intervalos_horarios_solapan(hora_a, hora_b):
    a = _minutos_horario(hora_a)
    b = _minutos_horario(hora_b)
    return bool(a and b and a[0] < b[1] and b[0] < a[1])


def _dia_semana_espanol(fecha):
    return ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes',
            'Sábado', 'Domingo'][fecha.weekday()]


def _cobertura_coincide_cronograma(cur, fecha, aula, turno, titular, materia, hora):
    cur.execute(
        "SELECT config_json FROM cronograma_maestro WHERE aula=%s AND turno=%s",
        (aula, turno),
    )
    row = cur.fetchone()
    if not row or not row[0]:
        return False
    config = row[0]
    if isinstance(config, str):
        try:
            config = json.loads(config)
        except (ValueError, TypeError):
            return False
    bloques = config if isinstance(config, list) else [config] if isinstance(config, dict) else []
    dia = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'][fecha.weekday()]
    normalizar = lambda valor: _sin_acentos(str(valor or '')).strip().lower()
    hora_norm = _normalizar_horario_cobertura(hora)
    return any(
        isinstance(bloque, dict)
        and normalizar(bloque.get('dia')) == normalizar(dia)
        and _normalizar_horario_cobertura(bloque.get('hora')) == hora_norm
        and normalizar(bloque.get('asig')) == normalizar(materia)
        and normalizar(bloque.get('doc')) == normalizar(titular)
        for bloque in bloques
    )


def init_db():
    DDL = """
    CREATE TABLE IF NOT EXISTS aula_catalogo (
        aula         VARCHAR(50) NOT NULL,
        turno        VARCHAR(20) NOT NULL,
        nombre       VARCHAR(150) NOT NULL,
        anio         VARCHAR(20),
        especialidad VARCHAR(150),
        curso        VARCHAR(150),
        aliases      JSONB,
        fuente       VARCHAR(250),
        actualizado  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY (aula, turno)
    );
    CREATE TABLE IF NOT EXISTS cronograma_maestro (
        aula        VARCHAR(50)  NOT NULL,
        turno       VARCHAR(20)  NOT NULL,
        config_json JSONB,
        PRIMARY KEY (aula, turno)
    );
    CREATE TABLE IF NOT EXISTS aspirantes (
        id     SERIAL PRIMARY KEY,
        aula   VARCHAR(50)  NOT NULL,
        turno  VARCHAR(20)  NOT NULL,
        grado  VARCHAR(50),
        nombre VARCHAR(150) NOT NULL,
        UNIQUE (aula, turno, nombre)
    );
    CREATE TABLE IF NOT EXISTS tipos_novedad (
        id                    SERIAL PRIMARY KEY,
        nombre                VARCHAR(80) UNIQUE NOT NULL,
        permite_justificacion BOOLEAN NOT NULL DEFAULT TRUE,
        justificada_por_defecto BOOLEAN,
        activo                BOOLEAN NOT NULL DEFAULT TRUE,
        creado_en             TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS docentes (
        id            SERIAL PRIMARY KEY,
        nombre        VARCHAR(150) NOT NULL,
        email         VARCHAR(150) UNIQUE NOT NULL,
        dni           VARCHAR(20)  UNIQUE NOT NULL,
        password_hash TEXT         NOT NULL,
        es_pgnp       BOOLEAN NOT NULL DEFAULT FALSE,
        creado_en     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS coberturas_docente (
        id             SERIAL PRIMARY KEY,
        fecha          DATE NOT NULL,
        aula           VARCHAR(50) NOT NULL,
        turno          VARCHAR(20) NOT NULL CHECK (turno IN ('TM', 'TT')),
        titular        VARCHAR(150) NOT NULL,
        materia        VARCHAR(150) NOT NULL,
        hora           VARCHAR(40) NOT NULL,
        pgnp_id        INTEGER REFERENCES docentes(id),
        estado         VARCHAR(20) NOT NULL DEFAULT 'pendiente'
                       CHECK (estado IN ('solicitada', 'pendiente', 'aprobada', 'rechazada', 'completada', 'cancelada')),
        solicitada_por VARCHAR(150) NOT NULL,
        solicitada_en  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        motivo_solicitud TEXT,
        revisada_por   VARCHAR(150),
        revisada_en    TIMESTAMP,
        firmado_en     TIMESTAMP
    );
    CREATE UNIQUE INDEX IF NOT EXISTS uq_cobertura_docente_horario_solicitada
        ON coberturas_docente(fecha, aula, turno, hora, materia)
        WHERE estado IN ('solicitada', 'pendiente', 'aprobada', 'completada');
    CREATE INDEX IF NOT EXISTS idx_cobertura_docente_pgnp_fecha
        ON coberturas_docente(pgnp_id, fecha, estado);
    CREATE TABLE IF NOT EXISTS minutas (
        id            SERIAL PRIMARY KEY,
        aula          VARCHAR(50)  NOT NULL,
        fecha         DATE         NOT NULL,
        turno         VARCHAR(20)  NOT NULL,
        bedel         VARCHAR(150),
        sub_bedel     VARCHAR(150),
        fe            INTEGER,
        presentes     INTEGER,
        cant_ausentes INTEGER,
        schedule_json JSONB,
        ausentes_json JSONB,
        novedades     TEXT,
        fecha_carga   TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS firmas_docentes (
        id            SERIAL PRIMARY KEY,
        docente       VARCHAR(150) NOT NULL,
        aula          VARCHAR(50)  NOT NULL,
        turno         VARCHAR(20)  NOT NULL,
        fecha         DATE         NOT NULL,
        hora_firma    TIME         NOT NULL,
        timestamp_utc TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
        pin_usado     VARCHAR(10),
        UNIQUE (docente, aula, turno, fecha)
    );
    CREATE TABLE IF NOT EXISTS justificaciones_ausencia (
        id            SERIAL PRIMARY KEY,
        docente       VARCHAR(150) NOT NULL,
        aula          VARCHAR(50)  NOT NULL,
        turno         VARCHAR(20)  NOT NULL,
        fecha         DATE         NOT NULL,
        motivo        VARCHAR(200) NOT NULL,
        comentario    TEXT,
        registrado_por VARCHAR(150),
        creado_en     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
        observacion_revision TEXT,
        UNIQUE (docente, aula, turno, fecha)
    );
    CREATE TABLE IF NOT EXISTS calendario_no_actividad (
        id            SERIAL PRIMARY KEY,
        fecha         DATE NOT NULL,
        alcance       VARCHAR(20) NOT NULL CHECK (alcance IN ('institucion', 'turno', 'aula')),
        turno         VARCHAR(20),
        aula          VARCHAR(50),
        motivo        VARCHAR(200) NOT NULL,
        estado        VARCHAR(20) NOT NULL DEFAULT 'programado'
                      CHECK (estado IN ('programado', 'confirmado')),
        excepciones   JSONB NOT NULL DEFAULT '[]'::jsonb,
        creado_por    VARCHAR(150) NOT NULL,
        creado_en     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        confirmado_por VARCHAR(150),
        confirmado_en TIMESTAMP,
        actualizado   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        CHECK (
            (alcance = 'institucion' AND turno IS NULL AND aula IS NULL) OR
            (alcance = 'turno' AND turno IN ('TM', 'TT') AND aula IS NULL) OR
            (alcance = 'aula' AND turno IN ('TM', 'TT') AND aula IS NOT NULL)
        )
    );
    CREATE INDEX IF NOT EXISTS idx_calendario_no_actividad_fecha
        ON calendario_no_actividad(fecha, estado);
    CREATE UNIQUE INDEX IF NOT EXISTS uq_calendario_no_actividad_alcance
        ON calendario_no_actividad(fecha, alcance, (COALESCE(turno, '')), (COALESCE(aula, '')))
        WHERE estado IN ('programado', 'confirmado');
    CREATE TABLE IF NOT EXISTS config_sistema (
        clave        VARCHAR(60) PRIMARY KEY,
        valor        TEXT NOT NULL,
        descripcion  TEXT,
        actualizado  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS adelantos_horario (
        id             SERIAL PRIMARY KEY,
        docente_id     INTEGER NOT NULL REFERENCES docentes(id),
        docente        VARCHAR(150) NOT NULL,
        aula           VARCHAR(50) NOT NULL,
        turno          VARCHAR(20) NOT NULL CHECK (turno IN ('TM', 'TT')),
        materia        VARCHAR(150) NOT NULL,
        fecha_original DATE NOT NULL,
        hora_original  VARCHAR(40) NOT NULL,
        fecha_nueva    DATE NOT NULL,
        hora_nueva     VARCHAR(40) NOT NULL,
        estado         VARCHAR(20) NOT NULL DEFAULT 'aplicado'
                       CHECK (estado IN ('aplicado', 'revocado')),
        creado_en      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
        revocado_por   VARCHAR(150),
        revocado_en    TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_adelantos_docente_fecha
        ON adelantos_horario(docente_id, fecha_nueva DESC);
    CREATE INDEX IF NOT EXISTS idx_adelantos_fechas_aula
        ON adelantos_horario(fecha_original, fecha_nueva, aula, turno)
        WHERE estado = 'aplicado';
    CREATE TABLE IF NOT EXISTS pin_overrides (
        id           SERIAL PRIMARY KEY,
        aula         VARCHAR(50) NOT NULL,
        turno        VARCHAR(20) NOT NULL,
        fecha        DATE        NOT NULL,
        pin_nuevo    VARCHAR(10) NOT NULL,
        motivo       TEXT,
        creado_en    TIMESTAMP   DEFAULT CURRENT_TIMESTAMP,
        UNIQUE (aula, turno, fecha)
    );
    CREATE TABLE IF NOT EXISTS usuarios_admin (
        id            SERIAL PRIMARY KEY,
        usuario       VARCHAR(80)  UNIQUE NOT NULL,
        nombre        VARCHAR(150) NOT NULL,
        password_hash TEXT         NOT NULL,
        rol           VARCHAR(30)  DEFAULT 'plana_mayor',
        activo        BOOLEAN      DEFAULT TRUE,
        debe_cambiar_pass BOOLEAN  DEFAULT FALSE,
        creado_por    VARCHAR(80),
        creado_en     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
        ultimo_login  TIMESTAMP,
        totp_secret   VARCHAR(64),
        totp_activado BOOLEAN      DEFAULT FALSE
    );
    CREATE TABLE IF NOT EXISTS cronograma_versiones (
        id           SERIAL PRIMARY KEY,
        aula         VARCHAR(50)  NOT NULL,
        turno        VARCHAR(20)  NOT NULL,
        config_json  JSONB        NOT NULL,
        creado_en    TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
        creado_por   VARCHAR(150),
        motivo       VARCHAR(200),
        bloques_cnt  INTEGER
    );
    CREATE INDEX IF NOT EXISTS idx_crono_ver_aula_turno
        ON cronograma_versiones(aula, turno, creado_en DESC);
    CREATE TABLE IF NOT EXISTS audit_log (
        id           SERIAL PRIMARY KEY,
        fecha        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        usuario      VARCHAR(150),
        rol          VARCHAR(30),
        accion       VARCHAR(60) NOT NULL,
        tabla        VARCHAR(60),
        registro_ref VARCHAR(200),
        detalle      TEXT,
        ip           VARCHAR(60)
    );
    CREATE INDEX IF NOT EXISTS idx_audit_fecha ON audit_log(fecha DESC);
    CREATE TABLE IF NOT EXISTS failed_logins (
        id        SERIAL PRIMARY KEY,
        fecha     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        tipo      VARCHAR(30) NOT NULL,
        detalle   TEXT,
        ip        VARCHAR(60)
    );
    CREATE INDEX IF NOT EXISTS idx_failed_fecha ON failed_logins(fecha DESC);
    CREATE TABLE IF NOT EXISTS system_log (
        id        SERIAL PRIMARY KEY,
        fecha     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        nivel     VARCHAR(10) NOT NULL,
        endpoint  VARCHAR(200),
        mensaje   TEXT,
        traceback TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_syslog_fecha ON system_log(fecha DESC);
    CREATE TABLE IF NOT EXISTS bedeles_telegram (
        id                SERIAL PRIMARY KEY,
        telegram_user_id  BIGINT       UNIQUE NOT NULL,
        telegram_username VARCHAR(80),
        nombre_telegram   VARCHAR(150),
        aula              VARCHAR(50)  NOT NULL,
        turno             VARCHAR(20)  NOT NULL,
        vinculado_en      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
        ultimo_acceso     TIMESTAMP,
        activo            BOOLEAN      DEFAULT TRUE
    );
    CREATE INDEX IF NOT EXISTS idx_bedeles_tg_aula ON bedeles_telegram(aula, turno);
    CREATE TABLE IF NOT EXISTS bedel_link_tokens (
        token       VARCHAR(50) PRIMARY KEY,
        tipo        VARCHAR(20) NOT NULL,
        aula        VARCHAR(50),
        turno       VARCHAR(20),
        tg_user_id  BIGINT,
        tg_username VARCHAR(80),
        creado_en   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expira_en   TIMESTAMP NOT NULL,
        usado       BOOLEAN DEFAULT FALSE
    );
    CREATE INDEX IF NOT EXISTS idx_bedel_tok_exp ON bedel_link_tokens(expira_en);
    CREATE TABLE IF NOT EXISTS recordatorios_telegram (
        id            SERIAL PRIMARY KEY,
        fecha_objetivo TIMESTAMP NOT NULL,
        mensaje       TEXT NOT NULL,
        creado_por    VARCHAR(150),
        creado_en     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        enviado       BOOLEAN DEFAULT FALSE,
        enviado_en    TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_recordatorios_pend ON recordatorios_telegram(fecha_objetivo)
        WHERE enviado = FALSE;
    CREATE TABLE IF NOT EXISTS bot_comando_log (
        id           SERIAL PRIMARY KEY,
        fecha        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        comando      VARCHAR(60),
        tg_user_id   BIGINT,
        chat_id      VARCHAR(40),
        es_privado   BOOLEAN,
        ok           BOOLEAN DEFAULT TRUE,
        error        TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_botlog_fecha ON bot_comando_log(fecha DESC);
    """

    # Migraciones idempotentes: si la tabla existe pero le faltan columnas
    # (creada con un schema viejo), las agregamos sin perder datos.
    MIGRACIONES = [
        "ALTER TABLE firmas_docentes ADD COLUMN IF NOT EXISTS hora_firma    TIME",
        "ALTER TABLE firmas_docentes ADD COLUMN IF NOT EXISTS timestamp_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE firmas_docentes ADD COLUMN IF NOT EXISTS pin_usado     VARCHAR(10)",
        "ALTER TABLE docentes        ADD COLUMN IF NOT EXISTS creado_en     TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE docentes        ADD COLUMN IF NOT EXISTS es_pgnp       BOOLEAN NOT NULL DEFAULT FALSE",
        "ALTER TABLE coberturas_docente ALTER COLUMN pgnp_id DROP NOT NULL",
        "ALTER TABLE coberturas_docente ADD COLUMN IF NOT EXISTS motivo_solicitud TEXT",
        """CREATE UNIQUE INDEX IF NOT EXISTS uq_cobertura_docente_horario_solicitada
           ON coberturas_docente(fecha, aula, turno, hora, materia)
           WHERE estado IN ('solicitada', 'pendiente', 'aprobada', 'completada')""",
        "ALTER TABLE coberturas_docente DROP CONSTRAINT IF EXISTS coberturas_docente_estado_check",
        """ALTER TABLE coberturas_docente ADD CONSTRAINT coberturas_docente_estado_check
           CHECK (estado IN ('solicitada', 'pendiente', 'aprobada', 'rechazada', 'completada', 'cancelada'))""",
        # Estado de la justificación: aprobada (Plana Mayor) / pendiente (auto-justif docente) / rechazada
        "ALTER TABLE justificaciones_ausencia ADD COLUMN IF NOT EXISTS estado       VARCHAR(20) DEFAULT 'aprobada'",
        "ALTER TABLE justificaciones_ausencia ADD COLUMN IF NOT EXISTS revisado_por VARCHAR(150)",
        "ALTER TABLE justificaciones_ausencia ADD COLUMN IF NOT EXISTS revisado_en  TIMESTAMP",
        "ALTER TABLE justificaciones_ausencia ADD COLUMN IF NOT EXISTS observacion_revision TEXT",
        # Adjuntos (certificado médico, parte de servicio, etc.) — guardamos solo el path al archivo
        "ALTER TABLE justificaciones_ausencia ADD COLUMN IF NOT EXISTS adjunto_nombre VARCHAR(255)",
        "ALTER TABLE justificaciones_ausencia ADD COLUMN IF NOT EXISTS adjunto_path   VARCHAR(500)",
        # 2FA TOTP en usuarios_admin
        "ALTER TABLE usuarios_admin ADD COLUMN IF NOT EXISTS totp_secret   VARCHAR(64)",
        "ALTER TABLE usuarios_admin ADD COLUMN IF NOT EXISTS totp_activado BOOLEAN DEFAULT FALSE",
        # Geolocalización opcional en las firmas
        "ALTER TABLE firmas_docentes ADD COLUMN IF NOT EXISTS lat          DOUBLE PRECISION",
        "ALTER TABLE firmas_docentes ADD COLUMN IF NOT EXISTS lng          DOUBLE PRECISION",
        "ALTER TABLE firmas_docentes ADD COLUMN IF NOT EXISTS precision_m  REAL",
        # Si config_json/schedule_json/ausentes_json quedaron como TEXT por schema viejo, los convertimos a JSONB
        "ALTER TABLE cronograma_maestro ALTER COLUMN config_json TYPE JSONB USING config_json::jsonb",
        "ALTER TABLE minutas ALTER COLUMN schedule_json TYPE JSONB USING schedule_json::jsonb",
        "ALTER TABLE minutas ALTER COLUMN ausentes_json TYPE JSONB USING ausentes_json::jsonb",
        # Si firmas_docentes.fecha quedó como TEXT por un schema viejo, lo convertimos a DATE
        "ALTER TABLE firmas_docentes ALTER COLUMN fecha TYPE DATE USING fecha::date",
        # Idem para minutas.fecha si está como TEXT
        "ALTER TABLE minutas         ALTER COLUMN fecha TYPE DATE USING fecha::date",
        # Si minutas.{fe, presentes, cant_ausentes} quedaron como TEXT, convertir a INTEGER
        # (necesario para SUM() y comparaciones numéricas en /ranking, /cobertura, etc.)
        """ALTER TABLE minutas ALTER COLUMN fe TYPE INTEGER
           USING CASE WHEN NULLIF(BTRIM(fe::text), '') ~ '^[+-]?[0-9]+$'
                      THEN BTRIM(fe::text)::INTEGER ELSE NULL END""",
        """ALTER TABLE minutas ALTER COLUMN presentes TYPE INTEGER
           USING CASE WHEN NULLIF(BTRIM(presentes::text), '') ~ '^[+-]?[0-9]+$'
                      THEN BTRIM(presentes::text)::INTEGER ELSE NULL END""",
        """ALTER TABLE minutas ALTER COLUMN cant_ausentes TYPE INTEGER
           USING CASE WHEN NULLIF(BTRIM(cant_ausentes::text), '') ~ '^[+-]?[0-9]+$'
                      THEN BTRIM(cant_ausentes::text)::INTEGER ELSE NULL END""",
        # Eliminar minutas duplicadas (mismo aula+fecha+turno) dejando solo la última
        """DELETE FROM minutas a USING minutas b
           WHERE a.id < b.id AND a.aula=b.aula AND a.fecha=b.fecha AND a.turno=b.turno""",
        # Garantizar unicidad: una sola minuta por aula+fecha+turno
        """DO $$ BEGIN
             IF NOT EXISTS (
                 SELECT 1 FROM pg_constraint
                 WHERE conname = 'minutas_aula_fecha_turno_unique'
                   AND conrelid = 'minutas'::regclass
             ) THEN
                 ALTER TABLE minutas
                 ADD CONSTRAINT minutas_aula_fecha_turno_unique
                 UNIQUE (aula, fecha, turno);
             END IF;
           END $$""",
        # ── Limpieza idempotente de nombres de docentes con basura (comas/espacios sueltos) ──
        r"""UPDATE firmas_docentes
            SET docente = TRIM(REGEXP_REPLACE(REGEXP_REPLACE(docente, '^[\s,.\-/()]+', '', 'g'), '[\s,.\-/()]+$', '', 'g'))
            WHERE docente ~ '^[\s,.\-/()]' OR docente ~ '[\s,.\-/()]$'""",
        r"""UPDATE docentes
            SET nombre = TRIM(REGEXP_REPLACE(REGEXP_REPLACE(nombre, '^[\s,.\-/()]+', '', 'g'), '[\s,.\-/()]+$', '', 'g'))
            WHERE nombre ~ '^[\s,.\-/()]' OR nombre ~ '[\s,.\-/()]$'""",
        r"""UPDATE justificaciones_ausencia
            SET docente = TRIM(REGEXP_REPLACE(REGEXP_REPLACE(docente, '^[\s,.\-/()]+', '', 'g'), '[\s,.\-/()]+$', '', 'g'))
            WHERE docente ~ '^[\s,.\-/()]' OR docente ~ '[\s,.\-/()]$'""",
    ]
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(DDL)
            conn.commit()  # Persistir tablas/índices ANTES de migrar
            for nombre in ('GUARDIA', 'COMISION', 'SSD', 'ENFERMEDAD', 'LICENCIA', 'OTRO'):
                cur.execute("""
                    INSERT INTO tipos_novedad (nombre)
                    VALUES (%s) ON CONFLICT (nombre) DO NOTHING
                """, (nombre,))
            conn.commit()
            for sql in MIGRACIONES:
                try:
                    cur.execute(sql)
                    # Cada migración se confirma de forma independiente: si una falla
                    # (p.ej. el ADD CONSTRAINT ya existente), su rollback no debe revertir
                    # las migraciones anteriores (ADD COLUMN totp_secret, lat/lng, adjunto_*…).
                    conn.commit()
                except Exception as me:
                    print(f"[SIPA] Migración omitida ({me}): {sql}")
                    conn.rollback()  # Solo revierte ESTA migración
        conn.commit()
        # ── Limpieza profunda del cronograma_maestro.config_json (JSONB anidado) ──
        try:
            _limpiar_nombres_en_cronograma(conn)
        except Exception as ce:
            print(f"[SIPA] Limpieza de cronograma omitida: {ce}")
            conn.rollback()
        try:
            _sembrar_catalogo_aulas(conn)
            conn.commit()
        except Exception as ae:
            print(f"[SIPA] Catálogo de aulas omitido: {ae}")
            conn.rollback()
        print("[SIPA] DB inicializada OK.")
    except Exception as e:
        print(f"[SIPA] ERROR init_db: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def _normalizar_nombre_docente(raw) -> str:
    """
    Normalización defensiva de un nombre de docente antes de guardarlo / consultarlo.

    Maneja basura común: comas/puntos/espacios sueltos al inicio o final,
    múltiples espacios internos, NBSP, comas sin espacio (`APELLIDO,NOMBRE`),
    y prefijos vacíos del estilo `, APELLIDO, NOMBRE`.

    Garantiza:
      - Sin coma, punto o espacio al inicio o al final.
      - Comas internas siempre con un espacio detrás.
      - Sin espacios dobles.
      - UPPERCASE consistente para evitar duplicados case-sensitive.
      - Cadena vacía si el input no es interpretable como nombre.
    """
    if raw is None:
        return ''
    s = str(raw).replace('\xa0', ' ').strip()
    if not s:
        return ''
    # Quita prefijos basura: comas, puntos, guiones, slashes y espacios al inicio
    s = re.sub(r'^[\s,.\-/()]+', '', s)
    # Quita sufijos basura
    s = re.sub(r'[\s,.\-/()]+$', '', s)
    # Coma sin espacio: "APELLIDO,NOMBRE" → "APELLIDO, NOMBRE"
    s = re.sub(r',(?=\S)', ', ', s)
    # Punto entre tokens como separador erróneo: "PEÑA. ARIEL" → "PEÑA, ARIEL"
    s = re.sub(r'\.(\s+[A-ZÁÉÍÓÚÑ])', r',\1', s)
    # Múltiples comas seguidas → una sola
    s = re.sub(r',\s*,+', ', ', s)
    # Espacios dobles → uno solo
    s = re.sub(r'\s{2,}', ' ', s)
    return s.strip().upper()


def _clave_nombre_visible_docente(raw) -> str:
    """Clave que conserva el orden del nombre usado por horario y firma."""
    return _sin_acentos(_normalizar_nombre_docente(raw)).casefold()


def _clave_docente_para_match(raw) -> str:
    """Normaliza los nombres para comparar firmas/cronogramas/justificaciones.
    Acepta distintas variantes de formato (con coma, sin coma, con espacios extra,
    con tildes o puntos) y devuelve un identificador estable para comparar.
    El orden de los tokens no importa: "PEREZ, JUAN" y "JUAN PEREZ" deben coincidir.
    """
    s = _normalizar_nombre_docente(raw)
    if not s:
        return ''
    s = _sin_acentos(s).upper().strip()
    tokens = [t for t in re.split(r'[\s,]+', s) if t]
    return ' '.join(sorted(tokens)).strip()


def _limpiar_nombres_en_cronograma(conn) -> int:
    """
    Recorre cronograma_maestro.config_json y limpia nombres de docentes
    con basura (comas/espacios al inicio). Idempotente: solo actualiza si cambia.
    Retorna cantidad de bloques limpiados.
    """
    patron_sucio = re.compile(r'^[\s,.\-/()]+|[\s,.\-/()]+$')
    cambios = 0
    with conn.cursor() as cur:
        cur.execute("SELECT aula, turno, config_json FROM cronograma_maestro WHERE config_json IS NOT NULL")
        filas = cur.fetchall()
        for aula, turno, cfg in filas:
            if isinstance(cfg, str):
                try:    cfg = json.loads(cfg)
                except (ValueError, TypeError): continue
            if not isinstance(cfg, list):
                continue
            mod = False
            for b in cfg:
                if not isinstance(b, dict):
                    continue
                doc = b.get('doc')
                if isinstance(doc, str) and patron_sucio.search(doc):
                    nuevo = _normalizar_nombre_docente(doc)
                    if nuevo != doc:
                        b['doc'] = nuevo
                        mod = True
                        cambios += 1
            if mod:
                cur.execute(
                    "UPDATE cronograma_maestro SET config_json = %s::jsonb WHERE aula=%s AND turno=%s",
                    (json.dumps(cfg), aula, turno)
                )
    if cambios:
        conn.commit()
        print(f"[SIPA] Cronograma: {cambios} nombre(s) de docente normalizados.")
    return cambios


init_db()


# ═══════════════════════════════════════════════════════════════════════════
# RATE LIMITING — Bloqueo por IP ante intentos de login repetidos
# ═══════════════════════════════════════════════════════════════════════════
# Estructura: { ip → {'intentos': int, 'bloqueado_hasta': datetime | None} }
_RATE_LIMIT: dict = {}
_RATE_MAX_INTENTOS = 5       # fallos antes del bloqueo
_RATE_BLOQUEO_SEG  = 300     # segundos bloqueado (5 min)

def _rl_ip() -> str:
    try:    return request.remote_addr or 'unknown'
    except Exception: return 'unknown'

def _rl_verificar() -> bool:
    """Devuelve True si la IP puede continuar, False si está bloqueada."""
    ip = _rl_ip()
    ahora = datetime.now()
    entrada = _RATE_LIMIT.get(ip)
    if not entrada:
        return True
    bloqueado_hasta = entrada.get('bloqueado_hasta')
    if bloqueado_hasta and ahora < bloqueado_hasta:
        return False
    if bloqueado_hasta and ahora >= bloqueado_hasta:
        # Bloqueo expirado — resetear
        _RATE_LIMIT.pop(ip, None)
    return True

def _rl_registrar_fallo():
    ip = _rl_ip()
    ahora = datetime.now()
    entrada = _RATE_LIMIT.setdefault(ip, {'intentos': 0, 'bloqueado_hasta': None})
    entrada['intentos'] += 1
    if entrada['intentos'] >= _RATE_MAX_INTENTOS:
        entrada['bloqueado_hasta'] = ahora + timedelta(seconds=_RATE_BLOQUEO_SEG)
        entrada['intentos'] = 0  # Resetear contador para el próximo ciclo

def _rl_limpiar_expirados():
    """Elimina entradas con bloqueo expirado (llamado desde el scheduler)."""
    ahora = datetime.now()
    expirados = [ip for ip, e in list(_RATE_LIMIT.items())
                 if not e.get('bloqueado_hasta') or e['bloqueado_hasta'] < ahora]
    for ip in expirados:
        _RATE_LIMIT.pop(ip, None)

def _rl_respuesta_bloqueada():
    """Respuesta JSON estándar para IP bloqueada."""
    return jsonify({
        'error': f'Demasiados intentos fallidos. Intente nuevamente en {_RATE_BLOQUEO_SEG // 60} minutos.'
    }), 429


# ═══════════════════════════════════════════════════════════════════════════
# UTILIDADES DE BACKEND
# ═══════════════════════════════════════════════════════════════════════════

def generar_pin_diario(aula: str, turno: str) -> str:
    hoy = datetime.now().strftime('%Y-%m-%d')
    # ¿Hay override manual del Super Usuario para este aula+turno+fecha?
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT pin_nuevo FROM pin_overrides
                WHERE aula=%s AND turno=%s AND fecha=%s
            """, (aula.upper(), turno.upper(), hoy))
            row = cur.fetchone()
            if row and row[0]:
                conn.close()
                return row[0]
        conn.close()
    except Exception:
        pass  # Si pin_overrides no existe aún, seguimos con el cálculo normal
    semilla = f"{hoy}-{aula.upper()}-{turno}-GNA-2026"
    return str(int(hashlib.md5(semilla.encode()).hexdigest(), 16))[-4:].zfill(4)


# Sal para la tabla docentes y usuarios_admin (distinta de las sales SU/Admin-maestra).
# Si se cambia PASS_SALT en .env, todos los hashes con la sal vieja dejarán de funcionar.
PASS_SALT = os.getenv("PASS_SALT", "SIPA_GNA_2026_PassSalt_v1")

def hash_password(p: str) -> str:
    """Hash para docentes y usuarios_admin.
    Si bcrypt está disponible, genera hash bcrypt (seguro contra brute-force).
    Si no, cae a SHA256+sal (compatible con instalaciones sin bcrypt)."""
    if BCRYPT_OK:
        return bcrypt.hashpw(p.encode(), bcrypt.gensalt()).decode()
    return hashlib.sha256((PASS_SALT + p + PASS_SALT).encode()).hexdigest()

def _hash_password_sha256(p: str) -> str:
    """Hash SHA256+sal — mantener para verificar hashes existentes."""
    return hashlib.sha256((PASS_SALT + p + PASS_SALT).encode()).hexdigest()

def _hash_password_legacy(p: str) -> str:
    """Hash sin sal usado antes de la v1.1 — solo para migración en login."""
    return hashlib.sha256(p.encode()).hexdigest()

def _es_hash_bcrypt(h: str) -> bool:
    """Detecta si un hash almacenado es bcrypt (empieza con $2b$ o $2a$)."""
    return h.startswith('$2b$') or h.startswith('$2a$')

def _validar_password(password: str) -> str | None:
    """Valida la fortaleza mínima de un password. Devuelve mensaje de error o None si es válido."""
    if len(password) < 8:
        return 'La contraseña debe tener al menos 8 caracteres.'
    if not re.search(r'[A-Za-z]', password):
        return 'La contraseña debe contener al menos una letra.'
    if not re.search(r'[0-9]', password):
        return 'La contraseña debe contener al menos un número.'
    return None


def _verificar_y_migrar_hash(conn, tabla: str, campo_hash: str, campo_id: str, id_val,
                              password: str, hash_almacenado: str) -> bool:
    """Comprueba si el password coincide (bcrypt, SHA256+sal, o legacy) y
    migra progresivamente al algoritmo más seguro disponible."""

    # Prioridad 1: ya es bcrypt → verificar directo
    if _es_hash_bcrypt(hash_almacenado):
        if BCRYPT_OK and bcrypt.checkpw(password.encode(), hash_almacenado.encode()):
            return True
        return False

    # Prioridad 2: SHA256+sal actual
    if hash_almacenado == _hash_password_sha256(password):
        _migrar_a_mejor_hash(conn, tabla, campo_hash, campo_id, id_val, password)
        return True

    # Prioridad 3: hash legacy sin sal
    if hash_almacenado == _hash_password_legacy(password):
        _migrar_a_mejor_hash(conn, tabla, campo_hash, campo_id, id_val, password)
        return True

    return False


def _migrar_a_mejor_hash(conn, tabla: str, campo_hash: str, campo_id: str,
                          id_val, password: str):
    """Migra silenciosamente al hash más seguro disponible (bcrypt si existe)."""
    nuevo_hash = hash_password(password)  # usa bcrypt si está disponible
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE {tabla} SET {campo_hash}=%s WHERE {campo_id}=%s",
                (nuevo_hash, id_val)
            )
        conn.commit()
    except Exception:
        pass


def verificar_pin(pin: str):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT DISTINCT aula, turno FROM cronograma_maestro")
            for aula, turno in cur.fetchall():
                if generar_pin_diario(aula, turno) == pin:
                    return aula, turno
        return None, None
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# SUPER USUARIO (TIC) — Autenticación con SHA-256 + salt, tokens en memoria
# ═══════════════════════════════════════════════════════════════════════════

# Salt institucional fijo (puede pasarse a .env). Lo unimos al password
# antes de hashear para que un dump de la BD no pueda atacarse con rainbow tables.
SU_SALT = os.getenv("SU_SALT", "SIPA_GNA_2026_TIC_Salt_v1")

# Hash del password "SU_CboCuello_TIC_2026!" — calculado offline:
#   sha256(salt + password + salt) → hex
SU_PASSWORD_HASH = os.getenv(
    "SU_PASSWORD_HASH",
    hashlib.sha256((SU_SALT + "SU_CboCuello_TIC_2026!" + SU_SALT).encode()).hexdigest()
)

# Hash para la clave de Plana Mayor (rol estándar de Administración)
# Default: "1234" — debe cambiarse vía env en producción.
ADMIN_SALT = os.getenv("ADMIN_SALT", "SIPA_GNA_2026_AdminSalt_v1")
ADMIN_PASSWORD_HASH = os.getenv(
    "ADMIN_PASSWORD_HASH",
    hashlib.sha256((ADMIN_SALT + "1234" + ADMIN_SALT).encode()).hexdigest()
)

# Tokens activos en memoria (en producción esto iría a una tabla de sesiones)
_SU_TOKENS    = {}  # token → expira_dt
_ADMIN_TOKENS = {}  # token → expira_dt
_DOCENTE_TOKENS = {}  # token → {id, nombre, es_pgnp, expira}
# Metadata de sesiones para "Quién está online" (Bloque TIC 2)
# token → {rol, usuario, ip, user_agent, login_at, last_seen}
_SESIONES_META = {}


def _registrar_sesion(tok: str, rol: str, usuario: str):
    """Guarda metadata al crear un token (login)."""
    ahora = datetime.now()
    _SESIONES_META[tok] = {
        'rol': rol,
        'usuario': usuario,
        'ip': _safe_ip(),
        'user_agent': (request.headers.get('User-Agent', '') or '')[:200] if request else '',
        'login_at': ahora.isoformat(),
        'last_seen': ahora.isoformat(),
    }


def _tocar_sesion(tok: str):
    """Actualiza last_seen al validar un token."""
    if tok in _SESIONES_META:
        _SESIONES_META[tok]['last_seen'] = datetime.now().isoformat()

def _su_hash(password: str) -> str:
    return hashlib.sha256((SU_SALT + password + SU_SALT).encode()).hexdigest()

def _su_token_valido(req) -> bool:
    tok = req.headers.get('X-SU-Token', '')
    if not tok or tok not in _SU_TOKENS:
        return False
    if _SU_TOKENS[tok] < datetime.now():
        _SU_TOKENS.pop(tok, None)
        _SESIONES_META.pop(tok, None)
        return False
    _tocar_sesion(tok)
    return True

def _exigir_su(req):
    """Devuelve None si OK, o una respuesta JSON 403 si falla."""
    if not _su_token_valido(req):
        return jsonify({'error': 'Esta operación requiere autenticación de Super Usuario (TIC).'}), 403
    return None


@app.route('/api/su/login', methods=['POST'])
def su_login():
    if not _rl_verificar():
        return _rl_respuesta_bloqueada()
    d = request.json or {}
    password = d.get('password', '')
    if not password:
        return jsonify({'error': 'Password requerido'}), 400
    if _su_hash(password) != SU_PASSWORD_HASH:
        _rl_registrar_fallo()
        _log_failed_login('su', 'Password incorrecto')
        return jsonify({'error': 'Credenciales inválidas. Acceso denegado.'}), 403
    tok = secrets.token_urlsafe(32)
    _SU_TOKENS[tok] = datetime.now() + timedelta(hours=4)
    _registrar_sesion(tok, 'super_usuario', 'TIC')
    return jsonify({
        'token':  tok,
        'rol':    'super_usuario',
        'expira': _SU_TOKENS[tok].isoformat(),
    })


@app.route('/api/su/logout', methods=['POST'])
def su_logout():
    tok = request.headers.get('X-SU-Token', '')
    _SU_TOKENS.pop(tok, None)
    _SESIONES_META.pop(tok, None)
    return jsonify({'msj': 'Sesión técnica cerrada.'})


@app.route('/api/su/validar', methods=['GET'])
def su_validar():
    """Permite al frontend confirmar que un token sigue vigente."""
    return jsonify({'valido': _su_token_valido(request)})


# ─── PLANA MAYOR (admin estándar) — login con hash, sin password en JS ───
def _admin_hash(p: str) -> str:
    return hashlib.sha256((ADMIN_SALT + p + ADMIN_SALT).encode()).hexdigest()

def _admin_token_valido(req) -> bool:
    tok = req.headers.get('X-Admin-Token', '')
    if not tok or tok not in _ADMIN_TOKENS:
        return False
    if _ADMIN_TOKENS[tok] < datetime.now():
        _ADMIN_TOKENS.pop(tok, None)
        _SESIONES_META.pop(tok, None)
        return False
    _tocar_sesion(tok)
    return True


def _docente_token_meta(req):
    token = req.headers.get('X-Docente-Token', '')
    meta = _DOCENTE_TOKENS.get(token)
    if not meta:
        return None
    if meta['expira'] < datetime.now():
        _DOCENTE_TOKENS.pop(token, None)
        _SESIONES_META.pop(token, None)
        return None
    _tocar_sesion(token)
    return meta

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    """Login en dos vías:
       - usuario + password  → busca en usuarios_admin
       - solo password       → fallback a la clave maestra .env (compat)"""
    if not _rl_verificar():
        return _rl_respuesta_bloqueada()
    d = request.json or {}
    usuario  = (d.get('usuario') or '').strip().lower()
    password = d.get('password', '')
    if not password:
        return jsonify({'error': 'Password requerido'}), 400

    # Vía 1: usuario nombrado contra la tabla
    if usuario:
        codigo_2fa = (d.get('codigo_2fa') or '').strip()
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, nombre, password_hash, activo, debe_cambiar_pass,
                           totp_secret, totp_activado
                    FROM usuarios_admin WHERE usuario=%s
                """, (usuario,))
                row = cur.fetchone()
            if row and row[3] and _verificar_y_migrar_hash(
                    conn, 'usuarios_admin', 'password_hash', 'id', row[0], password, row[2]):
                # Si tiene 2FA activado, validar el código
                if row[6] and row[5]:
                    if not codigo_2fa:
                        return jsonify({
                            'requiere_2fa': True,
                            'mensaje': 'Ingrese el código de 6 dígitos de su autenticador.'
                        }), 401
                    if not _totp_verificar(row[5], codigo_2fa):
                        _rl_registrar_fallo()
                        _log_failed_login('admin', f'2FA incorrecto: {usuario}')
                        return jsonify({'error':'Código 2FA inválido'}), 403
                # Actualizar último_login
                with conn.cursor() as cur:
                    cur.execute("UPDATE usuarios_admin SET ultimo_login=CURRENT_TIMESTAMP WHERE id=%s",(row[0],))
                conn.commit()
                tok = secrets.token_urlsafe(24)
                _ADMIN_TOKENS[tok] = datetime.now() + timedelta(hours=8)
                _ADMIN_TOKENS[tok+'__user'] = {'id': row[0], 'nombre': row[1], 'usuario': usuario}
                _registrar_sesion(tok, 'plana_mayor', usuario)
                _log_audit(usuario, 'plana_mayor', 'LOGIN_OK', 'usuarios_admin', f'id={row[0]}', None)
                return jsonify({
                    'token': tok, 'rol': 'plana_mayor',
                    'usuario': usuario, 'nombre': row[1],
                    'debe_cambiar_pass': bool(row[4]),
                })
            _rl_registrar_fallo()
            _log_failed_login('admin', f'usuario={usuario}')
            return jsonify({'error':'Usuario o clave incorrectos.'}), 403
        finally:
            conn.close()

    # Vía 2: solo password contra hash maestro (compat)
    if _admin_hash(password) != ADMIN_PASSWORD_HASH:
        _rl_registrar_fallo()
        _log_failed_login('admin', 'Password incorrecto (clave maestra)')
        return jsonify({'error': 'Clave incorrecta.'}), 403
    tok = secrets.token_urlsafe(24)
    _ADMIN_TOKENS[tok] = datetime.now() + timedelta(hours=8)
    _ADMIN_TOKENS[tok+'__user'] = {'id': 0, 'nombre': 'Clave Maestra', 'usuario': 'admin'}
    _registrar_sesion(tok, 'plana_mayor', 'admin (Clave Maestra)')
    return jsonify({'token': tok, 'rol': 'plana_mayor', 'usuario':'admin', 'nombre':'Clave Maestra'})


# CRUD de usuarios admin (sólo SU puede gestionar)
@app.route('/api/su/usuarios_admin', methods=['GET'])
def su_listar_usuarios_admin():
    err = _exigir_su(request)
    if err: return err
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, usuario, nombre, rol, activo, debe_cambiar_pass,
                       creado_por, creado_en::text, ultimo_login::text
                FROM usuarios_admin ORDER BY usuario
            """)
            cols = [c[0] for c in cur.description]
            geo_params = _cargar_params()
            resultado = []
            for r in cur.fetchall():
                item = dict(zip(cols, r))
                geo = _clasificar_geolocalizacion(
                    item.get('lat'), item.get('lng'), item.get('precision_m'), geo_params
                )
                item['geo_estado'] = geo['estado']
                item['geo_mensaje'] = geo['mensaje']
                item['geo_distancia_m'] = geo['distancia_m']
                resultado.append(item)
            return jsonify(resultado)
    finally:
        conn.close()

@app.route('/api/su/usuarios_admin', methods=['POST'])
def su_crear_usuario_admin():
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    usuario  = (d.get('usuario') or '').strip().lower()
    nombre   = (d.get('nombre')  or '').strip()
    password = d.get('password') or secrets.token_urlsafe(8)[:8]
    rol      = (d.get('rol') or 'plana_mayor').strip()
    if not re.match(r'^[a-z0-9._-]{3,40}$', usuario):
        return jsonify({'error':'Usuario inválido (3-40 chars, minúsculas/dígitos/._-)'}), 400
    if not nombre:
        return jsonify({'error':'Nombre requerido'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO usuarios_admin (usuario, nombre, password_hash, rol, debe_cambiar_pass, creado_por)
                VALUES (%s,%s,%s,%s,TRUE,%s)
                ON CONFLICT (usuario) DO NOTHING
                RETURNING id
            """, (usuario, nombre, hash_password(password), rol, 'TIC'))
            row = cur.fetchone()
        if not row:
            conn.rollback()
            return jsonify({'error':'Ya existe un usuario con ese nombre.'}), 409
        conn.commit()
        _log_audit('TIC','super_usuario','CREAR_USUARIO_ADMIN','usuarios_admin', usuario, f'nombre={nombre}, rol={rol}')
        return jsonify({'msj': f'Usuario "{usuario}" creado.', 'password_inicial': password})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/su/usuarios_admin/<int:uid>', methods=['DELETE'])
def su_eliminar_usuario_admin(uid):
    err = _exigir_su(request)
    if err: return err
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM usuarios_admin WHERE id=%s RETURNING usuario", (uid,))
            row = cur.fetchone()
        if not row: return jsonify({'error':'No existe.'}), 404
        conn.commit()
        _log_audit('TIC','super_usuario','ELIMINAR_USUARIO_ADMIN','usuarios_admin', row[0])
        return jsonify({'msj': f'Usuario "{row[0]}" eliminado.'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/su/usuarios_admin/<int:uid>/toggle', methods=['POST'])
def su_toggle_usuario_admin(uid):
    err = _exigir_su(request)
    if err: return err
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE usuarios_admin SET activo = NOT activo WHERE id=%s RETURNING usuario, activo", (uid,))
            row = cur.fetchone()
        if not row: return jsonify({'error':'No existe.'}), 404
        conn.commit()
        _log_audit('TIC','super_usuario','TOGGLE_USUARIO_ADMIN','usuarios_admin', row[0], f'activo={row[1]}')
        return jsonify({'msj': f'Usuario {row[0]} ahora {"ACTIVO" if row[1] else "INACTIVO"}'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/su/usuarios_admin/<int:uid>/reset_pass', methods=['POST'])
def su_reset_usuario_admin(uid):
    err = _exigir_su(request)
    if err: return err
    nueva = (request.json or {}).get('password') or ''
    if nueva:
        err_pwd = _validar_password(nueva)
        if err_pwd:
            return jsonify({'error': err_pwd}), 400
    else:
        nueva = secrets.token_urlsafe(10)[:10]
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE usuarios_admin SET password_hash=%s, debe_cambiar_pass=TRUE
                WHERE id=%s RETURNING usuario
            """, (hash_password(nueva), uid))
            row = cur.fetchone()
        if not row: return jsonify({'error':'No existe.'}), 404
        conn.commit()
        _log_audit('TIC','super_usuario','RESET_PASS_ADMIN','usuarios_admin', row[0])
        return jsonify({'msj': f'Password reseteado para "{row[0]}"', 'nueva_password': nueva})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    tok = request.headers.get('X-Admin-Token', '')
    info = _ADMIN_TOKENS.pop(tok+'__user', None)
    _ADMIN_TOKENS.pop(tok, None)
    _ADMIN_TOKENS.pop(tok+'__impersonacion', None)
    if info:
        _log_audit(info.get('usuario','?'), 'plana_mayor', 'LOGOUT', None, None, None)
    return jsonify({'msj': 'Sesión cerrada.'})

@app.route('/api/admin/validar', methods=['GET'])
def admin_validar():
    return jsonify({'valido': _admin_token_valido(request)})


# ═══════════════════════════════════════════════════════════════════════════
# 2FA TOTP (RFC 6238) — implementación nativa sin nuevas dependencias
# ═══════════════════════════════════════════════════════════════════════════
import base64, hmac, struct, time as _time

def _totp_b32_generar_secret(longitud_bytes=20):
    """Genera un secret aleatorio de 20 bytes y lo devuelve en Base32 sin '='."""
    return base64.b32encode(secrets.token_bytes(longitud_bytes)).decode().rstrip('=')

def _totp_codigo(secret_b32, paso=30, digitos=6, t=None):
    """Calcula el código TOTP de 6 dígitos para 'secret_b32' (Base32) según RFC 6238."""
    if t is None: t = _time.time()
    # Reconstruir padding base32
    pad = '=' * ((8 - len(secret_b32) % 8) % 8)
    try:
        key = base64.b32decode(secret_b32 + pad, casefold=True)
    except Exception:
        return None
    contador = int(t // paso)
    msg = struct.pack('>Q', contador)
    h = hmac.new(key, msg, 'sha1').digest()
    offset = h[-1] & 0x0F
    val = struct.unpack('>I', h[offset:offset+4])[0] & 0x7FFFFFFF
    return str(val % (10 ** digitos)).zfill(digitos)

def _totp_verificar(secret_b32, codigo_usuario, ventana=1):
    """Verifica que el código coincida (acepta ±1 paso de 30s = ±30s de drift)."""
    if not secret_b32 or not codigo_usuario:
        return False
    codigo_usuario = str(codigo_usuario).strip()
    ahora = _time.time()
    for delta in range(-ventana, ventana + 1):
        if _totp_codigo(secret_b32, t=ahora + delta * 30) == codigo_usuario:
            return True
    return False


@app.route('/api/su/2fa/setup', methods=['POST'])
def su_2fa_setup():
    """Genera un secret TOTP para el usuario admin indicado.
       Devuelve el secret + URL otpauth para escanear con Google Authenticator."""
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    uid = d.get('uid')
    if not uid:
        return jsonify({'error': 'Falta uid del usuario admin'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT usuario, nombre FROM usuarios_admin WHERE id=%s", (uid,))
            row = cur.fetchone()
            if not row:
                return jsonify({'error': 'Usuario no encontrado'}), 404
            usuario, nombre = row
            secret = _totp_b32_generar_secret()
            cur.execute("""
                UPDATE usuarios_admin SET totp_secret=%s, totp_activado=FALSE WHERE id=%s
            """, (secret, uid))
        conn.commit()
        issuer = 'SIPA-GNA'
        label  = f'{issuer}:{usuario}'
        url_otpauth = (
            f'otpauth://totp/{label}?secret={secret}'
            f'&issuer={issuer}&algorithm=SHA1&digits=6&period=30'
        )
        _log_audit('TIC', 'super_usuario', '2FA_SETUP', 'usuarios_admin',
                   f'usuario={usuario}', 'Secret generado, pendiente verificación')
        return jsonify({
            'secret': secret,
            'usuario': usuario,
            'nombre': nombre,
            'otpauth_url': url_otpauth,
            'mensaje': 'Escanee el QR con Google Authenticator y luego verifique con un código de 6 dígitos para activar.',
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/su/2fa/verify', methods=['POST'])
def su_2fa_verify():
    """Verifica que el código TOTP es correcto y activa el 2FA para el usuario."""
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    uid = d.get('uid')
    codigo = (d.get('codigo') or '').strip()
    if not uid or not codigo:
        return jsonify({'error': 'uid y codigo son requeridos'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT usuario, totp_secret FROM usuarios_admin WHERE id=%s", (uid,))
            row = cur.fetchone()
            if not row or not row[1]:
                return jsonify({'error': 'Primero llame a /setup para generar el secret'}), 400
            usuario, secret = row
            if not _totp_verificar(secret, codigo):
                return jsonify({'error': 'Código incorrecto. Verifique la hora de su teléfono.'}), 400
            cur.execute("UPDATE usuarios_admin SET totp_activado=TRUE WHERE id=%s", (uid,))
        conn.commit()
        _log_audit('TIC', 'super_usuario', '2FA_ACTIVADO', 'usuarios_admin',
                   f'usuario={usuario}', None)
        return jsonify({'msj': f'2FA activado correctamente para {usuario}'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/su/2fa/disable', methods=['POST'])
def su_2fa_disable():
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    uid = d.get('uid')
    if not uid: return jsonify({'error':'uid requerido'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE usuarios_admin SET totp_activado=FALSE, totp_secret=NULL
                WHERE id=%s RETURNING usuario
            """, (uid,))
            row = cur.fetchone()
        if not row: return jsonify({'error':'No existe'}), 404
        conn.commit()
        _log_audit('TIC','super_usuario','2FA_DESACTIVADO','usuarios_admin', row[0])
        return jsonify({'msj': f'2FA desactivado para {row[0]}'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# HELPERS DE LOGGING (audit + failed logins + sistema)
# ═══════════════════════════════════════════════════════════════════════════
def _safe_ip():
    try:    return request.remote_addr or '?'
    except Exception: return '?'

def _safe_path():
    try:    return request.path or '?'
    except Exception: return '?'

def _log_json(level: str, event: str, **extra):
    """Emite un log estructurado JSON a stdout (para ELK/Grafana/journald)."""
    entry = {
        'ts': datetime.now().isoformat(),
        'level': level,
        'event': event,
        'pid': os.getpid(),
    }
    entry.update({k: v for k, v in extra.items() if v is not None})
    try:
        print(json.dumps(entry, ensure_ascii=False, default=str), flush=True)
    except Exception:
        pass

def _log_audit(usuario, rol, accion, tabla=None, registro_ref=None, detalle=None):
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO audit_log (usuario, rol, accion, tabla, registro_ref, detalle, ip)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
            """, (usuario or '?', rol or 'desconocido', accion,
                  tabla, registro_ref, detalle, _safe_ip()))
        conn.commit()
        conn.close()
    except Exception:
        pass
    _log_json('INFO', 'audit', usuario=usuario, rol=rol, accion=accion,
              tabla=tabla, ref=registro_ref, ip=_safe_ip())

def _log_failed_login(tipo, detalle=''):
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO failed_logins (tipo, detalle, ip)
                VALUES (%s,%s,%s)
            """, (tipo, detalle, _safe_ip()))
        conn.commit()
        conn.close()
        # Notificar a Telegram si supera umbral (sin bloquear el login)
        try:
            threading.Thread(target=_tg_check_login_sospechoso, daemon=True).start()
        except Exception:
            pass
    except Exception:
        pass

def _log_system(nivel, mensaje, traceback_txt=None):
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO system_log (nivel, endpoint, mensaje, traceback)
                VALUES (%s,%s,%s,%s)
            """, (nivel, _safe_path(),
                  (mensaje or '')[:2000], (traceback_txt or '')[:6000]))
        conn.commit()
        conn.close()
    except Exception:
        pass
    _log_json(nivel, 'system', endpoint=_safe_path(), mensaje=mensaje)


# ═══════════════════════════════════════════════════════════════════════════
# MODO MANTENIMIENTO — middleware global
# ═══════════════════════════════════════════════════════════════════════════
_MAINT_BYPASS_PATHS = (
    '/api/su/',          # Endpoints SU siempre accesibles
    '/api/admin/login',  # Plana Mayor puede loguearse
    '/api/sse/',         # Stream SSE para monitor en vivo
    '/api/kiosko/',      # Pantalla pública del hall — solo lectura
    '/static/',          # Recursos estáticos
    '/api/parametros_publicos',
)

@app.before_request
def _check_maintenance_mode():
    # Sólo aplicamos a /api/*
    path = request.path or ''
    if not path.startswith('/api/'):
        return None
    if any(path.startswith(p) for p in _MAINT_BYPASS_PATHS):
        return None
    # Si hay token SU válido, dejamos pasar (TIC siempre puede operar)
    if _su_token_valido(request):
        return None
    # Consultamos la bandera
    try:
        params = parametros if parametros is not None else _cargar_params()
        if params.get('modo_mantenimiento', {}).get('valor', '0') == '1':
            return jsonify({
                'error': 'Sistema en mantenimiento. Vuelva a intentar en unos minutos.',
                'mantenimiento': True,
            }), 503
    except Exception:
        pass
    return None


# Cabeceras de seguridad en todas las respuestas HTTP
@app.after_request
def _security_headers(response):
    response.headers['X-Frame-Options']        = 'SAMEORIGIN'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-XSS-Protection']       = '1; mode=block'
    response.headers['Referrer-Policy']        = 'strict-origin-when-cross-origin'
    # CSP permisivo para SPA con recursos inline (estilos e imágenes propios)
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'self';"
    )
    return response


# Errores no manejados → log al sistema
@app.errorhandler(500)
def _handle_500(e):
    _log_system('ERROR', str(e), _traceback.format_exc())
    return jsonify({'error': 'Error interno', 'detalle': str(e)}), 500


# ═══════════════════════════════════════════════════════════════════════════
# ██████  PARSER WORD  ██████
# ═══════════════════════════════════════════════════════════════════════════

HORA_RE = re.compile(r'(\d{3,4})\s*[-\u2013]\s*(\d{3,4})')

# Tipos de comillas tipográficas que usa Word al cerrar "21"
_COMILLAS = '\u201c\u201d\u2018\u2019\u201e\u201f\u00ab\u00bb"\''

_DIA_MAP_RAW = {
    'LUNES': 'Lunes',   'LUN': 'Lunes',   'L U N E S': 'Lunes',
    'MARTES': 'Martes', 'MAR': 'Martes',  'M A R T E S': 'Martes',
    'MIERCOLES': 'Miércoles', 'MIÉRCOLES': 'Miércoles',
    'MIE': 'Miércoles', 'MIÉ': 'Miércoles',
    'M I E R C O L E S': 'Miércoles', 'M I É R C O L E S': 'Miércoles',
    'JUEVES': 'Jueves', 'JUE': 'Jueves', 'J U E V E S': 'Jueves',
    'VIERNES': 'Viernes', 'VIE': 'Viernes', 'V I E R N E S': 'Viernes',
    'SABADO': 'Sábado', 'SÁBADO': 'Sábado', 'SAB': 'Sábado',
}

# Grados militares a eliminar del inicio de un nombre
_GRADO_RE = re.compile(
    r'^('
    r'SGTO\.?\s*AY\.?|SGTO\.?|'
    r'SARG\.?\s*1RO\.?|SARG\.?\s*AY\.?|SARG\.?|'
    r'STO\.?\s*1RO\.?|STO\.?\s*1°|STO\.?|'
    r'SRO\.?|SRTO\.?|'
    r'CBO\.?\s*1RO\.?|CBO\.?|CABO\s*1RO\.?|CABO\.?|'
    r'2DO\.?\s*CTE\.?|'
    r'1ER\.?\s*ALF\.?|1°\s*ALF\.?|1ER\s+ALF\.?|'
    r'ALF\.?|SUBALF\.?|'
    r'SUB-?OF\.?\s*PR\.?|SUBOF\.?\s*PR\.?|'
    r'CRO\.?|1RO\.?|1ER\.?'
    r')\s*',
    re.I
)

_ORDEN_RE   = re.compile(r'\(?\s*ORDEN\s+CERRADO\s*\)?', re.I)
_TURNO_NOTA = re.compile(r'\bSE\s+DICTA\s+EN\s+AULA\b.*', re.I)
_DESIGNAR_RE = re.compile(r'profesor\s+a\s+designar', re.I)
_CUATR_RE    = re.compile(
    r'\(\s*(?:1|2)\s*[°º]?\s*[Cc](?:[°º]?\s*(?:uatrimestre)?)?\s*\)',
    re.I
)
_PAREN_FINAL_DOC_RE = re.compile(r'\(([^)]{2,80})\)\s*$')

# Vocabulario de materias (para separar asig de nombre de docente en 1 línea)
_PALABRAS_MATERIA = {
    'USO','RACIONAL','LA','FUERZA','DE','DEL','III','II','I',
    'CONSTRUCCIÓN','CONSTRUCCION','ROL','PROFESIONAL',
    'PROMOCIÓN','PROMOCION','SALUD','ENTRENAMIENTO','FÍSICO','FISICO',
    'HISTORIA','SIST','SEG','ARG','PREVENCIÓN','PREVENCION','PREV','DELITO',
    'IDIOMA','EXTRANJERO','TALLER','CRIMINALÍSTICA','CRIMINALISTICA',
    'CRIMINAL','ANÁLISIS','ANALISIS','INFORMACIÓN','INFORMACION',
    'Y','EN','LOS','SISTEMAS','INVESTIGACIÓN','INVESTIGACION',
    'PROCEDIMIENTOS','PARA','GESTIÓN','GESTION','SEGURIDAD',
    'VIAL','ESTADÍSTICA','ESTADISTICA','ACCIDENTOLOGÍA','ACCIDENTOLOGIA',
    'PSICOLOGÍA','PSICOLOGIA','APLICADA','CRIMINOLOGÍA','CRIMINOLOGIA',
    'DOCUMENTOLOGÍA','DOCUMENTOLOGIA','QUÍMICA','QUIMICA','ORGÁNICA','ORGANICA',
    'PAPILOSCOPÍA','PAPILOSCOPÌA','CONTABILIDAD','PÚBLICA','PUBLICA',
    'ECONOMÍA','ECONOMIA','FINANZAS','LEGISLACIÓN','LEGISLACION',
    'PRÁCTICA','PRACTICA','IMPOSITIVA','COMUNICACIONES','INGLÉS','INGLES',
    'TÉCNICO','TECNICO','FRANCÉS','FRANCES','INFORMÁTICA','INFORMATICA',
    'ORDEN','CERRADO','TURNO','TARDE','MAÑANA','AULA','TUSPYC','DICTA',
    'SE','OSP','INF','AN','PERIT','CALIGRÁF','TECNOLOGÍAS','TECNOLOGIAS',
    'GESTIÓN','GESTION','SIST.','INF.','LAS','SUS','EL',
}


def _sin_acentos(txt: str) -> str:
    n = unicodedata.normalize('NFD', txt)
    return ''.join(c for c in n if unicodedata.category(c) != 'Mn')


def _normalizar_dia(raw: str) -> str:
    """Acepta L U N E S, Lun, LUNES, Lunes, Mar, etc."""
    compacto = re.sub(r'\n', ' ', raw).strip()
    # Unir letras sueltas separadas por espacio: "L U N E S" → "LUNES"
    compacto = re.sub(r'(?<=[A-ZÁÉÍÓÚa-záéíóú]) (?=[A-ZÁÉÍÓÚa-záéíóú])', '', compacto)
    compacto = _sin_acentos(compacto.upper())
    for key, val in _DIA_MAP_RAW.items():
        if _sin_acentos(key.upper()) in compacto:
            return val
    return ''


def _normalizar_hora(h: str) -> str:
    """'0720' → '07:20'. Corrige typos MM>=60 → '00'."""
    h = h.strip().zfill(4)
    hh, mm = h[:2], h[2:]
    if int(mm) >= 60:
        mm = '00'
    return f"{hh}:{mm}"


def _limpiar_nombre(raw: str) -> str:
    """Quita grado militar, (ORDEN CERRADO), paréntesis sueltos y basura."""
    s = raw.replace('\xa0', ' ').strip()
    if _DESIGNAR_RE.search(s):
        return ''
    s = _ORDEN_RE.sub('', s)
    s = _TURNO_NOTA.sub('', s)
    # Punto como separador de apellido: "PEÑA. ARIEL" → "PEÑA, ARIEL"
    s = re.sub(r'\.(\s+[A-ZÁÉÍÓÚA-Z])', r',\1', s)
    s = re.sub(r'^\s*\([^)]{0,12}\)\s*', '', s)  # "(1C) NOMBRE" → "NOMBRE"
    s = re.sub(r'^\s*\)\s*', '', s)                 # ") NOMBRE"   → "NOMBRE"
    s = _GRADO_RE.sub('', s)
    # Limpieza de bordes: caracteres no-letras (comas, puntos, espacios, guiones, paréntesis)
    s = re.sub(r'^[-/\s(,.]+|[-/\s.,()]+$', '', s)
    # Si quedó otra coma o punto al inicio después de la limpieza, repetir
    s = re.sub(r'^[,.\s]+', '', s)
    s = re.sub(r'\s*[-–/]\s*AULA\s+\d+.*$', '', s, flags=re.I)
    s = re.sub(r'\s{2,}', ' ', s).strip()
    # Normalizar coma sin espacio: "APELLIDO,NOMBRE" → "APELLIDO, NOMBRE"
    s = re.sub(r',(?=\S)', ', ', s)
    return s.upper()


# Fragmentos de nombres de asignaturas que no son docentes
_FRAGMENTOS_ASIG = frozenset({
    'CRIMIN', 'PERIT', 'PAPILO', 'PSICOL', 'CALIGRAF', 'DOCUM',
    'CRIM', 'INVEST', 'PROCED', 'LEGI', 'INFORM',
})


def _es_ruido(txt: str) -> bool:
    if not txt or len(txt) < 2:
        return True
    letras = re.sub(r'[^A-ZÁÉÍÓÚa-záéíóú]', '', txt)
    if len(letras) < 2:
        return True
    if re.fullmatch(r'[\d\s.TM/\-–°ºC]+', txt):
        return True
    if re.search(r'\b(TURNO|TARDE|MAÑANA|TUSPYC|T\.M\.?|T\.T\.?)\b', txt.upper()):
        return True
    # Fragmento suelto de nombre de asignatura (ej. "CRIMIN", "PERIT")
    toks = re.sub(r'[^A-ZÁÉÍÓÚ]', ' ', txt.upper()).split()
    if len(toks) == 1 and toks[0] in _FRAGMENTOS_ASIG:
        return True
    return False


# ── PARSEO DE HEADER DE COLUMNA DE AULA ─────────────────────────────────────

def _parse_header_aula(txt: str) -> dict:
    """
    Extrae de '3º TUSPyC "17"' o '3º TUSPCIC  "22"':
      numero      → '17'
      anio        → '3'
      orientacion → 'TUSPyC'
      idioma      → '' | 'FRANCÉS' | 'INGLES'
    Soporta comillas tipográficas de Word y espacios no-breakables (\xa0).
    """
    txt = txt.replace('\xa0', ' ').strip()

    # Número de aula: entre cualquier par de comillas
    m_num = re.search(
        r'[' + _COMILLAS + r'](\d+)[' + _COMILLAS + r']',
        txt
    )
    # Fallback: número de 2-3 dígitos suelto si no hay comillas
    if not m_num:
        m_num = re.search(r'\b(\d{2,3})\b', txt)
    numero = m_num.group(1) if m_num else None

    # Año: dígito antes de º/°
    m_anio = re.search(r'(\d)[°º]', txt)
    anio   = m_anio.group(1) if m_anio else '3'

    # Idioma si está explícito
    m_id = re.search(r'\b(FRANC[EÉ]S|INGLES|INGL[EÉ]S|PORTUGU[EÉ]S)\b', txt, re.I)
    idioma = m_id.group(1).upper() if m_id else ''

    # Orientación: sigla tipo TUSP* en mayúsculas (quitar año, numero, idioma)
    limpio = re.sub(r'\d[°º]\s*', '', txt)
    limpio = re.sub(r'[' + _COMILLAS + r']\d+[' + _COMILLAS + r']', '', limpio)
    if numero:
        limpio = re.sub(r'\b' + numero + r'\b', '', limpio)
    if idioma:
        limpio = re.sub(idioma, '', limpio, flags=re.I)
    orientacion = re.sub(r'\s+', ' ', limpio).strip().strip('"\'')

    return {
        'numero':      numero,
        'anio':        anio,
        'orientacion': orientacion,
        'idioma':      idioma,
    }


# ── HELPERS DE PARSEO DE CELDA ───────────────────────────────────────────────

def _dividir_por_slash(texto: str) -> list:
    """Divide 'MATE1 (1°C) / MATE2 (2°C)' respetando paréntesis."""
    partes, actual, nivel = [], [], 0
    for c in texto:
        if c == '(':
            nivel += 1; actual.append(c)
        elif c == ')':
            nivel = max(0, nivel - 1); actual.append(c)
        elif c == '/' and nivel == 0:
            parte = ''.join(actual).strip()
            if parte:
                partes.append(parte)
            actual = []
        else:
            actual.append(c)
    if actual:
        parte = ''.join(actual).strip()
        if parte:
            partes.append(parte)
    return partes if partes else [texto]


def _doc_desde_linea(linea: str):
    """
    Dada una línea que contiene asignatura + posible docente,
    devuelve (asignatura_limpia, docente_limpio).
    Estrategias (en orden):
      1. "profesor a designar" → docente vacío
      2. Paréntesis al final: 'MATERIA (DOCENTE)' si el contenido no es cuatrimestre
      3. Dos o más espacios: 'MATERIA   DOCENTE'
      4. Después del último marcador de cuatrimestre: 'MATERIA (1°C) DOCENTE'
      5. Vocabulario: último token que no es palabra de materia
    """
    linea = linea.replace('\xa0', ' ').strip()
    linea = _TURNO_NOTA.sub('', linea).strip()

    # Estrategia 1
    if _DESIGNAR_RE.search(linea):
        asig = _CUATR_RE.sub('', linea)
        asig = _DESIGNAR_RE.sub('', asig)
        return re.sub(r'\s{2,}', ' ', asig).strip().rstrip('.,/ '), ''

    # Estrategia 2: paréntesis final que no sea cuatrimestre
    m = _PAREN_FINAL_DOC_RE.search(linea)
    if m and not _CUATR_RE.fullmatch(m.group(0).strip()):
        contenido = m.group(1).strip()
        doc_c = _limpiar_nombre(contenido)
        if doc_c and not _es_ruido(doc_c):
            asig = linea[:m.start()].strip().rstrip('–- ')
            asig = _CUATR_RE.sub('', asig).strip()
            return re.sub(r'\s{2,}', ' ', asig).strip(), doc_c

    # Estrategia 3: doble espacio (o \xa0 ya normalizado) como separador
    m3 = re.search(r'  +', linea)
    if m3:
        parte_asig = linea[:m3.start()].strip()
        parte_doc  = linea[m3.end():].strip()
        doc_c = _limpiar_nombre(parte_doc)
        if doc_c and not _es_ruido(doc_c):
            asig = _CUATR_RE.sub('', parte_asig).strip()
            return re.sub(r'\s{2,}', ' ', asig).strip(), doc_c

    # Estrategia 4: después del último marcador de cuatrimestre
    matches = list(_CUATR_RE.finditer(linea))
    if matches:
        ultimo = matches[-1]
        resto = linea[ultimo.end():].strip()
        doc_c = _limpiar_nombre(resto)
        if doc_c and not _es_ruido(doc_c):
            asig = _CUATR_RE.sub('', linea).strip()
            return re.sub(r'\s{2,}', ' ', asig).strip(), doc_c

    # Estrategia 5: vocabulario de materias
    sin_p  = re.sub(r'\([^)]*\)', '', linea).strip()
    tokens = sin_p.split()
    i_split = len(tokens)
    for i in range(len(tokens) - 1, -1, -1):
        tok = _sin_acentos(tokens[i]).upper().rstrip('.,/°')
        if tok in _PALABRAS_MATERIA:
            break
        i_split = i
    asig  = re.sub(r'\s*\([^)]*\)', '', ' '.join(tokens[:i_split])).strip()
    doc_r = ' '.join(tokens[i_split:]).strip()
    doc_c = _limpiar_nombre(doc_r)
    asig  = re.sub(r'[-/]\s*$', '', asig).strip()
    if _es_ruido(doc_c):
        doc_c = ''
    return re.sub(r'\s{2,}', ' ', asig).strip(), doc_c


# ── PARSEO DE CELDA DE HORARIO ───────────────────────────────────────────────

def _parse_celda(celda) -> list:
    """
    Recibe el objeto celda de python-docx (no el texto plano).
    Devuelve lista de {'asig': str, 'doc_raw': str}.

    ESTRATEGIA:
      A) ≥2 párrafos, último párrafo parece docente → primeros=asig, último=docente
         (incluye: limpiar leading '/' en párrafos intermedios, herencia de docente
          entre tramos cuando hay slash interno en párrafos de asig)
      B) 1 párrafo (o fallback) → normalizar \xa0, dividir por slash respetando
         paréntesis, aplicar _doc_desde_linea a cada tramo, heredar último docente
         conocido a tramos sin docente.
    """
    # Normalizar \xa0 en todos los párrafos
    parrafos = []
    for p in celda.paragraphs:
        txt = p.text.replace('\xa0', ' ').strip()
        if txt:
            parrafos.append((p, txt))

    if not parrafos:
        return []

    resultados = []

    # ── CASO A: múltiples párrafos ───────────────────────────────────────────
    if len(parrafos) >= 2:
        ultimo_txt = parrafos[-1][1]
        doc_l = _limpiar_nombre(ultimo_txt)

        # Decidir si el último párrafo es realmente el docente:
        # - no contiene marcador de cuatrimestre
        # - no parece vocabulario de materia (primer token)
        es_docente = False
        if not _CUATR_RE.search(ultimo_txt):
            primer_tok = _sin_acentos(ultimo_txt.split()[0]).upper().rstrip('.,')
            if primer_tok not in _PALABRAS_MATERIA:
                es_docente = True

        if es_docente:
            # Párrafos intermedios son asignaturas (pueden tener slash entre sí)
            lineas_asig = []
            for _, txt in parrafos[:-1]:
                txt = re.sub(r'^[/\s]+', '', txt).strip()  # limpiar '/' inicial
                if txt:
                    lineas_asig.append(txt)

            # Unir con ' / ' y dividir de nuevo respetando paréntesis
            texto_asig = ' / '.join(lineas_asig)
            tramos = _dividir_por_slash(texto_asig)
            for tramo in tramos:
                tramo = _CUATR_RE.sub('', tramo).strip()
                tramo = re.sub(r'[-/\s]+$', '', tramo).strip()
                if tramo:
                    resultados.append({'asig': tramo, 'doc_raw': doc_l})
            return resultados

        # Si el último no parece docente, tratar todos los párrafos como líneas
        # y caer al caso B con el texto completo
        texto_completo = ' / '.join(txt for _, txt in parrafos)
    else:
        texto_completo = parrafos[0][1]

    # ── CASO B: línea(s) únicas o fallback ──────────────────────────────────
    tramos = _dividir_por_slash(texto_completo)
    ultimo_doc = ''
    for tramo in tramos:
        tramo = re.sub(r'^[/\s]+', '', tramo).strip()
        if not tramo:
            continue
        asig, doc = _doc_desde_linea(tramo)
        if not doc and ultimo_doc:
            doc = ultimo_doc
        if doc:
            ultimo_doc = doc
        asig = re.sub(r'\s{2,}', ' ', asig).strip()
        if asig and not _es_ruido(asig):
            resultados.append({'asig': asig, 'doc_raw': doc})

    return resultados


# ── CANONICALIZACIÓN DE NOMBRES ──────────────────────────────────────────────

def _similitud(a: str, b: str) -> float:
    return SequenceMatcher(
        None, _sin_acentos(a).lower(), _sin_acentos(b).lower()
    ).ratio()


# Primeros nombres muy comunes que NO son apellidos
_NOMBRES_PROPIOS = {
    # masculinos
    'JUAN', 'JOSE', 'LUIS', 'CARLOS', 'PABLO', 'JORGE', 'PEDRO', 'DIEGO',
    'OMAR', 'HUGO', 'OSCAR', 'DANIEL', 'SERGIO', 'GUSTAVO', 'MARIO',
    'ARIEL', 'FABIO', 'FABIAN', 'RAUL', 'IVAN', 'RUBEN', 'HERNAN',
    'MARTIN', 'WALTER', 'MARCELO', 'JAVIER', 'LUCAS', 'MAURO', 'JESUS',
    'ORLANDO', 'MAXIMILIANO', 'LEONARDO', 'NOLBERTO', 'ALBANO', 'TOMAS',
    'DAMIAN', 'MILTON', 'GERMAN', 'RAFAEL', 'ALEJANDRO', 'CRISTIAN',
    'MATIAS', 'RAMON', 'MARCOS', 'JULIAN', 'LUCIO', 'ALEXIS', 'ROMAN',
    'ELICEO', 'ETANISLAO', 'EUGENIO', 'VALENTIN', 'FEDERICO', 'ROBERTO',
    'ALBERTO', 'NICOLAS', 'EMILIO', 'SEBASTIAN', 'GERARDO', 'ERNESTO',
    'CLAUDIO', 'GABRIEL', 'MIGUEL', 'FRANCISCO', 'EDUARDO', 'ANDRES',
    # femeninos
    'MARIA', 'ANA', 'SILVANA', 'SILVIA', 'CECILIA', 'ANDREA', 'PATRICIA',
    'CLAUDIA', 'YANINA', 'PAOLA', 'CANDIDA', 'MARCIA', 'IVANA', 'ROXANA',
    'SILVINA', 'YENIFER', 'MONICA', 'ELBINA', 'ANALIA', 'VERONICA',
    'LORENA', 'NATALIA', 'ALEJANDRA', 'JULIETA', 'ROMINA',
}


def _tokens_apellido(nombre: str) -> frozenset:
    """Tokens significativos que probablemente sean apellido (no nombre de pila)."""
    s = _sin_acentos(nombre).upper()
    s = re.sub(r'[^A-Z\s]', ' ', s)
    toks = {t for t in s.split() if len(t) > 3}
    apellidos = toks - _NOMBRES_PROPIOS
    return frozenset(apellidos) if apellidos else frozenset(toks)


def _pila_tokens(nombre: str) -> frozenset:
    """Tokens que probablemente son nombres de pila (están en _NOMBRES_PROPIOS)."""
    s = _sin_acentos(nombre).upper()
    s = re.sub(r'[^A-Z\s]', ' ', s)
    return frozenset({t for t in s.split() if len(t) > 3} & _NOMBRES_PROPIOS)


def _canonicalizar_nombres(pool: list) -> dict:
    """
    Agrupa variantes del mismo docente usando intersección de tokens de apellido.
    Retorna {variante_raw → nombre_canónico_limpio}.
    El canónico es el de mayor puntaje: con coma > más largo > más completo.
    """
    limpio_pool = []
    for n in pool:
        lim = _limpiar_nombre(n)
        if lim and not _es_ruido(lim):
            limpio_pool.append((n, lim))

    grupos = []
    for orig, lim in limpio_pool:
        toks = _tokens_apellido(lim)
        pila = _pila_tokens(lim)
        asignado = False
        for grupo in grupos:
            rep_orig, rep_lim = max(grupo, key=lambda x: len(x[1]))
            rep_toks = _tokens_apellido(rep_lim)
            rep_pila = _pila_tokens(rep_lim)
            # Sin apellidos en común → personas distintas
            if not (toks & rep_toks):
                continue
            # Ambos tienen nombres de pila identificables y no coinciden → personas distintas
            if pila and rep_pila and not (pila & rep_pila):
                continue
            # Apellido truncado (subconjunto) O similitud alta
            if toks <= rep_toks or rep_toks <= toks or _similitud(lim, rep_lim) >= 0.72:
                grupo.append((orig, lim))
                asignado = True
                break
        if not asignado:
            grupos.append([(orig, lim)])

    canon_map = {}
    for grupo in grupos:
        def _puntaje(x):
            s = x[1]
            # Preferir: con coma > más largo > no solo apellido
            return (1 if ',' in s else 0) * 10000 + len(s)
        _, mejor_lim = max(grupo, key=_puntaje)
        for orig, _ in grupo:
            canon_map[orig] = mejor_lim

    return canon_map


# ── FUNCIÓN PRINCIPAL DE PARSEO ──────────────────────────────────────────────

def parse_word_schedule(ruta_docx, turno_default: str = 'TT'):
    """
    Parsea un archivo Word de horarios GNA.

    Lee los objetos celda reales (no .text) para usar párrafos y runs,
    extrae el número + orientación de cada aula desde el encabezado,
    normaliza días con letras sueltas (L U N E S → Lunes) y horas militares
    (0720-0820 → 07:20-08:20), corrige typos (0880 → 08:00), y
    canonicaliza variantes del mismo docente.

    Returns:
        bloques  (list[dict]):  [{aula, turno, anio, orientacion, idioma,
                                  dia, hora, asig, doc_raw, doc_canon}]
        mapa     (dict):        {variante → canónico}
        errores  (list[str]):   advertencias
    """
    if not DOCX_OK or DocxDocument is None:
        return [], {}, ['python-docx no está instalado.'], {}

    doc     = DocxDocument(ruta_docx)
    bloques = []
    errores = []
    diag    = {'tablas_total': 0, 'tablas_horario': 0, 'tablas_saltadas': 0,
               'por_tabla': []}

    for idx_tabla, tabla in enumerate(doc.tables):
        diag['tablas_total'] += 1
        filas = tabla.rows
        if not filas:
            diag['tablas_saltadas'] += 1
            errores.append(f"Tabla {idx_tabla}: sin filas.")
            continue

        # ── Verificar que es tabla de horario (tiene columna HORA) ──
        h_up = [_sin_acentos(c.text).upper() for c in filas[0].cells]
        if not any('HORA' in h for h in h_up):
            diag['tablas_saltadas'] += 1
            cabecera_preview = ' | '.join(h_up[:5])
            errores.append(
                f"Tabla {idx_tabla}: sin columna HORA (cabecera: {cabecera_preview[:80]})"
            )
            continue

        diag['tablas_horario'] += 1

        # ── Extraer metadatos de cada columna de aula (índices ≥ 2) ──
        aulas_cols = []
        # Detectar índice real de la columna HORA (puede no ser 1)
        idx_hora = next((i for i, h in enumerate(h_up) if 'HORA' in h), 1)
        for ci in range(idx_hora + 1, len(filas[0].cells)):
            raw_header = filas[0].cells[ci].text.strip()
            # Saltar columnas duplicadas (celdas fusionadas aparecen repetidas)
            if aulas_cols and filas[0].cells[ci] is filas[0].cells[aulas_cols[-1][0]]:
                continue
            meta = _parse_header_aula(raw_header)
            if not meta['numero']:
                errores.append(
                    f"Tabla {idx_tabla} col {ci}: sin número de aula en '{raw_header[:40]}'"
                )
            aulas_cols.append((ci, meta))

        if not aulas_cols:
            diag['tablas_saltadas'] += 1
            errores.append(f"Tabla {idx_tabla}: sin columnas de aulas detectadas.")
            continue

        dia_actual  = ''
        hora_actual = ''
        bloques_tabla = 0

        for fila in filas[1:]:
            celdas = fila.cells
            if len(celdas) < 2:
                continue

            # Día (puede ser "L\nU\nN\nE\nS" con saltos de línea)
            raw_dia = celdas[0].text.strip()
            if raw_dia:
                d = _normalizar_dia(raw_dia)
                if d:
                    dia_actual = d

            # Hora (puede estar partida en 2 párrafos: "1420-" / "1520")
            hora_parrafos = [
                p.text.strip()
                for p in celdas[idx_hora].paragraphs
                if p.text.strip()
            ]
            hora_joined = ''.join(hora_parrafos).replace(' ', '').replace('\xa0', '')
            m_h = HORA_RE.search(hora_joined)
            if m_h:
                hora_actual = (
                    f"{_normalizar_hora(m_h.group(1))}"
                    f"-{_normalizar_hora(m_h.group(2))}"
                )

            if not dia_actual or not hora_actual:
                continue

            for (ci, meta) in aulas_cols:
                if ci >= len(celdas):
                    continue
                for b in _parse_celda(celdas[ci]):
                    bloques.append({
                        'aula':        meta['numero'] or f'T{idx_tabla}C{ci}',
                        'turno':       turno_default,
                        'anio':        meta['anio'],
                        'orientacion': meta['orientacion'],
                        'idioma':      meta['idioma'],
                        'dia':         dia_actual,
                        'hora':        hora_actual,
                        'asig':        b['asig'],
                        'doc_raw':     b['doc_raw'],
                    })
                    bloques_tabla += 1

        aulas_tabla = list({c[1]['numero'] for c in aulas_cols if c[1]['numero']})
        diag['por_tabla'].append({
            'idx': idx_tabla,
            'aulas': aulas_tabla,
            'bloques': bloques_tabla,
        })

    # ── Canonicalizar nombres de docentes ──
    todos_docs = list({b['doc_raw'] for b in bloques if b['doc_raw']})
    mapa       = _canonicalizar_nombres(todos_docs)
    for b in bloques:
        b['doc_canon'] = mapa.get(b['doc_raw'], _limpiar_nombre(b['doc_raw']))

    return bloques, mapa, errores, diag


def _bloques_a_config_json(bloques: list) -> dict:
    """
    Convierte lista de bloques a estructura:
    { "aula|turno" → [{"dia","hora","asig","doc","anio","orientacion","idioma"}] }
    También retorna un dict de metadatos de aula.
    """
    config = {}
    for b in bloques:
        key = f"{b['aula']}|{b['turno']}"
        if key not in config:
            config[key] = []
        config[key].append({
            'dia':         b['dia'],
            'hora':        b['hora'],
            'asig':        b['asig'],
            'doc':         _normalizar_nombre_docente(b['doc_canon'] or b['doc_raw']),
            'anio':        b.get('anio', ''),
            'orientacion': b.get('orientacion', ''),
            'idioma':      b.get('idioma', ''),
        })
    return config


# ═══════════════════════════════════════════════════════════════════════════
# RUTAS PRINCIPALES
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    return render_template('index.html')


# ── PWA: el service worker debe servirse desde la raíz para tener scope sobre toda la app
@app.route('/service-worker.js')
def service_worker():
    resp = make_response(send_from_directory(
        os.path.join(app.root_path, 'static'),
        'service-worker.js',
        mimetype='application/javascript'
    ))
    # Sin cache para que el navegador siempre detecte versiones nuevas del SW
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Service-Worker-Allowed'] = '/'
    return resp


# ── MODO KIOSKO — Pantalla pública para TV del hall (sin login) ──
@app.route('/kiosko')
def kiosko():
    return render_template('kiosko.html')


@app.route('/api/kiosko/data', methods=['GET'])
def kiosko_data():
    """Datos en vivo para la pantalla del hall. Solo lectura, sin auth."""
    hoy = date.today()
    ahora = datetime.now()
    dia_hoy = ['Lunes','Martes','Miércoles','Jueves','Viernes',
               'Sábado','Domingo'][hoy.weekday()]
    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Aulas con clase ahora mismo (en su rango horario)
            cur.execute("SELECT aula, turno, config_json FROM cronograma_maestro")
            rows = cur.fetchall()

            # Firmas de hoy
            cur.execute("""
                SELECT aula, turno FROM firmas_docentes
                WHERE fecha=%s
            """, (hoy.isoformat(),))
            firmas_set = {(a, t) for a, t in cur.fetchall()}

            # KPIs globales del día
            cur.execute("SELECT COUNT(*) FROM firmas_docentes WHERE fecha=%s", (hoy.isoformat(),))
            firmas_hoy = cur.fetchone()[0]
            cur.execute("SELECT COUNT(DISTINCT aula) FROM minutas WHERE fecha=%s", (hoy.isoformat(),))
            aulas_op = cur.fetchone()[0]

        clases_ahora = []
        clases_prox = []  # las que empiezan dentro de los próximos 30 min
        for aula, turno, config in rows:
            if not config: continue
            if isinstance(config, str):
                try: config = json.loads(config)
                except (ValueError, TypeError): continue
            bloques = config if isinstance(config, list) else ([config] if isinstance(config, dict) else [])
            for b in bloques:
                if not isinstance(b, dict): continue
                if b.get('dia', '') != dia_hoy: continue
                hora_str = b.get('hora', '')
                if '-' not in hora_str: continue
                ini_s, fin_s = hora_str.split('-')
                ini_dt = _fin_clase_con_tolerancia(hoy, ini_s + '-' + ini_s, 0)
                fin_dt = _fin_clase_con_tolerancia(hoy, hora_str, 0)
                if not ini_dt or not fin_dt: continue
                en_curso = (ini_dt <= ahora <= fin_dt)
                proxima  = (ini_dt > ahora and (ini_dt - ahora).total_seconds() <= 1800)
                if en_curso or proxima:
                    item = {
                        'aula': aula, 'turno': turno,
                        'hora': hora_str, 'materia': b.get('asig',''),
                        'docente': (b.get('doc','') or '').split(',')[0],
                        'firmado': (aula, turno) in firmas_set,
                    }
                    (clases_ahora if en_curso else clases_prox).append(item)
        clases_ahora.sort(key=lambda x: x['hora'])
        clases_prox.sort(key=lambda x: x['hora'])

        return jsonify({
            'hoy': hoy.isoformat(),
            'ahora': ahora.isoformat(),
            'dia': dia_hoy,
            'kpis': {
                'firmas_hoy': firmas_hoy,
                'aulas_op': aulas_op,
                'clases_en_curso': len(clases_ahora),
            },
            'clases_ahora': clases_ahora[:12],
            'clases_proximas': clases_prox[:6],
        })
    finally:
        conn.close()


@app.route('/manifest.json')
def manifest_json():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'manifest.json',
                               mimetype='application/manifest+json')


@app.route('/api/init_db', methods=['POST'])
def api_init_db():
    try:
        init_db()
        return jsonify({'msj': 'Tablas verificadas/creadas correctamente.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/diagnostico', methods=['GET'])
def diagnostico():
    # Tablas operativas (siempre deben existir)
    tablas = [
        # Datos académicos
        'aula_catalogo', 'cronograma_maestro', 'cronograma_versiones', 'aspirantes', 'tipos_novedad', 'docentes',
        # Operatividad diaria
        'minutas', 'firmas_docentes', 'justificaciones_ausencia', 'pin_overrides',
        # Seguridad y auditoría
        'usuarios_admin', 'audit_log', 'failed_logins', 'system_log',
        # Configuración
        'config_sistema',
        # Telegram / Bot
        'bedeles_telegram', 'bedel_link_tokens', 'recordatorios_telegram', 'bot_comando_log',
    ]
    # Tablas opcionales: solo existen tras archivar el primer ciclo
    tablas_opcionales = ['minutas_archivo', 'firmas_archivo']

    resultado = {}
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            for tabla in tablas:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {tabla}")
                    resultado[tabla] = {'filas': cur.fetchone()[0], 'ok': True, 'opcional': False}
                except Exception as e:
                    resultado[tabla] = {'ok': False, 'error': str(e)[:80], 'opcional': False}
                    conn.rollback()
            for tabla in tablas_opcionales:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {tabla}")
                    resultado[tabla] = {'filas': cur.fetchone()[0], 'ok': True, 'opcional': True}
                except Exception:
                    # No existe aún — esto es ESPERADO, no un error
                    resultado[tabla] = {'ok': True, 'opcional': True, 'pendiente': True,
                                        'filas': 0,
                                        'mensaje': 'Se creará al archivar el primer ciclo'}
                    conn.rollback()
        cfg = _load_db_config()
        ahora = datetime.now()
        # Tokens activos en memoria
        su_activos    = sum(1 for exp in _SU_TOKENS.values()
                            if isinstance(exp, datetime) and exp > ahora)
        admin_activos = sum(1 for k, v in _ADMIN_TOKENS.items()
                            if not k.endswith(('__user','__impersonacion'))
                            and isinstance(v, datetime) and v > ahora)
        # Rate limiter
        ips_bloqueadas = sum(1 for e in _RATE_LIMIT.values()
                             if e.get('bloqueado_hasta') and e['bloqueado_hasta'] > ahora)
        return jsonify({
            'estado':   'conectado',
            'version':  'SIPA-GNA-2026-v1.1',
            'servidor': {
                'ahora':           ahora.isoformat(),
                'debug':           os.getenv('FLASK_DEBUG','0') == '1',
                'scheduler_activo': _SCHEDULER_RUNNING,
            },
            'sesiones': {
                'su_activas':         su_activos,
                'admin_activas':      admin_activos,
                'ips_bloqueadas_rl':  ips_bloqueadas,
            },
            'tablas':   resultado,
            'conexion': {
                'host': cfg['host'], 'port': cfg['port'],
                'dbname': cfg['dbname'], 'user': cfg['user'],
                'es_personalizada': os.path.exists(DB_CONFIG_FILE),
            },
        })
    except Exception as e:
        return jsonify({'estado': 'error', 'detalle': str(e)}), 500
    finally:
        if conn:
            conn.close()


# ─── CONEXIÓN A BASE DE DATOS REMOTA ──────────────────────────────────────

@app.route('/api/db_connection', methods=['GET'])
def db_connection_actual():
    """Devuelve la configuración actual (sin password). Requiere SU."""
    err = _exigir_su(request)
    if err: return err
    cfg = _load_db_config()
    return jsonify({
        'host':              cfg['host'],
        'port':              cfg['port'],
        'dbname':            cfg['dbname'],
        'user':              cfg['user'],
        'es_personalizada':  os.path.exists(DB_CONFIG_FILE),
    })


@app.route('/api/db_connection/test', methods=['POST'])
def db_connection_test():
    """Prueba una conexión sin guardarla. Requiere SU."""
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    try:
        conn = psycopg2.connect(
            host=d.get('host', '').strip(),
            port=str(d.get('port', '5432')).strip(),
            dbname=d.get('dbname', '').strip(),
            user=d.get('user', '').strip(),
            password=d.get('password', ''),
            connect_timeout=6,
        )
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
        conn.close()
        _log_audit('TIC', 'super_usuario', 'DB_TEST_OK', None,
                   f'{d.get("host","?")}:{d.get("port","?")}/{d.get("dbname","?")}', None)
        return jsonify({'ok': True, 'version': version})
    except Exception as e:
        _log_audit('TIC', 'super_usuario', 'DB_TEST_FAIL', None,
                   f'{d.get("host","?")}:{d.get("port","?")}/{d.get("dbname","?")}', str(e)[:200])
        return jsonify({'ok': False, 'error': str(e)}), 400


@app.route('/api/db_connection', methods=['POST'])
def db_connection_guardar():
    """Prueba la conexión y, si funciona, la persiste y crea las tablas. Requiere SU.
    Implementa rollback: si init_db falla en la nueva BD, restaura el archivo previo."""
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    cfg = {
        'host':     d.get('host', '').strip(),
        'port':     str(d.get('port', '5432')).strip(),
        'dbname':   d.get('dbname', '').strip(),
        'user':     d.get('user', '').strip(),
        'password': d.get('password', ''),
    }
    if not (cfg['host'] and cfg['dbname'] and cfg['user']):
        return jsonify({'error': 'Host, base de datos y usuario son obligatorios.'}), 400

    # 1) Test de conexión antes de tocar nada
    try:
        conn = psycopg2.connect(
            host=cfg['host'], port=cfg['port'], dbname=cfg['dbname'],
            user=cfg['user'], password=cfg['password'], connect_timeout=6,
        )
        conn.close()
    except Exception as e:
        return jsonify({'error': f'No se pudo conectar: {e}'}), 400

    # 2) Backup del archivo de config previo (para rollback)
    backup_previo = None
    if os.path.exists(DB_CONFIG_FILE):
        try:
            with open(DB_CONFIG_FILE, 'r', encoding='utf-8') as fh:
                backup_previo = fh.read()
        except Exception:
            backup_previo = None

    # 3) Escribir nueva config
    try:
        with open(DB_CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        return jsonify({'error': f'Falló guardar config: {e}'}), 500

    # 4) Inicializar tablas en la nueva BD — si falla, ROLLBACK
    try:
        init_db()
    except Exception as e:
        # Restaurar archivo previo
        try:
            if backup_previo is not None:
                with open(DB_CONFIG_FILE, 'w', encoding='utf-8') as fh:
                    fh.write(backup_previo)
            else:
                os.remove(DB_CONFIG_FILE)
        except Exception:
            pass
        return jsonify({'error': f'Conexión OK pero init_db falló: {e}. Configuración revertida.'}), 500

    _log_audit('TIC', 'super_usuario', 'DB_CONNECTION_SAVE', None,
               f'{cfg["host"]}:{cfg["port"]}/{cfg["dbname"]}',
               f'usuario_db={cfg["user"]}')
    return jsonify({
        'msj':  f'Conectado a {cfg["host"]}:{cfg["port"]}/{cfg["dbname"]} y tablas inicializadas.',
        'host': cfg['host'], 'dbname': cfg['dbname'], 'user': cfg['user'],
    })


@app.route('/api/db_connection/reset', methods=['POST'])
def db_connection_reset():
    """Elimina la config personalizada y vuelve al .env / default. Requiere SU."""
    err = _exigir_su(request)
    if err: return err
    try:
        if os.path.exists(DB_CONFIG_FILE):
            os.remove(DB_CONFIG_FILE)
        cfg = _load_db_config()
        _log_audit('TIC', 'super_usuario', 'DB_CONNECTION_RESET', None,
                   f'{cfg["host"]}:{cfg["port"]}/{cfg["dbname"]}', 'Volvió a .env / default')
        return jsonify({
            'msj': f'Conexión restaurada al original: {cfg["host"]}:{cfg["port"]}/{cfg["dbname"]}',
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ─── CATÁLOGO ACADÉMICO Y PINes ────────────────────────────────────────────

def _obtener_info_aula(aula: str, turno: str) -> dict:
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT aula, turno, nombre, anio, especialidad, curso, aliases, fuente
                FROM aula_catalogo
                WHERE aula=%s AND turno=%s
            """, (aula.upper(), turno.upper()))
            row = cur.fetchone()
        if not row:
            return {
                'aula': aula.upper(), 'turno': turno.upper(), 'nombre': aula.upper(),
                'anio': '', 'especialidad': '', 'curso': '', 'aliases': [], 'fuente': '',
            }
        return {
            'aula': row[0], 'turno': row[1], 'nombre': row[2],
            'anio': row[3] or '', 'especialidad': row[4] or '',
            'curso': row[5] or '', 'aliases': row[6] or [], 'fuente': row[7] or '',
        }
    finally:
        conn.close()


@app.route('/api/aulas_catalogo', methods=['GET'])
def aulas_catalogo():
    turno = request.args.get('turno', '').strip().upper()
    query = request.args.get('q', '').strip()
    condiciones = []
    parametros = []
    if turno in ('TM', 'TT'):
        condiciones.append('turno=%s')
        parametros.append(turno)
    if query:
        condiciones.append(
            "(aula ILIKE %s OR nombre ILIKE %s OR especialidad ILIKE %s OR curso ILIKE %s)"
        )
        patron = f'%{query}%'
        parametros.extend([patron, patron, patron, patron])
    where = f"WHERE {' AND '.join(condiciones)}" if condiciones else ''
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT aula, turno, nombre, anio, especialidad, curso, aliases, fuente
                FROM aula_catalogo {where}
                ORDER BY turno, aula
            """, parametros)
            rows = cur.fetchall()
        return jsonify([{
            'aula': r[0], 'turno': r[1], 'nombre': r[2], 'anio': r[3] or '',
            'especialidad': r[4] or '', 'curso': r[5] or '',
            'aliases': r[6] or [], 'fuente': r[7] or '',
        } for r in rows])
    finally:
        conn.close()


@app.route('/api/aulas_catalogo', methods=['PUT'])
def actualizar_aula_catalogo():
    err = _exigir_su(request)
    if err:
        return err
    d = request.json or {}
    original_aula = str(d.get('aula_original', '')).strip().upper()
    original_turno = str(d.get('turno_original', '')).strip().upper()
    aula = str(d.get('aula', '')).strip().upper()
    turno = str(d.get('turno', '')).strip().upper()
    nombre = str(d.get('nombre', '')).strip()
    if not all([original_aula, original_turno, aula, turno, nombre]):
        return jsonify({'error': 'Aula, turno y nombre son obligatorios'}), 400
    if turno not in ('TM', 'TT'):
        return jsonify({'error': 'Turno inválido'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE aula_catalogo
                SET aula=%s, turno=%s, nombre=%s, anio=%s,
                    especialidad=%s, curso=%s, fuente='Edición manual',
                    actualizado=CURRENT_TIMESTAMP
                WHERE aula=%s AND turno=%s
                RETURNING aula, turno, nombre, anio, especialidad, curso
            """, (
                aula, turno, nombre, str(d.get('anio', '')).strip(),
                str(d.get('especialidad', '')).strip(), str(d.get('curso', '')).strip(),
                original_aula, original_turno,
            ))
            row = cur.fetchone()
        if not row:
            conn.rollback()
            return jsonify({'error': 'El aula original no existe'}), 404
        if (aula, turno) != (original_aula, original_turno):
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE cronograma_maestro
                    SET aula=%s, turno=%s
                    WHERE aula=%s AND turno=%s
                """, (aula, turno, original_aula, original_turno))
        conn.commit()
        _log_audit('Super Usuario', 'su', 'ACTUALIZAR_AULA_CATALOGO',
                   'aula_catalogo', f'{original_aula}/{original_turno}',
                   f'nuevo={aula}/{turno}; nombre={nombre}')
        return jsonify({
            'aula': row[0], 'turno': row[1], 'nombre': row[2],
            'anio': row[3] or '', 'especialidad': row[4] or '', 'curso': row[5] or '',
        })
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({'error': 'Ya existe otra aula con ese número y turno'}), 409
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/aula_info/<aula>/<turno>', methods=['GET'])
def aula_info(aula, turno):
    return jsonify(_obtener_info_aula(aula, turno))


# ─── PINes ────────────────────────────────────────────────────────────────

@app.route('/api/pines_operativos', methods=['GET'])
def pines_operativos():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT cm.aula, cm.turno,
                       ac.nombre, ac.anio, ac.especialidad, ac.curso,
                       COALESCE(
                           (SELECT a.grado FROM aspirantes a
                            WHERE a.aula = cm.aula AND a.turno = cm.turno
                              AND a.grado IS NOT NULL
                            LIMIT 1),
                           ''
                       ) AS grado
                FROM cronograma_maestro cm
                LEFT JOIN aula_catalogo ac ON ac.aula=cm.aula AND ac.turno=cm.turno
                ORDER BY cm.turno, cm.aula
            """)
            rows = cur.fetchall()
        return jsonify([
            {'aula': aula, 'turno': turno, 'grado': grado or '',
             'nombre': nombre or aula, 'anio': anio or '',
             'especialidad': especialidad or '', 'curso': curso or '',
             'pin': generar_pin_diario(aula, turno)}
            for aula, turno, nombre, anio, especialidad, curso, grado in rows
        ])
    finally:
        conn.close()


@app.route('/api/validar_pin', methods=['POST'])
def validar_pin():
    data     = request.json or {}
    pin_user = str(data.get('pin', '')).strip()
    if not pin_user:
        return jsonify({'error': 'PIN requerido'}), 400
    aula, turno = verificar_pin(pin_user)
    if aula:
        info = _obtener_info_aula(aula, turno)
        return jsonify({'status': 'ok', 'aula': aula, 'turno': turno,
                        'aula_info': info})
    return jsonify({'error': 'PIN no válido para ninguna aula activa hoy'}), 403


@app.route('/api/bedel/vincular_telegram', methods=['POST'])
def bedel_vincular_telegram():
    """El Bedel ingresa el código de 6 dígitos que le dio el bot y queda vinculado.
    Requiere que ya esté autenticado por PIN (aula+turno vienen del front)."""
    if not _telegram_bedel_habilitado():
        return jsonify({'ok': False, 'error': 'La integración de Telegram para Bedelía está desactivada por TIC.'}), 403
    d = request.json or {}
    codigo = (d.get('codigo') or '').strip()
    aula   = (d.get('aula')   or '').strip().upper()
    turno  = (d.get('turno')  or '').strip().upper()
    if not (codigo and aula and turno):
        return jsonify({'ok': False, 'error': 'Faltan codigo, aula y turno'}), 400
    if len(codigo) != 6 or not codigo.isdigit():
        return jsonify({'ok': False, 'error': 'El código debe ser de 6 dígitos'}), 400
    ok, msj, tg_uid = _bedel_consumir_codigo(codigo, aula, turno)
    if ok:
        # Notificamos al bot privado del Bedel que se vinculó OK
        try:
            cfg = _telegram_config_actual()
            if cfg and tg_uid:
                texto = (
                    f"✅ <b>VINCULACIÓN EXITOSA</b>\n\n"
                    f"🏫 Estás vinculado al aula <b>{_tg_esc(aula)}</b> ({_tg_esc(turno)}).\n\n"
                    f"Ahora podés usar:\n"
                    f"  🔑 <code>/mi_pin</code>\n"
                    f"  📊 <code>/mi_aula</code>\n"
                    f"  📚 <code>/mi_padron</code>\n"
                    f"  📅 <code>/mi_cronograma</code>\n"
                    f"  🔗 <code>/link_pc</code> — login mágico al SIPA"
                )
                _bot_responder(cfg['token'], tg_uid, texto)
        except Exception:
            pass
        _log_audit(f'BEDEL:{aula}/{turno}', 'bedel', 'VINCULAR_TELEGRAM',
                   'bedeles_telegram', f'tg_user_id={tg_uid}')
        return jsonify({'ok': True, 'msj': msj})
    return jsonify({'ok': False, 'error': msj}), 400


@app.route('/api/bedel/login_magic', methods=['POST'])
def bedel_login_magic():
    """Consume un token de login mágico generado vía /link_pc en el bot.
    Devuelve aula+turno como si hubiera ingresado por PIN, si TIC habilitó Telegram para Bedelía."""
    if not _telegram_bedel_habilitado():
        return jsonify({
            'error': 'Telegram para Bedelía está desactivado por TIC. Ingrese con el PIN diario.'
        }), 403
    d   = request.json or {}
    tok = (d.get('token') or '').strip()
    if not tok:
        return jsonify({'error': 'Token requerido'}), 400
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT aula, turno, expira_en, usado FROM bedel_link_tokens
                WHERE token=%s AND tipo='login'
            """, (tok,))
            row = cur.fetchone()
            if not row:
                return jsonify({'error': 'Token inválido'}), 403
            aula, turno, exp, usado = row
            if usado:
                return jsonify({'error': 'Token ya utilizado'}), 403
            if exp < datetime.now():
                return jsonify({'error': 'Token expirado'}), 403
            cur.execute("UPDATE bedel_link_tokens SET usado=TRUE WHERE token=%s", (tok,))
        conn.commit()
        conn.close()
        _log_audit(f'BEDEL:{aula}/{turno}', 'bedel', 'LOGIN_MAGIC', None, f'token={tok[:8]}')
        return jsonify({'status': 'ok', 'aula': aula, 'turno': turno,
                        'aula_info': _obtener_info_aula(aula, turno)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/su/bedeles_telegram', methods=['GET'])
def su_bedeles_telegram_lista():
    """Lista de bedeles vinculados con Telegram (para TIC)."""
    if not _su_token_valido(request):
        return jsonify({'error': 'Token SU inválido'}), 403
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT aula, turno, telegram_username, nombre_telegram,
                       vinculado_en::text, ultimo_acceso::text, activo
                FROM bedeles_telegram
                ORDER BY aula, turno
            """)
            cols = [c[0] for c in cur.description]
            return jsonify([dict(zip(cols, r)) for r in cur.fetchall()])
    finally:
        conn.close()


def _telegram_bedel_habilitado() -> bool:
    return _cargar_params().get('telegram_bedel_login_activo', {}).get('valor') == '1'


@app.route('/api/bedel/telegram/status', methods=['GET'])
def bedel_telegram_status():
    response = jsonify({'activo': _telegram_bedel_habilitado()})
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route('/api/su/telegram/acceso_bedelia', methods=['GET', 'POST'])
def su_telegram_acceso_bedelia():
    if not _su_token_valido(request):
        return jsonify({'error': 'Token SU inválido'}), 403
    if request.method == 'GET':
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM bedeles_telegram WHERE activo=TRUE")
                fila = cur.fetchone()
            return jsonify({
                'activo': _telegram_bedel_habilitado(),
                'bedeles_vinculados': fila[0] if fila else 0,
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            conn.close()

    datos = request.get_json(silent=True)
    if not isinstance(datos, dict) or not isinstance(datos.get('activo'), bool):
        return jsonify({'error': 'Indique activo como verdadero o falso.'}), 400
    activo = '1' if datos['activo'] else '0'
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO config_sistema (clave, valor, descripcion, actualizado)
                VALUES ('telegram_bedel_login_activo', %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (clave) DO UPDATE
                SET valor=EXCLUDED.valor, actualizado=CURRENT_TIMESTAMP
            """, (
                activo,
                PARAMS_DEFAULT['telegram_bedel_login_activo']['descripcion'],
            ))
        conn.commit()
        _log_audit(
            'TIC', 'super_usuario', 'CONFIGURAR_ACCESO_TELEGRAM_BEDELIA',
            'config_sistema', 'telegram_bedel_login_activo', f'activo={activo}',
        )
        return jsonify({
            'activo': activo == '1',
            'msj': 'Telegram para Bedelía activado. El PIN diario sigue vigente.'
            if activo == '1'
            else 'Telegram para Bedelía completamente desactivado. Bedelía continúa ingresando con el PIN diario.',
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ─── ASPIRANTES ───────────────────────────────────────────────────────────

@app.route('/api/aspirantes', methods=['GET'])
def get_aspirantes():
    aula  = request.args.get('aula', '').strip().upper()
    turno = request.args.get('turno', '').strip().upper()
    conn  = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT grado, nombre FROM aspirantes "
                "WHERE aula=%s AND turno=%s ORDER BY nombre",
                (aula, turno)
            )
            return jsonify([{'grado': r[0], 'nombre': r[1]}
                            for r in cur.fetchall()])
    finally:
        conn.close()


@app.route('/api/aspirantes', methods=['POST'])
def guardar_aspirantes_manual():
    """Reemplaza el padrón completo de un aula+turno con la lista provista."""
    d          = request.json or {}
    aula       = d.get('aula',  '').strip().upper()
    turno      = d.get('turno', '').strip().upper()
    aspirantes = d.get('aspirantes', [])

    if not aula or not turno:
        return jsonify({'error': 'aula y turno requeridos'}), 400

    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM aspirantes WHERE aula=%s AND turno=%s",
                (aula, turno)
            )
            insertados = 0
            for a in aspirantes:
                nombre = (a.get('nombre') or '').strip()
                if not nombre:
                    continue
                grado = (a.get('grado') or '').strip()
                cur.execute(
                    "INSERT INTO aspirantes (aula, turno, grado, nombre) "
                    "VALUES (%s, %s, %s, %s) "
                    "ON CONFLICT (aula, turno, nombre) "
                    "DO UPDATE SET grado = EXCLUDED.grado",
                    (aula, turno, grado, nombre)
                )
                insertados += 1
        conn.commit()
        return jsonify({'msj': f'Padrón guardado: {insertados} aspirantes en Aula {aula} ({turno}).'})
    except Exception as e:
        if conn: conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if conn: conn.close()


# ─── MINUTAS ──────────────────────────────────────────────────────────────

@app.route('/api/minutas', methods=['GET'])
def get_minutas():
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, aula, fecha::text, turno, bedel, sub_bedel,
                       fe, presentes, cant_ausentes,
                       schedule_json, ausentes_json, novedades,
                       fecha_carga::text
                FROM minutas ORDER BY fecha DESC, fecha_carga DESC
            """)
            cols = [d[0] for d in cur.description]
            rows = cur.fetchall()
            cur.execute("""
                SELECT c.aula, c.fecha::text, c.turno, c.id, c.titular,
                       c.materia, c.hora, p.nombre, c.estado, c.firmado_en::text
                FROM coberturas_docente c
                LEFT JOIN docentes p ON p.id=c.pgnp_id
                WHERE c.estado IN ('aprobada','completada')
            """)
            coberturas_por_minuta = {}
            for aula, fecha, turno, cobertura_id, titular, materia, hora, pgnp, estado, firmado_en in cur.fetchall():
                key = (aula, fecha, turno)
                coberturas_por_minuta.setdefault(key, []).append({
                    'id': cobertura_id, 'titular': titular, 'materia': materia,
                    'hora': hora, 'pgnp': pgnp, 'estado': estado,
                    'firmado_en': firmado_en,
                })
        result = []
        for row in rows:
            d = dict(zip(cols, row))
            # schedule_json / ausentes_json: psycopg2 a veces devuelve string en vez de list
            sched = d.pop('schedule_json')
            if isinstance(sched, str):
                try:    sched = json.loads(sched)
                except (ValueError, TypeError): sched = []
            d['schedule'] = sched if isinstance(sched, list) else []

            ausen = d.pop('ausentes_json')
            if isinstance(ausen, str):
                try:    ausen = json.loads(ausen)
                except (ValueError, TypeError): ausen = []
            d['ausentes'] = ausen if isinstance(ausen, list) else []
            d['coberturas'] = coberturas_por_minuta.get(
                (d['aula'], d['fecha'], d['turno']), []
            )

            result.append(d)
        return jsonify(result)
    except Exception as e:
        print(f"[get_minutas] ERROR: {e}\n{_traceback.format_exc()}")
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 500
    finally:
        if conn:
            conn.close()


@app.route('/api/monitor/aulas-dia', methods=['GET'])
def monitor_aulas_dia():
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    fecha_texto = (request.args.get('fecha') or date.today().isoformat()).strip()
    try:
        fecha = date.fromisoformat(fecha_texto)
    except ValueError:
        return jsonify({'error': 'La fecha debe tener formato AAAA-MM-DD.'}), 400
    aula_detalle = (request.args.get('aula') or '').strip().upper()
    turno_detalle = (request.args.get('turno') or '').strip().upper()
    if bool(aula_detalle) != bool(turno_detalle):
        return jsonify({'error': 'Para consultar el detalle indique aula y turno.'}), 400
    if turno_detalle and turno_detalle not in ('TM', 'TT'):
        return jsonify({'error': 'El turno debe ser TM o TT.'}), 400
    dia = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'][fecha.weekday()]

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT aula, turno, config_json
                FROM cronograma_maestro
                WHERE (%s='' OR (aula=%s AND turno=%s))
                ORDER BY turno, aula
            """, (aula_detalle, aula_detalle, turno_detalle))
            cronogramas = cur.fetchall()
            cur.execute("""
                SELECT id, aula, turno, bedel, sub_bedel, fe, presentes,
                       cant_ausentes, schedule_json, ausentes_json, novedades,
                       fecha_carga::text
                FROM minutas WHERE fecha=%s AND (%s='' OR (aula=%s AND turno=%s))
            """, (fecha, aula_detalle, aula_detalle, turno_detalle))
            minutas = cur.fetchall()
            cur.execute("""
                SELECT aula, turno, COUNT(*)
                FROM aspirantes
                WHERE %s='' OR (aula=%s AND turno=%s)
                GROUP BY aula, turno
            """, (aula_detalle, aula_detalle, turno_detalle))
            padrones = {(row[0], row[1]): row[2] for row in cur.fetchall()}
            cur.execute("""
                SELECT docente, aula, turno, hora_firma::text
                FROM firmas_docentes
                WHERE fecha=%s AND (%s='' OR (aula=%s AND turno=%s))
            """, (fecha, aula_detalle, aula_detalle, turno_detalle))
            firmas = cur.fetchall()
            cur.execute("""
                SELECT c.id, c.aula, c.turno, c.titular, c.materia, c.hora,
                       p.nombre, c.estado, c.firmado_en::text, c.motivo_solicitud
                FROM coberturas_docente c
                LEFT JOIN docentes p ON p.id=c.pgnp_id
                WHERE c.fecha=%s AND (%s='' OR (c.aula=%s AND c.turno=%s))
                  AND c.estado IN ('solicitada','pendiente','aprobada','completada')
                ORDER BY c.aula, c.turno, c.hora
            """, (fecha, aula_detalle, aula_detalle, turno_detalle))
            coberturas = cur.fetchall()
            cierres = _cargar_cierres_fecha(cur, fecha)
            if aula_detalle:
                cur.execute("""
                    SELECT grado, nombre FROM aspirantes
                    WHERE aula=%s AND turno=%s ORDER BY nombre
                """, (aula_detalle, turno_detalle))
                aspirantes = [{'grado': row[0], 'nombre': row[1]} for row in cur.fetchall()]
            else:
                aspirantes = []

        def json_lista(valor):
            if isinstance(valor, str):
                try:
                    valor = json.loads(valor)
                except (ValueError, TypeError):
                    return []
            return valor if isinstance(valor, list) else []

        minuta_por_aula = {}
        for row in minutas:
            minuta_por_aula[(row[1], row[2])] = {
                'id': row[0], 'bedel': row[3], 'sub_bedel': row[4],
                'fe': row[5], 'presentes': row[6], 'cant_ausentes': row[7],
                'schedule': json_lista(row[8]), 'ausentes': json_lista(row[9]),
                'novedades': row[10] or '', 'fecha_carga': row[11],
            }
        firmas_por_docente = {}
        for docente, aula, turno, hora_firma in firmas:
            clave = (aula, turno, _sin_acentos(_normalizar_nombre_docente(docente)).lower())
            firmas_por_docente[clave] = (hora_firma or '')[:5]
        coberturas_por_aula = {}
        for row in coberturas:
            coberturas_por_aula.setdefault((row[1], row[2]), []).append({
                'id': row[0], 'titular': row[3], 'materia': row[4],
                'hora': row[5], 'pgnp': row[6], 'estado': row[7],
                'firmado_en': row[8], 'motivo': row[9] or '',
            })

        aulas = {}
        for aula, turno, config in cronogramas:
            if isinstance(config, str):
                try:
                    config = json.loads(config)
                except (ValueError, TypeError):
                    config = []
            bloques = config if isinstance(config, list) else [config] if isinstance(config, dict) else []
            clases = [
                bloque for bloque in bloques
                if isinstance(bloque, dict)
                and _sin_acentos(str(bloque.get('dia') or '')).lower()
                    == _sin_acentos(dia).lower()
                and bloque.get('asig')
            ]
            if not clases or _sin_actividad_en_fecha(cierres, fecha, aula, turno):
                continue
            minuta = minuta_por_aula.get((aula, turno))
            clases_minuta = minuta.get('schedule', []) if minuta else []
            clases_resultado = []
            for bloque in clases:
                hora = str(bloque.get('hora') or '')
                materia = str(bloque.get('asig') or '')
                docente = str(bloque.get('doc') or '').strip()
                estado_minuta = next((
                    str(item.get('estado') or '').upper()
                    for item in clases_minuta
                    if isinstance(item, dict)
                    and _normalizar_horario_cobertura(item.get('hora')) == _normalizar_horario_cobertura(hora)
                    and _sin_acentos(str(item.get('asig') or '')).strip().lower()
                        == _sin_acentos(materia).strip().lower()
                    and _sin_acentos(str(item.get('doc') or '')).strip().lower()
                        == _sin_acentos(docente).strip().lower()
                ), '')
                hora_firma = firmas_por_docente.get((
                    aula, turno, _sin_acentos(_normalizar_nombre_docente(docente)).lower()
                ))
                estado = 'firmado' if hora_firma else (
                    'ausente' if estado_minuta == 'A' else
                    'presente' if estado_minuta == 'P' else 'pendiente'
                )
                clases_resultado.append({
                    'hora': hora, 'materia': materia, 'docente': docente,
                    'estado': estado, 'hora_firma': hora_firma,
                })
            key = (aula, turno)
            aulas[key] = {
                'aula': aula, 'turno': turno,
                'fe': minuta['fe'] if minuta else padrones.get(key, 0),
                'presentes': minuta['presentes'] if minuta else None,
                'ausentes': minuta['cant_ausentes'] if minuta else None,
                'minuta': minuta,
                'clases': clases_resultado,
                'coberturas': coberturas_por_aula.get(key, []),
                'aspirantes': aspirantes if aula_detalle else None,
            }
        return jsonify({
            'fecha': fecha.isoformat(), 'dia': dia,
            'aulas': list(aulas.values()),
            'cierres': cierres,
            'detalle': bool(aula_detalle),
        })
    except Exception as e:
        print(f"[monitor_aulas_dia] ERROR: {e}\n{_traceback.format_exc()}")
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 500
    finally:
        conn.close()


@app.route('/api/minutas', methods=['POST'])
def guardar_minuta():
    d    = request.json or {}
    reqs = ['aula', 'fecha', 'turno', 'fe', 'presentes', 'cant_ausentes']
    for campo in reqs:
        if campo not in d:
            return jsonify({'error': f'Campo requerido: {campo}'}), 400
    aula  = d['aula'].strip().upper()
    fecha = str(d['fecha']).strip()
    turno = str(d['turno']).strip().upper()
    try:
        datetime.strptime(fecha, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error': 'La fecha debe tener formato AAAA-MM-DD.'}), 400
    if turno not in ('TM', 'TT'):
        return jsonify({'error': 'Seleccione un turno válido.'}), 400
    ausentes = []
    for ausente in d.get('ausentes', []):
        if not isinstance(ausente, dict):
            continue
        item = dict(ausente)
        if item.get('causa_tipo') == 'OTRO':
            item['causa'] = str(item.get('causa_detalle') or item.get('causa') or '').strip()
        else:
            item['causa'] = str(item.get('causa_tipo') or item.get('causa') or '').strip()
        ausentes.append(item)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cierres = _cargar_cierres_fecha(cur, fecha)
            if _sin_actividad_en_fecha(cierres, fecha, aula, turno):
                return jsonify({
                    'error': 'No se puede cargar la minuta: el calendario confirma que no hay actividad para esta aula y turno.'
                }), 409
            cur.execute("""
                SELECT nombre, permite_justificacion, justificada_por_defecto
                FROM tipos_novedad
                WHERE activo=TRUE
            """)
            tipos_novedad = {
                str(nombre).strip().upper(): (permite, por_defecto)
                for nombre, permite, por_defecto in cur.fetchall()
            }
            cur.execute("""
                SELECT ausentes_json
                FROM minutas
                WHERE aula=%s AND fecha=%s AND turno=%s
            """, (aula, fecha, turno))
            anterior_row = cur.fetchone()
            anterior = anterior_row[0] if anterior_row else []
            if isinstance(anterior, str):
                anterior = json.loads(anterior or '[]')
            anteriores = {
                str(item.get('nombre', '')).strip().upper(): item
                for item in (anterior if isinstance(anterior, list) else [])
                if isinstance(item, dict) and item.get('nombre')
            }

            cambios_justificacion = []
            for item in ausentes:
                nombre_ausente = str(item.get('nombre') or '').strip()
                anterior_item = anteriores.get(nombre_ausente.upper())
                tipo_causa = str(item.get('causa_tipo') or item.get('causa') or '').strip().upper()
                configuracion = tipos_novedad.get(tipo_causa)
                item['es_justificada'] = _resolver_justificacion_ausencia(
                    configuracion, anterior_item
                )
                anterior_valor = (
                    anterior_item.get('es_justificada')
                    if isinstance(anterior_item, dict) else None
                )
                if nombre_ausente and item['es_justificada'] != anterior_valor:
                    cambios_justificacion.append(
                        (nombre_ausente, anterior_valor, item['es_justificada'], item.get('causa', ''))
                    )
            cur.execute("""
                INSERT INTO minutas
                  (aula, fecha, turno, bedel, sub_bedel, fe, presentes,
                   cant_ausentes, schedule_json, ausentes_json, novedades)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (aula, fecha, turno) DO UPDATE SET
                  bedel         = EXCLUDED.bedel,
                  sub_bedel     = EXCLUDED.sub_bedel,
                  fe            = EXCLUDED.fe,
                  presentes     = EXCLUDED.presentes,
                  cant_ausentes = EXCLUDED.cant_ausentes,
                  schedule_json = EXCLUDED.schedule_json,
                  ausentes_json = EXCLUDED.ausentes_json,
                  novedades     = EXCLUDED.novedades,
                  fecha_carga   = CURRENT_TIMESTAMP
            """, (
                aula, fecha, turno,
                d.get('bedel',''), d.get('sub_bedel',''),
                int(d['fe']), int(d['presentes']), int(d['cant_ausentes']),
                json.dumps(d.get('schedule', [])),
                json.dumps(ausentes),
                d.get('novedades', ''),
            ))
        conn.commit()
        for nombre_ausente, anterior_valor, nuevo_valor, causa in cambios_justificacion:
            _log_audit(
                d.get('bedel') or 'Bedelía',
                'bedelia',
                'CAMBIAR_JUSTIFICACION_ASPIRANTE',
                'minutas',
                f'{aula} · {turno} · {fecha} · {nombre_ausente}',
                f'anterior={anterior_valor!r}; nuevo={nuevo_valor!r}; causa={causa}',
            )
        # Disparar envío automático a Telegram en background (no bloquea la respuesta HTTP)
        try:
            minuta_para_telegram = {
                'aula': aula, 'fecha': fecha, 'turno': turno,
                'bedel': d.get('bedel',''), 'sub_bedel': d.get('sub_bedel',''),
                'fe': int(d['fe']), 'presentes': int(d['presentes']),
                'cant_ausentes': int(d['cant_ausentes']),
                'ausentes': ausentes,
                'novedades': d.get('novedades', ''),
            }
            threading.Thread(
                target=_enviar_minuta_telegram,
                args=(minuta_para_telegram,),
                daemon=True
            ).start()
            # Hook adicional: alerta de baja asistencia (< 70%)
            threading.Thread(
                target=_tg_check_baja_asistencia,
                args=(minuta_para_telegram,),
                daemon=True
            ).start()
        except Exception as te:
            print(f"[telegram] No se pudo lanzar envio en background: {te}")
        return jsonify({'msj': 'Guardado exitoso'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


def _resolver_justificacion_ausencia(configuracion, anterior=None):
    """Conserva la clasificación histórica o aplica la regla vigente de TIC."""
    if isinstance(anterior, dict):
        return anterior.get('es_justificada')
    if configuracion is None:
        return None
    permite, por_defecto = configuracion
    if permite is False:
        return False
    return por_defecto if isinstance(por_defecto, bool) else None


# ─── HORAS CÁTEDRA DE ASPIRANTES ───────────────────────────────────────────

def _duracion_horas_catedra(hora: str) -> float:
    """Convierte un rango HHMM-HHMM en horas, sin aceptar duraciones inválidas."""
    partes = re.split(r'\s*[-–]\s*', str(hora or '').strip())
    if len(partes) != 2:
        return 0.0

    def minutos(valor):
        digitos = re.sub(r'\D', '', valor)
        if len(digitos) not in (3, 4):
            return None
        digitos = digitos.zfill(4)
        hh, mm = int(digitos[:2]), int(digitos[2:])
        return hh * 60 + mm if 0 <= hh < 24 and 0 <= mm < 60 else None

    inicio, fin = minutos(partes[0]), minutos(partes[1])
    if inicio is None or fin is None or fin <= inicio:
        return 0.0
    return (fin - inicio) / 60.0


def _calcular_horas_catedra(desde, hasta, aula='', turno='', nombre='',
                            materia='') -> dict:
    """Calcula horas por aspirante y materia desde minutas y padrón existentes."""
    filtros = ['fecha BETWEEN %s AND %s']
    params = [desde, hasta]
    if aula:
        filtros.append('aula=%s')
        params.append(aula.upper())
    if turno:
        filtros.append('turno=%s')
        params.append(turno.upper())

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT aula, turno, fecha::text, schedule_json, ausentes_json
                FROM minutas
                WHERE {' AND '.join(filtros)}
                ORDER BY fecha
            """, params)
            minutas = cur.fetchall()
            calendario = _cargar_calendario_no_actividad(cur, desde, hasta)
            cur.execute("""
                SELECT aula, turno, nombre FROM aspirantes
                WHERE (%s = '' OR aula=%s) AND (%s = '' OR turno=%s)
            """, (aula.upper(), aula.upper(), turno.upper(), turno.upper()))
            padron = {}
            for aula_p, turno_p, nombre_p in cur.fetchall():
                padron.setdefault((aula_p, turno_p), []).append(nombre_p)

        acumulado = {}
        for aula_n, turno_n, fecha, schedule, ausentes in minutas:
            if _sin_actividad_en_fecha(calendario, fecha, aula_n, turno_n):
                continue
            if isinstance(schedule, str):
                schedule = json.loads(schedule or '[]')
            if isinstance(ausentes, str):
                ausentes = json.loads(ausentes or '[]')
            if not isinstance(schedule, list):
                continue
            ausentes_map = {
                str(a.get('nombre', '')).strip().upper(): a
                for a in (ausentes if isinstance(ausentes, list) else [])
                if isinstance(a, dict) and a.get('nombre')
            }
            for bloque in schedule:
                if not isinstance(bloque, dict):
                    continue
                asignatura = str(bloque.get('asig') or '').strip()
                horas = _duracion_horas_catedra(bloque.get('hora', ''))
                if not asignatura or horas <= 0:
                    continue
                if materia and materia.lower() not in asignatura.lower():
                    continue
                aspirantes = padron.get((aula_n, turno_n), [])
                # Mantener compatibilidad con minutas antiguas sin padrón cargado.
                if not aspirantes:
                    aspirantes = list(ausentes_map)
                for aspirante in aspirantes:
                    novedad = ausentes_map.get(str(aspirante).strip().upper())
                    if nombre and nombre.lower() not in aspirante.lower():
                        continue
                    clave = (aspirante, aula_n, turno_n, asignatura)
                    item = acumulado.setdefault(clave, {
                        'aspirante': aspirante, 'aula': aula_n, 'turno': turno_n,
                        'materia': asignatura, 'horas_totales': 0.0,
                        'horas_asistidas': 0.0, 'horas_justificadas': 0.0,
                        'horas_no_justificadas': 0.0, 'horas_sin_clasificar': 0.0,
                    })
                    item['horas_totales'] += horas
                    justificada = novedad.get('es_justificada') if novedad else None
                    if justificada is True:
                        item['horas_justificadas'] += horas
                    elif justificada is False:
                        item['horas_no_justificadas'] += horas
                    else:
                        if novedad:
                            item['horas_sin_clasificar'] += horas

        for item in acumulado.values():
            item['horas_asistidas'] = max(
                0.0,
                item['horas_totales'] - item['horas_justificadas']
                - item['horas_no_justificadas'] - item['horas_sin_clasificar']
            )
            total = item['horas_totales']
            item['porcentaje_asistencia'] = round(
                (item['horas_asistidas'] + item['horas_justificadas']) * 100 / total, 2
            ) if total else 0.0
            item['porcentaje_inasistencia'] = round(
                item['horas_no_justificadas'] * 100 / total, 2
            ) if total else 0.0
            item['estado'] = (
                'SIN CLASIFICAR' if item['horas_sin_clasificar'] else
                'OBSERVADO' if item['horas_no_justificadas'] else 'REGULAR'
            )

        filas = list(acumulado.values())
        resumen = {
            'horas_totales': round(sum(x['horas_totales'] for x in filas), 2),
            'horas_asistidas': round(sum(x['horas_asistidas'] for x in filas), 2),
            'horas_justificadas': round(sum(x['horas_justificadas'] for x in filas), 2),
            'horas_no_justificadas': round(sum(x['horas_no_justificadas'] for x in filas), 2),
            'horas_sin_clasificar': round(sum(x['horas_sin_clasificar'] for x in filas), 2),
        }
        total = resumen['horas_totales']
        resumen['porcentaje_asistencia'] = round(
            (resumen['horas_asistidas'] + resumen['horas_justificadas']) * 100 / total, 2
        ) if total else 0.0
        resumen['porcentaje_inasistencia'] = round(
            resumen['horas_no_justificadas'] * 100 / total, 2
        ) if total else 0.0
        return {'resumen': resumen, 'detalle': filas}
    finally:
        conn.close()


@app.route('/api/plana_mayor/horas_catedra', methods=['GET'])
def horas_catedra():
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    desde = request.args.get('desde', '2000-01-01')
    hasta = request.args.get('hasta', date.today().isoformat())
    try:
        desde_date = datetime.strptime(desde, '%Y-%m-%d').date()
        hasta_date = datetime.strptime(hasta, '%Y-%m-%d').date()
        if desde_date > hasta_date:
            return jsonify({'error': 'La fecha desde no puede ser posterior a la fecha hasta'}), 400
        resultado = _calcular_horas_catedra(
            desde, hasta, request.args.get('aula', ''),
            request.args.get('turno', ''), request.args.get('aspirante', ''),
            request.args.get('materia', '')
        )
        return jsonify(resultado)
    except (ValueError, TypeError, json.JSONDecodeError) as e:
        return jsonify({'error': f'Datos de asistencia inválidos: {e}'}), 400


@app.route('/api/tipos_novedad', methods=['GET'])
def listar_tipos_novedad():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, permite_justificacion, justificada_por_defecto
                FROM tipos_novedad WHERE activo=TRUE ORDER BY nombre
            """)
            return jsonify([{
                'id': r[0], 'nombre': r[1],
                'permite_justificacion': r[2],
                'justificada_por_defecto': r[3],
            } for r in cur.fetchall()])
    finally:
        conn.close()


@app.route('/api/tipos_novedad', methods=['POST'])
def crear_tipo_novedad():
    err = _exigir_su(request)
    if err:
        return err
    d = request.json or {}
    nombre = str(d.get('nombre', '')).strip().upper()
    if not nombre:
        return jsonify({'error': 'El nombre de la novedad es obligatorio'}), 400
    if len(nombre) > 80:
        return jsonify({'error': 'El nombre no puede superar 80 caracteres'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, activo
                FROM tipos_novedad
                WHERE nombre=%s
                FOR UPDATE
            """, (nombre,))
            existente = cur.fetchone()
            if existente and existente[1]:
                conn.rollback()
                return jsonify({'error': 'Ya existe una novedad con ese nombre'}), 409
            if existente:
                cur.execute("""
                    UPDATE tipos_novedad
                    SET permite_justificacion=%s,
                        justificada_por_defecto=%s,
                        activo=TRUE
                    WHERE id=%s
                    RETURNING id, nombre, permite_justificacion, justificada_por_defecto
                """, (
                    bool(d.get('permite_justificacion', True)),
                    d.get('justificada_por_defecto'),
                    existente[0],
                ))
            else:
                cur.execute("""
                    INSERT INTO tipos_novedad
                        (nombre, permite_justificacion, justificada_por_defecto)
                    VALUES (%s, %s, %s)
                    RETURNING id, nombre, permite_justificacion, justificada_por_defecto
                """, (
                    nombre,
                    bool(d.get('permite_justificacion', True)),
                    d.get('justificada_por_defecto'),
                ))
            row = cur.fetchone()
        conn.commit()
        _log_audit('Super Usuario', 'su',
                   'REACTIVAR_TIPO_NOVEDAD' if existente else 'CREAR_TIPO_NOVEDAD',
                   'tipos_novedad',
                   str(row[0]), f'nombre={nombre}')
        return jsonify({
            'id': row[0], 'nombre': row[1],
            'permite_justificacion': row[2],
            'justificada_por_defecto': row[3],
        }), 201
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({'error': 'Ya existe una novedad con ese nombre'}), 409
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/tipos_novedad/<int:tipo_id>', methods=['PUT'])
def actualizar_tipo_novedad(tipo_id):
    err = _exigir_su(request)
    if err:
        return err
    d = request.json or {}
    campos = {}
    if 'nombre' in d:
        nombre = str(d['nombre']).strip().upper()
        if not nombre or len(nombre) > 80:
            return jsonify({'error': 'El nombre es obligatorio y no puede superar 80 caracteres'}), 400
        campos['nombre'] = nombre
    if 'permite_justificacion' in d:
        campos['permite_justificacion'] = bool(d['permite_justificacion'])
    if 'justificada_por_defecto' in d:
        campos['justificada_por_defecto'] = d['justificada_por_defecto']
    if 'activo' in d:
        campos['activo'] = bool(d['activo'])
    if not campos:
        return jsonify({'error': 'No se recibieron cambios'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            sets = ', '.join(f'{campo}=%s' for campo in campos)
            cur.execute(
                f'UPDATE tipos_novedad SET {sets} WHERE id=%s '
                'RETURNING id, nombre, permite_justificacion, justificada_por_defecto, activo',
                list(campos.values()) + [tipo_id],
            )
            row = cur.fetchone()
        if not row:
            conn.rollback()
            return jsonify({'error': 'Tipo de novedad no encontrado'}), 404
        conn.commit()
        _log_audit('Super Usuario', 'su', 'ACTUALIZAR_TIPO_NOVEDAD', 'tipos_novedad',
                   str(tipo_id), f'cambios={campos}')
        return jsonify({
            'id': row[0], 'nombre': row[1],
            'permite_justificacion': row[2],
            'justificada_por_defecto': row[3], 'activo': row[4],
        })
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({'error': 'Ya existe una novedad con ese nombre'}), 409
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/tipos_novedad/<int:tipo_id>', methods=['DELETE'])
def eliminar_tipo_novedad(tipo_id):
    err = _exigir_su(request)
    if err:
        return err
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE tipos_novedad SET activo=FALSE
                WHERE id=%s
                RETURNING nombre
            """, (tipo_id,))
            row = cur.fetchone()
        if not row:
            conn.rollback()
            return jsonify({'error': 'Tipo de novedad no encontrado'}), 404
        conn.commit()
        _log_audit('Super Usuario', 'su', 'DESACTIVAR_TIPO_NOVEDAD', 'tipos_novedad',
                   str(tipo_id), f'nombre={row[0]}')
        return jsonify({'msj': 'Tipo de novedad desactivado'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/calendario/no_actividad', methods=['GET', 'POST'])
def calendario_no_actividad():
    if request.method == 'GET':
        if not _admin_token_valido(request) and not _su_token_valido(request):
            return jsonify({'error': 'No autorizado'}), 403
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, fecha::text, alcance, turno, aula, motivo, estado,
                           excepciones, creado_por, creado_en::text,
                           confirmado_por, confirmado_en::text
                    FROM calendario_no_actividad
                    ORDER BY fecha DESC, id DESC
                """)
                items = [{
                    'id': r[0], 'fecha': r[1], 'alcance': r[2],
                    'turno': r[3], 'aula': r[4], 'motivo': r[5],
                    'estado': r[6], 'excepciones': r[7] or [],
                    'creado_por': r[8], 'creado_en': r[9],
                    'confirmado_por': r[10], 'confirmado_en': r[11],
                } for r in cur.fetchall()]
            return jsonify(items)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            conn.close()

    err = _exigir_su(request)
    if err:
        return err
    evento, error = _validar_alcance_calendario(request.json or {})
    if error:
        return jsonify({'error': error}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            if evento['alcance'] == 'aula':
                cur.execute(
                    "SELECT 1 FROM cronograma_maestro WHERE aula=%s AND turno=%s",
                    (evento['aula'], evento['turno']),
                )
                if not cur.fetchone():
                    return jsonify({'error': 'El aula no existe en el cronograma del turno seleccionado.'}), 400
            cur.execute("""
                SELECT id FROM calendario_no_actividad
                WHERE fecha=%s AND alcance=%s
                  AND COALESCE(turno,'')=COALESCE(%s,'')
                  AND COALESCE(aula,'')=COALESCE(%s,'')
                  AND estado IN ('programado','confirmado')
            """, (evento['fecha'], evento['alcance'], evento['turno'], evento['aula']))
            if cur.fetchone():
                return jsonify({'error': 'Ya existe un día sin actividad para esa fecha y alcance.'}), 409
            cur.execute("""
                INSERT INTO calendario_no_actividad
                    (fecha, alcance, turno, aula, motivo, creado_por)
                VALUES (%s,%s,%s,%s,%s,%s)
                RETURNING id, fecha::text, alcance, turno, aula, motivo, estado,
                          excepciones, creado_por, creado_en::text
            """, (
                evento['fecha'], evento['alcance'], evento['turno'], evento['aula'],
                evento['motivo'], _usuario_sesion_actual(request),
            ))
            row = cur.fetchone()
        conn.commit()
        usuario = _usuario_sesion_actual(request)
        _log_audit(usuario, 'super_usuario', 'CREAR_DIA_SIN_ACTIVIDAD',
                   'calendario_no_actividad', str(row[0]),
                   f'{row[1]} · {row[2]} · {row[5]}')
        return jsonify({
            'id': row[0], 'fecha': row[1], 'alcance': row[2], 'turno': row[3],
            'aula': row[4], 'motivo': row[5], 'estado': row[6],
            'excepciones': row[7] or [], 'creado_por': row[8], 'creado_en': row[9],
        }), 201
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({'error': 'Ya existe un día sin actividad para esa fecha y alcance.'}), 409
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/calendario/estado', methods=['GET'])
def estado_calendario_no_actividad():
    fecha = (request.args.get('fecha') or '').strip()
    aula = (request.args.get('aula') or '').strip().upper()
    turno = (request.args.get('turno') or '').strip().upper()
    try:
        datetime.strptime(fecha, '%Y-%m-%d')
    except ValueError:
        return jsonify({'error': 'La fecha debe tener formato AAAA-MM-DD.'}), 400
    if not aula or turno not in ('TM', 'TT'):
        return jsonify({'error': 'Aula y turno válidos son obligatorios.'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cierres = _cargar_cierres_fecha(cur, fecha)
        sin_actividad = _sin_actividad_en_fecha(cierres, fecha, aula, turno)
        return jsonify({
            'sin_actividad': sin_actividad,
            'mensaje': (
                'El calendario confirma que no hay actividad para esta aula y turno.'
                if sin_actividad else ''
            ),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/calendario/no_actividad/<int:evento_id>', methods=['PUT', 'DELETE'])
def editar_calendario_no_actividad(evento_id):
    err = _exigir_su(request)
    if err:
        return err
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha::text, alcance, turno, aula, estado
                FROM calendario_no_actividad WHERE id=%s FOR UPDATE
            """, (evento_id,))
            anterior = cur.fetchone()
            if not anterior:
                return jsonify({'error': 'Día sin actividad no encontrado.'}), 404
            if anterior[4] != 'programado':
                return jsonify({'error': 'Reabra el día desde Plana Mayor antes de modificarlo.'}), 409
            if request.method == 'DELETE':
                cur.execute("DELETE FROM calendario_no_actividad WHERE id=%s", (evento_id,))
                conn.commit()
                _log_audit(_usuario_sesion_actual(request), 'super_usuario',
                           'ELIMINAR_DIA_SIN_ACTIVIDAD', 'calendario_no_actividad',
                           str(evento_id), f'{anterior[0]} · {anterior[1]}')
                return jsonify({'msj': 'Día sin actividad eliminado.'})

            evento, error = _validar_alcance_calendario(request.json or {})
            if error:
                return jsonify({'error': error}), 400
            if evento['alcance'] == 'aula':
                cur.execute(
                    "SELECT 1 FROM cronograma_maestro WHERE aula=%s AND turno=%s",
                    (evento['aula'], evento['turno']),
                )
                if not cur.fetchone():
                    return jsonify({'error': 'El aula no existe en el cronograma del turno seleccionado.'}), 400
            cur.execute("""
                SELECT 1 FROM calendario_no_actividad
                WHERE fecha=%s AND alcance=%s
                  AND COALESCE(turno,'')=COALESCE(%s,'')
                  AND COALESCE(aula,'')=COALESCE(%s,'')
                  AND estado IN ('programado','confirmado') AND id<>%s
            """, (
                evento['fecha'], evento['alcance'], evento['turno'],
                evento['aula'], evento_id,
            ))
            if cur.fetchone():
                return jsonify({'error': 'Ya existe un día sin actividad para esa fecha y alcance.'}), 409
            cur.execute("""
                UPDATE calendario_no_actividad
                SET fecha=%s, alcance=%s, turno=%s, aula=%s, motivo=%s,
                    actualizado=CURRENT_TIMESTAMP
                WHERE id=%s AND estado='programado'
            """, (
                evento['fecha'], evento['alcance'], evento['turno'],
                evento['aula'], evento['motivo'], evento_id,
            ))
        conn.commit()
        _log_audit(_usuario_sesion_actual(request), 'super_usuario',
                   'ACTUALIZAR_DIA_SIN_ACTIVIDAD', 'calendario_no_actividad',
                   str(evento_id),
                   f"{evento['fecha']} · {evento['alcance']} · {evento['motivo']}")
        return jsonify({'msj': 'Día sin actividad actualizado.'})
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({'error': 'Ya existe un día sin actividad para esa fecha y alcance.'}), 409
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/calendario/no_actividad/<int:evento_id>/confirmar', methods=['POST'])
def confirmar_calendario_no_actividad(evento_id):
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    usuario = _usuario_sesion_actual(request)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE calendario_no_actividad
                SET estado='confirmado', confirmado_por=%s,
                    confirmado_en=CURRENT_TIMESTAMP, actualizado=CURRENT_TIMESTAMP
                WHERE id=%s AND estado='programado'
                RETURNING fecha::text, alcance, motivo
            """, (usuario, evento_id))
            row = cur.fetchone()
            if not row:
                return jsonify({'error': 'El día no existe o ya fue confirmado.'}), 409
        conn.commit()
        _log_audit(usuario, 'plana_mayor', 'CONFIRMAR_DIA_SIN_ACTIVIDAD',
                   'calendario_no_actividad', str(evento_id),
                   f'{row[0]} · {row[1]} · {row[2]}')
        return jsonify({'msj': 'Día sin actividad confirmado.'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/calendario/no_actividad/<int:evento_id>/reabrir', methods=['POST'])
def reabrir_calendario_no_actividad(evento_id):
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    usuario = _usuario_sesion_actual(request)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha::text, alcance, turno, aula
                FROM calendario_no_actividad WHERE id=%s AND estado='confirmado'
                FOR UPDATE
            """, (evento_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({'error': 'El día no existe o no está confirmado.'}), 409
            cur.execute("""
                SELECT 1 FROM calendario_no_actividad
                WHERE fecha=%s AND alcance=%s
                  AND COALESCE(turno,'')=COALESCE(%s,'')
                  AND COALESCE(aula,'')=COALESCE(%s,'')
                  AND estado='programado' AND id<>%s
            """, (row[0], row[1], row[2], row[3], evento_id))
            if cur.fetchone():
                return jsonify({'error': 'Existe otra programación activa con el mismo alcance y fecha.'}), 409
            cur.execute("""
                UPDATE calendario_no_actividad
                SET estado='programado', confirmado_por=NULL, confirmado_en=NULL,
                    actualizado=CURRENT_TIMESTAMP
                WHERE id=%s
                RETURNING fecha::text, alcance, motivo
            """, (evento_id,))
            row = cur.fetchone()
        conn.commit()
        _log_audit(usuario, 'plana_mayor', 'REABRIR_DIA_SIN_ACTIVIDAD',
                   'calendario_no_actividad', str(evento_id),
                   f'{row[0]} · {row[1]} · {row[2]}')
        return jsonify({'msj': 'Día reabierto; las clases volverán a contar según el cronograma.'})
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({'error': 'Existe otra programación activa con el mismo alcance y fecha.'}), 409
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/calendario/no_actividad/<int:evento_id>/excepciones', methods=['POST'])
def gestionar_excepcion_calendario(evento_id):
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    d = request.json or {}
    if not isinstance(d, dict):
        return jsonify({'error': 'El cuerpo de la solicitud debe ser un objeto JSON.'}), 400
    aula = str(d.get('aula') or '').strip().upper()
    turno = str(d.get('turno') or '').strip().upper()
    motivo = str(d.get('motivo') or '').strip()
    accion = str(d.get('accion') or 'agregar').strip().lower()
    if not aula or len(aula) > 50 or turno not in ('TM', 'TT'):
        return jsonify({'error': 'Seleccione aula y turno válidos.'}), 400
    if accion not in ('agregar', 'quitar') or (accion == 'agregar' and len(motivo) > 200):
        return jsonify({'error': 'Datos de excepción inválidos.'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT alcance, turno, estado, excepciones
                FROM calendario_no_actividad WHERE id=%s FOR UPDATE
            """, (evento_id,))
            row = cur.fetchone()
            if not row:
                return jsonify({'error': 'Día sin actividad no encontrado.'}), 404
            if row[2] != 'confirmado':
                return jsonify({'error': 'Confirme el día antes de administrar excepciones.'}), 409
            if row[0] == 'aula':
                return jsonify({'error': 'Las excepciones se configuran en cierres por institución o turno.'}), 400
            if row[0] == 'turno' and row[1] != turno:
                return jsonify({'error': 'La excepción debe pertenecer al mismo turno del cierre.'}), 400
            cur.execute(
                "SELECT 1 FROM cronograma_maestro WHERE aula=%s AND turno=%s",
                (aula, turno),
            )
            if not cur.fetchone():
                return jsonify({'error': 'El aula no existe en el cronograma del turno seleccionado.'}), 400
            excepciones = row[3] or []
            if isinstance(excepciones, str):
                excepciones = json.loads(excepciones or '[]')
            excepciones = [
                x for x in excepciones if not (
                    isinstance(x, dict)
                    and str(x.get('aula', '')).strip().upper() == aula
                    and str(x.get('turno', '')).strip().upper() == turno
                )
            ]
            if accion == 'agregar':
                if not motivo:
                    return jsonify({'error': 'Indique el motivo de la excepción.'}), 400
                excepciones.append({
                    'aula': aula, 'turno': turno, 'motivo': motivo,
                    'autorizado_por': _usuario_sesion_actual(request),
                    'autorizado_en': datetime.now().isoformat(timespec='seconds'),
                })
            cur.execute("""
                UPDATE calendario_no_actividad
                SET excepciones=%s::jsonb, actualizado=CURRENT_TIMESTAMP
                WHERE id=%s
            """, (json.dumps(excepciones, ensure_ascii=False), evento_id))
        conn.commit()
        usuario = _usuario_sesion_actual(request)
        _log_audit(usuario, 'plana_mayor',
                   'AUTORIZAR_EXCEPCION_DIA_SIN_ACTIVIDAD' if accion == 'agregar'
                   else 'QUITAR_EXCEPCION_DIA_SIN_ACTIVIDAD',
                   'calendario_no_actividad', str(evento_id),
                   f'Aula {aula} ({turno}) · {motivo or "excepción quitada"}')
        return jsonify({'msj': 'Excepción actualizada.', 'excepciones': excepciones})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ─── DOCENTES ─────────────────────────────────────────────────────────────

@app.route('/api/docentes/lista_oficial', methods=['GET'])
def lista_oficial_docentes():
    """
    Retorna todos los nombres canónicos de docentes en los cronogramas.
    """
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT config_json FROM cronograma_maestro "
                "WHERE config_json IS NOT NULL"
            )
            rows = cur.fetchall()

        nombres_raw = set()
        for (config,) in rows:
            if not config:
                continue
            if isinstance(config, str):
                try:    config = json.loads(config)
                except (ValueError, TypeError): continue
            bloques = config if isinstance(config, list) else ([config] if isinstance(config, dict) else [])
            for b in bloques:
                if isinstance(b, dict) and b.get('doc'):
                    n = b['doc'].strip()
                    if n:
                        nombres_raw.add(n)

        # Re-canonicalizar para unificar variantes que llegaron de distintas imports
        mapa = _canonicalizar_nombres(list(nombres_raw))
        canonicos = set(mapa.values())
        return jsonify(sorted(canonicos))
    finally:
        conn.close()


@app.route('/api/docentes/nombres-cronograma', methods=['GET'])
def nombres_docentes_cronograma():
    """Nombres tal como están cargados, para que el registro coincida con las aulas."""
    conn = get_db()
    try:
        ubicaciones = {}
        with conn.cursor() as cur:
            cur.execute("""
                SELECT aula, turno, config_json
                FROM cronograma_maestro
                WHERE config_json IS NOT NULL
            """)
            for aula, turno, config in cur.fetchall():
                if isinstance(config, str):
                    try:
                        config = json.loads(config)
                    except (ValueError, TypeError):
                        continue
                bloques = config if isinstance(config, list) else [config] if isinstance(config, dict) else []
                for bloque in bloques:
                    if not isinstance(bloque, dict):
                        continue
                    nombre = str(bloque.get('doc') or '').strip()
                    if not nombre:
                        continue
                    item = ubicaciones.setdefault(nombre, {'nombre': nombre, 'bloques': 0, 'aulas': set()})
                    item['bloques'] += 1
                    item['aulas'].add(f'{aula} ({turno})')
        return jsonify([
            {'nombre': nombre, 'bloques': info['bloques'], 'aulas': sorted(info['aulas'])}
            for nombre, info in sorted(ubicaciones.items(), key=lambda item: item[0].casefold())
        ])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/docentes', methods=['GET'])
def listar_docentes_compatibilidad():
    """Alias histórico para clientes que consultan el padrón de docentes."""
    return lista_oficial_docentes()


@app.route('/api/docente/registro', methods=['POST'])
def docente_registro():
    d        = request.json or {}
    # Normaliza defensivamente: evita guardar "  , APELLIDO, NOMBRE  " o variantes
    nombre   = _normalizar_nombre_docente(d.get('nombre', ''))
    dni      = d.get('dni', '').strip()
    email    = d.get('email', '').strip().lower()
    password = d.get('password', '')
    es_pgnp  = d.get('es_pgnp') is True
    if not all([nombre, dni, email, password]):
        return jsonify({'error': 'Todos los campos son requeridos'}), 400
    err_pwd = _validar_password(password)
    if err_pwd:
        return jsonify({'error': err_pwd}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM docentes WHERE email=%s OR dni=%s", (email, dni)
            )
            if cur.fetchone():
                return jsonify({'error': 'El email o DNI ya están registrados'}), 409
            if not es_pgnp:
                cur.execute("SELECT id, nombre FROM docentes WHERE es_pgnp=FALSE")
                if any(
                    _clave_docente_para_match(cuenta[1]) == _clave_docente_para_match(nombre)
                    for cuenta in cur.fetchall()
                ):
                    return jsonify({
                        'error': 'Ya existe una cuenta docente con ese nombre. Inicie sesión o recupere su clave; '
                                 'si se trata de un homónimo, solicite a TIC que lo revise antes de crear otra cuenta.'
                    }), 409
                cur.execute("""
                    SELECT config_json FROM cronograma_maestro
                    WHERE config_json IS NOT NULL
                """)
                nombre_en_cronograma = False
                nombre_norm = _clave_nombre_visible_docente(nombre)
                for (config,) in cur.fetchall():
                    if isinstance(config, str):
                        try:
                            config = json.loads(config)
                        except (ValueError, TypeError):
                            continue
                    bloques = config if isinstance(config, list) else [config] if isinstance(config, dict) else []
                    if any(
                        isinstance(bloque, dict)
                        and _clave_nombre_visible_docente(bloque.get('doc')) == nombre_norm
                        for bloque in bloques
                    ):
                        nombre_en_cronograma = True
                        break
                if not nombre_en_cronograma:
                    return jsonify({
                        'error': 'Seleccione su nombre exactamente como aparece en el cronograma. '
                                 'Si no lo encuentra o está mal escrito, solicite a TIC que lo corrija en Limpieza.'
                    }), 400
            cur.execute(
                "INSERT INTO docentes (nombre, email, dni, password_hash, es_pgnp) "
                "VALUES (%s,%s,%s,%s,%s)",
                (nombre, email, dni, hash_password(password), es_pgnp)
            )
        conn.commit()
        return jsonify({
            'msj': 'Cuenta creada exitosamente.',
            'vinculada_cronograma': not es_pgnp,
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/docente/login', methods=['POST'])
def docente_login():
    if not _rl_verificar():
        return _rl_respuesta_bloqueada()
    d        = request.json or {}
    email    = d.get('email', '').strip().lower()
    password = d.get('password', '')
    if not email or not password:
        return jsonify({'error': 'Email y contraseña requeridos'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, nombre, password_hash, es_pgnp FROM docentes WHERE email=%s",
                (email,)
            )
            row = cur.fetchone()
        if not row or not _verificar_y_migrar_hash(
                conn, 'docentes', 'password_hash', 'id', row[0], password, row[2]):
            _rl_registrar_fallo()
            _log_failed_login('docente', f'Email: {email}')
            return jsonify({'error': 'Credenciales incorrectas'}), 401
        token = secrets.token_urlsafe(32)
        meta = {
            'id': row[0],
            'nombre': row[1],
            'es_pgnp': bool(row[3]),
            'expira': datetime.now() + timedelta(hours=8),
        }
        _DOCENTE_TOKENS[token] = meta
        _registrar_sesion(token, 'docente', row[1])
        return jsonify({'nombre': row[1], 'es_pgnp': bool(row[3]), 'token': token})
    finally:
        conn.close()


@app.route('/api/docente/logout', methods=['POST'])
def docente_logout():
    token = request.headers.get('X-Docente-Token', '')
    _DOCENTE_TOKENS.pop(token, None)
    _SESIONES_META.pop(token, None)
    return jsonify({'msj': 'Sesión docente cerrada.'})


@app.route('/api/su/docentes_pgnp', methods=['GET'])
def listar_docentes_pgnp():
    err = _exigir_su(request)
    if err:
        return err
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, email, es_pgnp
                FROM docentes
                ORDER BY es_pgnp DESC, nombre
            """)
            return jsonify([
                {'id': row[0], 'nombre': row[1], 'email': row[2], 'es_pgnp': row[3]}
                for row in cur.fetchall()
            ])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/su/docentes_pgnp/<int:docente_id>', methods=['PUT'])
def configurar_docente_pgnp(docente_id):
    err = _exigir_su(request)
    if err:
        return err
    d = request.json or {}
    if not isinstance(d, dict) or not isinstance(d.get('es_pgnp'), bool):
        return jsonify({'error': 'Indique es_pgnp como valor booleano.'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE docentes SET es_pgnp=%s
                WHERE id=%s RETURNING nombre, email, es_pgnp
            """, (d['es_pgnp'], docente_id))
            row = cur.fetchone()
            if not row:
                return jsonify({'error': 'Cuenta docente no encontrada.'}), 404
            if not d['es_pgnp']:
                cur.execute("""
                    UPDATE coberturas_docente SET estado='cancelada'
                    WHERE pgnp_id=%s AND estado IN ('pendiente','aprobada')
                """, (docente_id,))
        conn.commit()
        _log_audit('TIC', 'super_usuario', 'CAMBIAR_ESTADO_PGNP',
                   'docentes', str(docente_id), f'es_pgnp={row[2]}')
        return jsonify({'id': docente_id, 'nombre': row[0], 'email': row[1], 'es_pgnp': row[2]})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/plana_mayor/pgnp', methods=['GET'])
def listar_pgnp_habilitados():
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, nombre FROM docentes WHERE es_pgnp=TRUE ORDER BY nombre")
            return jsonify([{'id': row[0], 'nombre': row[1]} for row in cur.fetchall()])
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/plana_mayor/coberturas', methods=['GET', 'POST'])
def gestionar_coberturas_docente():
    if request.method == 'GET':
        if not _admin_token_valido(request) and not _su_token_valido(request):
            return jsonify({'error': 'No autorizado'}), 403
        estado = (request.args.get('estado') or '').strip().lower()
        if estado and estado not in ('solicitada', 'pendiente', 'aprobada', 'rechazada', 'completada', 'cancelada'):
            return jsonify({'error': 'Filtro de estado inválido.'}), 400
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT c.id, c.fecha::text, c.aula, c.turno, c.titular,
                           c.materia, c.hora, c.pgnp_id, p.nombre, c.estado,
                           c.solicitada_por, c.solicitada_en::text, c.revisada_por,
                               c.revisada_en::text, c.firmado_en::text, c.motivo_solicitud
                    FROM coberturas_docente c
                        LEFT JOIN docentes p ON p.id=c.pgnp_id
                    WHERE (%s='' OR c.estado=%s)
                    ORDER BY c.fecha DESC, c.hora, c.id DESC
                    LIMIT 300
                """, (estado, estado))
                items = [{
                    'id': r[0], 'fecha': r[1], 'aula': r[2], 'turno': r[3],
                    'titular': r[4], 'materia': r[5], 'hora': r[6],
                    'pgnp_id': r[7], 'pgnp': r[8], 'estado': r[9],
                    'solicitada_por': r[10], 'solicitada_en': r[11],
                    'revisada_por': r[12], 'revisada_en': r[13], 'firmado_en': r[14],
                    'motivo_solicitud': r[15],
                } for r in cur.fetchall()]
            return jsonify(items)
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            conn.close()

    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    d = request.json or {}
    if not isinstance(d, dict):
        return jsonify({'error': 'El cuerpo de la solicitud debe ser un objeto JSON.'}), 400
    try:
        fecha = date.fromisoformat(str(d.get('fecha') or '').strip())
        pgnp_id = int(d.get('pgnp_id'))
    except (ValueError, TypeError):
        return jsonify({'error': 'Fecha y PGNP válidos son obligatorios.'}), 400
    if fecha < date.today():
        return jsonify({'error': 'No se pueden programar coberturas en fechas pasadas.'}), 400
    aula = str(d.get('aula') or '').strip().upper()
    turno = str(d.get('turno') or '').strip().upper()
    titular = _normalizar_nombre_docente(d.get('titular') or '')
    materia = str(d.get('materia') or '').strip()
    hora = str(d.get('hora') or '').strip()
    if not aula or len(aula) > 50 or turno not in ('TM', 'TT'):
        return jsonify({'error': 'Seleccione aula y turno válidos.'}), 400
    if not titular or len(titular) > 150 or not materia or len(materia) > 150:
        return jsonify({'error': 'Titular, materia y horario son obligatorios.'}), 400
    hora = _normalizar_horario_cobertura(hora)
    if not hora:
        return jsonify({'error': 'El horario debe ser válido, por ejemplo 08:00-09:20.'}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            if not _cobertura_coincide_cronograma(
                cur, fecha, aula, turno, titular, materia, hora
            ):
                return jsonify({
                    'error': 'La fecha, titular, materia y horario deben coincidir con una clase del cronograma oficial.'
                }), 400
            cur.execute("SELECT nombre, es_pgnp FROM docentes WHERE id=%s", (pgnp_id,))
            docente = cur.fetchone()
            if not docente:
                return jsonify({'error': 'Cuenta docente PGNP no encontrada.'}), 404
            if not docente[1]:
                return jsonify({'error': 'La cuenta seleccionada no está habilitada como PGNP por TIC.'}), 400
            if _sin_acentos(docente[0]).strip().lower() == _sin_acentos(titular).strip().lower():
                return jsonify({'error': 'El PGNP debe ser distinto del docente titular.'}), 400
            cur.execute("""
                INSERT INTO coberturas_docente
                    (fecha, aula, turno, titular, materia, hora, pgnp_id, solicitada_por)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id
            """, (
                fecha.isoformat(), aula, turno, titular, materia, hora, pgnp_id,
                _usuario_sesion_actual(request),
            ))
            cobertura_id = cur.fetchone()[0]
        conn.commit()
        _log_audit(_usuario_sesion_actual(request), 'plana_mayor',
                   'SOLICITAR_COBERTURA_PGNP', 'coberturas_docente',
                   str(cobertura_id), f'{fecha} · {aula}/{turno} · {materia} · PGNP {docente[0]}')
        return jsonify({'id': cobertura_id, 'estado': 'pendiente',
                        'msj': 'Solicitud de cobertura creada; requiere autorización de Plana Mayor.'}), 201
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({'error': 'Ya hay una solicitud o cobertura para esa clase, fecha y horario.'}), 409
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/plana_mayor/coberturas/<int:cobertura_id>/revisar', methods=['POST'])
def revisar_cobertura_docente(cobertura_id):
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    d = request.json or {}
    decision = str(d.get('decision') or '').strip().lower()
    if decision not in ('aprobar', 'rechazar'):
        return jsonify({'error': 'La decisión debe ser aprobar o rechazar.'}), 400
    usuario = _usuario_sesion_actual(request)
    nuevo_estado = 'aprobada' if decision == 'aprobar' else 'rechazada'
    d_pgnp_id = d.get('pgnp_id')
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT estado, pgnp_id, titular
                FROM coberturas_docente WHERE id=%s FOR UPDATE
            """, (cobertura_id,))
            anterior = cur.fetchone()
            if not anterior or anterior[0] not in ('pendiente', 'solicitada'):
                return jsonify({'error': 'La solicitud no existe o ya fue revisada.'}), 409
            pgnp_id = anterior[1]
            if decision == 'aprobar' and anterior[0] == 'solicitada':
                try:
                    pgnp_id = int(d_pgnp_id)
                except (TypeError, ValueError):
                    return jsonify({'error': 'Seleccione una cuenta PGNP para autorizar la solicitud.'}), 400
            if decision == 'aprobar':
                cur.execute(
                    "SELECT nombre, es_pgnp FROM docentes WHERE id=%s",
                    (pgnp_id,),
                )
                pgnp = cur.fetchone()
                if not pgnp or not pgnp[1]:
                    return jsonify({'error': 'La cuenta PGNP no está habilitada por TIC.'}), 400
                if _sin_acentos(pgnp[0]).strip().lower() == _sin_acentos(anterior[2]).strip().lower():
                    return jsonify({'error': 'El PGNP debe ser distinto del docente titular.'}), 400
            cur.execute("""
                UPDATE coberturas_docente
                SET estado=%s, revisada_por=%s, revisada_en=CURRENT_TIMESTAMP,
                    pgnp_id=COALESCE(%s,pgnp_id)
                WHERE id=%s AND estado IN ('pendiente','solicitada')
                  AND (
                      %s='rechazada' OR EXISTS (
                          SELECT 1 FROM docentes
                          WHERE docentes.id=COALESCE(%s,coberturas_docente.pgnp_id)
                            AND es_pgnp=TRUE
                      )
                  )
                RETURNING fecha::text, aula, turno, titular, materia, pgnp_id
            """, (
                nuevo_estado, usuario, pgnp_id if decision == 'aprobar' else None,
                cobertura_id, nuevo_estado,
                pgnp_id if decision == 'aprobar' else None,
            ))
            row = cur.fetchone()
            if not row:
                return jsonify({'error': 'La solicitud no existe o ya fue revisada.'}), 409
        conn.commit()
        _log_audit(usuario, 'plana_mayor',
                   'APROBAR_COBERTURA_PGNP' if decision == 'aprobar' else 'RECHAZAR_COBERTURA_PGNP',
                   'coberturas_docente', str(cobertura_id),
                   f'{row[0]} · {row[1]}/{row[2]} · {row[4]} · titular {row[3]}')
        return jsonify({'msj': f'Cobertura {nuevo_estado}.', 'estado': nuevo_estado})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/docente/coberturas', methods=['GET'])
def docente_coberturas_asignadas():
    meta = _docente_token_meta(request)
    if not meta:
        return jsonify({'error': 'Inicie sesión nuevamente para consultar las coberturas.'}), 401
    if not meta['es_pgnp']:
        return jsonify({'error': 'Esta función está habilitada solo para cuentas PGNP.'}), 403
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, fecha::text, aula, turno, titular, materia, hora,
                       estado, revisada_por, revisada_en::text, firmado_en::text
                FROM coberturas_docente
                WHERE pgnp_id=%s AND estado IN ('aprobada','completada')
                ORDER BY fecha DESC, hora
                LIMIT 100
            """, (meta['id'],))
            items = [{
                'id': r[0], 'fecha': r[1], 'aula': r[2], 'turno': r[3],
                'titular': r[4], 'materia': r[5], 'hora': r[6], 'estado': r[7],
                'revisada_por': r[8], 'revisada_en': r[9], 'firmado_en': r[10],
            } for r in cur.fetchall()]
        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/docente/coberturas/<int:cobertura_id>/firmar', methods=['POST'])
def firmar_cobertura_docente(cobertura_id):
    meta = _docente_token_meta(request)
    if not meta:
        return jsonify({'error': 'Inicie sesión nuevamente para firmar la cobertura.'}), 401
    if not meta['es_pgnp']:
        return jsonify({'error': 'Solo las cuentas PGNP habilitadas pueden firmar una cobertura.'}), 403
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE coberturas_docente
                SET estado='completada', firmado_en=CURRENT_TIMESTAMP
                WHERE id=%s AND pgnp_id=%s AND estado='aprobada' AND fecha=CURRENT_DATE
                RETURNING fecha::text, aula, turno, materia, hora, titular
            """, (cobertura_id, meta['id']))
            row = cur.fetchone()
            if not row:
                cur.execute("""
                    SELECT estado, firmado_en::text FROM coberturas_docente
                    WHERE id=%s AND pgnp_id=%s
                """, (cobertura_id, meta['id']))
                existente = cur.fetchone()
                if existente and existente[0] == 'completada':
                    return jsonify({'ya_firmada': True, 'firmado_en': existente[1],
                                    'msj': 'La cobertura ya estaba firmada.'})
                return jsonify({
                    'error': 'La cobertura no está aprobada, no corresponde a su cuenta o no es de la fecha de hoy.'
                }), 409
        conn.commit()
        _log_audit(meta['nombre'], 'pgnp', 'FIRMA_COBERTURA_PGNP',
                   'coberturas_docente', str(cobertura_id),
                   f'{row[0]} · {row[1]}/{row[2]} · {row[3]} · titular {row[5]}')
        return jsonify({
            'msj': 'Cobertura firmada; esta constancia no reemplaza la asistencia del titular.',
            'firmado_en': datetime.now().isoformat(timespec='seconds'),
            'materia': row[3], 'titular': row[5],
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/coberturas/aula', methods=['GET'])
def coberturas_aprobadas_aula():
    fecha = (request.args.get('fecha') or '').strip()
    aula = (request.args.get('aula') or '').strip().upper()
    turno = (request.args.get('turno') or '').strip().upper()
    try:
        date.fromisoformat(fecha)
    except ValueError:
        return jsonify({'error': 'La fecha debe tener formato AAAA-MM-DD.'}), 400
    if not aula or turno not in ('TM', 'TT'):
        return jsonify({'error': 'Aula y turno válidos son obligatorios.'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.id, c.fecha::text, c.aula, c.turno, c.titular,
                       c.materia, c.hora, p.nombre, c.estado, c.firmado_en::text
                FROM coberturas_docente c
                LEFT JOIN docentes p ON p.id=c.pgnp_id
                WHERE c.fecha=%s AND c.aula=%s AND c.turno=%s
                  AND c.estado IN ('solicitada','aprobada','completada')
                ORDER BY c.hora
            """, (fecha, aula, turno))
            items = [{
                'id': r[0], 'fecha': r[1], 'aula': r[2], 'turno': r[3],
                'titular': r[4], 'materia': r[5], 'hora': r[6],
                'pgnp': r[7], 'estado': r[8], 'firmado_en': r[9],
            } for r in cur.fetchall()]
        return jsonify(items)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/bedel/coberturas/solicitar', methods=['POST'])
def bedel_solicitar_cobertura():
    d = request.json or {}
    if not isinstance(d, dict):
        return jsonify({'error': 'El cuerpo de la solicitud debe ser un objeto JSON.'}), 400
    pin = str(d.get('pin') or '').strip()
    aula, turno = verificar_pin(pin)
    if not aula:
        return jsonify({'error': 'PIN no válido o expirado.'}), 403
    if str(d.get('aula') or '').strip().upper() != aula or str(d.get('turno') or '').strip().upper() != turno:
        return jsonify({'error': 'El PIN no corresponde al aula y turno de la solicitud.'}), 403
    fecha_texto = str(d.get('fecha') or '').strip()
    if fecha_texto != date.today().isoformat():
        return jsonify({'error': 'Bedelía solo puede solicitar cobertura para la fecha actual.'}), 400
    titular = _normalizar_nombre_docente(d.get('titular') or '')
    materia = str(d.get('materia') or '').strip()
    hora = _normalizar_horario_cobertura(d.get('hora'))
    motivo = str(d.get('motivo') or '').strip()
    if not titular or len(titular) > 150 or not materia or len(materia) > 150:
        return jsonify({'error': 'Seleccione una clase válida del cronograma.'}), 400
    if not hora:
        return jsonify({'error': 'El horario de la clase no es válido.'}), 400
    if not motivo or len(motivo) > 500:
        return jsonify({'error': 'Describa brevemente por qué necesita una cobertura.'}), 400
    fecha = date.today()
    conn = get_db()
    try:
        with conn.cursor() as cur:
            if not _cobertura_coincide_cronograma(
                cur, fecha, aula, turno, titular, materia, hora
            ):
                return jsonify({'error': 'La clase seleccionada no coincide con el cronograma oficial.'}), 400
            cierres = _cargar_cierres_fecha(cur, fecha)
            if _sin_actividad_en_fecha(cierres, fecha, aula, turno):
                return jsonify({'error': 'No se pueden solicitar coberturas durante un día sin actividad confirmado.'}), 409
            cur.execute("""
                INSERT INTO coberturas_docente
                    (fecha, aula, turno, titular, materia, hora, estado,
                     solicitada_por, motivo_solicitud)
                VALUES (%s,%s,%s,%s,%s,%s,'solicitada',%s,%s)
                RETURNING id
            """, (
                fecha.isoformat(), aula, turno, titular, materia, hora,
                f'Bedelía · Aula {aula} ({turno})', motivo,
            ))
            cobertura_id = cur.fetchone()[0]
        conn.commit()
        _log_audit(f'BEDEL:{aula}/{turno}', 'bedel',
                   'SOLICITAR_COBERTURA_PGNP', 'coberturas_docente',
                   str(cobertura_id), f'{fecha} · {materia} · titular {titular} · {motivo}')
        return jsonify({
            'id': cobertura_id, 'estado': 'solicitada',
            'msj': 'Solicitud enviada a Plana Mayor. Espere la autorización antes de dar por confirmada la cobertura.',
        }), 201
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return jsonify({'error': 'Ya existe una solicitud o cobertura para esa clase y fecha.'}), 409
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/docente/recuperar', methods=['POST'])
def docente_recuperar():
    d          = request.json or {}
    email      = d.get('email', '').strip().lower()
    dni        = d.get('dni', '').strip()
    nueva_pass = d.get('nueva_password', '')
    if not all([email, dni, nueva_pass]):
        return jsonify({'error': 'Todos los campos son requeridos'}), 400
    err_pwd = _validar_password(nueva_pass)
    if err_pwd:
        return jsonify({'error': err_pwd}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM docentes WHERE email=%s AND dni=%s",
                (email, dni)
            )
            if not cur.fetchone():
                return jsonify({'error': 'No se encontró una cuenta con ese email y DNI'}), 404
            cur.execute(
                "UPDATE docentes SET password_hash=%s WHERE email=%s AND dni=%s",
                (hash_password(nueva_pass), email, dni)
            )
        conn.commit()
        return jsonify({'msj': 'Contraseña actualizada'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ─── FIRMAS DE ASISTENCIA ─────────────────────────────────────────────────

@app.route('/api/docente/firmar', methods=['POST'])
def docente_firmar():
    d       = request.json or {}
    pin     = str(d.get('pin', '')).strip()
    # Normaliza defensivamente para evitar duplicados / nombres con comas iniciales sueltas
    docente = _normalizar_nombre_docente(d.get('docente', ''))
    # Geolocalización opcional (si el navegador la entregó)
    lat = d.get('lat')
    lng = d.get('lng')
    prec = d.get('precision')
    try: lat  = float(lat)  if lat  is not None else None
    except (TypeError, ValueError): lat = None
    try: lng  = float(lng)  if lng  is not None else None
    except (TypeError, ValueError): lng = None
    try: prec = float(prec) if prec is not None else None
    except (TypeError, ValueError): prec = None
    if lat is not None and not -90 <= lat <= 90:
        return jsonify({'error': 'La latitud recibida no es válida.'}), 400
    if lng is not None and not -180 <= lng <= 180:
        return jsonify({'error': 'La longitud recibida no es válida.'}), 400
    if prec is not None and (not math.isfinite(prec) or prec < 0):
        return jsonify({'error': 'La precisión GPS recibida no es válida.'}), 400
    if not pin or not docente:
        return jsonify({'error': 'PIN y nombre de docente requeridos'}), 400

    aula, turno = verificar_pin(pin)
    if not aula:
        return jsonify({'error': 'PIN no válido o expirado'}), 403

    ahora    = datetime.now()
    hoy_iso  = ahora.date().isoformat()  # 'YYYY-MM-DD' — compatible con DATE y TEXT

    # Validar que sea ventana operativa (parámetros configurables)
    try:
        params = _cargar_params()
        tol_antes  = int(params.get('tolerancia_antes_min',  {}).get('valor','15') or 15)
        tol_despues = int(params.get('tolerancia_despues_min',{}).get('valor','10') or 10)
        en_ventana = _docente_tiene_clase_ahora(aula, turno, docente, ahora, tol_antes, tol_despues)
        if en_ventana is False:  # explícito: None = no se pudo verificar
            return jsonify({
                'error': f'Fuera de horario. Solo se puede firmar entre {tol_antes} min antes y {tol_despues} min después del fin de su clase.'
            }), 403
    except Exception as ve:
        print(f"[firmar] No se pudo validar ventana: {ve}")
    conn     = get_db()
    try:
        with conn.cursor() as cur:
            cierres = _cargar_cierres_fecha(cur, hoy_iso)
            if _sin_actividad_en_fecha(cierres, hoy_iso, aula, turno):
                return jsonify({
                    'error': 'El calendario institucional confirma que hoy no hay actividad para esta aula y turno.'
                }), 409
            cur.execute("""
                SELECT id, hora_firma::text FROM firmas_docentes
                WHERE docente=%s AND aula=%s AND turno=%s AND fecha=%s
            """, (docente, aula, turno, hoy_iso))
            existente = cur.fetchone()

            if existente:
                return jsonify({
                    'msj':       'Ya había firmado anteriormente',
                    'aula':      aula,
                    'turno':     turno,
                    'hora_firma': (existente[1] or '')[:5],
                    'ya_firmado': True,
                })

            hora_str = ahora.strftime('%H:%M:%S')
            cur.execute("""
                INSERT INTO firmas_docentes
                  (docente, aula, turno, fecha, hora_firma, pin_usado, lat, lng, precision_m)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (docente, aula, turno, hoy_iso, hora_str, pin, lat, lng, prec))
        conn.commit()
        geo = _clasificar_geolocalizacion(lat, lng, prec)
        _log_audit(
            docente, 'docente', 'FIRMA_PRESENTISMO',
            'firmas_docentes', f'Aula {aula} ({turno}) {hoy_iso}',
            f'hora={hora_str}; geo={geo["estado"]}; distancia_m={geo["distancia_m"] or ""}'
        )
        # Push en tiempo real al monitor de Plana Mayor
        _sse_notificar({
            'tipo': 'firma',
            'docente': docente,
            'aula': aula,
            'turno': turno,
            'hora_firma': ahora.strftime('%H:%M'),
            'tiene_geo': lat is not None and lng is not None,
            'geo_estado': _clasificar_geolocalizacion(lat, lng, prec)['estado'],
            'ts': datetime.now().isoformat(),
        })
        return jsonify({
            'msj':       'Firma registrada exitosamente',
            'aula':      aula,
            'turno':     turno,
            'hora_firma': ahora.strftime('%H:%M'),
            'ya_firmado': False,
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/firmas_docentes', methods=['GET'])
def get_firmas_docentes():
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    fecha   = request.args.get('fecha', date.today().isoformat())
    docente = request.args.get('docente')
    aula    = request.args.get('aula')
    turno   = request.args.get('turno')

    filtros    = ['fecha = %s']
    parametros = [fecha]
    if docente:
        filtros.append('docente ILIKE %s'); parametros.append(f'%{docente}%')
    if aula:
        filtros.append('aula = %s'); parametros.append(aula.upper())
    if turno:
        filtros.append('turno = %s'); parametros.append(turno)

    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT docente, aula, turno, fecha::text,
                       hora_firma::text,
                       timestamp_utc::text AS ts_utc,
                       lat, lng, precision_m
                FROM firmas_docentes
                WHERE {' AND '.join(filtros)}
                ORDER BY hora_firma
            """, parametros)
            cols = [d[0] for d in cur.description]
            return jsonify([dict(zip(cols, r)) for r in cur.fetchall()])
    except Exception as e:
        print(f"[firmas_docentes] ERROR: {e}\n{_traceback.format_exc()}")
        return jsonify({
            'error': f'{type(e).__name__}: {e}',
            'filtros': {'fecha': fecha, 'aula': aula, 'turno': turno, 'docente': docente},
        }), 500
    finally:
        if conn:
            conn.close()


@app.route('/api/su/firmas/ubicaciones', methods=['GET'])
def consultar_ubicaciones_firmas_tic():
    error = _exigir_su(request)
    if error:
        return error
    desde = (request.args.get('desde') or date.today().isoformat()).strip()
    hasta = (request.args.get('hasta') or date.today().isoformat()).strip()
    try:
        date.fromisoformat(desde)
        date.fromisoformat(hasta)
    except ValueError:
        return jsonify({'error': 'Rango de fechas inválido. Use AAAA-MM-DD.'}), 400
    if desde > hasta:
        return jsonify({'error': 'La fecha desde no puede ser posterior a hasta.'}), 400

    filtros = ['fecha BETWEEN %s AND %s']
    parametros = [desde, hasta]
    aula = (request.args.get('aula') or '').strip().upper()
    turno = (request.args.get('turno') or '').strip().upper()
    docente = (request.args.get('docente') or '').strip()
    if aula:
        filtros.append('aula = %s')
        parametros.append(aula)
    if turno:
        if turno not in ('TM', 'TT'):
            return jsonify({'error': 'El turno debe ser TM o TT.'}), 400
        filtros.append('turno = %s')
        parametros.append(turno)
    if docente:
        if len(docente) > 150:
            return jsonify({'error': 'El nombre del docente no puede superar 150 caracteres.'}), 400
        filtros.append('docente ILIKE %s')
        parametros.append(f'%{docente}%')

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT docente, aula, turno, fecha::text, hora_firma::text,
                       timestamp_utc::text, lat, lng, precision_m
                FROM firmas_docentes
                WHERE {' AND '.join(filtros)}
                ORDER BY fecha DESC, hora_firma DESC, docente
                LIMIT 501
            """, parametros)
            filas = cur.fetchall()
        return jsonify({
            'firmas': [{
                'docente': fila[0], 'aula': fila[1], 'turno': fila[2],
                'fecha': fila[3], 'hora_firma': (fila[4] or '')[:5],
                'timestamp': fila[5], 'lat': fila[6], 'lng': fila[7],
                'precision_m': fila[8],
            } for fila in filas[:500]],
            'limite_alcanzado': len(filas) > 500,
        })
    except Exception as e:
        print(f"[ubicaciones_firmas_tic] ERROR: {e}\n{_traceback.format_exc()}")
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 500
    finally:
        conn.close()


@app.route('/api/firmas_docentes/export', methods=['GET'])
def exportar_firmas_docentes():
    """Exporta firmas y estado geográfico para Plana Mayor o TIC."""
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    desde = request.args.get('desde', date.today().isoformat())
    hasta = request.args.get('hasta', desde)
    try:
        date.fromisoformat(desde)
        date.fromisoformat(hasta)
    except ValueError:
        return jsonify({'error': 'Rango de fechas inválido. Use AAAA-MM-DD.'}), 400
    if desde > hasta:
        return jsonify({'error': 'La fecha desde no puede ser posterior a hasta.'}), 400

    filtros = ['fecha BETWEEN %s AND %s']
    parametros = [desde, hasta]
    aula = (request.args.get('aula') or '').strip().upper()
    turno = (request.args.get('turno') or '').strip().upper()
    docente = (request.args.get('docente') or '').strip()
    if aula:
        filtros.append('aula = %s')
        parametros.append(aula)
    if turno:
        filtros.append('turno = %s')
        parametros.append(turno)
    if docente:
        filtros.append('docente ILIKE %s')
        parametros.append(f'%{docente}%')

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT docente, aula, turno, fecha::text, hora_firma::text,
                       lat, lng, precision_m
                FROM firmas_docentes
                WHERE {' AND '.join(filtros)}
                ORDER BY fecha, hora_firma, docente
            """, parametros)
            filas = cur.fetchall()
        params = _cargar_params()
    finally:
        conn.close()

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(['Docente', 'Aula', 'Turno', 'Fecha', 'Hora', 'Latitud',
                     'Longitud', 'Precision_m', 'Estado_geografico', 'Distancia_m'])
    for docente, aula_v, turno_v, fecha_v, hora_v, lat, lng, precision in filas:
        geo = _clasificar_geolocalizacion(lat, lng, precision, params)
        writer.writerow([
            docente, aula_v, turno_v, fecha_v, hora_v, lat or '', lng or '',
            precision or '', geo['estado'], geo['distancia_m'] or '',
        ])
    nombre = f"firmas_docentes_{desde}_{hasta}.csv"
    return Response(
        '\ufeff' + out.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{nombre}"'}
    )


@app.route('/api/firmas_docentes/historial', methods=['GET'])
def historial_firmas():
    desde   = request.args.get('desde', '2024-01-01')
    hasta   = request.args.get('hasta', date.today().isoformat())
    docente = request.args.get('docente')
    aula    = request.args.get('aula')
    turno   = request.args.get('turno')

    if not _admin_token_valido(request) and not _su_token_valido(request):
        meta = _docente_token_meta(request)
        nombre_solicitado = _normalizar_nombre_docente(docente or '')
        nombre_sesion = _normalizar_nombre_docente(meta['nombre']) if meta else ''
        if not meta or not docente or _sin_acentos(nombre_solicitado).lower() != _sin_acentos(nombre_sesion).lower():
            return jsonify({'error': 'No autorizado para consultar este historial.'}), 403

    filtros    = ['fecha BETWEEN %s AND %s']
    parametros = [desde, hasta]
    if docente:
        filtros.append('docente ILIKE %s'); parametros.append(f'%{docente}%')
    if aula:
        filtros.append('aula = %s'); parametros.append(aula.upper())
    if turno:
        filtros.append('turno = %s'); parametros.append(turno)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT docente, aula, turno, fecha::text,
                       hora_firma::text, timestamp_utc::text AS timestamp,
                       lat, lng, precision_m
                FROM firmas_docentes
                WHERE {' AND '.join(filtros)}
                ORDER BY fecha DESC, hora_firma
            """, parametros)
            cols = [d[0] for d in cur.description]
            firmas = [dict(zip(cols, r)) for r in cur.fetchall()]
            for f in firmas:
                f['estado']     = 'presente'
                f['materia']    = ''
                f['hora_clase'] = ''

            # Si se filtró por docente específico, agregamos ausencias auto-computadas
            if docente:
                ausencias = _calcular_ausencias_docente(cur, docente, desde, hasta, firmas)
                firmas.extend(ausencias)
                firmas.sort(
                    key=lambda x: (x['fecha'], x.get('hora_firma') or x.get('hora_clase') or ''),
                    reverse=True
                )

            return jsonify(firmas)
    finally:
        conn.close()


# ─── CÁLCULO DE AUSENCIAS AUTOMÁTICAS ─────────────────────────────────────

def _calcular_ausencias_docente(cur, docente_filtro, desde_str, hasta_str, firmas_actuales):
    """
    Para cada clase pasada del docente en el rango [desde, hasta], si no existe
    firma registrada y la clase ya terminó (fin + 10 min de tolerancia),
    devuelve un registro con estado='ausente'. No persiste nada — se calcula on-the-fly.
    """
    try:
        fecha_ini = datetime.strptime(desde_str, '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(hasta_str, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return []

    ahora     = datetime.now()
    fecha_fin = min(fecha_fin, ahora.date())
    if fecha_ini > fecha_fin:
        return []

    cur.execute("SELECT aula, turno, config_json FROM cronograma_maestro")
    rows = cur.fetchall()
    calendario = _cargar_calendario_no_actividad(
        cur, fecha_ini.isoformat(), fecha_fin.isoformat()
    )

    DIAS = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']
    docente_norm = _sin_acentos(docente_filtro).lower().strip()

    # Pre-procesar bloques del docente
    bloques_docente = []
    for aula_n, turno_n, config in rows:
        if not config:
            continue
        if isinstance(config, str):
            try:    config = json.loads(config)
            except (ValueError, TypeError): continue
        bloques = config if isinstance(config, list) else ([config] if isinstance(config, dict) else [])
        for b in bloques:
            if not isinstance(b, dict): continue
            doc_b = (b.get('doc') or '').strip()
            if _sin_acentos(doc_b).lower() != docente_norm:
                continue
            bloques_docente.append({
                'aula':    aula_n,
                'turno':   turno_n,
                'dia':     b.get('dia', ''),
                'hora':    b.get('hora', ''),
                'materia': b.get('asig', ''),
                'doc':     doc_b,
            })

    if not bloques_docente:
        return []

    # Conjunto de (aula, turno, fecha) ya cubiertos por firmas reales → no duplicar
    ya_firmadas = {(f['aula'], f['turno'], f['fecha']) for f in firmas_actuales}

    ausencias = []
    d = fecha_ini
    while d <= fecha_fin:
        dia_nombre = DIAS[d.weekday()]
        for b in bloques_docente:
            if b['dia'] != dia_nombre:
                continue
            fecha_iso = d.isoformat()
            if _sin_actividad_en_fecha(calendario, fecha_iso, b['aula'], b['turno']):
                continue
            if (b['aula'], b['turno'], fecha_iso) in ya_firmadas:
                continue
            fin_tol = _fin_clase_con_tolerancia(d, b['hora'], 10)
            if not fin_tol or fin_tol > ahora:
                continue  # clase aún no terminó con tolerancia
            ausencias.append({
                'docente':     b['doc'],
                'aula':        b['aula'],
                'turno':       b['turno'],
                'fecha':       fecha_iso,
                'hora_firma':  None,
                'timestamp':   None,
                'estado':      'ausente',
                'materia':     b['materia'],
                'hora_clase':  b['hora'],
            })
        d += timedelta(days=1)
    return ausencias


def _docente_tiene_clase_ahora(aula, turno, docente, ahora, tol_antes_min, tol_despues_min):
    """Devuelve True si el docente tiene clase en el aula/turno indicado y ahora está
    dentro de la ventana operativa [inicio - tol_antes, fin + tol_despues].
    None si no se pudo determinar (sin cronograma o nombre no matchea)."""
    DIAS = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']
    dia_hoy = DIAS[ahora.weekday()]
    docente_norm = _sin_acentos(docente).lower().strip()
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT config_json FROM cronograma_maestro WHERE aula=%s AND turno=%s",
                (aula, turno))
            row = cur.fetchone()
            cur.execute("""
                SELECT aula, turno, materia, fecha_original::text, hora_original,
                       fecha_nueva::text, hora_nueva
                FROM adelantos_horario
                WHERE estado='aplicado' AND docente=%s
                  AND (fecha_original=%s OR fecha_nueva=%s)
            """, (docente, ahora.date(), ahora.date()))
            adelantos = cur.fetchall()
        config = row[0] if row and row[0] else []
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except (ValueError, TypeError):
                config = []
        bloques = config if isinstance(config, list) else ([config] if isinstance(config, dict) else [])
        clases_del_doc = []
        for b in bloques:
            if not isinstance(b, dict): continue
            if b.get('dia','') != dia_hoy: continue
            if _sin_acentos(b.get('doc','') or '').lower().strip() != docente_norm: continue
            hora_str = b.get('hora','')
            if '-' not in hora_str: continue
            fue_adelantada = any(
                fecha_original == ahora.date().isoformat()
                and aula_movida == aula and turno_movido == turno
                and _sin_acentos(materia_movida).strip().lower()
                    == _sin_acentos(str(b.get('asig') or '')).strip().lower()
                and _normalizar_horario_cobertura(hora_original) == _normalizar_horario_cobertura(hora_str)
                for aula_movida, turno_movido, materia_movida, fecha_original,
                    hora_original, _fecha_nueva, _hora_nueva in adelantos
            )
            if fue_adelantada:
                clases_del_doc.append(hora_str)
                continue
            ini_dt = _fin_clase_con_tolerancia(ahora.date(), hora_str.split('-')[0]+'-'+hora_str.split('-')[0], -tol_antes_min)
            fin_dt = _fin_clase_con_tolerancia(ahora.date(), hora_str, tol_despues_min)
            if ini_dt and fin_dt and ini_dt <= ahora <= fin_dt:
                return True
            clases_del_doc.append(hora_str)
        for aula_movida, turno_movido, _materia, _fecha_original, _hora_original, fecha_nueva, hora_nueva in adelantos:
            if aula_movida != aula or turno_movido != turno or fecha_nueva != ahora.date().isoformat():
                continue
            ini_dt = _fin_clase_con_tolerancia(
                ahora.date(), hora_nueva.split('-')[0] + '-' + hora_nueva.split('-')[0],
                -tol_antes_min,
            )
            fin_dt = _fin_clase_con_tolerancia(ahora.date(), hora_nueva, tol_despues_min)
            if ini_dt and fin_dt and ini_dt <= ahora <= fin_dt:
                return True
            clases_del_doc.append(hora_nueva)
        if not clases_del_doc:
            return None  # No matchea con cronograma: dejar pasar (caso reemplazos)
        return False  # Tiene clases pero ninguna está en ventana ahora
    finally:
        conn.close()


def _clasificar_geolocalizacion(lat, lng, precision=None, parametros=None):
    """Clasifica una firma sin bloquearla cuando la geolocalización no está configurada."""
    if lat is None or lng is None:
        return {'estado': 'sin_datos', 'distancia_m': None, 'mensaje': 'Sin coordenadas'}
    if not (-90 <= float(lat) <= 90 and -180 <= float(lng) <= 180):
        return {'estado': 'invalida', 'distancia_m': None, 'mensaje': 'Coordenadas inválidas'}

    params = _cargar_params()
    try:
        ref_lat = float(params.get('institucion_lat', {}).get('valor', '') or '')
        ref_lng = float(params.get('institucion_lng', {}).get('valor', '') or '')
        radio = float(params.get('radio_geolocalizacion_m', {}).get('valor', '100') or 100)
    except (TypeError, ValueError):
        return {'estado': 'sin_configurar', 'distancia_m': None, 'mensaje': 'Punto institucional no configurado'}
    if not (-90 <= ref_lat <= 90 and -180 <= ref_lng <= 180) or radio <= 0:
        return {'estado': 'sin_configurar', 'distancia_m': None, 'mensaje': 'Punto institucional no configurado'}

    radio_tierra = 6371000
    lat1, lat2 = math.radians(float(lat)), math.radians(ref_lat)
    dlat = math.radians(ref_lat - float(lat))
    dlng = math.radians(ref_lng - float(lng))
    hav = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    distancia = 2 * radio_tierra * math.asin(math.sqrt(min(1, hav)))
    estado = 'dentro' if distancia <= radio else 'fuera'
    precision_txt = f' (precisión ±{round(float(precision))} m)' if precision is not None else ''
    return {
        'estado': estado,
        'distancia_m': round(distancia, 1),
        'mensaje': f'{"Dentro" if estado == "dentro" else "Fuera"} del radio institucional{precision_txt}',
    }


def _fin_clase_con_tolerancia(fecha_obj, hora_str, tol_min):
    """Parsea 'HH:MM-HH:MM' y devuelve datetime(fecha, fin) + tol_min."""
    if not hora_str or '-' not in hora_str:
        return None
    fin_str = hora_str.split('-')[1].strip()
    digitos = re.sub(r'[^\d]', '', fin_str)
    if len(digitos) < 3:
        return None
    digitos = digitos.zfill(4)
    try:
        hh = int(digitos[:2]); mm = int(digitos[2:4])
        if not (0 <= hh < 24): return None
        if mm >= 60: mm = 0
        return datetime.combine(fecha_obj, time(hh, mm)) + timedelta(minutes=tol_min)
    except (ValueError, TypeError):
        return None


# ─── HORARIO SEMANAL DEL DOCENTE ──────────────────────────────────────────

@app.route('/api/horario_docente', methods=['GET'])
def horario_docente():
    """Devuelve TODAS las clases del docente con info de firma (para las de HOY)."""
    nombre = request.args.get('nombre', '').strip()
    if not nombre:
        return jsonify([])

    DIAS_ORDEN = {'Lunes':1,'Martes':2,'Miércoles':3,'Jueves':4,
                  'Viernes':5,'Sábado':6,'Domingo':7}
    hoy     = date.today()
    hoy_iso = hoy.isoformat()
    dia_hoy = ['Lunes','Martes','Miércoles','Jueves','Viernes',
               'Sábado','Domingo'][hoy.weekday()]

    conn = None
    try:
        conn = get_db()
        rows = []
        firmas_hoy = {}
        cierres_hoy = []

        with conn.cursor() as cur:
            cur.execute("SELECT aula, turno, config_json FROM cronograma_maestro")
            rows = cur.fetchall()
            cierres_hoy = _cargar_cierres_fecha(cur, hoy_iso)

        # Cargar firmas del día (en transacción aparte por si la columna no existe)
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT aula, turno, hora_firma::text
                    FROM firmas_docentes
                    WHERE docente=%s AND fecha=%s
                """, (nombre, hoy_iso))
                firmas_hoy = {(a, t): (hf[:5] if hf else None)
                              for a, t, hf in cur.fetchall()}
        except Exception as fe:
            # Si firmas_docentes tiene schema viejo, seguimos sin info de firma
            print(f"[horario_docente] firmas omitidas: {fe}")
            conn.rollback()
            firmas_hoy = {}

        # Cargar justificaciones de HOY del docente
        justifs_hoy = {}
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT aula, turno, motivo, comentario, estado
                    FROM justificaciones_ausencia
                    WHERE docente=%s AND fecha=%s
                """, (nombre, hoy_iso))
                for a, t, m, c, est in cur.fetchall():
                    justifs_hoy[(a, t)] = {
                        'motivo': m, 'comentario': c,
                        'estado_justif': est or 'aprobada',
                    }
        except Exception as je:
            print(f"[horario_docente] justifs omitidas: {je}")
            conn.rollback()
            justifs_hoy = {}

        resultado = []
        nombre_norm = _sin_acentos(nombre).lower()
        for aula, turno, config in rows:
            if not config:
                continue
            if isinstance(config, str):
                try:    config = json.loads(config)
                except (ValueError, TypeError): continue
            bloques = config if isinstance(config, list) else ([config] if isinstance(config, dict) else [])
            for b in bloques:
                if not isinstance(b, dict):
                    continue
                doc_block = b.get('doc', '').strip()
                if _sin_acentos(doc_block).lower() != nombre_norm:
                    continue
                es_hoy = (b.get('dia', '') == dia_hoy)
                just = justifs_hoy.get((aula, turno)) if es_hoy else None
                resultado.append({
                    'aula':            aula,
                    'turno':           turno,
                    'dia':             b.get('dia', ''),
                    'hora':            b.get('hora', ''),
                    'materia':         b.get('asig', ''),
                    'anio':            b.get('anio', ''),
                    'orientacion':     b.get('orientacion', ''),
                    'es_hoy':          es_hoy,
                    'sin_actividad':   es_hoy and _sin_actividad_en_fecha(
                        cierres_hoy, hoy_iso, aula, turno
                    ),
                    'firmado':         es_hoy and (aula, turno) in firmas_hoy,
                    'hora_firma':      firmas_hoy.get((aula, turno)) if es_hoy else None,
                    'justif_estado':   just.get('estado_justif') if just else None,
                    'justif_motivo':   just.get('motivo')        if just else None,
                    'justif_coment':   just.get('comentario')    if just else None,
                })

        resultado.sort(key=lambda x: (DIAS_ORDEN.get(x['dia'], 99), x['hora']))
        return jsonify(resultado)
    except Exception as e:
        print(f"[horario_docente] ERROR: {e}\n{_traceback.format_exc()}")
        return jsonify({
            'error': f'{type(e).__name__}: {e}',
            'nombre': nombre,
        }), 500
    finally:
        if conn:
            conn.close()


@app.route('/api/docente/adelantos-horario', methods=['GET', 'POST'])
def docente_adelantos_horario():
    meta = _docente_token_meta(request)
    if not meta:
        return jsonify({'error': 'Inicie sesión nuevamente para gestionar adelantos.'}), 401
    if meta.get('es_pgnp'):
        return jsonify({'error': 'Los adelantos de horario están disponibles para docentes titulares.'}), 403
    docente_id = meta['id']
    docente = _normalizar_nombre_docente(meta['nombre'])
    if request.method == 'GET':
        conn = get_db()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, aula, turno, materia, fecha_original::text,
                           hora_original, fecha_nueva::text, hora_nueva,
                           estado, creado_en::text, revocado_por, revocado_en::text,
                           EXISTS (
                               SELECT 1 FROM firmas_docentes f
                               WHERE f.docente=adelantos_horario.docente
                                 AND f.aula=adelantos_horario.aula
                                 AND f.turno=adelantos_horario.turno
                                 AND f.fecha=adelantos_horario.fecha_nueva
                           )
                    FROM adelantos_horario
                    WHERE docente_id=%s
                    ORDER BY creado_en DESC, id DESC
                    LIMIT 100
                """, (docente_id,))
                casos = [{
                    'id': r[0], 'aula': r[1], 'turno': r[2], 'materia': r[3],
                    'fecha_original': r[4], 'hora_original': r[5],
                    'fecha_nueva': r[6], 'hora_nueva': r[7], 'estado': r[8],
                    'creado_en': r[9], 'revocado_por': r[10], 'revocado_en': r[11],
                    'firmado': r[12],
                } for r in cur.fetchall()]
            activo = _cargar_params().get('adelantos_horario_activo', {}).get('valor') == '1'
            return jsonify({'activo': activo, 'casos': casos})
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            conn.close()

    if meta.get('es_pgnp'):
        return jsonify({'error': 'Las cuentas PGNP no pueden adelantar clases titulares.'}), 403
    d = request.json or {}
    if not isinstance(d, dict):
        return jsonify({'error': 'El cuerpo de la solicitud debe ser un objeto JSON.'}), 400
    try:
        fecha_original = date.fromisoformat(str(d.get('fecha_original') or '').strip())
        fecha_nueva = date.fromisoformat(str(d.get('fecha_nueva') or '').strip())
    except ValueError:
        return jsonify({'error': 'Indique fechas válidas para la clase original y el adelanto.'}), 400
    hoy = date.today()
    if fecha_nueva < hoy or fecha_original < hoy or fecha_original > hoy + timedelta(days=180):
        return jsonify({'error': 'Solo se pueden adelantar clases futuras dentro de los próximos 180 días.'}), 400
    if fecha_nueva > fecha_original:
        return jsonify({'error': 'La nueva fecha debe ser anterior o igual a la fecha original.'}), 400

    aula = str(d.get('aula') or '').strip().upper()
    turno = str(d.get('turno') or '').strip().upper()
    materia = str(d.get('materia') or '').strip()
    hora_original = _normalizar_horario_cobertura(d.get('hora_original'))
    minutos_originales = _minutos_horario(hora_original)
    inicio_nuevo = re.sub(r'\D', '', str(d.get('hora_nueva_inicio') or '').strip())
    if len(inicio_nuevo) not in (3, 4):
        return jsonify({'error': 'Indique una hora de inicio válida para el adelanto.'}), 400
    inicio_nuevo = inicio_nuevo.zfill(4)
    hora_num, minuto_num = int(inicio_nuevo[:2]), int(inicio_nuevo[2:])
    if hora_num > 23 or minuto_num > 59:
        return jsonify({'error': 'La hora de inicio propuesta no es válida.'}), 400
    if not aula or len(aula) > 50 or turno not in ('TM', 'TT'):
        return jsonify({'error': 'Seleccione un aula y turno válidos.'}), 400
    if not materia or len(materia) > 150 or not minutos_originales:
        return jsonify({'error': 'La materia y el horario original deben ser válidos.'}), 400
    duracion = minutos_originales[1] - minutos_originales[0]
    inicio_minutos = hora_num * 60 + minuto_num
    fin_minutos = inicio_minutos + duracion
    if fin_minutos >= 24 * 60:
        return jsonify({'error': 'El horario propuesto debe terminar antes de la medianoche.'}), 400
    hora_nueva = (
        f'{hora_num:02d}:{minuto_num:02d}-'
        f'{fin_minutos // 60:02d}:{fin_minutos % 60:02d}'
    )
    inicio_original_dt = datetime.combine(fecha_original, time(
        minutos_originales[0] // 60, minutos_originales[0] % 60
    ))
    fin_nueva_dt = datetime.combine(fecha_nueva, time(
        fin_minutos // 60, fin_minutos % 60
    ))
    if fin_nueva_dt > inicio_original_dt:
        return jsonify({'error': 'El horario adelantado debe finalizar antes del inicio original de la clase.'}), 400
    if fecha_nueva == hoy and fin_nueva_dt <= datetime.now():
        return jsonify({'error': 'El horario propuesto ya finalizó; seleccione una hora futura.'}), 400
    if fecha_original == hoy and inicio_original_dt <= datetime.now():
        return jsonify({'error': 'No se puede adelantar una clase cuyo horario original ya comenzó.'}), 409

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f'docente:{docente_id}',))
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f'aula:{aula}:{turno}',))
            cur.execute("""
                SELECT valor FROM config_sistema
                WHERE clave='adelantos_horario_activo' FOR UPDATE
            """)
            fila_config = cur.fetchone()
            if not fila_config or fila_config[0] != '1':
                return jsonify({'error': 'La función de adelantos está desactivada por TIC.'}), 409

            cur.execute(
                "SELECT aula, turno, config_json FROM cronograma_maestro"
            )
            cronogramas = cur.fetchall()
            dia_original = _dia_semana_espanol(fecha_original)
            origen_encontrado = False
            for aula_cfg, turno_cfg, config in cronogramas:
                if isinstance(config, str):
                    try:
                        config = json.loads(config)
                    except (ValueError, TypeError):
                        config = []
                bloques = config if isinstance(config, list) else [config] if isinstance(config, dict) else []
                if aula_cfg != aula or turno_cfg != turno:
                    continue
                origen_encontrado = any(
                    isinstance(b, dict)
                    and _sin_acentos(str(b.get('dia') or '')).lower()
                        == _sin_acentos(dia_original).lower()
                    and _normalizar_horario_cobertura(b.get('hora')) == hora_original
                    and _sin_acentos(str(b.get('asig') or '')).strip().lower()
                        == _sin_acentos(materia).strip().lower()
                    and _sin_acentos(str(b.get('doc') or '')).strip().lower()
                        == _sin_acentos(docente).strip().lower()
                    for b in bloques
                )
                break
            if not origen_encontrado:
                return jsonify({'error': 'La clase original no coincide con el cronograma del docente.'}), 400

            for fecha_comprobar in {fecha_original, fecha_nueva}:
                cierres = _cargar_cierres_fecha(cur, fecha_comprobar)
                if _sin_actividad_en_fecha(cierres, fecha_comprobar, aula, turno):
                    return jsonify({'error': 'No se puede adelantar una clase en una fecha sin actividad confirmada.'}), 409
            cur.execute("""
                SELECT 1 FROM minutas
                WHERE aula=%s AND turno=%s AND fecha IN (%s,%s)
                LIMIT 1
            """, (aula, turno, fecha_original, fecha_nueva))
            if cur.fetchone():
                return jsonify({'error': 'No se puede cambiar el horario: ya existe una minuta para la fecha original o la propuesta.'}), 409
            cur.execute("""
                SELECT 1 FROM firmas_docentes
                WHERE docente=%s AND aula=%s AND turno=%s AND fecha IN (%s,%s)
                LIMIT 1
            """, (docente, aula, turno, fecha_original, fecha_nueva))
            if cur.fetchone():
                return jsonify({'error': 'No se puede cambiar el horario: ya hay una firma registrada en una de esas fechas.'}), 409
            cur.execute("""
                SELECT 1 FROM adelantos_horario
                WHERE docente_id=%s AND estado='aplicado'
                  AND fecha_original=%s AND aula=%s AND turno=%s
                  AND materia=%s AND hora_original=%s
                LIMIT 1
            """, (docente_id, fecha_original, aula, turno, materia, hora_original))
            if cur.fetchone():
                return jsonify({'error': 'Esta clase ya tiene un adelanto aplicado.'}), 409

            dia_nuevo = _dia_semana_espanol(fecha_nueva)
            for aula_cfg, turno_cfg, config in cronogramas:
                if isinstance(config, str):
                    try:
                        config = json.loads(config)
                    except (ValueError, TypeError):
                        continue
                bloques = config if isinstance(config, list) else [config] if isinstance(config, dict) else []
                for bloque in bloques:
                    if not isinstance(bloque, dict):
                        continue
                    if _sin_acentos(str(bloque.get('dia') or '')).lower() != _sin_acentos(dia_nuevo).lower():
                        continue
                    otro_docente = _sin_acentos(str(bloque.get('doc') or '')).strip().lower()
                    misma_aula = aula_cfg == aula and turno_cfg == turno
                    mismo_docente = otro_docente == _sin_acentos(docente).strip().lower()
                    if not (misma_aula or mismo_docente):
                        continue
                    es_clase_origen_movida = (
                        fecha_nueva == fecha_original and misma_aula and
                        _normalizar_horario_cobertura(bloque.get('hora')) == hora_original and
                        _sin_acentos(str(bloque.get('asig') or '')).strip().lower()
                            == _sin_acentos(materia).strip().lower() and
                        otro_docente == _sin_acentos(docente).strip().lower()
                    )
                    if not es_clase_origen_movida and _intervalos_horarios_solapan(
                        hora_nueva, bloque.get('hora')
                    ):
                        return jsonify({'error': 'El horario propuesto se superpone con otra clase del docente o del aula.'}), 409

            cur.execute("""
                SELECT docente_id, aula, turno, hora_nueva
                FROM adelantos_horario
                WHERE estado='aplicado' AND fecha_nueva=%s
                  AND (docente_id=%s OR (aula=%s AND turno=%s))
            """, (fecha_nueva, docente_id, aula, turno))
            for id_doc, aula_existente, turno_existente, hora_existente in cur.fetchall():
                if _intervalos_horarios_solapan(hora_nueva, hora_existente):
                    return jsonify({'error': 'El horario propuesto se superpone con otro adelanto ya aplicado.'}), 409

            cur.execute("""
                INSERT INTO adelantos_horario
                    (docente_id, docente, aula, turno, materia,
                     fecha_original, hora_original, fecha_nueva, hora_nueva)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                RETURNING id, creado_en::text
            """, (
                docente_id, docente, aula, turno, materia,
                fecha_original, hora_original, fecha_nueva, hora_nueva,
            ))
            caso = cur.fetchone()
        conn.commit()
        _log_audit(
            docente, 'docente', 'ADELANTO_HORARIO_AUTO_APLICADO',
            'adelantos_horario', str(caso[0]),
            f'{aula}/{turno} · {materia} · {fecha_original} {hora_original} → {fecha_nueva} {hora_nueva}',
        )
        return jsonify({
            'id': caso[0], 'estado': 'aplicado',
            'msj': 'Adelanto aplicado automáticamente y registrado para revisión.',
            'fecha_original': fecha_original.isoformat(), 'hora_original': hora_original,
            'fecha_nueva': fecha_nueva.isoformat(), 'hora_nueva': hora_nueva,
        }), 201
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/adelantos-horario/dia', methods=['GET'])
def adelantos_horario_dia():
    try:
        fecha = date.fromisoformat(str(request.args.get('fecha') or '').strip())
    except ValueError:
        return jsonify({'error': 'La fecha debe tener formato AAAA-MM-DD.'}), 400
    aula = (request.args.get('aula') or '').strip().upper()
    turno = (request.args.get('turno') or '').strip().upper()
    if not aula or turno not in ('TM', 'TT'):
        return jsonify({'error': 'Aula y turno válidos son obligatorios.'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, docente, materia, fecha_original::text, hora_original,
                       fecha_nueva::text, hora_nueva
                FROM adelantos_horario
                WHERE estado='aplicado' AND aula=%s AND turno=%s
                  AND (fecha_original=%s OR fecha_nueva=%s)
                ORDER BY hora_nueva, id
            """, (aula, turno, fecha, fecha))
            cambios = cur.fetchall()
        return jsonify({
            'retiradas': [{
                'id': r[0], 'docente': r[1], 'materia': r[2],
                'fecha': r[3], 'hora': r[4],
            } for r in cambios if r[3] == fecha.isoformat()],
            'incorporadas': [{
                'id': r[0], 'docente': r[1], 'materia': r[2],
                'fecha': r[5], 'hora': r[6],
                'fecha_original': r[3], 'hora_original': r[4],
            } for r in cambios if r[5] == fecha.isoformat()],
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ─── CONFIGURACIÓN DE AULAS (CRONOGRAMA) ──────────────────────────────────

@app.route('/api/config_aula', methods=['GET'])
def get_config_aula_all():
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT aula, turno, config_json FROM cronograma_maestro "
                "ORDER BY turno, aula"
            )
            rows = cur.fetchall()
        resultado = []
        for aula, turno, config in rows:
            if isinstance(config, str):
                try:    config = json.loads(config)
                except (ValueError, TypeError): config = []
            bloques = config if isinstance(config, list) else ([config] if isinstance(config, dict) else [])
            for b in bloques:
                if isinstance(b, dict):
                    resultado.append({
                        'aula':        aula,
                        'turno':       turno,
                        'dia':         b.get('dia', ''),
                        'hora':        b.get('hora', ''),
                        'asig':        b.get('asig', ''),
                        'doc':         b.get('doc', ''),
                        'anio':        b.get('anio', ''),
                        'orientacion': b.get('orientacion', ''),
                        'idioma':      b.get('idioma', ''),
                    })
        return jsonify(resultado)
    finally:
        conn.close()


@app.route('/api/config_aula/<aula>/<turno>', methods=['GET'])
def get_config_aula(aula, turno):
    aula  = aula.strip().upper()
    turno = turno.strip().upper()
    conn  = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT config_json FROM cronograma_maestro "
                "WHERE aula=%s AND turno=%s",
                (aula, turno)
            )
            row = cur.fetchone()
        if not row or not row[0]:
            return jsonify([])
        config = row[0]
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except (ValueError, TypeError):
                return jsonify([])
        bloques = config if isinstance(config, list) else ([config] if isinstance(config, dict) else [])
        return jsonify([b for b in bloques if isinstance(b, dict)])
    finally:
        conn.close()


@app.route('/api/config_aula', methods=['POST'])
def guardar_config_aula():
    d     = request.json or {}
    aula  = d.get('aula', '').strip().upper()
    turno = d.get('turno', '').strip().upper()
    nombre = d.get('nombre', '').strip()
    config = d.get('config', [])
    if not aula or not turno:
        return jsonify({'error': 'aula y turno requeridos'}), 400
    if not isinstance(config, list):
        return jsonify({'error': 'config debe ser una lista de bloques'}), 400
    if len(nombre) > 150:
        return jsonify({'error': 'El nombre del aula no puede superar 150 caracteres'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            _guardar_version_cronograma(cur, aula, turno, motivo='Edición manual', creado_por='Plana Mayor')
            cur.execute("""
                INSERT INTO cronograma_maestro (aula, turno, config_json)
                VALUES (%s,%s,%s)
                ON CONFLICT (aula, turno)
                DO UPDATE SET config_json = EXCLUDED.config_json
            """, (aula, turno, json.dumps(config)))
            if nombre:
                cur.execute("""
                    INSERT INTO aula_catalogo (aula, turno, nombre, fuente, actualizado)
                    VALUES (%s, %s, %s, 'Edición manual', CURRENT_TIMESTAMP)
                    ON CONFLICT (aula, turno) DO UPDATE SET
                        nombre=EXCLUDED.nombre, actualizado=CURRENT_TIMESTAMP
                """, (aula, turno, nombre))
        conn.commit()
        return jsonify({'msj': 'Cronograma guardado'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ─── UPLOAD: PADRÓN EXCEL ─────────────────────────────────────────────────

@app.route('/api/upload_padron', methods=['POST'])
def upload_padron():
    if 'file' not in request.files:
        return jsonify({'error': 'No se recibió archivo'}), 400
    if not PANDAS_OK:
        return jsonify({'error': 'pandas no está instalado'}), 500

    archivo = request.files['file']
    turno   = request.form.get('turno', 'TM').strip().upper()
    fname   = archivo.filename.lower()

    try:
        contenido = archivo.read()
        df = (pd.read_csv(io.BytesIO(contenido), encoding='utf-8', on_bad_lines='skip')
              if fname.endswith('.csv')
              else pd.read_excel(io.BytesIO(contenido)))

        df.columns = [c.strip().upper() for c in df.columns]
        if not {'AULA', 'NOMBRE'}.issubset(set(df.columns)):
            return jsonify({
                'error': f'Faltan columnas. Encontradas: {list(df.columns)}. '
                         f'Requeridas: AULA, NOMBRE (+ opcional GRADO)'
            }), 400

        if 'GRADO' not in df.columns:
            df['GRADO'] = 'ASP'

        df = df.dropna(subset=['AULA', 'NOMBRE'])
        df['AULA']   = df['AULA'].astype(str).str.strip().str.upper()
        df['NOMBRE'] = df['NOMBRE'].astype(str).str.strip().str.upper()
        df['GRADO']  = df['GRADO'].astype(str).str.strip().str.upper()

        conn = get_db()
        insertados = 0
        try:
            with conn.cursor() as cur:
                for _, row in df.iterrows():
                    cur.execute("""
                        INSERT INTO aspirantes (aula, turno, grado, nombre)
                        VALUES (%s,%s,%s,%s)
                        ON CONFLICT (aula, turno, nombre)
                        DO UPDATE SET grado = EXCLUDED.grado
                    """, (row['AULA'], turno, row['GRADO'], row['NOMBRE']))
                    insertados += 1
                for a in df['AULA'].unique():
                    cur.execute("""
                        INSERT INTO cronograma_maestro (aula, turno, config_json)
                        VALUES (%s,%s,%s) ON CONFLICT DO NOTHING
                    """, (a, turno, json.dumps([])))
            conn.commit()
        finally:
            conn.close()

        return jsonify({'msj': f'Padrón importado: {insertados} registros.'})
    except Exception as e:
        return jsonify({'error': f'Error procesando archivo: {e}'}), 500


# ─── UPLOAD: WORD CRONOGRAMA (NUEVO PARSER) ───────────────────────────────

@app.route('/api/upload_word_schedule', methods=['POST'])
def upload_word_schedule():
    if not DOCX_OK:
        return jsonify({'error': 'python-docx no instalado. Ejecute: pip install python-docx'}), 500
    if 'file' not in request.files:
        return jsonify({'error': 'No se recibió archivo'}), 400

    archivo = request.files['file']
    turno   = request.form.get('turno', 'TT').strip().upper()

    try:
        contenido = io.BytesIO(archivo.read())
        bloques, mapa, errores, diag = parse_word_schedule(contenido, turno)

        if not bloques:
            return jsonify({
                'error': 'No se pudieron extraer bloques horarios. '
                         'Verifique que el documento tenga tablas con columnas DÍA y HORA.',
                'errores_detalle': errores,
                'diagnostico': diag,
            }), 400

        # Convertir a estructura por aula
        config_por_aula = _bloques_a_config_json(bloques)

        conn = get_db()
        aulas_guardadas = 0
        try:
            with conn.cursor() as cur:
                for key, config in config_por_aula.items():
                    aula, t = key.split('|', 1)
                    # Versionar antes de sobrescribir
                    _guardar_version_cronograma(cur, aula, t,
                                                motivo='Importación desde Word',
                                                creado_por='SU/Importación')
                    cur.execute("""
                        INSERT INTO cronograma_maestro (aula, turno, config_json)
                        VALUES (%s,%s,%s)
                        ON CONFLICT (aula, turno)
                        DO UPDATE SET config_json = EXCLUDED.config_json
                    """, (aula, t, json.dumps(config)))
                    aulas_guardadas += 1
            conn.commit()
        finally:
            conn.close()

        # Armar resumen de docentes canónicos
        canonicos = sorted({b['doc_canon'] for b in bloques if b['doc_canon']})
        variantes_resumen = [
            {'canon': c, 'variantes': [v for v, cv in mapa.items() if cv == c and v != c]}
            for c in canonicos
            if any(v for v, cv in mapa.items() if cv == c and v != c)
        ]

        # Resumen por aula para mostrar en UI
        resumen_aulas = []
        for pt in diag.get('por_tabla', []):
            for a in pt['aulas']:
                resumen_aulas.append({
                    'aula':    a,
                    'turno':   turno,
                    'bloques': sum(
                        1 for b in bloques
                        if b['aula'] == a and b['turno'] == turno
                    ),
                })

        return jsonify({
            'msj': (
                f'Cronograma importado: {len(bloques)} bloques horarios, '
                f'{aulas_guardadas} aulas registradas.'
            ),
            'aulas':     aulas_guardadas,
            'bloques':   len(bloques),
            'resumen_aulas': resumen_aulas,
            'docentes_canonicos': canonicos,
            'variantes_agrupadas': variantes_resumen,
            'advertencias': errores,
            'diagnostico': diag,
        })

    except Exception as e:
        return jsonify({'error': f'Error procesando Word: {e}',
                        'traceback': _traceback.format_exc()}), 500


# ═══════════════════════════════════════════════════════════════════════════
# AUDITORÍA DE ASISTENCIA — Búsqueda, Inasistencias, Justificaciones, Export
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/api/docentes/buscar', methods=['GET'])
def buscar_docentes():
    """Busca docentes por apellido (en cronograma) o DNI (en registrados)."""
    q = request.args.get('q', '').strip()
    if not q or len(q) < 2:
        return jsonify([])

    q_norm = _sin_acentos(q).lower()
    conn = get_db()
    try:
        # Cuentas registradas
        registrados = {}
        with conn.cursor() as cur:
            cur.execute("""
                SELECT nombre, dni, email FROM docentes
                WHERE nombre ILIKE %s OR dni ILIKE %s
                ORDER BY nombre LIMIT 25
            """, (f'%{q}%', f'%{q}%'))
            for n, d, e in cur.fetchall():
                registrados[n] = {'nombre': n, 'dni': d, 'email': e, 'registrado': True}

        # Nombres en cronograma_maestro (canonicalizados)
        with conn.cursor() as cur:
            cur.execute("SELECT config_json FROM cronograma_maestro WHERE config_json IS NOT NULL")
            rows = cur.fetchall()

        nombres_raw = set()
        for (config,) in rows:
            if not config: continue
            if isinstance(config, str):
                try: config = json.loads(config)
                except (ValueError, TypeError): continue
            bloques = config if isinstance(config, list) else ([config] if isinstance(config, dict) else [])
            for b in bloques:
                if isinstance(b, dict) and b.get('doc'):
                    nombres_raw.add(b['doc'].strip())

        mapa = _canonicalizar_nombres(list(nombres_raw))
        canonicos = sorted(set(mapa.values()))

        # Filtrar por la query
        resultados = list(registrados.values())
        registrados_set = set(registrados.keys())
        for nombre in canonicos:
            if nombre in registrados_set: continue
            if q_norm in _sin_acentos(nombre).lower():
                resultados.append({
                    'nombre': nombre, 'dni': None, 'email': None, 'registrado': False
                })
        resultados.sort(key=lambda x: x['nombre'])
        return jsonify(resultados[:25])
    finally:
        conn.close()


def _calcular_inasistencias(desde: str, hasta: str, turno: str = '',
                             incluir_justificadas: bool = False,
                             limite: int = 500) -> tuple:
    """Núcleo de cálculo de inasistencias. Devuelve (lista_ausencias, total_sin_limite).
    Lanza ValueError si las fechas son inválidas o el rango supera MAX_DIAS.
    Llamar directamente desde código Python (sin pasar por HTTP)."""
    MAX_DIAS = 90
    try:
        fecha_ini = datetime.strptime(desde, '%Y-%m-%d').date()
        fecha_fin = datetime.strptime(hasta, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        raise ValueError('Fechas inválidas (formato YYYY-MM-DD)')

    if (fecha_fin - fecha_ini).days > MAX_DIAS:
        raise ValueError(f'El rango máximo es {MAX_DIAS} días. Use desde/hasta para acotar el período.')

    ahora     = datetime.now()
    fecha_fin = min(fecha_fin, ahora.date())
    if fecha_ini > fecha_fin:
        return [], 0

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT docente, aula, turno, fecha::text
                FROM firmas_docentes WHERE fecha BETWEEN %s AND %s
            """, (desde, hasta))
            firmas_map = {
                (_clave_docente_para_match(d), a.upper(), t.upper(), f): True
                for d, a, t, f in cur.fetchall()
            }

        justifs = {}
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT docente, aula, turno, fecha::text, motivo, comentario,
                           registrado_por, creado_en::text, estado
                    FROM justificaciones_ausencia WHERE fecha BETWEEN %s AND %s
                """, (desde, hasta))
                for d, a, t, f, m, c, rp, ce, est in cur.fetchall():
                    justifs[(_clave_docente_para_match(d), a.upper(), t.upper(), f)] = {
                        'motivo': m, 'comentario': c,
                        'registrado_por': rp, 'creado_en': ce,
                        'estado_justif': est or 'aprobada',
                    }
        except Exception as je:
            print(f"[inasistencias] justifs no disponibles: {je}")
            conn.rollback()

        with conn.cursor() as cur:
            cur.execute("SELECT aula, turno, config_json FROM cronograma_maestro")
            crono_rows = cur.fetchall()
            calendario = _cargar_calendario_no_actividad(
                cur, fecha_ini.isoformat(), fecha_fin.isoformat()
            )
    finally:
        conn.close()

    DIAS = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']
    ausencias = []
    d_actual = fecha_ini
    while d_actual <= fecha_fin:
        dia_nombre = DIAS[d_actual.weekday()]
        fecha_iso  = d_actual.isoformat()
        for aula_n, turno_n, config in crono_rows:
            if turno and turno_n != turno: continue
            if not config: continue
            if _sin_actividad_en_fecha(calendario, fecha_iso, aula_n, turno_n):
                continue
            if isinstance(config, str):
                try: config = json.loads(config)
                except (ValueError, TypeError): continue
            bloques = config if isinstance(config, list) else ([config] if isinstance(config, dict) else [])
            for b in bloques:
                if not isinstance(b, dict): continue
                if b.get('dia', '') != dia_nombre: continue
                doc_b = (b.get('doc') or '').strip()
                if not doc_b: continue
                doc_norm = _clave_docente_para_match(doc_b)
                firmada = any(
                    fd_key == doc_norm and fa == aula_n.upper() and ft == turno_n.upper() and ff == fecha_iso
                    for fd_key, fa, ft, ff in firmas_map
                )
                if firmada: continue
                fin_tol = _fin_clase_con_tolerancia(d_actual, b.get('hora', ''), 10)
                if not fin_tol or fin_tol > ahora: continue
                just_key = (_clave_docente_para_match(doc_b), aula_n.upper(), turno_n.upper(), fecha_iso)
                just = justifs.get(just_key)
                if just:
                    est_j = just.get('estado_justif', 'aprobada')
                    estado_row = ('justificado' if est_j == 'aprobada'
                                  else 'pendiente_aprobacion' if est_j == 'pendiente'
                                  else 'ausente')
                else:
                    estado_row = 'ausente'
                if not incluir_justificadas and estado_row == 'justificado':
                    continue
                ausencias.append({
                    'docente':        doc_b,
                    'aula':           aula_n,
                    'turno':          turno_n,
                    'fecha':          fecha_iso,
                    'dia':            dia_nombre,
                    'hora_clase':     b.get('hora', ''),
                    'materia':        b.get('asig', ''),
                    'estado':         estado_row,
                    'estado_justif':  just.get('estado_justif') if just else None,
                    'motivo':         just['motivo']            if just else None,
                    'comentario':     just['comentario']        if just else None,
                    'registrado_por': just.get('registrado_por') if just else None,
                })
        d_actual += timedelta(days=1)

    ausencias.sort(key=lambda x: (x['fecha'], x['hora_clase']), reverse=True)
    return ausencias[:limite], len(ausencias)


@app.route('/api/inasistencias', methods=['GET'])
def inasistencias_listado():
    """Lista ausencias del cuerpo docente. Requiere auth (Plana Mayor o SU)."""
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    desde  = request.args.get('desde', date.today().isoformat())
    hasta  = request.args.get('hasta', date.today().isoformat())
    turno  = request.args.get('turno', '').strip().upper()
    incl_j = request.args.get('incluir_justificadas', '0') == '1'
    limite = min(int(request.args.get('limite', '500') or 500), 2000)
    try:
        resultado, total = _calcular_inasistencias(desde, hasta, turno, incl_j, limite)
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400
    response = jsonify(resultado)
    response.headers['X-Total-Count'] = str(total)
    response.headers['X-Limite']      = str(limite)
    return response


@app.route('/api/justificacion_ausencia', methods=['POST'])
def justificar_ausencia():
    """Registra (o actualiza) la justificación de una ausencia."""
    d = request.json or {}
    docente   = d.get('docente', '').strip()
    aula      = d.get('aula', '').strip().upper()
    turno     = d.get('turno', '').strip().upper()
    fecha     = d.get('fecha', '').strip()
    motivo    = d.get('motivo', '').strip()
    coment    = d.get('comentario', '').strip()
    reg_por   = d.get('registrado_por', '').strip()

    if not all([docente, aula, turno, fecha, motivo]):
        return jsonify({'error': 'Faltan campos requeridos (docente, aula, turno, fecha, motivo).'}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO justificaciones_ausencia
                  (docente, aula, turno, fecha, motivo, comentario, registrado_por, estado, revisado_por, revisado_en)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'aprobada', %s, CURRENT_TIMESTAMP)
                ON CONFLICT (docente, aula, turno, fecha)
                DO UPDATE SET motivo=EXCLUDED.motivo,
                              comentario=EXCLUDED.comentario,
                              registrado_por=EXCLUDED.registrado_por,
                              estado='aprobada',
                              revisado_por=EXCLUDED.revisado_por,
                              revisado_en=CURRENT_TIMESTAMP
            """, (docente, aula, turno, fecha, motivo, coment, reg_por or None, reg_por or 'Plana Mayor'))
        conn.commit()
        _log_audit(reg_por or 'Plana Mayor', 'plana_mayor', 'JUSTIFICAR_AUSENCIA',
                   'justificaciones_ausencia', f'{docente} · Aula {aula} ({turno}) · {fecha}',
                   f'motivo={motivo}')
        _sse_notificar({
            'tipo': 'justificacion',
            'docente': docente, 'aula': aula, 'turno': turno, 'fecha': fecha,
            'motivo': motivo,
            'registrado_por': reg_por or 'Plana Mayor',
            'ts': datetime.now().isoformat(),
        })
        return jsonify({'msj': f'Ausencia justificada: {docente} · Aula {aula} · {fecha}'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/justificacion_ausencia', methods=['DELETE'])
def eliminar_justificacion():
    d = request.json or {}
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM justificaciones_ausencia
                WHERE docente=%s AND aula=%s AND turno=%s AND fecha=%s
            """, (d.get('docente'), d.get('aula','').upper(),
                  d.get('turno','').upper(), d.get('fecha')))
        conn.commit()
        return jsonify({'msj': 'Justificación eliminada.'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/docente/pendientes', methods=['GET'])
def docente_pendientes():
    """Devuelve clases del docente en los últimos N días que NO tienen firma
    ni justificación activa (aprobada o pendiente). Excluye HOY (ya se ve en MIS MATERIAS)."""
    nombre = request.args.get('nombre', '').strip()
    try:
        dias = int(request.args.get('dias', '7'))
    except (ValueError, TypeError):
        dias = 7
    if not nombre:
        return jsonify([])

    ahora     = datetime.now()
    hoy       = ahora.date()
    fecha_ini = hoy - timedelta(days=dias)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT aula, turno, config_json FROM cronograma_maestro")
            crono_rows = cur.fetchall()
            calendario = _cargar_calendario_no_actividad(
                cur, fecha_ini.isoformat(), hoy.isoformat()
            )

        # Firmas del docente en el rango
        firmas_set = set()
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT aula, turno, fecha::text
                    FROM firmas_docentes
                    WHERE docente=%s AND fecha BETWEEN %s AND %s
                """, (nombre, fecha_ini.isoformat(), hoy.isoformat()))
                firmas_set = {(a, t, f) for a, t, f in cur.fetchall()}
        except Exception:
            conn.rollback()

        # Justificaciones del docente en el rango
        justifs = {}
        try:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT aula, turno, fecha::text, motivo, estado
                    FROM justificaciones_ausencia
                    WHERE docente=%s AND fecha BETWEEN %s AND %s
                """, (nombre, fecha_ini.isoformat(), hoy.isoformat()))
                for a, t, f, m, est in cur.fetchall():
                    justifs[(a, t, f)] = {'motivo': m, 'estado': est or 'aprobada'}
        except Exception:
            conn.rollback()

        DIAS = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']
        docente_norm = _sin_acentos(nombre).lower()
        pendientes = []

        d = fecha_ini
        while d < hoy:  # excluimos HOY (ya se renderiza en MIS MATERIAS)
            dia_nombre = DIAS[d.weekday()]
            fecha_iso  = d.isoformat()
            for aula_n, turno_n, config in crono_rows:
                if not config: continue
                if isinstance(config, str):
                    try: config = json.loads(config)
                    except (ValueError, TypeError): continue
                bloques = config if isinstance(config, list) else ([config] if isinstance(config, dict) else [])
                for b in bloques:
                    if not isinstance(b, dict): continue
                    if b.get('dia','') != dia_nombre: continue
                    doc_b = (b.get('doc') or '').strip()
                    if _sin_acentos(doc_b).lower() != docente_norm: continue
                    if _sin_actividad_en_fecha(calendario, fecha_iso, aula_n, turno_n):
                        continue

                    # Firmó → no pendiente
                    if (aula_n, turno_n, fecha_iso) in firmas_set:
                        continue

                    # Tiene just aprobada o pendiente → no pendiente
                    just = justifs.get((aula_n, turno_n, fecha_iso))
                    if just and just['estado'] in ('aprobada', 'pendiente'):
                        continue

                    # ¿Ya terminó con tolerancia?
                    fin_tol = _fin_clase_con_tolerancia(d, b.get('hora',''), 10)
                    if not fin_tol or fin_tol > ahora:
                        continue

                    pendientes.append({
                        'aula':           aula_n,
                        'turno':          turno_n,
                        'fecha':          fecha_iso,
                        'dia':            dia_nombre,
                        'hora_clase':     b.get('hora',''),
                        'materia':        b.get('asig',''),
                        'justif_rechazada': bool(just),  # si tenía just rechazada
                    })
            d += timedelta(days=1)

        # Más recientes primero
        pendientes.sort(key=lambda x: (x['fecha'], x['hora_clase']), reverse=True)
        return jsonify(pendientes)
    finally:
        conn.close()


@app.route('/api/docente/justificaciones', methods=['GET'])
def docente_justificaciones():
    meta = _docente_token_meta(request)
    if not meta:
        respuesta = jsonify({'error': 'Inicie sesión nuevamente para consultar sus justificaciones.'})
        respuesta.headers['Cache-Control'] = 'private, no-store'
        return respuesta, 401

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha::text, aula, turno, motivo, comentario,
                       COALESCE(estado, 'aprobada') AS estado,
                       revisado_en::text, observacion_revision
                FROM justificaciones_ausencia
                WHERE docente=%s
                ORDER BY fecha DESC, id DESC
                LIMIT 100
            """, (meta['nombre'],))
            cols = [d[0] for d in cur.description]
            justificaciones = [dict(zip(cols, row)) for row in cur.fetchall()]
        respuesta = jsonify(justificaciones)
        respuesta.headers['Cache-Control'] = 'private, no-store'
        return respuesta
    finally:
        conn.close()


@app.route('/api/docente/justificar', methods=['POST'])
def docente_autojustificar():
    """El docente justifica su propia ausencia. Requiere reingresar password
    como firma digital de conformidad. Queda en estado='pendiente'."""
    d = request.json or {}
    email     = d.get('email', '').strip().lower()
    password  = d.get('password', '')
    aula      = d.get('aula', '').strip().upper()
    turno     = d.get('turno', '').strip().upper()
    fecha     = d.get('fecha', '').strip()
    motivo    = d.get('motivo', '').strip()
    coment    = d.get('comentario', '').strip()

    if not all([email, password, aula, turno, fecha, motivo, coment]):
        return jsonify({'error': 'Todos los campos son obligatorios (incluido comentario y clave).'}), 400

    # Verificar credenciales del docente
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, nombre, password_hash FROM docentes WHERE email=%s",
                (email,)
            )
            row = cur.fetchone()
        if not row or not _verificar_y_migrar_hash(
                conn, 'docentes', 'password_hash', 'id', row[0], password, row[2]):
            return jsonify({'error': 'Credenciales incorrectas. La justificación no fue enviada.'}), 401
        docente_nombre = row[1]

        with conn.cursor() as cur:
            cierres = _cargar_cierres_fecha(cur, fecha)
            if _sin_actividad_en_fecha(cierres, fecha, aula, turno):
                return jsonify({
                    'error': 'No se pueden justificar ausencias en una fecha confirmada como día sin actividad.'
                }), 409
            cur.execute("""
                INSERT INTO justificaciones_ausencia
                  (docente, aula, turno, fecha, motivo, comentario, registrado_por, estado)
                VALUES (%s, %s, %s, %s, %s, %s, %s, 'pendiente')
                ON CONFLICT (docente, aula, turno, fecha)
                DO UPDATE SET motivo=EXCLUDED.motivo,
                              comentario=EXCLUDED.comentario,
                              registrado_por=EXCLUDED.registrado_por,
                              estado='pendiente',
                              revisado_por=NULL,
                              revisado_en=NULL
            """, (docente_nombre, aula, turno, fecha, motivo, coment,
                  f'AUTO:{docente_nombre}'))
            # Recuperar el ID para los botones
            cur.execute("""
                SELECT id FROM justificaciones_ausencia
                WHERE docente=%s AND aula=%s AND turno=%s AND fecha=%s
            """, (docente_nombre, aula, turno, fecha))
            justif_row = cur.fetchone()
            justif_id = justif_row[0] if justif_row else None
        conn.commit()
        # Push a Telegram con botones de aprobar/rechazar
        if justif_id:
            try:
                threading.Thread(
                    target=_tg_notificar_justificacion_nueva,
                    args=(justif_id, docente_nombre, aula, turno, fecha, motivo, coment),
                    daemon=True
                ).start()
            except Exception:
                pass
        return jsonify({
            'msj':     'Justificación enviada. Quedó pendiente de aprobación por la Plana Mayor.',
            'estado':  'pendiente',
            'docente': docente_nombre,
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/justificacion/aprobar', methods=['POST'])
def aprobar_justificacion():
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    d = request.json or {}
    revisado_por = (d.get('revisado_por') or 'Plana Mayor').strip()
    observacion = (d.get('observacion_revision') or '').strip()
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE justificaciones_ausencia
                SET estado='aprobada',
                    revisado_por=%s,
                    revisado_en=CURRENT_TIMESTAMP,
                    observacion_revision=%s
                WHERE docente=%s AND aula=%s AND turno=%s AND fecha=%s
                  AND estado='pendiente'
                RETURNING id
            """, (revisado_por,
                  observacion,
                  d.get('docente'), d.get('aula','').upper(),
                  d.get('turno','').upper(), d.get('fecha')))
            if not cur.fetchone():
                return jsonify({'error':'La solicitud no está pendiente o no existe.'}), 404
        conn.commit()
        _log_audit(revisado_por, 'plana_mayor', 'APROBAR_JUSTIFICACION',
                   'justificaciones_ausencia',
                   f"{d.get('docente')}|{d.get('aula')}|{d.get('fecha')}", observacion or None)
        return jsonify({'msj':'✅ Justificación aprobada.'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/justificacion/pendientes', methods=['GET'])
def listar_justificaciones_pendientes():
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    estado_filtro = request.args.get('estado', 'pendiente')
    if estado_filtro not in ('pendiente', 'resueltas'):
        return jsonify({'error': 'Estado de consulta inválido.'}), 400
    where_estado = "estado='pendiente'" if estado_filtro == 'pendiente' else "estado IN ('aprobada','rechazada')"
    orden = 'creado_en ASC, id ASC' if estado_filtro == 'pendiente' else 'revisado_en DESC, id DESC'
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*)
                FROM justificaciones_ausencia
                WHERE estado='pendiente'
            """)
            total_pendientes = cur.fetchone()[0]
            cur.execute(f"""
                SELECT id, docente, aula, turno, fecha::text, motivo, comentario,
                       registrado_por, creado_en::text, adjunto_nombre, estado,
                       revisado_por, revisado_en::text, observacion_revision
                FROM justificaciones_ausencia
                WHERE {where_estado}
                ORDER BY {orden}
            """)
            pendientes = [{
                'id': row[0],
                'docente': row[1],
                'aula': row[2],
                'turno': row[3],
                'fecha': row[4],
                'motivo': row[5],
                'comentario': row[6],
                'registrado_por': row[7],
                'creado_en': row[8],
                'adjunto_nombre': row[9],
                'estado': row[10],
                'revisado_por': row[11],
                'revisado_en': row[12],
                'observacion_revision': row[13],
            } for row in cur.fetchall()]
        return jsonify({'items': pendientes, 'pendientes': total_pendientes})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/justificacion/rechazar', methods=['POST'])
def rechazar_justificacion():
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    d = request.json or {}
    revisado_por = (d.get('revisado_por') or 'Plana Mayor').strip()
    observacion = (d.get('observacion_revision') or '').strip()
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE justificaciones_ausencia
                SET estado='rechazada',
                    revisado_por=%s,
                    revisado_en=CURRENT_TIMESTAMP,
                    observacion_revision=%s
                WHERE docente=%s AND aula=%s AND turno=%s AND fecha=%s
                  AND estado='pendiente'
                RETURNING id
            """, (revisado_por,
                  observacion,
                  d.get('docente'), d.get('aula','').upper(),
                  d.get('turno','').upper(), d.get('fecha')))
            if not cur.fetchone():
                return jsonify({'error':'La solicitud no está pendiente o no existe.'}), 404
        conn.commit()
        _log_audit(revisado_por, 'plana_mayor', 'RECHAZAR_JUSTIFICACION',
                   'justificaciones_ausencia',
                   f"{d.get('docente')}|{d.get('aula')}|{d.get('fecha')}", observacion or None)
        return jsonify({'msj':'❌ Justificación rechazada.'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/justificacion/<int:jid>/adjuntar', methods=['POST'])
def justificacion_adjuntar(jid):
    """Sube un archivo (certif. médico, parte de servicio, etc.) y lo asocia
    a una justificación existente. Acepta PDF/JPG/PNG hasta 5 MB."""
    if 'archivo' not in request.files:
        return jsonify({'error':'Adjunte un archivo en el campo "archivo"'}), 400
    f = request.files['archivo']
    if not f.filename:
        return jsonify({'error':'Nombre de archivo vacío'}), 400
    nombre_safe = re.sub(r'[^A-Za-z0-9._-]', '_', f.filename)[:120]
    extension = (nombre_safe.rsplit('.',1)[-1] if '.' in nombre_safe else '').lower()
    if extension not in {'pdf','jpg','jpeg','png','webp'}:
        return jsonify({'error':'Formato no permitido (use PDF, JPG, PNG)'}), 400

    upl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads', 'justifs')
    os.makedirs(upl_dir, exist_ok=True)
    nombre_final = f"justif_{jid}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{nombre_safe}"
    path_final = os.path.join(upl_dir, nombre_final)

    data = f.read()
    if len(data) > 5 * 1024 * 1024:
        return jsonify({'error':'Archivo demasiado grande (máx 5 MB)'}), 400
    with open(path_final, 'wb') as fh:
        fh.write(data)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE justificaciones_ausencia
                SET adjunto_nombre=%s, adjunto_path=%s
                WHERE id=%s
                RETURNING docente, aula, turno, fecha::text
            """, (nombre_safe, nombre_final, jid))
            row = cur.fetchone()
        if not row:
            try: os.remove(path_final)
            except Exception: pass
            return jsonify({'error':'Justificación no encontrada'}), 404
        conn.commit()
        _log_audit('docente o admin', 'usuario', 'ADJUNTAR_JUSTIF',
                   'justificaciones_ausencia', f'id={jid}', nombre_safe)
        return jsonify({'msj':'Adjunto guardado correctamente', 'nombre': nombre_safe})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/justificacion/<int:jid>/adjunto', methods=['GET'])
def justificacion_descargar(jid):
    """Devuelve el archivo adjunto (auth: admin o SU)."""
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error':'No autorizado'}), 403
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT adjunto_nombre, adjunto_path FROM justificaciones_ausencia WHERE id=%s", (jid,))
            row = cur.fetchone()
    finally:
        conn.close()
    if not row or not row[1]:
        return jsonify({'error':'Sin adjunto'}), 404
    upl_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads', 'justifs')
    return send_from_directory(upl_dir, row[1], as_attachment=True, download_name=row[0])


@app.route('/api/inasistencias/export', methods=['GET'])
def exportar_inasistencias():
    """Genera CSV de las inasistencias del rango. Requiere auth (Plana Mayor o SU)."""
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    desde        = request.args.get('desde', date.today().isoformat())
    hasta        = request.args.get('hasta', date.today().isoformat())
    turno        = request.args.get('turno', '').strip().upper()
    incluir_just = request.args.get('incluir_justificadas', '1') == '1'
    try:
        data, _ = _calcular_inasistencias(desde, hasta, turno, incluir_just, limite=2000)
    except ValueError as ve:
        return jsonify({'error': str(ve)}), 400

    si = io.StringIO()
    si.write('﻿')  # BOM para que Excel abra bien UTF-8
    writer = csv.writer(si, delimiter=';')
    writer.writerow(['Fecha','Día','Hora','Turno','Aula','Docente','Materia','Estado','Motivo','Comentario'])
    for r in data:
        writer.writerow([
            r.get('fecha',''), r.get('dia',''), r.get('hora_clase',''),
            r.get('turno',''), r.get('aula',''), r.get('docente',''),
            r.get('materia',''), r.get('estado',''),
            r.get('motivo','') or '', r.get('comentario','') or '',
        ])
    nombre = f'inasistencias_{desde}_a_{hasta}.csv'
    return Response(si.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': f'attachment; filename="{nombre}"'})


@app.route('/api/reporte_operativo/export', methods=['GET'])
def exportar_reporte_operativo():
    """Exporta en un único CSV minutas, firmas y ausencias del período."""
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    desde = request.args.get('desde', date.today().isoformat())
    hasta = request.args.get('hasta', desde)
    turno = (request.args.get('turno') or '').strip().upper()
    aula = (request.args.get('aula') or '').strip().upper()
    try:
        date.fromisoformat(desde)
        date.fromisoformat(hasta)
    except ValueError:
        return jsonify({'error': 'Rango de fechas inválido. Use AAAA-MM-DD.'}), 400
    if desde > hasta:
        return jsonify({'error': 'La fecha desde no puede ser posterior a hasta.'}), 400

    filtros = ['fecha BETWEEN %s AND %s']
    parametros = [desde, hasta]
    if turno:
        filtros.append('turno=%s')
        parametros.append(turno)
    if aula:
        filtros.append('aula=%s')
        parametros.append(aula)
    where_sql = ' AND '.join(filtros)
    filas = []
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT fecha::text, turno, aula, bedel, presentes, cant_ausentes,
                       novedades
                FROM minutas WHERE {where_sql}
                ORDER BY fecha, turno, aula
            """, parametros)
            for fecha_v, turno_v, aula_v, bedel, presentes, ausentes, novedades in cur.fetchall():
                filas.append(['MINUTA', fecha_v, turno_v, aula_v, '', '', '', '',
                              presentes if presentes is not None else '',
                              ausentes if ausentes is not None else '', bedel or '',
                              novedades or ''])

            cur.execute(f"""
                SELECT fecha::text, turno, aula, docente, hora_firma::text,
                       lat, lng, precision_m
                FROM firmas_docentes WHERE {where_sql}
                ORDER BY fecha, turno, aula, hora_firma
            """, parametros)
            geo_params = _cargar_params()
            for fecha_v, turno_v, aula_v, docente, hora_firma, lat, lng, precision in cur.fetchall():
                geo = _clasificar_geolocalizacion(lat, lng, precision, geo_params)
                filas.append(['FIRMA', fecha_v, turno_v, aula_v, docente or '',
                              hora_firma or '', geo['estado'], geo['distancia_m'] or '',
                              '', '', '', ''])

            cur.execute(f"""
                SELECT fecha::text, turno, aula, docente, motivo, comentario, estado
                FROM justificaciones_ausencia WHERE {where_sql}
                ORDER BY fecha, turno, aula, docente
            """, parametros)
            for fecha_v, turno_v, aula_v, docente, motivo, comentario, estado in cur.fetchall():
                filas.append(['AUSENCIA', fecha_v, turno_v, aula_v, docente or '',
                              '', estado or '', motivo or '', '', '', '',
                              comentario or ''])
    finally:
        conn.close()

    out = io.StringIO()
    out.write('\ufeff')
    writer = csv.writer(out, delimiter=';')
    writer.writerow(['Tipo', 'Fecha', 'Turno', 'Aula', 'Docente', 'Hora',
                     'Estado', 'Distancia_m', 'Presentes', 'Ausentes',
                     'Bedel', 'Detalle'])
    writer.writerows(filas)
    nombre = f'reporte_operativo_{desde}_a_{hasta}.csv'
    return Response(
        out.getvalue(), mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename="{nombre}"'}
    )


@app.route('/api/reporte_operativo/print', methods=['GET'])
def imprimir_reporte_operativo():
    """Genera una vista HTML imprimible del reporte operativo consolidado."""
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    desde = request.args.get('desde', date.today().isoformat())
    hasta = request.args.get('hasta', desde)
    turno = (request.args.get('turno') or '').strip().upper()
    aula = (request.args.get('aula') or '').strip().upper()
    try:
        date.fromisoformat(desde)
        date.fromisoformat(hasta)
    except ValueError:
        return jsonify({'error': 'Rango de fechas inválido. Use AAAA-MM-DD.'}), 400
    if desde > hasta:
        return jsonify({'error': 'La fecha desde no puede ser posterior a hasta.'}), 400

    filtros = ['fecha BETWEEN %s AND %s']
    parametros = [desde, hasta]
    if turno:
        filtros.append('turno=%s')
        parametros.append(turno)
    if aula:
        filtros.append('aula=%s')
        parametros.append(aula)
    where_sql = ' AND '.join(filtros)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(f"""
                SELECT fecha::text, turno, aula, bedel, presentes, cant_ausentes, novedades
                FROM minutas WHERE {where_sql}
                ORDER BY fecha, turno, aula
            """, parametros)
            minutas = cur.fetchall()
            cur.execute(f"""
                SELECT fecha::text, turno, aula, docente, hora_firma::text,
                       lat, lng, precision_m
                FROM firmas_docentes WHERE {where_sql}
                ORDER BY fecha, turno, aula, hora_firma
            """, parametros)
            firmas = cur.fetchall()
            cur.execute(f"""
                SELECT fecha::text, turno, aula, docente, motivo, estado, comentario
                FROM justificaciones_ausencia WHERE {where_sql}
                ORDER BY fecha, turno, aula, docente
            """, parametros)
            ausencias = cur.fetchall()
        geo_params = _cargar_params()
    finally:
        conn.close()

    esc = lambda value: html.escape(str(value or ''))
    firmas_geo = [_clasificar_geolocalizacion(r[5], r[6], r[7], geo_params)
                  for r in firmas]
    dentro = sum(g['estado'] == 'dentro' for g in firmas_geo)
    fuera = sum(g['estado'] == 'fuera' for g in firmas_geo)
    sin_geo = sum(g['estado'] == 'sin_datos' for g in firmas_geo)
    resumen = (
        f'<div class="kpis"><b>Minutas: {len(minutas)}</b>'
        f'<b>Firmas: {len(firmas)}</b><b>Ausencias: {len(ausencias)}</b>'
        f'<b>Dentro de zona: {dentro}</b><b>Fuera de zona: {fuera}</b>'
        f'<b>Sin GPS: {sin_geo}</b></div>'
    )
    rows_minutas = ''.join(
        f'<tr><td>{esc(f)}</td><td>{esc(t)}</td><td>{esc(a)}</td>'
        f'<td>{esc(p)}</td><td>{esc(au)}</td><td>{esc(b)}</td>'
        f'<td>{esc(n)}</td></tr>'
        for f, t, a, b, p, au, n in minutas
    ) or '<tr><td colspan="7">Sin minutas en el período.</td></tr>'
    rows_firmas = ''.join(
        f'<tr><td>{esc(r[0])}</td><td>{esc(r[1])}</td><td>{esc(r[2])}</td>'
        f'<td>{esc(r[3])}</td><td>{esc(r[4])}</td><td>{esc(g["estado"])}</td>'
        f'<td>{esc(g["distancia_m"])}</td></tr>'
        for r, g in zip(firmas, firmas_geo)
    ) or '<tr><td colspan="7">Sin firmas en el período.</td></tr>'
    rows_ausencias = ''.join(
        f'<tr><td>{esc(f)}</td><td>{esc(t)}</td><td>{esc(a)}</td>'
        f'<td>{esc(d)}</td><td>{esc(m)}</td><td>{esc(e)}</td>'
        f'<td>{esc(c)}</td></tr>'
        for f, t, a, d, m, e, c in ausencias
    ) or '<tr><td colspan="7">Sin ausencias registradas.</td></tr>'
    filtros_txt = f'{desde} al {hasta}' + (f' · Turno {turno}' if turno else '') + (f' · Aula {aula}' if aula else '')
    documento = f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>Reporte operativo SIPA</title><style>
body{{font-family:Arial,sans-serif;color:#172033;margin:24px;font-size:12px}}
h1{{color:#123b5d;margin:0 0 4px}} h2{{color:#123b5d;border-bottom:2px solid #b8c9d6;padding-bottom:5px;margin-top:24px}}
.meta{{color:#526579;margin-bottom:14px}} .kpis{{display:flex;gap:8px;flex-wrap:wrap;margin:12px 0}}
.kpis b{{border:1px solid #cbd5e1;border-radius:6px;padding:8px;background:#f8fafc}}
table{{border-collapse:collapse;width:100%;margin-top:8px}} th,td{{border:1px solid #cbd5e1;padding:5px;text-align:left}}
th{{background:#e8f1f6;color:#123b5d}} tr{{page-break-inside:avoid}}
.pie{{margin-top:24px;color:#64748b;font-size:10px}} @media print{{button{{display:none}}}}
</style></head><body><button onclick="window.print()">🖨️ Imprimir / Guardar PDF</button>
<h1>S.I.P.A. — Reporte Operativo</h1><div class="meta">{esc(filtros_txt)} · Generado: {esc(datetime.now().strftime('%d/%m/%Y %H:%M'))}</div>
{resumen}<h2>Minutas diarias</h2><table><tr><th>Fecha</th><th>Turno</th><th>Aula</th><th>Bedel</th><th>Presentes</th><th>Ausentes</th><th>Novedades</th></tr>{rows_minutas}</table>
<h2>Firmas docentes y geolocalización</h2><table><tr><th>Fecha</th><th>Turno</th><th>Aula</th><th>Docente</th><th>Hora</th><th>Estado GPS</th><th>Distancia m</th></tr>{rows_firmas}</table>
<h2>Ausencias y justificaciones</h2><table><tr><th>Fecha</th><th>Turno</th><th>Aula</th><th>Docente</th><th>Motivo</th><th>Estado</th><th>Comentario</th></tr>{rows_ausencias}</table>
<div class="pie">Documento generado por SIPA · Uso institucional</div></body></html>"""
    return Response(documento, mimetype='text/html; charset=utf-8',
                    headers={'Cache-Control': 'no-store'})


# ═══════════════════════════════════════════════════════════════════════════
# PARTE DIARIO — VISTA IMPRIMIBLE (PDF via Ctrl+P del navegador)
# ═══════════════════════════════════════════════════════════════════════════
@app.route('/api/parte_pdf', methods=['GET'])
def parte_pdf_view():
    """Genera una página HTML lista para imprimir (Ctrl+P → PDF) con membrete GNA.
    Params: ?fecha=YYYY-MM-DD&aula=17&turno=TM"""
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403

    fecha_str = request.args.get('fecha', date.today().isoformat())
    aula      = request.args.get('aula', '').strip()
    turno     = request.args.get('turno', '').strip().upper()

    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Datos de la minuta
            where_parts = ["fecha=%s"]
            params_q: list = [fecha_str]
            if aula:
                where_parts.append("aula=%s"); params_q.append(aula)
            if turno:
                where_parts.append("turno=%s"); params_q.append(turno)
            where_sql = " AND ".join(where_parts)

            cur.execute(f"""
                SELECT aula, fecha::text, turno, bedel, sub_bedel,
                       fe, presentes, cant_ausentes, schedule_json,
                       ausentes_json, novedades, fecha_carga::text
                FROM minutas WHERE {where_sql}
                ORDER BY aula, turno
            """, params_q)
            minutas_raw = cur.fetchall()
            cols_m = [c[0] for c in cur.description]

            # Firmas del día
            cur.execute("""
                SELECT aula, turno, docente, hora_firma::text, fecha::text
                FROM firmas_docentes WHERE fecha=%s
                ORDER BY aula, hora_firma
            """, (fecha_str,))
            firmas_raw = cur.fetchall()

        # Agrupar firmas por aula+turno
        firmas_dict: dict = {}
        for a, t, doc, hora, f in firmas_raw:
            key = f"{a}_{t}"
            firmas_dict.setdefault(key, []).append({'docente': doc, 'hora': hora or ''})

        # Procesar minutas
        minutas = []
        for row in minutas_raw:
            m = dict(zip(cols_m, row))
            sched = m.get('schedule_json')
            if isinstance(sched, str):
                try: sched = json.loads(sched)
                except: sched = []
            m['schedule'] = sched if isinstance(sched, list) else []
            ausen = m.get('ausentes_json')
            if isinstance(ausen, str):
                try: ausen = json.loads(ausen)
                except: ausen = []
            m['ausentes'] = ausen if isinstance(ausen, list) else []
            fk = f"{m['aula']}_{m['turno']}"
            m['firmas'] = firmas_dict.get(fk, [])
            minutas.append(m)

        # Formatear fecha
        try:
            fd = date.fromisoformat(fecha_str)
            _DIAS_ES = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']
            _MESES_ES = ['','enero','febrero','marzo','abril','mayo','junio',
                         'julio','agosto','septiembre','octubre','noviembre','diciembre']
            fecha_larga = f"{_DIAS_ES[fd.weekday()]} {fd.day} de {_MESES_ES[fd.month]} de {fd.year}"
        except:
            fecha_larga = fecha_str

        # Construir HTML
        html_minutas = ""
        for m in minutas:
            filas_sched = ""
            for s in m['schedule']:
                filas_sched += f"<tr><td>{s.get('hora','')}</td><td>{s.get('materia','')}</td><td>{s.get('docente','')}</td></tr>\n"
            filas_firmas = ""
            for f in m['firmas']:
                filas_firmas += f"<tr><td>{f['docente']}</td><td>{f['hora']}</td></tr>\n"
            filas_ausentes = ""
            for a in m['ausentes']:
                nombre = a if isinstance(a, str) else a.get('nombre', str(a))
                filas_ausentes += f"<tr><td>{nombre}</td></tr>\n"

            html_minutas += f"""
            <div class="parte-bloque">
                <h2>Aula {m['aula']} — Turno {m['turno']}</h2>
                <table class="info-tabla">
                    <tr><td><b>Bedel:</b></td><td>{m.get('bedel','') or '—'}</td>
                        <td><b>Sub-Bedel:</b></td><td>{m.get('sub_bedel','') or '—'}</td></tr>
                    <tr><td><b>F.E.:</b></td><td>{m.get('fe','') or '—'}</td>
                        <td><b>Presentes:</b></td><td>{m.get('presentes','') or '—'}</td></tr>
                    <tr><td><b>Ausentes:</b></td><td>{m.get('cant_ausentes','') or '0'}</td>
                        <td><b>Cargada:</b></td><td>{m.get('fecha_carga','')[:16] if m.get('fecha_carga') else '—'}</td></tr>
                </table>
                {'<h3>Cronograma de clases</h3><table class="datos"><thead><tr><th>Hora</th><th>Materia</th><th>Docente</th></tr></thead><tbody>' + filas_sched + '</tbody></table>' if filas_sched else ''}
                {'<h3>Firmas de docentes</h3><table class="datos"><thead><tr><th>Docente</th><th>Hora firma</th></tr></thead><tbody>' + filas_firmas + '</tbody></table>' if filas_firmas else '<p><i>Sin firmas registradas</i></p>'}
                {'<h3>Aspirantes ausentes</h3><table class="datos"><thead><tr><th>Nombre</th></tr></thead><tbody>' + filas_ausentes + '</tbody></table>' if filas_ausentes else ''}
                {'<h3>Novedades</h3><p>' + (m.get("novedades") or "—") + '</p>' if m.get('novedades') else ''}
            </div>
            """

        if not minutas:
            html_minutas = '<p style="text-align:center;color:#888;margin:40px 0;">No hay minutas cargadas para esta fecha/filtro.</p>'

        html = f"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<title>Parte Diario — {fecha_larga}</title>
<style>
  @page {{ size: A4; margin: 15mm 12mm; }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family: 'Segoe UI', Arial, sans-serif; font-size:11pt; color:#1a1a1a; }}
  .membrete {{ text-align:center; border-bottom:3px double #1a3a5c; padding-bottom:12px; margin-bottom:18px; }}
  .membrete h1 {{ font-size:15pt; color:#1a3a5c; margin:4px 0; }}
  .membrete p {{ font-size:9pt; color:#555; }}
  .membrete .escudo {{ font-size:14pt; }}
  .fecha-header {{ text-align:center; font-size:12pt; font-weight:bold; color:#333; margin-bottom:20px; }}
  .parte-bloque {{ page-break-inside:avoid; margin-bottom:22px; border:1px solid #ccc; border-radius:6px; padding:14px; }}
  .parte-bloque h2 {{ font-size:13pt; color:#1a3a5c; border-bottom:1px solid #ddd; padding-bottom:4px; margin-bottom:10px; }}
  .parte-bloque h3 {{ font-size:10pt; color:#444; margin:12px 0 4px; }}
  table.info-tabla {{ width:100%; font-size:10pt; margin-bottom:8px; }}
  table.info-tabla td {{ padding:2px 6px; }}
  table.datos {{ width:100%; border-collapse:collapse; font-size:9.5pt; }}
  table.datos th {{ background:#e8eef4; color:#1a3a5c; padding:4px 8px; text-align:left; border:1px solid #ccc; }}
  table.datos td {{ padding:3px 8px; border:1px solid #ddd; }}
  table.datos tr:nth-child(even) {{ background:#f8f9fa; }}
  .pie {{ text-align:center; font-size:8pt; color:#888; margin-top:30px; border-top:1px solid #ccc; padding-top:8px; }}
  @media print {{
    .no-print {{ display:none !important; }}
    body {{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
  }}
  .btn-imprimir {{ display:block; margin:20px auto; padding:10px 30px; font-size:13pt;
    background:#1a3a5c; color:white; border:none; border-radius:8px; cursor:pointer; }}
  .btn-imprimir:hover {{ background:#2a5a8c; }}
</style>
</head>
<body>
<button class="btn-imprimir no-print" onclick="window.print()">🖨️ Imprimir / Guardar PDF</button>

<div class="membrete">
    <div class="escudo">🇦🇷</div>
    <p>REPÚBLICA ARGENTINA — MINISTERIO DE SEGURIDAD</p>
    <h1>GENDARMERÍA NACIONAL</h1>
    <p>Escuela de Suboficiales "Cbo. Raúl R. Cuello"</p>
    <p>Sistema Integral de Partes de Aula (S.I.P.A.)</p>
</div>

<div class="fecha-header">PARTE DIARIO — {fecha_larga.upper()}</div>

{html_minutas}

<div class="pie">
    Documento generado automáticamente por S.I.P.A. el {datetime.now().strftime('%d/%m/%Y a las %H:%M')} hs.
    <br>Este documento no requiere firma digital — los datos provienen del sistema de registro electrónico.
</div>
</body></html>"""

        return Response(html, mimetype='text/html; charset=utf-8')
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# SU — AUDITORÍA Y LOGS
# ═══════════════════════════════════════════════════════════════════════════
@app.route('/api/su/audit_log', methods=['GET'])
def su_audit_log():
    err = _exigir_su(request)
    if err: return err
    limit = min(int(request.args.get('limit', 100)), 500)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, fecha::text, usuario, rol, accion, tabla, registro_ref, detalle, ip
                FROM audit_log ORDER BY fecha DESC LIMIT %s
            """, (limit,))
            cols = [c[0] for c in cur.description]
            return jsonify([dict(zip(cols, r)) for r in cur.fetchall()])
    finally:
        conn.close()


@app.route('/api/su/rate_limit', methods=['GET'])
def su_rate_limit_estado():
    """Lista el estado actual del rate limiter (IPs bloqueadas y con intentos fallidos). Solo SU."""
    err = _exigir_su(request)
    if err: return err
    ahora = datetime.now()
    resultado = []
    for ip, entrada in _RATE_LIMIT.items():
        bloqueado_hasta = entrada.get('bloqueado_hasta')
        resultado.append({
            'ip':              ip,
            'intentos':        entrada.get('intentos', 0),
            'bloqueada':       bool(bloqueado_hasta and bloqueado_hasta > ahora),
            'bloqueada_hasta': bloqueado_hasta.isoformat() if bloqueado_hasta else None,
            'segundos_restantes': max(0, int((bloqueado_hasta - ahora).total_seconds()))
                                  if bloqueado_hasta and bloqueado_hasta > ahora else 0,
        })
    resultado.sort(key=lambda x: x['bloqueada'], reverse=True)
    return jsonify({
        'total_entradas':   len(resultado),
        'ips_bloqueadas':   sum(1 for r in resultado if r['bloqueada']),
        'max_intentos':     _RATE_MAX_INTENTOS,
        'bloqueo_segundos': _RATE_BLOQUEO_SEG,
        'entradas':         resultado,
    })


@app.route('/api/su/rate_limit/<path:ip>', methods=['DELETE'])
def su_rate_limit_desbloquear(ip):
    """Desbloquea una IP específica del rate limiter. Solo SU."""
    err = _exigir_su(request)
    if err: return err
    if ip in _RATE_LIMIT:
        _RATE_LIMIT.pop(ip)
        _log_audit('TIC', 'super_usuario', 'RL_DESBLOQUEO', None, ip, 'Desbloqueado manualmente')
        return jsonify({'msj': f'IP {ip} desbloqueada.'})
    return jsonify({'msj': f'IP {ip} no estaba en el rate limiter.'})


@app.route('/api/su/rate_limit', methods=['DELETE'])
def su_rate_limit_limpiar_todo():
    """Limpia todo el rate limiter. Solo SU."""
    err = _exigir_su(request)
    if err: return err
    n = len(_RATE_LIMIT)
    _RATE_LIMIT.clear()
    _log_audit('TIC', 'super_usuario', 'RL_RESET_TOTAL', None, None, f'{n} entradas eliminadas')
    return jsonify({'msj': f'Rate limiter limpiado. {n} entradas eliminadas.'})


@app.route('/api/su/failed_logins', methods=['GET'])
def su_failed_logins():
    err = _exigir_su(request)
    if err: return err
    limit = min(int(request.args.get('limit', 100)), 500)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, fecha::text, tipo, detalle, ip
                FROM failed_logins ORDER BY fecha DESC LIMIT %s
            """, (limit,))
            cols = [c[0] for c in cur.description]
            return jsonify([dict(zip(cols, r)) for r in cur.fetchall()])
    finally:
        conn.close()


@app.route('/api/su/system_log', methods=['GET'])
def su_system_log():
    err = _exigir_su(request)
    if err: return err
    limit = min(int(request.args.get('limit', 100)), 500)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, fecha::text, nivel, endpoint, mensaje, traceback
                FROM system_log ORDER BY fecha DESC LIMIT %s
            """, (limit,))
            cols = [c[0] for c in cur.description]
            return jsonify([dict(zip(cols, r)) for r in cur.fetchall()])
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# SU — MODO MANTENIMIENTO + HEALTH CHECK
# ═══════════════════════════════════════════════════════════════════════════
_APP_STARTED_AT = datetime.now()

@app.route('/api/su/maintenance', methods=['POST'])
def su_maintenance_toggle():
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    activo = '1' if d.get('activo') else '0'
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO config_sistema (clave, valor, descripcion, actualizado)
                VALUES ('modo_mantenimiento', %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (clave) DO UPDATE
                  SET valor = EXCLUDED.valor, actualizado = CURRENT_TIMESTAMP
            """, (activo, PARAMS_DEFAULT['modo_mantenimiento']['descripcion']))
        conn.commit()
        _log_audit('TIC', 'super_usuario',
                   'MAINTENANCE_' + ('ON' if activo == '1' else 'OFF'),
                   'config_sistema', 'modo_mantenimiento', f'valor={activo}')
        _sse_notificar({
            'tipo': 'mantenimiento',
            'activo': activo == '1',
            'ts': datetime.now().isoformat(),
        })
        return jsonify({
            'msj':    f'Modo mantenimiento {"ACTIVADO" if activo == "1" else "DESACTIVADO"}.',
            'activo': activo == '1',
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/su/health', methods=['GET'])
def su_health():
    err = _exigir_su(request)
    if err: return err
    status = {
        'ahora':             datetime.now().isoformat(),
        'uptime_seg':        int((datetime.now() - _APP_STARTED_AT).total_seconds()),
        'sesiones_su':       len(_SU_TOKENS),
        'sesiones_admin':    len(_ADMIN_TOKENS),
        'db_ok':             False,
        'db_error':          None,
        'tablas_filas':      {},
        'modo_mantenimiento': _cargar_params().get('modo_mantenimiento', {}).get('valor', '0') == '1',
    }
    conn = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            status['pg_version'] = cur.fetchone()[0].split(',')[0]
            # 17 operativas
            tablas = [
                'cronograma_maestro','cronograma_versiones','aspirantes','docentes',
                'minutas','firmas_docentes','justificaciones_ausencia','pin_overrides',
                'usuarios_admin','audit_log','failed_logins','system_log',
                'config_sistema',
                'bedeles_telegram','bedel_link_tokens','recordatorios_telegram','bot_comando_log',
            ]
            for t in tablas:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {t}")
                    status['tablas_filas'][t] = cur.fetchone()[0]
                except Exception:
                    conn.rollback()
                    status['tablas_filas'][t] = None
            # 2 opcionales (archivo): si no existen, no es error
            for t in ['minutas_archivo','firmas_archivo']:
                try:
                    cur.execute(f"SELECT COUNT(*) FROM {t}")
                    status['tablas_filas'][t] = cur.fetchone()[0]
                except Exception:
                    conn.rollback()
                    status['tablas_filas'][t] = '—'   # marca explícita: pendiente
        status['db_ok'] = True
    except Exception as e:
        status['db_error'] = str(e)
    finally:
        if conn: conn.close()

    # ── Health check real del bot Telegram ──
    status['telegram'] = {'configurado': False, 'bot_ok': False, 'bot_nombre': None, 'error': None}
    try:
        cfg = _telegram_config_actual()
        if cfg and cfg.get('token'):
            status['telegram']['configurado'] = True
            import urllib.request
            tg_url = f"https://api.telegram.org/bot{cfg['token']}/getMe"
            req_tg = urllib.request.Request(tg_url, method='GET')
            with urllib.request.urlopen(req_tg, timeout=5) as resp:
                tg_data = json.loads(resp.read().decode())
                if tg_data.get('ok'):
                    status['telegram']['bot_ok'] = True
                    bot_info = tg_data.get('result', {})
                    status['telegram']['bot_nombre'] = bot_info.get('first_name', '')
                    status['telegram']['bot_username'] = bot_info.get('username', '')
                else:
                    status['telegram']['error'] = 'API respondio ok=false'
    except Exception as e:
        status['telegram']['error'] = str(e)[:200]

    status['scheduler_activo'] = bool(_SCHEDULER_RUNNING)
    status['bot_loop_activo'] = bool(_BOT_LOOP_RUNNING)

    return jsonify(status)


# ═══════════════════════════════════════════════════════════════════════════
# SU — GESTIÓN DE USUARIOS Y SESIONES
# ═══════════════════════════════════════════════════════════════════════════
@app.route('/api/su/revoke_tokens', methods=['POST'])
def su_revoke_tokens():
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    scope = d.get('scope', 'admin')  # 'admin' | 'su' | 'all'
    revocados = 0
    if scope in ('admin','all'):
        revocados += len(_ADMIN_TOKENS)
        _ADMIN_TOKENS.clear()
    if scope in ('su','all'):
        # No revocar el propio token activo
        tok_actual = request.headers.get('X-SU-Token','')
        otros = [t for t in _SU_TOKENS if t != tok_actual]
        revocados += len(otros)
        for t in otros: _SU_TOKENS.pop(t, None)
    if scope == 'all':
        revocados += len(_DOCENTE_TOKENS)
        for token in list(_DOCENTE_TOKENS):
            _SESIONES_META.pop(token, None)
        _DOCENTE_TOKENS.clear()
    _log_audit('TIC','super_usuario','REVOKE_TOKENS', detalle=f'scope={scope}, revocados={revocados}')
    return jsonify({'msj': f'Sesiones revocadas: {revocados}', 'scope': scope})


@app.route('/api/su/reset_docente_password', methods=['POST'])
def su_reset_docente():
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    email   = (d.get('email') or '').strip().lower()
    new_pwd = d.get('new_password') or secrets.token_urlsafe(8)[:8]
    if not email:
        return jsonify({'error':'email requerido'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE docentes SET password_hash=%s WHERE email=%s
                RETURNING id, nombre
            """, (hash_password(new_pwd), email))
            row = cur.fetchone()
        if not row:
            conn.rollback()
            return jsonify({'error': 'No existe un docente con ese email'}), 404
        conn.commit()
        for token, meta in list(_DOCENTE_TOKENS.items()):
            if meta['id'] == row[0]:
                _DOCENTE_TOKENS.pop(token, None)
                _SESIONES_META.pop(token, None)
        _log_audit('TIC','super_usuario','RESET_PASSWORD_DOCENTE',
                   'docentes', email, f'docente={row[1]}')
        return jsonify({'msj': f'Password reseteado para {row[1]}', 'nueva_password': new_pwd})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/su/listar_docentes', methods=['GET'])
def su_listar_docentes():
    err = _exigir_su(request)
    if err: return err
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, email, dni, creado_en::text
                FROM docentes ORDER BY nombre
            """)
            cols = [c[0] for c in cur.description]
            return jsonify([dict(zip(cols, r)) for r in cur.fetchall()])
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# SU — RESET MAESTRO DEL CRONOGRAMA
# ═══════════════════════════════════════════════════════════════════════════
@app.route('/api/su/hard_reset_cronograma', methods=['POST'])
def su_hard_reset_cronograma():
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    if (d.get('confirmacion') or '').strip() != 'PURGAR CRONOGRAMA':
        return jsonify({'error':'Frase incorrecta. Escriba exactamente: PURGAR CRONOGRAMA'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM cronograma_maestro")
            previo = cur.fetchone()[0]
            cur.execute("TRUNCATE cronograma_maestro RESTART IDENTITY")
        conn.commit()
        _log_audit('TIC','super_usuario','HARD_RESET_CRONOGRAMA',
                   'cronograma_maestro', None, f'filas_eliminadas={previo}')
        return jsonify({'msj': f'Cronograma purgado. Filas eliminadas: {previo}'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# SSE — PUSH EN TIEMPO REAL (firmas, justificaciones, alertas)
# Más simple que WebSockets, sin nuevas dependencias, auto-reconexión nativa.
# ═══════════════════════════════════════════════════════════════════════════
import queue as _queue
_SSE_SUBS = {}            # id_conexion → queue.Queue
_SSE_LOCK = threading.Lock()

def _sse_notificar(evento_dict):
    """Push un evento a todos los suscriptores activos. No bloquea."""
    with _SSE_LOCK:
        muertos = []
        for qid, q in _SSE_SUBS.items():
            try:
                q.put_nowait(evento_dict)
            except Exception:
                muertos.append(qid)
        for qid in muertos:
            _SSE_SUBS.pop(qid, None)


def _sse_suscribir():
    """Crea cola dedicada para esta conexión. Devuelve (id, cola)."""
    q = _queue.Queue(maxsize=200)
    qid = secrets.token_hex(8)
    with _SSE_LOCK:
        _SSE_SUBS[qid] = q
    return qid, q


def _sse_desuscribir(qid):
    with _SSE_LOCK:
        _SSE_SUBS.pop(qid, None)


def _token_admin_o_su_via_query(req):
    """EventSource no soporta headers personalizados → token viene por query."""
    tok = req.args.get('token', '')
    if not tok: return False
    # Aceptamos token de admin o de SU
    if tok in _ADMIN_TOKENS:
        v = _ADMIN_TOKENS.get(tok)
        if isinstance(v, datetime) and v > datetime.now():
            return True
    if tok in _SU_TOKENS:
        v = _SU_TOKENS.get(tok)
        if isinstance(v, datetime) and v > datetime.now():
            return True
    return False


@app.route('/api/sse/monitor', methods=['GET'])
def sse_monitor():
    """Stream de eventos en tiempo real. Auth por query string ?token=XXX."""
    if not _token_admin_o_su_via_query(request):
        return jsonify({'error':'No autorizado (token en query string requerido)'}), 403

    qid, q = _sse_suscribir()
    token_inicial = request.args.get('token', '')
    revalidaciones = 0

    def generar():
        nonlocal revalidaciones
        yield f"event: conectado\ndata: {json.dumps({'qid': qid, 'ts': datetime.now().isoformat()})}\n\n"
        try:
            while True:
                try:
                    evt = q.get(timeout=25)
                    if evt is None:
                        break
                    tipo = evt.get('tipo', 'update')
                    yield f"event: {tipo}\ndata: {json.dumps(evt, default=str)}\n\n"
                except _queue.Empty:
                    # Cada 60s (cada 2-3 timeouts) re-validar token contra los stores actuales
                    revalidaciones += 1
                    if revalidaciones % 2 == 0:
                        v_adm = _ADMIN_TOKENS.get(token_inicial)
                        v_su  = _SU_TOKENS.get(token_inicial)
                        valido = (isinstance(v_adm, datetime) and v_adm > datetime.now()) or \
                                 (isinstance(v_su,  datetime) and v_su  > datetime.now())
                        if not valido:
                            yield f"event: token_expirado\ndata: {json.dumps({'ts': datetime.now().isoformat()})}\n\n"
                            break
                    yield f": ping {datetime.now().isoformat()}\n\n"
        except (GeneratorExit, BrokenPipeError):
            pass
        finally:
            _sse_desuscribir(qid)

    return Response(stream_with_context(generar()),
                    mimetype='text/event-stream',
                    headers={
                        'Cache-Control': 'no-cache',
                        'X-Accel-Buffering': 'no',  # importante si está detrás de nginx
                        'Connection': 'keep-alive',
                    })


@app.route('/api/sse/stats', methods=['GET'])
def sse_stats():
    """Cuántos clientes hay escuchando — útil para diagnóstico."""
    err = _exigir_su(request)
    if err: return err
    return jsonify({
        'conexiones_activas': len(_SSE_SUBS),
        'ids': list(_SSE_SUBS.keys()),
    })


# ═══════════════════════════════════════════════════════════════════════════
# VERSIONADO DE CRONOGRAMAS — historial + restore
# ═══════════════════════════════════════════════════════════════════════════
def _guardar_version_cronograma(cur, aula, turno, motivo='Sobrescritura', creado_por='Sistema'):
    """Antes de sobrescribir un cronograma, guarda la versión actual en cronograma_versiones."""
    try:
        cur.execute("""
            SELECT config_json FROM cronograma_maestro
            WHERE aula=%s AND turno=%s
        """, (aula, turno))
        row = cur.fetchone()
        if not row or not row[0]:
            return  # Nada que versionar
        config = row[0]
        if isinstance(config, str):
            try: config_parsed = json.loads(config)
            except (ValueError, TypeError): config_parsed = []
        else:
            config_parsed = config
        bloques_cnt = len(config_parsed) if isinstance(config_parsed, list) else 0
        cur.execute("""
            INSERT INTO cronograma_versiones (aula, turno, config_json, creado_por, motivo, bloques_cnt)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (aula, turno, json.dumps(config_parsed), creado_por, motivo, bloques_cnt))
    except Exception as e:
        print(f"[versionado] No se pudo guardar versión de {aula}/{turno}: {e}")


@app.route('/api/su/cronograma_versiones', methods=['GET'])
def su_cronograma_versiones():
    """Lista versiones históricas de un aula+turno o todas."""
    err = _exigir_su(request)
    if err: return err
    aula  = request.args.get('aula', '').strip().upper()
    turno = request.args.get('turno', '').strip().upper()
    conn = get_db()
    try:
        with conn.cursor() as cur:
            if aula and turno:
                cur.execute("""
                    SELECT id, aula, turno, creado_en::text, creado_por, motivo, bloques_cnt
                    FROM cronograma_versiones
                    WHERE aula=%s AND turno=%s
                    ORDER BY creado_en DESC LIMIT 50
                """, (aula, turno))
            else:
                cur.execute("""
                    SELECT id, aula, turno, creado_en::text, creado_por, motivo, bloques_cnt
                    FROM cronograma_versiones
                    ORDER BY creado_en DESC LIMIT 100
                """)
            cols = [c[0] for c in cur.description]
            return jsonify([dict(zip(cols, r)) for r in cur.fetchall()])
    finally:
        conn.close()


@app.route('/api/su/cronograma_versiones/<int:vid>/restaurar', methods=['POST'])
def su_cronograma_restaurar(vid):
    """Restaura una versión guardada (y guarda la actual como otra versión, como undo)."""
    err = _exigir_su(request)
    if err: return err
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT aula, turno, config_json
                FROM cronograma_versiones WHERE id=%s
            """, (vid,))
            row = cur.fetchone()
            if not row:
                return jsonify({'error':'Versión no encontrada'}), 404
            aula, turno, cfg = row
            # Snapshot del actual antes de restaurar (para poder revertir el revert)
            _guardar_version_cronograma(cur, aula, turno,
                                        motivo=f'Snapshot pre-restore v{vid}',
                                        creado_por='TIC')
            # Restaurar
            if isinstance(cfg, str):
                try: cfg_str = cfg
                except: cfg_str = json.dumps(cfg)
            else:
                cfg_str = json.dumps(cfg)
            cur.execute("""
                INSERT INTO cronograma_maestro (aula, turno, config_json)
                VALUES (%s, %s, %s)
                ON CONFLICT (aula, turno) DO UPDATE
                SET config_json = EXCLUDED.config_json
            """, (aula, turno, cfg_str))
        conn.commit()
        _log_audit('TIC','super_usuario','RESTAURAR_CRONOGRAMA',
                   'cronograma_maestro', f'{aula}/{turno}', f'desde version id={vid}')
        return jsonify({'msj': f'Cronograma de Aula {aula} ({turno}) restaurado desde v{vid}'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# CONSOLA SQL READ-ONLY (TIC) — solo SELECTs, ROLLBACK siempre
# ═══════════════════════════════════════════════════════════════════════════
_SQL_BLOQUEADAS = re.compile(
    r'\b(INSERT|UPDATE|DELETE|DROP|TRUNCATE|CREATE|ALTER|GRANT|REVOKE|'
    r'COMMIT|ROLLBACK|VACUUM|REINDEX|COPY|EXECUTE|CALL)\b',
    re.IGNORECASE
)

@app.route('/api/su/sql', methods=['POST'])
def su_sql_console():
    """Ejecuta una query SELECT y devuelve hasta 500 filas. Bloquea cualquier
       comando que modifique datos. La transacción siempre se rollbackea."""
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    query = (d.get('query') or '').strip().rstrip(';')
    if not query:
        return jsonify({'error':'Query vacía'}), 400
    if _SQL_BLOQUEADAS.search(query):
        return jsonify({'error':'Solo se permiten queries SELECT. Comandos de modificación bloqueados.'}), 403
    # Rechazar múltiples sentencias por si acaso
    if ';' in query:
        return jsonify({'error':'No se permiten múltiples sentencias (; separadora)'}), 400
    if not re.match(r'^\s*(SELECT|WITH|SHOW|EXPLAIN)\b', query, re.IGNORECASE):
        return jsonify({'error':'Solo se permiten SELECT / WITH / SHOW / EXPLAIN'}), 403

    conn = get_db()
    try:
        # Forzar transacción read-only para defensa en profundidad
        with conn.cursor() as cur:
            cur.execute("SET TRANSACTION READ ONLY")
            cur.execute("SET LOCAL statement_timeout = '10s'")
            tiene_limit = bool(re.search(r'\bLIMIT\s+\d+', query, re.IGNORECASE))
            cur.execute(query if tiene_limit else (query + " LIMIT 500"))
            cols = [c[0] for c in cur.description] if cur.description else []
            filas = cur.fetchall()
        conn.rollback()  # Siempre rollback — defense in depth
        _log_audit('TIC','super_usuario','SQL_CONSOLE', None,
                   query[:80], f'{len(filas)} filas devueltas')
        return jsonify({
            'cols': cols,
            'rows': [[str(v) if not isinstance(v, (int, float, bool, type(None))) else v for v in r] for r in filas],
            'count': len(filas),
            'truncated': len(filas) == 500,
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 400
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# SU — DASHBOARD AGREGADO (gráficos + KPIs)
# ═══════════════════════════════════════════════════════════════════════════
@app.route('/tv')
def tv_dashboard():
    """Vista fullscreen para TV de oficina. Sin auth (pero sin datos sensibles)."""
    return render_template('tv.html')


@app.route('/status')
def status_publico():
    """Página de estado pública. Sin auth, sin datos sensibles."""
    return render_template('status.html')


@app.route('/api/tv/datos', methods=['GET'])
def tv_datos():
    """JSON para el dashboard TV. Cero datos personales — sólo agregados."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            # KPIs del día
            cur.execute("""
                SELECT COUNT(DISTINCT (aula, turno)),
                       COALESCE(SUM(fe::int), 0),
                       COALESCE(SUM(presentes::int), 0),
                       COALESCE(SUM(cant_ausentes::int), 0)
                FROM minutas WHERE fecha::date = CURRENT_DATE
            """)
            aulas_op, fe, pres, aus = cur.fetchone() or (0, 0, 0, 0)
            cur.execute("SELECT COUNT(*) FROM firmas_docentes WHERE fecha::date = CURRENT_DATE")
            firmas_hoy = cur.fetchone()[0]
            # Detalle por aula
            cur.execute("""
                SELECT aula, turno, fe::int, presentes::int, cant_ausentes::int
                FROM minutas WHERE fecha::date = CURRENT_DATE
                ORDER BY aula, turno
            """)
            aulas = []
            for a, t, f, p, au in cur.fetchall():
                pcta = round(100.0 * (p or 0) / (f or 1), 1) if (f or 0) > 0 else 0
                aulas.append({'aula': a, 'turno': t, 'fe': f or 0,
                              'presentes': p or 0, 'ausentes': au or 0, 'pct': pcta})
            # Tendencia última semana (sparkline)
            cur.execute("""
                SELECT fecha::date,
                       COALESCE(SUM(fe::int), 0),
                       COALESCE(SUM(presentes::int), 0)
                FROM minutas WHERE fecha::date >= CURRENT_DATE - 6
                GROUP BY fecha::date ORDER BY fecha::date
            """)
            tendencia = []
            for fec, f, p in cur.fetchall():
                pct = round(100.0 * (p or 0) / (f or 1), 1) if (f or 0) > 0 else 0
                tendencia.append({'fecha': fec.isoformat(), 'pct': pct})
            # Últimas 8 firmas (ticker)
            cur.execute("""
                SELECT docente, aula, turno, hora_firma::text, fecha::text
                FROM firmas_docentes
                WHERE timestamp_utc >= NOW() - INTERVAL '4 hours'
                ORDER BY timestamp_utc DESC LIMIT 8
            """)
            ultimas_firmas = [
                {'docente': d, 'aula': a, 'turno': t, 'hora': (h or '')[:5], 'fecha': f}
                for d, a, t, h, f in cur.fetchall()
            ]
        conn.close()
        pct_total = round(100.0 * pres / fe, 1) if fe > 0 else 0
        return jsonify({
            'kpis': {
                'aulas_operativas': aulas_op,
                'fe':                fe,
                'presentes':         pres,
                'ausentes':          aus,
                'firmas_hoy':        firmas_hoy,
                'pct_general':       pct_total,
            },
            'aulas':         aulas,
            'tendencia':     tendencia,
            'ultimas_firmas': ultimas_firmas,
            'fecha_iso':     date.today().isoformat(),
            'hora':          datetime.now().strftime('%H:%M:%S'),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/status/public', methods=['GET'])
def status_publico_api():
    """Status público sin auth. Solo info no sensible: servicios up/down + uptime."""
    estado = {
        'web':     True,    # si responde es porque está up
        'db':      False,
        'bot':     False,
        'scheduler': bool(_SCHEDULER_RUNNING),
    }
    # DB
    db_ms = None
    try:
        t0 = _time_mod.perf_counter()
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        conn.close()
        db_ms = round((_time_mod.perf_counter() - t0) * 1000, 1)
        estado['db'] = True
    except Exception:
        estado['db'] = False
    # Bot
    estado['bot'] = bool(_BOT_LOOP_RUNNING)
    # Uptime (simple — desde el arranque de este proceso)
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        boot = datetime.fromtimestamp(proc.create_time())
        delta = datetime.now() - boot
        uptime_str = f"{delta.days}d {delta.seconds // 3600}h {(delta.seconds % 3600) // 60}m"
    except Exception:
        uptime_str = '—'
    # Incidentes recientes (últimos 7 días, sin detalle sensible)
    incidentes = 0
    ultima_caida = None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*), MAX(fecha)::text FROM system_log
                WHERE nivel='ERROR' AND fecha >= NOW() - INTERVAL '7 days'
            """)
            r = cur.fetchone() or (0, None)
            incidentes = r[0]
            ultima_caida = r[1]
        conn.close()
    except Exception:
        pass
    return jsonify({
        'estado':       estado,
        'db_latency_ms': db_ms,
        'uptime':       uptime_str,
        'incidentes_7d': incidentes,
        'ultima_caida':  (ultima_caida or '')[:19].replace('T', ' ') if ultima_caida else None,
        'timestamp':    datetime.now().isoformat(),
    })


@app.route('/api/su/duplicados', methods=['GET'])
def su_duplicados():
    """Detecta posibles duplicados de docentes usando canonicalización por tokens
    de apellido + similitud. Útil para fusionar GARCIA vs García vs GARCIA, JUAN."""
    err = _exigir_su(request)
    if err: return err
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, email, dni FROM docentes
                ORDER BY nombre
            """)
            todos = cur.fetchall()
        conn.close()
        # Agrupar por canonicalización (mismas reglas que el parser)
        nombres = [r[1] for r in todos]
        mapa = _canonicalizar_nombres(nombres) if nombres else {}
        # Invertir mapa: canónico → [variantes]
        grupos = {}
        for variante, canonico in mapa.items():
            grupos.setdefault(canonico, []).append(variante)
        # Solo nos quedamos con grupos que tienen 2+ variantes (= duplicados)
        sospechosos = []
        nombre_to_row = {r[1]: r for r in todos}
        for canonico, variantes in grupos.items():
            if len(variantes) < 2:
                continue
            registros = []
            for var in variantes:
                row = nombre_to_row.get(var)
                if row:
                    registros.append({
                        'id': row[0], 'nombre': row[1],
                        'email': row[2] or '', 'dni': row[3] or '',
                    })
            if len(registros) >= 2:
                sospechosos.append({
                    'canonico': canonico,
                    'cantidad': len(registros),
                    'docentes': registros,
                })
        # También detectar emails duplicados (case-insensitive)
        emails_repetidos = []
        seen = {}
        for r in todos:
            em = (r[2] or '').strip().lower()
            if not em: continue
            seen.setdefault(em, []).append({'id': r[0], 'nombre': r[1], 'dni': r[3] or ''})
        for em, regs in seen.items():
            if len(regs) >= 2:
                emails_repetidos.append({'email': em, 'docentes': regs})
        return jsonify({
            'duplicados_por_nombre': sospechosos,
            'duplicados_por_email':  emails_repetidos,
            'total_docentes': len(todos),
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/su/fusionar_docente', methods=['POST'])
def su_fusionar_docente():
    """Fusiona docente_origen → docente_destino:
       - Mueve firmas, justificaciones, cronograma al destino
       - Borra el origen
       - Todo en una transacción"""
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    id_origen  = int(d.get('id_origen') or 0)
    id_destino = int(d.get('id_destino') or 0)
    if not id_origen or not id_destino or id_origen == id_destino:
        return jsonify({'ok': False, 'error': 'IDs inválidos'}), 400
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT nombre FROM docentes WHERE id=%s", (id_origen,))
            row_o = cur.fetchone()
            cur.execute("SELECT nombre FROM docentes WHERE id=%s", (id_destino,))
            row_d = cur.fetchone()
            if not row_o or not row_d:
                return jsonify({'ok': False, 'error': 'Algún docente no existe'}), 404
            nom_origen, nom_destino = row_o[0], row_d[0]
            # Mover firmas (case-insensitive)
            cur.execute("""
                UPDATE firmas_docentes SET docente=%s
                WHERE LOWER(docente)=LOWER(%s)
            """, (nom_destino, nom_origen))
            n_firmas = cur.rowcount
            # Mover justificaciones
            cur.execute("""
                UPDATE justificaciones_ausencia SET docente=%s
                WHERE LOWER(docente)=LOWER(%s)
            """, (nom_destino, nom_origen))
            n_justif = cur.rowcount
            # Eliminar el origen
            cur.execute("DELETE FROM docentes WHERE id=%s", (id_origen,))
        conn.commit()
        conn.close()
        _log_audit('TIC', 'super_usuario', 'FUSIONAR_DOCENTE', 'docentes',
                   f'{nom_origen} → {nom_destino}',
                   f'firmas={n_firmas} justif={n_justif}')
        return jsonify({
            'ok': True,
            'msj': f'Fusionado "{nom_origen}" → "{nom_destino}".',
            'firmas_movidas': n_firmas,
            'justif_movidas': n_justif,
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


def _analizar_vinculaciones_docentes(cur):
    cur.execute("""
        SELECT id, nombre, email, dni
        FROM docentes
        WHERE es_pgnp=FALSE
        ORDER BY nombre
    """)
    cuentas = [
        {'id': r[0], 'nombre': r[1], 'email': r[2], 'dni': r[3], 'aulas_vinculadas': []}
        for r in cur.fetchall()
    ]
    bloques_por_cuenta = {cuenta['id']: cuenta['aulas_vinculadas'] for cuenta in cuentas}
    cur.execute("""
        SELECT aula, turno, config_json
        FROM cronograma_maestro
        WHERE config_json IS NOT NULL
        ORDER BY aula, turno
    """)
    bloques_sin_cuenta = {}
    for aula, turno, config in cur.fetchall():
        if isinstance(config, str):
            try:
                config = json.loads(config)
            except (ValueError, TypeError):
                continue
        bloques = config if isinstance(config, list) else [config] if isinstance(config, dict) else []
        for indice, bloque in enumerate(bloques):
            if not isinstance(bloque, dict):
                continue
            nombre = str(bloque.get('doc') or '').strip()
            if not nombre:
                continue
            clave = _clave_nombre_visible_docente(nombre)
            coincidencias = [
                cuenta for cuenta in cuentas
                if _clave_nombre_visible_docente(cuenta['nombre']) == clave
            ]
            if len(coincidencias) == 1:
                bloques_por_cuenta[coincidencias[0]['id']].append({
                    'aula': aula,
                    'turno': turno,
                    'dia': str(bloque.get('dia') or ''),
                    'hora': str(bloque.get('hora') or ''),
                    'materia': str(bloque.get('asig') or ''),
                })
                continue
            if coincidencias:
                for cuenta in coincidencias:
                    bloques_por_cuenta[cuenta['id']].append({
                        'aula': aula,
                        'turno': turno,
                        'dia': str(bloque.get('dia') or ''),
                        'hora': str(bloque.get('hora') or ''),
                        'materia': str(bloque.get('asig') or ''),
                        'ambiguo': True,
                    })
            grupo = bloques_sin_cuenta.setdefault(nombre, {
                'nombre': nombre, 'bloques': [],
                'ambigua': len(coincidencias) > 1,
            })
            grupo['bloques'].append({
                'aula': aula,
                'turno': turno,
                'indice': indice,
                'dia': str(bloque.get('dia') or ''),
                'hora': str(bloque.get('hora') or ''),
                'materia': str(bloque.get('asig') or ''),
            })

    grupos = list(bloques_sin_cuenta.values())
    pares_seguros = {}
    for grupo in grupos:
        nombre = grupo['nombre']
        tokens_origen = re.findall(r'[A-Z0-9]+', _sin_acentos(nombre).upper())
        candidatos = []
        if not grupo['ambigua'] and len(tokens_origen) >= 2:
            for cuenta in cuentas:
                tokens_cuenta = re.findall(r'[A-Z0-9]+', _sin_acentos(cuenta['nombre']).upper())
                if len(tokens_cuenta) != len(tokens_origen) or len(tokens_cuenta) < 2:
                    continue
                # La comparación automática es deliberadamente conservadora:
                # mantiene el apellido/primer token y solo tolera un error menor
                # en los demás tokens, con nombres en el mismo orden.
                if tokens_origen[0] != tokens_cuenta[0]:
                    continue
                similitudes_tokens = [
                    _similitud(origen, destino)
                    for origen, destino in zip(tokens_origen, tokens_cuenta)
                ]
                diferencias = sum(
                    origen != destino
                    for origen, destino in zip(tokens_origen, tokens_cuenta)
                )
                if diferencias > 1 or any(valor < 0.90 for valor in similitudes_tokens[1:]):
                    continue
                similitud = _similitud(' '.join(tokens_origen), ' '.join(tokens_cuenta))
                if similitud >= 0.92:
                    candidatos.append((similitud, cuenta))

        candidatos.sort(key=lambda item: (-item[0], item[1]['nombre'].casefold()))
        if candidatos and (len(candidatos) == 1 or candidatos[0][0] - candidatos[1][0] >= 0.08):
            pares_seguros[nombre] = {
                'docente_id': candidatos[0][1]['id'],
                'docente': candidatos[0][1]['nombre'],
                'email': candidatos[0][1]['email'],
                'dni': candidatos[0][1]['dni'],
                'similitud': round(candidatos[0][0] * 100),
                'bloques': grupo['bloques'],
            }

    # No se automatiza si varias variantes apuntan a una misma cuenta:
    # podrían ser errores independientes o docentes distintos.
    usos_por_cuenta = {}
    for sugerencia in pares_seguros.values():
        usos_por_cuenta.setdefault(sugerencia['docente_id'], 0)
        usos_por_cuenta[sugerencia['docente_id']] += 1
    pares_seguros = {
        nombre: sugerencia for nombre, sugerencia in pares_seguros.items()
        if usos_por_cuenta[sugerencia['docente_id']] == 1
    }

    resultados = []
    for grupo in grupos:
        comparables = [
            {
                'id': cuenta['id'],
                'nombre': cuenta['nombre'],
                'email': cuenta['email'],
                'dni': cuenta['dni'],
                'similitud': round(_similitud(grupo['nombre'], cuenta['nombre']) * 100),
            }
            for cuenta in cuentas
        ]
        grupo['sugerencias'] = sorted(
            (cuenta for cuenta in comparables if cuenta['similitud'] >= 45),
            key=lambda cuenta: (-cuenta['similitud'], cuenta['nombre'].casefold()),
        )[:5]
        if grupo['nombre'] in pares_seguros:
            grupo['auto_sugerencia'] = pares_seguros[grupo['nombre']]
        resultados.append(grupo)
    resultados.sort(key=lambda grupo: (-len(grupo['bloques']), grupo['nombre'].casefold()))
    return resultados, cuentas, pares_seguros


@app.route('/api/su/vinculaciones_docentes', methods=['GET', 'POST'])
def su_vinculaciones_docentes():
    err = _exigir_su(request)
    if err:
        return err

    if request.method == 'GET':
        conn = get_db()
        try:
            with conn.cursor() as cur:
                resultados, cuentas, pares_seguros = _analizar_vinculaciones_docentes(cur)
            return jsonify({
                'sin_cuenta': resultados,
                'cuentas': cuentas,
                'auto_vinculables': [
                    {'nombre': nombre, **sugerencia}
                    for nombre, sugerencia in pares_seguros.items()
                ],
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
        finally:
            conn.close()

    datos = request.get_json(silent=True)
    if not isinstance(datos, dict):
        return jsonify({'error': 'El cuerpo debe ser un objeto JSON.'}), 400
    nombre_origen = str(datos.get('nombre') or '').strip()
    try:
        docente_id = int(datos.get('docente_id') or 0)
    except (TypeError, ValueError):
        docente_id = 0
    seleccion = datos.get('bloques')
    if not nombre_origen or not docente_id or not isinstance(seleccion, list) or not seleccion:
        return jsonify({'error': 'Indique el nombre, la cuenta destino y al menos un bloque.'}), 400
    if len(seleccion) > 250:
        return jsonify({'error': 'Seleccione como máximo 250 bloques por operación.'}), 400

    claves_seleccion = set()
    try:
        for item in seleccion:
            aula = str(item.get('aula') or '').strip()
            turno = str(item.get('turno') or '').strip().upper()
            indice = int(item.get('indice'))
            if not aula or turno not in ('TM', 'TT') or indice < 0:
                raise ValueError
            clave = (aula, turno, indice)
            if clave in claves_seleccion:
                return jsonify({'error': 'La selección contiene bloques repetidos.'}), 400
            claves_seleccion.add(clave)
    except (AttributeError, TypeError, ValueError):
        return jsonify({'error': 'La selección de bloques no es válida.'}), 400

    conn = get_db()
    try:
        actualizados = 0
        destino = None
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, nombre, es_pgnp FROM docentes
                WHERE id=%s FOR UPDATE
            """, (docente_id,))
            destino = cur.fetchone()
            if not destino:
                return jsonify({'error': 'La cuenta docente seleccionada ya no existe.'}), 404
            if destino[2]:
                return jsonify({'error': 'No se pueden vincular clases titulares a una cuenta PGNP.'}), 400
            cur.execute("SELECT id, nombre FROM docentes WHERE es_pgnp=FALSE")
            homonimos = [
                cuenta for cuenta in cur.fetchall()
                if cuenta[0] != destino[0]
                and _clave_nombre_visible_docente(cuenta[1]) == _clave_nombre_visible_docente(destino[1])
            ]
            if homonimos:
                return jsonify({
                    'error': 'Hay más de una cuenta con el mismo nombre oficial. No se pueden vincular aulas '
                             'hasta que TIC verifique si son duplicados o diferencie la identidad de cada docente.'
                }), 409

            filas_aula = {(aula, turno) for aula, turno, _ in claves_seleccion}
            configs = {}
            for aula, turno in filas_aula:
                cur.execute("""
                    SELECT config_json FROM cronograma_maestro
                    WHERE aula=%s AND turno=%s FOR UPDATE
                """, (aula, turno))
                fila = cur.fetchone()
                if not fila:
                    return jsonify({'error': f'El cronograma del aula {aula} ({turno}) ya no existe.'}), 409
                config = fila[0]
                if isinstance(config, str):
                    config = json.loads(config)
                if not isinstance(config, list):
                    return jsonify({'error': 'El cronograma cambió de formato; actualice el análisis antes de vincular.'}), 409
                configs[(aula, turno)] = config

            for aula, turno, indice in claves_seleccion:
                config = configs[(aula, turno)]
                if indice >= len(config) or not isinstance(config[indice], dict):
                    return jsonify({'error': 'Uno de los bloques cambió. Vuelva a analizar antes de vincular.'}), 409
                if str(config[indice].get('doc') or '').strip() != nombre_origen:
                    return jsonify({'error': 'Uno de los nombres cambió. Vuelva a analizar antes de vincular.'}), 409
                config[indice]['doc'] = destino[1]
                actualizados += 1

            for (aula, turno), config in configs.items():
                cur.execute("""
                    UPDATE cronograma_maestro
                    SET config_json=%s::jsonb
                    WHERE aula=%s AND turno=%s
                """, (json.dumps(config, ensure_ascii=False), aula, turno))
        conn.commit()
        _log_audit(
            'TIC', 'super_usuario', 'VINCULAR_DOCENTE_CRONOGRAMA',
            'cronograma_maestro', f'{nombre_origen} → {destino[1]}',
            f'bloques={actualizados}; aulas={len(filas_aula)}',
        )
        return jsonify({
            'ok': True,
            'msj': f'{actualizados} bloque(s) vinculados a {destino[1]}.',
            'bloques_actualizados': actualizados,
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/su/vinculaciones_docentes/aplicar-seguras', methods=['POST'])
def su_vinculaciones_docentes_aplicar_seguras():
    err = _exigir_su(request)
    if err:
        return err
    datos = request.get_json(silent=True)
    solicitudes = datos.get('vinculaciones') if isinstance(datos, dict) else None
    if not isinstance(solicitudes, list) or not solicitudes or len(solicitudes) > 250:
        return jsonify({'error': 'Seleccione entre 1 y 250 coincidencias seguras.'}), 400
    nombres = []
    try:
        for solicitud in solicitudes:
            nombre = str(solicitud.get('nombre') or '').strip()
            docente_id = int(solicitud.get('docente_id') or 0)
            if not nombre or not docente_id or nombre in nombres:
                raise ValueError
            nombres.append(nombre)
    except (AttributeError, TypeError, ValueError):
        return jsonify({'error': 'La selección contiene nombres o cuentas inválidos.'}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            _, _, seguras_actuales = _analizar_vinculaciones_docentes(cur)
            elegidas = []
            aulas_turnos = set()
            cuentas_destino = set()
            for solicitud in solicitudes:
                nombre = str(solicitud['nombre']).strip()
                docente_id = int(solicitud['docente_id'])
                sugerencia = seguras_actuales.get(nombre)
                if not sugerencia or sugerencia['docente_id'] != docente_id:
                    return jsonify({
                        'error': f'La coincidencia de "{nombre}" cambió o dejó de ser segura. Actualice el análisis.'
                    }), 409
                if docente_id in cuentas_destino:
                    return jsonify({'error': 'Una cuenta destino aparece más de una vez.'}), 400
                cuentas_destino.add(docente_id)
                for bloque in sugerencia['bloques']:
                    aula, turno = str(bloque['aula']), str(bloque['turno']).upper()
                    indice = int(bloque['indice'])
                    aulas_turnos.add((aula, turno))
                    elegidas.append((nombre, docente_id, aula, turno, indice))

            configs = {}
            for aula, turno in aulas_turnos:
                cur.execute("""
                    SELECT config_json FROM cronograma_maestro
                    WHERE aula=%s AND turno=%s FOR UPDATE
                """, (aula, turno))
                fila = cur.fetchone()
                if not fila:
                    return jsonify({'error': f'El cronograma de Aula {aula} ({turno}) ya no existe.'}), 409
                config = fila[0]
                if isinstance(config, str):
                    config = json.loads(config)
                if not isinstance(config, list):
                    return jsonify({'error': 'El cronograma cambió de formato. Actualice el análisis.'}), 409
                configs[(aula, turno)] = config

            destinos = {}
            for nombre, docente_id, aula, turno, indice in elegidas:
                config = configs[(aula, turno)]
                if indice >= len(config) or not isinstance(config[indice], dict):
                    return jsonify({'error': 'Un bloque cambió. Actualice el análisis antes de vincular.'}), 409
                if str(config[indice].get('doc') or '').strip() != nombre:
                    return jsonify({'error': 'Un nombre cambió. Actualice el análisis antes de vincular.'}), 409
                destinos[docente_id] = next(
                    item['docente'] for item in seguras_actuales.values()
                    if item['docente_id'] == docente_id
                )

            for nombre, docente_id, aula, turno, indice in elegidas:
                configs[(aula, turno)][indice]['doc'] = destinos[docente_id]
            for (aula, turno), config in configs.items():
                cur.execute("""
                    UPDATE cronograma_maestro
                    SET config_json=%s::jsonb
                    WHERE aula=%s AND turno=%s
                """, (json.dumps(config, ensure_ascii=False), aula, turno))
        conn.commit()
        total_bloques = len(elegidas)
        _log_audit(
            'TIC', 'super_usuario', 'VINCULAR_DOCENTES_COINCIDENCIAS_SEGURAS',
            'cronograma_maestro', f'grupos={len(solicitudes)}',
            f'bloques={total_bloques}; aulas={len(aulas_turnos)}',
        )
        return jsonify({
            'ok': True,
            'msj': f'{total_bloques} bloque(s) de {len(solicitudes)} nombre(s) vinculados.',
            'bloques_actualizados': total_bloques,
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/su/vinculaciones_docentes/aplicar-lote', methods=['POST'])
def su_vinculaciones_docentes_aplicar_lote():
    err = _exigir_su(request)
    if err:
        return err
    datos = request.get_json(silent=True)
    solicitudes = datos.get('vinculaciones') if isinstance(datos, dict) else None
    if not isinstance(solicitudes, list) or not solicitudes or len(solicitudes) > 250:
        return jsonify({'error': 'Seleccione entre 1 y 250 nombres para vincular.'}), 400

    nombres = set()
    try:
        for solicitud in solicitudes:
            nombre = str(solicitud.get('nombre') or '').strip()
            docente_id = int(solicitud.get('docente_id') or 0)
            modo = solicitud.get('modo')
            if not nombre or not docente_id or modo not in ('segura', 'manual') or nombre in nombres:
                raise ValueError
            nombres.add(nombre)
            if modo == 'manual' and not isinstance(solicitud.get('bloques'), list):
                raise ValueError
    except (AttributeError, TypeError, ValueError):
        return jsonify({'error': 'La selección de nombres o cuentas no es válida.'}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            grupos_actuales, cuentas, seguras = _analizar_vinculaciones_docentes(cur)
            grupos_por_nombre = {grupo['nombre']: grupo for grupo in grupos_actuales}
            cuentas_por_id = {int(cuenta['id']): cuenta for cuenta in cuentas}
            elegidas = []
            destinos = {}
            bloques_unicos = set()
            aulas_turnos = set()

            for solicitud in solicitudes:
                nombre = str(solicitud['nombre']).strip()
                docente_id = int(solicitud['docente_id'])
                modo = solicitud['modo']
                cuenta = cuentas_por_id.get(docente_id)
                grupo = grupos_por_nombre.get(nombre)
                if not cuenta or not grupo:
                    return jsonify({'error': f'El nombre "{nombre}" o la cuenta seleccionada ya no están disponibles.'}), 409
                if grupo['ambigua']:
                    return jsonify({'error': f'"{nombre}" coincide con varias cuentas homónimas; resuelva primero la identidad.'}), 409
                if modo == 'segura':
                    sugerencia = seguras.get(nombre)
                    if not sugerencia or sugerencia['docente_id'] != docente_id:
                        return jsonify({'error': f'La coincidencia de "{nombre}" cambió o dejó de ser segura.'}), 409
                    bloques = sugerencia['bloques']
                else:
                    seleccion = solicitud['bloques']
                    if not seleccion or len(seleccion) > 250:
                        return jsonify({'error': f'Seleccione bloques para "{nombre}".'}), 400
                    bloques_disponibles = {
                        (str(bloque['aula']), str(bloque['turno']).upper(), int(bloque['indice']))
                        for bloque in grupo['bloques']
                    }
                    bloques = []
                    for bloque in seleccion:
                        clave = (
                            str(bloque.get('aula') or '').strip(),
                            str(bloque.get('turno') or '').strip().upper(),
                            int(bloque.get('indice')),
                        )
                        if clave not in bloques_disponibles:
                            return jsonify({'error': f'Un bloque de "{nombre}" ya no está disponible. Actualice el análisis.'}), 409
                        bloques.append({
                            'aula': clave[0], 'turno': clave[1], 'indice': clave[2],
                        })

                if cuenta['id'] in destinos and destinos[cuenta['id']]['nombre'] != cuenta['nombre']:
                    return jsonify({'error': 'La cuenta destino cambió durante la operación.'}), 409
                destinos[cuenta['id']] = cuenta
                for bloque in bloques:
                    clave = (str(bloque['aula']), str(bloque['turno']).upper(), int(bloque['indice']))
                    if clave in bloques_unicos:
                        return jsonify({'error': 'La selección contiene bloques repetidos.'}), 400
                    bloques_unicos.add(clave)
                    aulas_turnos.add((clave[0], clave[1]))
                    elegidas.append((nombre, cuenta, *clave))

            for cuenta in destinos.values():
                if any(
                    otra['id'] != cuenta['id']
                    and _clave_nombre_visible_docente(otra['nombre']) == _clave_nombre_visible_docente(cuenta['nombre'])
                    for otra in cuentas
                ):
                    return jsonify({
                        'error': f'La cuenta "{cuenta["nombre"]}" tiene un homónimo. Resuelva el posible duplicado antes de vincular.'
                    }), 409

            configs = {}
            for aula, turno in aulas_turnos:
                cur.execute("""
                    SELECT config_json FROM cronograma_maestro
                    WHERE aula=%s AND turno=%s FOR UPDATE
                """, (aula, turno))
                fila = cur.fetchone()
                if not fila:
                    return jsonify({'error': f'El cronograma de Aula {aula} ({turno}) ya no existe.'}), 409
                config = fila[0]
                if isinstance(config, str):
                    config = json.loads(config)
                if not isinstance(config, list):
                    return jsonify({'error': 'El cronograma cambió de formato. Actualice el análisis.'}), 409
                configs[(aula, turno)] = config

            for nombre, cuenta, aula, turno, indice in elegidas:
                config = configs[(aula, turno)]
                if indice < 0 or indice >= len(config) or not isinstance(config[indice], dict):
                    return jsonify({'error': 'Un bloque cambió. Actualice el análisis antes de vincular.'}), 409
                if str(config[indice].get('doc') or '').strip() != nombre:
                    return jsonify({'error': f'El nombre cambió en Aula {aula} ({turno}). Actualice el análisis.'}), 409

            for _, cuenta, aula, turno, indice in elegidas:
                configs[(aula, turno)][indice]['doc'] = cuenta['nombre']
            for (aula, turno), config in configs.items():
                cur.execute("""
                    UPDATE cronograma_maestro
                    SET config_json=%s::jsonb
                    WHERE aula=%s AND turno=%s
                """, (json.dumps(config, ensure_ascii=False), aula, turno))

        conn.commit()
        _log_audit(
            'TIC', 'super_usuario', 'VINCULAR_DOCENTES_LOTE',
            'cronograma_maestro', f'nombres={len(nombres)}',
            f'bloques={len(elegidas)}; aulas={len(aulas_turnos)}',
        )
        return jsonify({
            'ok': True,
            'msj': f'{len(elegidas)} bloque(s) de {len(nombres)} nombre(s) vinculados.',
            'bloques_actualizados': len(elegidas),
        })
    except (TypeError, ValueError, KeyError) as e:
        conn.rollback()
        return jsonify({'error': f'La solicitud contiene datos inválidos: {e}'}), 400
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/su/huerfanos', methods=['GET'])
def su_huerfanos():
    """Detecta datos huérfanos:
       - Firmas de docentes que NO existen en la tabla docentes (puede ser válido si recién se cargó cronograma)
       - Justif. de docentes que no están en cronograma ni en docentes
       - Minutas duplicadas (mismo aula+fecha+turno, debería ser 0 por constraint)
       - Aspirantes en aulas sin cronograma
       - Cronograma sin aspirantes
       - Tokens caducos
    """
    err = _exigir_su(request)
    if err: return err
    try:
        conn = get_db()
        h = {}
        with conn.cursor() as cur:
            # 1. Firmas con docentes que no existen como cuenta
            cur.execute("""
                SELECT DISTINCT docente, COUNT(*) as cant
                FROM firmas_docentes f
                WHERE NOT EXISTS (
                    SELECT 1 FROM docentes d
                    WHERE LOWER(d.nombre) = LOWER(f.docente)
                )
                GROUP BY docente ORDER BY cant DESC LIMIT 30
            """)
            h['firmas_sin_cuenta'] = [{'docente': r[0], 'firmas': r[1]} for r in cur.fetchall()]
            # 2. Aspirantes en aulas SIN cronograma
            cur.execute("""
                SELECT a.aula, a.turno, COUNT(*) as cant
                FROM aspirantes a
                WHERE NOT EXISTS (
                    SELECT 1 FROM cronograma_maestro c
                    WHERE c.aula = a.aula AND c.turno = a.turno
                )
                GROUP BY a.aula, a.turno
            """)
            h['aspirantes_sin_cronograma'] = [
                {'aula': r[0], 'turno': r[1], 'aspirantes': r[2]} for r in cur.fetchall()
            ]
            # 3. Cronogramas SIN aspirantes
            cur.execute("""
                SELECT c.aula, c.turno
                FROM cronograma_maestro c
                WHERE NOT EXISTS (
                    SELECT 1 FROM aspirantes a
                    WHERE a.aula = c.aula AND a.turno = c.turno
                )
                ORDER BY c.aula, c.turno
            """)
            h['cronograma_sin_aspirantes'] = [
                {'aula': r[0], 'turno': r[1]} for r in cur.fetchall()
            ]
            # 4. Justificaciones de docentes que ya no aparecen ni en docentes ni en cronograma
            cur.execute("""
                SELECT DISTINCT j.docente, COUNT(*) as cant
                FROM justificaciones_ausencia j
                WHERE NOT EXISTS (SELECT 1 FROM docentes d WHERE LOWER(d.nombre)=LOWER(j.docente))
                  AND NOT EXISTS (
                      SELECT 1 FROM cronograma_maestro c, jsonb_array_elements(c.config_json::jsonb) b
                      WHERE LOWER(b->>'doc') = LOWER(j.docente)
                  )
                GROUP BY j.docente ORDER BY cant DESC LIMIT 30
            """)
            h['justif_sin_docente'] = [{'docente': r[0], 'cantidad': r[1]} for r in cur.fetchall()]
            # 5. Docentes en cronograma sin cuenta (no es huérfano per se, pero útil saberlo)
            cur.execute("""
                SELECT DISTINCT b->>'doc' as docente, COUNT(*) as bloques
                FROM cronograma_maestro c, jsonb_array_elements(c.config_json::jsonb) b
                WHERE b->>'doc' != ''
                  AND NOT EXISTS (
                      SELECT 1 FROM docentes d WHERE LOWER(d.nombre) = LOWER(b->>'doc')
                  )
                GROUP BY b->>'doc' ORDER BY bloques DESC LIMIT 30
            """)
            h['docentes_cronograma_sin_cuenta'] = [
                {'docente': r[0], 'bloques': r[1]} for r in cur.fetchall()
            ]
            # 6. Tokens caducos en bedel_link_tokens
            try:
                cur.execute("""
                    SELECT COUNT(*) FROM bedel_link_tokens
                    WHERE expira_en < NOW() OR usado=TRUE
                """)
                h['tokens_caducos'] = cur.fetchone()[0]
            except Exception:
                h['tokens_caducos'] = 0
            # 7. Recordatorios ya enviados hace más de 30 días
            try:
                cur.execute("""
                    SELECT COUNT(*) FROM recordatorios_telegram
                    WHERE enviado=TRUE AND enviado_en < NOW() - INTERVAL '30 days'
                """)
                h['recordatorios_viejos'] = cur.fetchone()[0]
            except Exception:
                h['recordatorios_viejos'] = 0
            # 8. Logs viejos (>90 días)
            cur.execute("SELECT COUNT(*) FROM system_log WHERE fecha < NOW() - INTERVAL '90 days'")
            h['system_log_viejo'] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM failed_logins WHERE fecha < NOW() - INTERVAL '90 days'")
            h['failed_logins_viejo'] = cur.fetchone()[0]
        conn.close()
        # Resumen total
        cantidad_total = (
            len(h['firmas_sin_cuenta']) +
            len(h['aspirantes_sin_cronograma']) +
            len(h['cronograma_sin_aspirantes']) +
            len(h['justif_sin_docente']) +
            len(h['docentes_cronograma_sin_cuenta']) +
            h['tokens_caducos'] +
            h['recordatorios_viejos'] +
            h['system_log_viejo'] +
            h['failed_logins_viejo']
        )
        h['total_hallazgos'] = cantidad_total
        return jsonify(h)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/su/limpiar_huerfanos', methods=['POST'])
def su_limpiar_huerfanos():
    """Limpia los huérfanos según las opciones que mande el front.
       d: {tokens_caducos: bool, recordatorios_viejos: bool, system_log: bool, failed_logins: bool}
       (Las cosas críticas como 'firmas sin cuenta' NUNCA se borran automáticamente)"""
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    resumen = {'borrado': {}, 'total': 0}
    try:
        conn = get_db()
        with conn.cursor() as cur:
            if d.get('tokens_caducos'):
                try:
                    cur.execute("DELETE FROM bedel_link_tokens WHERE expira_en < NOW() OR usado=TRUE")
                    resumen['borrado']['tokens_caducos'] = cur.rowcount
                except Exception:
                    resumen['borrado']['tokens_caducos'] = 0
            if d.get('recordatorios_viejos'):
                try:
                    cur.execute("""DELETE FROM recordatorios_telegram
                                   WHERE enviado=TRUE AND enviado_en < NOW() - INTERVAL '30 days'""")
                    resumen['borrado']['recordatorios_viejos'] = cur.rowcount
                except Exception:
                    resumen['borrado']['recordatorios_viejos'] = 0
            if d.get('system_log'):
                cur.execute("DELETE FROM system_log WHERE fecha < NOW() - INTERVAL '90 days'")
                resumen['borrado']['system_log'] = cur.rowcount
            if d.get('failed_logins'):
                cur.execute("DELETE FROM failed_logins WHERE fecha < NOW() - INTERVAL '90 days'")
                resumen['borrado']['failed_logins'] = cur.rowcount
        conn.commit()
        conn.close()
        resumen['total'] = sum(resumen['borrado'].values())
        _log_audit('TIC', 'super_usuario', 'LIMPIAR_HUERFANOS', None,
                   f"total={resumen['total']}", json.dumps(resumen['borrado']))
        return jsonify({'ok': True, 'msj': f"Limpieza OK. {resumen['total']} registros eliminados.", **resumen})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/su/sesiones_activas', methods=['GET'])
def su_sesiones_activas():
    """Devuelve todas las sesiones activas (SU + Plana Mayor + Bedeles por firmas + Docentes)."""
    err = _exigir_su(request)
    if err: return err
    ahora = datetime.now()
    sesiones = []
    # SU + Plana Mayor desde _SESIONES_META
    for tok, meta in list(_SESIONES_META.items()):
        # Verificar que el token todavía esté vigente
        expira = _SU_TOKENS.get(tok) or _ADMIN_TOKENS.get(tok)
        if not expira or expira < ahora:
            continue
        try:
            login_at  = datetime.fromisoformat(meta.get('login_at',  ahora.isoformat()))
            last_seen = datetime.fromisoformat(meta.get('last_seen', ahora.isoformat()))
        except Exception:
            login_at = last_seen = ahora
        sesiones.append({
            'token_short': tok[:10] + '…',
            'token_full':  tok,  # para forzar logout
            'rol':         meta.get('rol', '?'),
            'usuario':     meta.get('usuario', '?'),
            'ip':          meta.get('ip', '?'),
            'user_agent':  meta.get('user_agent', '')[:80],
            'login_at':    login_at.isoformat(),
            'last_seen':   last_seen.isoformat(),
            'minutos_activo':  int((ahora - login_at).total_seconds() / 60),
            'segundos_ultimo': int((ahora - last_seen).total_seconds()),
            'expira_en_min':   int((expira - ahora).total_seconds() / 60),
        })
    # Bedeles "activos": los que firmaron una minuta o hicieron firma en últimos 60 min
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT aula, turno, MAX(timestamp_utc) as ult
                FROM firmas_docentes
                WHERE timestamp_utc >= NOW() - INTERVAL '60 minutes'
                GROUP BY aula, turno
            """)
            for aula, turno, ult in cur.fetchall():
                sesiones.append({
                    'token_short': '—',
                    'token_full':  None,
                    'rol':         'bedel',
                    'usuario':     f'Aula {aula} ({turno})',
                    'ip':          '—',
                    'user_agent':  '—',
                    'login_at':    ult.isoformat() if ult else ahora.isoformat(),
                    'last_seen':   ult.isoformat() if ult else ahora.isoformat(),
                    'minutos_activo':  int((ahora - ult).total_seconds() / 60) if ult else 0,
                    'segundos_ultimo': int((ahora - ult).total_seconds()) if ult else 0,
                    'expira_en_min':   0,
                })
            # Docentes que firmaron en los últimos 30 min
            cur.execute("""
                SELECT docente, aula, turno, MAX(timestamp_utc) as ult
                FROM firmas_docentes
                WHERE timestamp_utc >= NOW() - INTERVAL '30 minutes'
                GROUP BY docente, aula, turno
                ORDER BY ult DESC LIMIT 10
            """)
            for doc, aula, turno, ult in cur.fetchall():
                sesiones.append({
                    'token_short': '—',
                    'token_full':  None,
                    'rol':         'docente',
                    'usuario':     f'{doc} · Aula {aula} ({turno})',
                    'ip':          '—',
                    'user_agent':  '—',
                    'login_at':    ult.isoformat() if ult else ahora.isoformat(),
                    'last_seen':   ult.isoformat() if ult else ahora.isoformat(),
                    'minutos_activo':  int((ahora - ult).total_seconds() / 60) if ult else 0,
                    'segundos_ultimo': int((ahora - ult).total_seconds()) if ult else 0,
                    'expira_en_min':   0,
                })
        conn.close()
    except Exception:
        pass
    # Ordenar: SU/Plana Mayor primero, luego Bedeles, luego Docentes
    orden = {'super_usuario': 0, 'plana_mayor': 1, 'bedel': 2, 'docente': 3}
    sesiones.sort(key=lambda s: (orden.get(s['rol'], 9), s['segundos_ultimo']))
    # Stats agregadas
    cnt_rol = {}
    for s in sesiones:
        cnt_rol[s['rol']] = cnt_rol.get(s['rol'], 0) + 1
    return jsonify({
        'sesiones': sesiones,
        'total':    len(sesiones),
        'stats':    cnt_rol,
        'ahora':    ahora.isoformat(),
    })


@app.route('/api/su/forzar_logout', methods=['POST'])
def su_forzar_logout():
    """Cierra una sesión específica por token (solo SU/Plana Mayor)."""
    err = _exigir_su(request)
    if err: return err
    d   = request.json or {}
    tok = (d.get('token') or '').strip()
    if not tok:
        return jsonify({'ok': False, 'error': 'Token requerido'}), 400
    meta = _SESIONES_META.get(tok, {})
    rol  = meta.get('rol', '?')
    usu  = meta.get('usuario', '?')
    cerrado = False
    if tok in _SU_TOKENS:
        _SU_TOKENS.pop(tok, None)
        cerrado = True
    if tok in _ADMIN_TOKENS:
        _ADMIN_TOKENS.pop(tok, None)
        _ADMIN_TOKENS.pop(tok + '__user', None)
        _ADMIN_TOKENS.pop(tok + '__impersonacion', None)
        cerrado = True
    if tok in _DOCENTE_TOKENS:
        _DOCENTE_TOKENS.pop(tok, None)
        cerrado = True
    _SESIONES_META.pop(tok, None)
    if not cerrado:
        return jsonify({'ok': False, 'error': 'Token no encontrado o ya expirado'}), 404
    _log_audit('TIC', 'super_usuario', 'FORZAR_LOGOUT', None, f'{rol}:{usu}',
               f'token={tok[:10]}...')
    return jsonify({'ok': True, 'msj': f'Sesión {rol} de {usu} cerrada.'})


@app.route('/api/su/buscar_global', methods=['GET'])
def su_buscar_global():
    """Búsqueda global tipo Spotlight: busca en docentes, cronograma, aulas,
    justificaciones, audit_log y minutas con una sola query unificada."""
    err = _exigir_su(request)
    if err: return err
    q = (request.args.get('q') or '').strip().upper()
    if len(q) < 2:
        return jsonify({'resultados': []})
    q_like = f'%{q}%'
    resultados = []
    try:
        conn = get_db()
        with conn.cursor() as cur:
            # Docentes registrados
            cur.execute("""
                SELECT id, nombre, email, dni FROM docentes
                WHERE UPPER(nombre) LIKE %s OR UPPER(email) LIKE %s OR dni LIKE %s
                ORDER BY nombre LIMIT 8
            """, (q_like, q_like, q_like))
            for did, nom, email, dni in cur.fetchall():
                resultados.append({
                    'tipo': 'docente', 'icono': '👨‍🏫',
                    'titulo': nom or '',
                    'subtitulo': f"DNI: {dni or '—'} · {email or 'sin email'}",
                    'accion': f"abrirPerfilDocente('{(nom or '').replace(chr(39), '')}')",
                })
            # Aulas con cronograma
            cur.execute("""
                SELECT DISTINCT aula, turno FROM cronograma_maestro
                WHERE UPPER(aula) LIKE %s ORDER BY aula, turno LIMIT 8
            """, (q_like,))
            for aula, turno in cur.fetchall():
                resultados.append({
                    'tipo': 'aula', 'icono': '🏫',
                    'titulo': f"Aula {aula} ({turno})",
                    'subtitulo': "Cronograma cargado",
                    'accion': f"abrirAulaDetalle('{aula}','{turno}')",
                })
            # Docentes que están en el cronograma pero no registrados
            cur.execute("""
                SELECT DISTINCT b->>'doc' as doc
                FROM cronograma_maestro c, jsonb_array_elements(c.config_json::jsonb) b
                WHERE UPPER(b->>'doc') LIKE %s AND b->>'doc' != ''
                ORDER BY doc LIMIT 6
            """, (q_like,))
            for (doc,) in cur.fetchall():
                resultados.append({
                    'tipo': 'docente-cronograma', 'icono': '📋',
                    'titulo': doc,
                    'subtitulo': "En cronograma (sin cuenta de S.I.P.A.)",
                    'accion': f"abrirPerfilDocente('{doc.replace(chr(39), '')}')",
                })
            # Justificaciones (motivo o docente)
            try:
                cur.execute("""
                    SELECT id, docente, aula, turno, fecha::text, motivo, estado
                    FROM justificaciones_ausencia
                    WHERE UPPER(docente) LIKE %s OR UPPER(motivo) LIKE %s
                    ORDER BY creado_en DESC LIMIT 5
                """, (q_like, q_like))
                for jid, doc, aula, turno, fec, mot, est in cur.fetchall():
                    ico_est = '⏳' if est == 'pendiente' else '✅' if est == 'aprobada' else '❌'
                    resultados.append({
                        'tipo': 'justif', 'icono': '📋',
                        'titulo': f"#{jid} · {doc}",
                        'subtitulo': f"{ico_est} {est} · Aula {aula} {turno} · {fec}",
                        'accion': f"abrirAuditoriaInasistencias()",
                    })
            except Exception:
                pass
            # Minutas con texto en novedades
            cur.execute("""
                SELECT id, aula, turno, fecha::text, novedades
                FROM minutas
                WHERE UPPER(novedades) LIKE %s
                ORDER BY fecha DESC LIMIT 5
            """, (q_like,))
            for mid, aula, turno, fec, nov in cur.fetchall():
                frag = (nov or '')[:80].replace('\n', ' ')
                resultados.append({
                    'tipo': 'minuta', 'icono': '📝',
                    'titulo': f"Minuta Aula {aula} ({turno})",
                    'subtitulo': f"{fec} · {frag}…",
                    'accion': f"abrirAulaDetalle('{aula}','{turno}')",
                })
            # Audit log (últimas acciones)
            cur.execute("""
                SELECT usuario, accion, tabla, registro_ref, fecha::text
                FROM audit_log
                WHERE UPPER(usuario) LIKE %s OR UPPER(accion) LIKE %s OR UPPER(registro_ref) LIKE %s
                ORDER BY fecha DESC LIMIT 5
            """, (q_like, q_like, q_like))
            for usu, acc, tab, ref, fec in cur.fetchall():
                resultados.append({
                    'tipo': 'audit', 'icono': '📜',
                    'titulo': f"{acc} · {usu}",
                    'subtitulo': f"{(fec or '')[:19].replace('T', ' ')} · {tab or ''} · {ref or ''}",
                    'accion': "mostrarCfgTab('cfg-auditoria', document.querySelector('[onclick*=cfg-auditoria]'))",
                })
        conn.close()
        return jsonify({'resultados': resultados, 'total': len(resultados)})
    except Exception as e:
        return jsonify({'error': str(e), 'resultados': []}), 500


@app.route('/api/su/dashboard', methods=['GET'])
def su_dashboard():
    err = _exigir_su(request)
    if err: return err

    # Rango configurable: ?rango=7|30|90|365 (default 7)
    try:
        rango_dias = min(int(request.args.get('rango', 7)), 365)
    except (TypeError, ValueError):
        rango_dias = 7
    if rango_dias < 1:
        rango_dias = 7

    hoy   = date.today()
    desde = hoy - timedelta(days=rango_dias - 1)  # incluye hoy

    # Período anterior para comparación (mismo largo, justo antes de 'desde')
    prev_hasta = desde - timedelta(days=1)
    prev_desde = prev_hasta - timedelta(days=rango_dias - 1)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            # KPIs de hoy
            cur.execute("SELECT COUNT(*) FROM firmas_docentes WHERE fecha=%s", (hoy.isoformat(),))
            firmas_hoy = cur.fetchone()[0]
            cur.execute("SELECT COUNT(DISTINCT aula) FROM minutas WHERE fecha=%s", (hoy.isoformat(),))
            aulas_op_hoy = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM justificaciones_ausencia WHERE fecha=%s", (hoy.isoformat(),))
            justifs_hoy = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM failed_logins WHERE fecha::date = %s", (hoy.isoformat(),))
            falls_hoy = cur.fetchone()[0]

            # ── Firmas por día (período actual) ──
            cur.execute("""
                SELECT fecha::text, COUNT(*) FROM firmas_docentes
                WHERE fecha BETWEEN %s AND %s
                GROUP BY fecha ORDER BY fecha
            """, (desde.isoformat(), hoy.isoformat()))
            firmas_serie = dict(cur.fetchall())

            # Estado geográfico de las firmas del período seleccionado.
            geo_firmas = {'dentro': 0, 'fuera': 0, 'sin_datos': 0,
                          'sin_configurar': 0, 'invalida': 0}
            geo_alertas = []
            geo_params = _cargar_params()
            cur.execute("""
                SELECT docente, aula, turno, fecha::text, hora_firma::text,
                       lat, lng, precision_m
                FROM firmas_docentes
                WHERE fecha BETWEEN %s AND %s
                ORDER BY fecha DESC, hora_firma DESC
            """, (desde.isoformat(), hoy.isoformat()))
            for docente, aula, turno, fecha_firma, hora_firma, lat, lng, precision in cur.fetchall():
                estado = _clasificar_geolocalizacion(
                    lat, lng, precision, geo_params
                )
                estado_nombre = estado['estado']
                geo_firmas[estado_nombre] = geo_firmas.get(estado_nombre, 0) + 1
                if estado_nombre == 'fuera' and len(geo_alertas) < 20:
                    geo_alertas.append({
                        'docente': docente, 'aula': aula, 'turno': turno,
                        'fecha': fecha_firma, 'hora': (hora_firma or '')[:5],
                        'distancia_m': estado['distancia_m'],
                    })

            # ── Firmas período anterior (comparación) ──
            cur.execute("""
                SELECT COUNT(*) FROM firmas_docentes
                WHERE fecha BETWEEN %s AND %s
            """, (prev_desde.isoformat(), prev_hasta.isoformat()))
            firmas_prev_total = cur.fetchone()[0]

            # ── Firmas período actual total ──
            firmas_actual_total = sum(firmas_serie.values())

            # Top docentes con justificaciones (proxy ausencias) — período seleccionado
            cur.execute("""
                SELECT docente, COUNT(*) as cnt FROM justificaciones_ausencia
                WHERE fecha >= %s
                GROUP BY docente ORDER BY cnt DESC LIMIT 10
            """, (desde.isoformat(),))
            top_ausentes = [{'docente': d, 'cnt': c} for d, c in cur.fetchall()]

            # Resumen ejecutivo institucional
            cur.execute("""
                SELECT COUNT(*) FROM minutas
                WHERE fecha BETWEEN %s AND %s
            """, (desde.isoformat(), hoy.isoformat()))
            total_minutas = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM justificaciones_ausencia
                WHERE fecha BETWEEN %s AND %s
            """, (desde.isoformat(), hoy.isoformat()))
            total_justificaciones = cur.fetchone()[0]

            cur.execute("""
                SELECT
                    SUM(CASE WHEN estado='pendiente' THEN 1 ELSE 0 END) AS pendientes,
                    SUM(CASE WHEN estado='aprobada' THEN 1 ELSE 0 END) AS aprobadas,
                    SUM(CASE WHEN estado='rechazada' THEN 1 ELSE 0 END) AS rechazadas
                FROM justificaciones_ausencia
                WHERE fecha BETWEEN %s AND %s
            """, (desde.isoformat(), hoy.isoformat()))
            justif_estado = cur.fetchone()
            justificaciones_pendientes = justif_estado[0] if justif_estado and justif_estado[0] is not None else 0
            justificaciones_aprobadas = justif_estado[1] if justif_estado and justif_estado[1] is not None else 0
            justificaciones_rechazadas = justif_estado[2] if justif_estado and justif_estado[2] is not None else 0

            cur.execute("""
                SELECT aula, COUNT(*) AS cnt
                FROM firmas_docentes
                WHERE fecha BETWEEN %s AND %s
                GROUP BY aula
                ORDER BY cnt DESC, aula
                LIMIT 1
            """, (desde.isoformat(), hoy.isoformat()))
            fila_aula_mas_activa = cur.fetchone()
            aula_mas_activa = {'aula': fila_aula_mas_activa[0], 'cnt': fila_aula_mas_activa[1]} if fila_aula_mas_activa else {'aula': '—', 'cnt': 0}

            cur.execute("""
                SELECT docente, COUNT(*) AS cnt
                FROM firmas_docentes
                WHERE fecha BETWEEN %s AND %s
                GROUP BY docente
                ORDER BY cnt DESC, docente
                LIMIT 5
            """, (desde.isoformat(), hoy.isoformat()))
            top_docentes_firmas = [{'docente': d, 'cnt': c} for d, c in cur.fetchall()]

            # Auditoría: acciones por día
            cur.execute("""
                SELECT fecha::date::text, COUNT(*) FROM audit_log
                WHERE fecha >= %s
                GROUP BY fecha::date ORDER BY fecha::date
            """, (desde.isoformat(),))
            audit_serie = dict(cur.fetchall())

            # Distribución por rol en audit_log
            cur.execute("""
                SELECT COALESCE(rol, 'sin_rol') AS rol, COUNT(*) FROM audit_log
                WHERE fecha >= %s
                GROUP BY rol ORDER BY COUNT(*) DESC
            """, (desde.isoformat(),))
            por_rol = [{'rol': r, 'cnt': c} for r, c in cur.fetchall()]

            # ── Minutas por turno (nuevo gráfico) ──
            cur.execute("""
                SELECT turno, COUNT(*) FROM minutas
                WHERE fecha BETWEEN %s AND %s
                GROUP BY turno ORDER BY turno
            """, (desde.isoformat(), hoy.isoformat()))
            minutas_turno = [{'turno': t, 'cnt': c} for t, c in cur.fetchall()]

        # Armar series con todos los días en orden
        n_dias = rango_dias
        dias       = [(desde + timedelta(days=i)).isoformat() for i in range(n_dias)]
        # Para rangos largos, formatear distinto
        if rango_dias <= 14:
            labels_dias = [(desde + timedelta(days=i)).strftime('%a %d/%m') for i in range(n_dias)]
        elif rango_dias <= 90:
            labels_dias = [(desde + timedelta(days=i)).strftime('%d/%m') for i in range(n_dias)]
        else:
            labels_dias = [(desde + timedelta(days=i)).strftime('%d/%m/%y') for i in range(n_dias)]

        firmas_data = [firmas_serie.get(d, 0) for d in dias]
        audit_data  = [audit_serie.get(d, 0)  for d in dias]

        # Variación porcentual vs período anterior
        if firmas_prev_total > 0:
            variacion_pct = round((firmas_actual_total - firmas_prev_total) / firmas_prev_total * 100, 1)
        else:
            variacion_pct = 100.0 if firmas_actual_total > 0 else 0.0

        resumen_ejecutivo = {
            'total_minutas': total_minutas,
            'total_firmas': firmas_actual_total,
            'justificaciones_total': total_justificaciones,
            'justificaciones_pendientes': justificaciones_pendientes,
            'justificaciones_aprobadas': justificaciones_aprobadas,
            'justificaciones_rechazadas': justificaciones_rechazadas,
            'aula_mas_activa': aula_mas_activa,
            'top_docentes_firmas': top_docentes_firmas,
            'top_ausentes': top_ausentes[:5],
            'alertas_operativas': geo_alertas[:5],
            'promedio_firmas_por_dia': round(firmas_actual_total / max(len(dias), 1), 2),
        }

        return jsonify({
            'rango_dias': rango_dias,
            'desde': desde.isoformat(),
            'hasta': hoy.isoformat(),
            'kpis': {
                'firmas_hoy': firmas_hoy,
                'aulas_op_hoy': aulas_op_hoy,
                'justifs_hoy': justifs_hoy,
                'falls_hoy': falls_hoy,
                'sesiones_admin': len([k for k in _ADMIN_TOKENS if '__' not in k]),
                'sesiones_su': len(_SU_TOKENS),
                'firmas_dentro': geo_firmas['dentro'],
                'firmas_fuera': geo_firmas['fuera'],
                'firmas_sin_geo': geo_firmas['sin_datos'],
            },
            'comparacion': {
                'firmas_actual': firmas_actual_total,
                'firmas_anterior': firmas_prev_total,
                'variacion_pct': variacion_pct,
            },
            'firmas_semanal': { 'labels': labels_dias, 'data': firmas_data },
            'audit_semanal':  { 'labels': labels_dias, 'data': audit_data  },
            'minutas_turno': minutas_turno,
            'top_ausentes': top_ausentes,
            'por_rol': por_rol,
            'geo_alertas': geo_alertas,
            'resumen_ejecutivo': resumen_ejecutivo,
            'generado_en': datetime.now().isoformat(),
        })
    finally:
        conn.close()


@app.route('/api/su/dashboard/print', methods=['GET'])
def su_dashboard_print():
    tok = request.headers.get('X-SU-Token', request.args.get('token', ''))
    if tok and tok in _SU_TOKENS and _SU_TOKENS[tok] > datetime.now():
        _tocar_sesion(tok)
    elif not tok or tok not in _SU_TOKENS or _SU_TOKENS[tok] <= datetime.now():
        return jsonify({'error': 'Esta operación requiere autenticación de Super Usuario (TIC).'}), 403

    try:
        rango_dias = min(int(request.args.get('rango', 7)), 365)
    except (TypeError, ValueError):
        rango_dias = 7
    if rango_dias < 1:
        rango_dias = 7

    hoy = date.today()
    desde = hoy - timedelta(days=rango_dias - 1)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM firmas_docentes WHERE fecha=%s", (hoy.isoformat(),))
            firmas_hoy = cur.fetchone()[0]
            cur.execute("SELECT COUNT(DISTINCT aula) FROM minutas WHERE fecha=%s", (hoy.isoformat(),))
            aulas_op_hoy = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM justificaciones_ausencia WHERE fecha=%s", (hoy.isoformat(),))
            justifs_hoy = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM failed_logins WHERE fecha::date = %s", (hoy.isoformat(),))
            falls_hoy = cur.fetchone()[0]

            cur.execute("""
                SELECT docente, COUNT(*) as cnt FROM justificaciones_ausencia
                WHERE fecha >= %s
                GROUP BY docente ORDER BY cnt DESC LIMIT 5
            """, (desde.isoformat(),))
            top_ausentes = cur.fetchall()

            geo_params = _cargar_params()
            geo_firmas = {'dentro': 0, 'fuera': 0, 'sin_datos': 0, 'sin_configurar': 0, 'invalida': 0}
            cur.execute("""
                SELECT docente, aula, turno, fecha::text, hora_firma::text,
                       lat, lng, precision_m
                FROM firmas_docentes
                WHERE fecha BETWEEN %s AND %s
                ORDER BY fecha DESC, hora_firma DESC
            """, (desde.isoformat(), hoy.isoformat()))
            geo_alertas = []
            for docente, aula, turno, fecha_firma, hora_firma, lat, lng, precision in cur.fetchall():
                estado = _clasificar_geolocalizacion(lat, lng, precision, geo_params)
                geo_firmas[estado['estado']] = geo_firmas.get(estado['estado'], 0) + 1
                if estado['estado'] == 'fuera' and len(geo_alertas) < 5:
                    geo_alertas.append({
                        'docente': docente, 'aula': aula, 'turno': turno,
                        'fecha': fecha_firma, 'hora': (hora_firma or '')[:5],
                        'distancia_m': estado['distancia_m'],
                    })

            cur.execute("""
                SELECT COUNT(*) FROM firmas_docentes
                WHERE fecha BETWEEN %s AND %s
            """, (desde.isoformat(), hoy.isoformat()))
            firmas_total = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM minutas WHERE fecha BETWEEN %s AND %s
            """, (desde.isoformat(), hoy.isoformat()))
            minutas_total = cur.fetchone()[0]

            cur.execute("""
                SELECT COUNT(*) FROM justificaciones_ausencia
                WHERE fecha BETWEEN %s AND %s
            """, (desde.isoformat(), hoy.isoformat()))
            justif_total = cur.fetchone()[0]

            cur.execute("""
                SELECT aula, COUNT(*) AS cnt
                FROM firmas_docentes
                WHERE fecha BETWEEN %s AND %s
                GROUP BY aula
                ORDER BY cnt DESC, aula
                LIMIT 1
            """, (desde.isoformat(), hoy.isoformat()))
            aula_mas_activa = cur.fetchone()

            cur.execute("""
                SELECT turno, COUNT(*) FROM minutas
                WHERE fecha BETWEEN %s AND %s
                GROUP BY turno ORDER BY turno
            """, (desde.isoformat(), hoy.isoformat()))
            minutas_turno = cur.fetchall()
    finally:
        conn.close()

    aula_mv = aula_mas_activa[0] if aula_mas_activa else '—'
    top_ausentes_html = ''.join(
        f'<tr><td>{html.escape(str(docente or "—"))}</td><td>{cnt}</td></tr>'
        for docente, cnt in top_ausentes
    ) or '<tr><td colspan="2">Sin datos</td></tr>'

    alertas_html = ''.join(
        f'<tr><td>{html.escape(str(a["fecha"]))}</td><td>{html.escape(str(a["hora"]))}</td><td>{html.escape(str(a["docente"]))}</td><td>{html.escape(str(a["aula"]))}</td><td>{html.escape(str(a["turno"]))}</td><td>{a["distancia_m"] if a.get("distancia_m") is not None else "—"}</td></tr>'
        for a in geo_alertas
    ) or '<tr><td colspan="6">Sin alertas</td></tr>'

    turno_html = ''.join(
        f'<tr><td>{html.escape(str(turno))}</td><td>{cnt}</td></tr>'
        for turno, cnt in minutas_turno
    ) or '<tr><td colspan="2">Sin datos</td></tr>'

    documento = f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <title>Resumen Ejecutivo SIPA</title>
  <style>
    body {{ font-family: Arial, sans-serif; color: #0f172a; margin: 24px; }}
    h1 {{ margin-bottom: 8px; }}
    .sub {{ color: #475569; margin-bottom: 18px; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin: 18px 0 22px; }}
    .card {{ border: 1px solid #cbd5e1; border-radius: 10px; padding: 12px; background: #f8fafc; }}
    .valor {{ font-size: 1.8em; font-weight: 700; margin-top: 8px; }}
    .label {{ color: #475569; font-size: 0.8em; text-transform: uppercase; letter-spacing: 0.04em; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 8px; }}
    th, td {{ border: 1px solid #cbd5e1; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #e2e8f0; }}
    .section {{ margin-top: 20px; }}
    .btn-print {{ display: inline-block; margin-bottom: 12px; padding: 8px 12px; border: 1px solid #0f172a; border-radius: 6px; background: #0f172a; color: white; cursor: pointer; }}
    @media print {{ .btn-print {{ display: none; }} }}
  </style>
</head>
<body>
  <button class="btn-print" onclick="window.print()">🖨️ Imprimir / Guardar PDF</button>
  <h1>S.I.P.A. — Resumen Ejecutivo</h1>
  <div class="sub">Período: {desde.isoformat()} a {hoy.isoformat()} · Rango: {rango_dias} días</div>

  <div class="grid">
    <div class="card"><div class="label">Minutas</div><div class="valor">{minutas_total}</div></div>
    <div class="card"><div class="label">Firmas</div><div class="valor">{firmas_total}</div></div>
    <div class="card"><div class="label">Justificaciones</div><div class="valor">{justif_total}</div></div>
    <div class="card"><div class="label">Firmas hoy</div><div class="valor">{firmas_hoy}</div></div>
    <div class="card"><div class="label">Aulas operativas</div><div class="valor">{aulas_op_hoy}</div></div>
    <div class="card"><div class="label">Aula más activa</div><div class="valor">{html.escape(str(aula_mv))}</div></div>
  </div>

  <div class="section">
    <h2>Top docentes con más justificaciones</h2>
    <table>
      <thead><tr><th>Docente</th><th>Cantidad</th></tr></thead>
      <tbody>{top_ausentes_html}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>Alertas fuera del radio institucional</h2>
    <table>
      <thead><tr><th>Fecha</th><th>Hora</th><th>Docente</th><th>Aula</th><th>Turno</th><th>Distancia</th></tr></thead>
      <tbody>{alertas_html}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>Minutas por turno</h2>
    <table>
      <thead><tr><th>Turno</th><th>Cantidad</th></tr></thead>
      <tbody>{turno_html}</tbody>
    </table>
  </div>

  <div class="section">
    <h2>Geolocalización</h2>
    <table>
      <thead><tr><th>Estado</th><th>Cantidad</th></tr></thead>
      <tbody>
        <tr><td>Dentro</td><td>{geo_firmas.get('dentro',0)}</td></tr>
        <tr><td>Fuera</td><td>{geo_firmas.get('fuera',0)}</td></tr>
        <tr><td>Sin GPS</td><td>{geo_firmas.get('sin_datos',0)}</td></tr>
        <tr><td>Sin configurar</td><td>{geo_firmas.get('sin_configurar',0)}</td></tr>
      </tbody>
    </table>
  </div>
</body>
</html>"""

    return Response(documento, mimetype='text/html; charset=utf-8', headers={'Cache-Control': 'no-store'})


@app.route('/api/su/dashboard/export', methods=['GET'])
def su_dashboard_export():
    err = _exigir_su(request)
    if err:
        return err

    try:
        rango_dias = min(int(request.args.get('rango', 7)), 365)
    except (TypeError, ValueError):
        rango_dias = 7
    if rango_dias < 1:
        rango_dias = 7

    hoy = date.today()
    desde = hoy - timedelta(days=rango_dias - 1)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM firmas_docentes WHERE fecha BETWEEN %s AND %s", (desde.isoformat(), hoy.isoformat()))
            total_firmas = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM minutas WHERE fecha BETWEEN %s AND %s", (desde.isoformat(), hoy.isoformat()))
            total_minutas = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM justificaciones_ausencia WHERE fecha BETWEEN %s AND %s", (desde.isoformat(), hoy.isoformat()))
            total_justificaciones = cur.fetchone()[0]
            cur.execute("SELECT SUM(CASE WHEN estado='pendiente' THEN 1 ELSE 0 END) FROM justificaciones_ausencia WHERE fecha BETWEEN %s AND %s", (desde.isoformat(), hoy.isoformat()))
            pendientes = cur.fetchone()[0] or 0
            cur.execute("SELECT SUM(CASE WHEN estado='aprobada' THEN 1 ELSE 0 END) FROM justificaciones_ausencia WHERE fecha BETWEEN %s AND %s", (desde.isoformat(), hoy.isoformat()))
            aprobadas = cur.fetchone()[0] or 0
            cur.execute("SELECT SUM(CASE WHEN estado='rechazada' THEN 1 ELSE 0 END) FROM justificaciones_ausencia WHERE fecha BETWEEN %s AND %s", (desde.isoformat(), hoy.isoformat()))
            rechazadas = cur.fetchone()[0] or 0
            cur.execute("SELECT aula, COUNT(*) FROM firmas_docentes WHERE fecha BETWEEN %s AND %s GROUP BY aula ORDER BY COUNT(*) DESC, aula LIMIT 1", (desde.isoformat(), hoy.isoformat()))
            aula_mas_activa = cur.fetchone()
            aula_mas_activa_txt = aula_mas_activa[0] if aula_mas_activa else '—'
            cur.execute("SELECT docente, COUNT(*) FROM firmas_docentes WHERE fecha BETWEEN %s AND %s GROUP BY docente ORDER BY COUNT(*) DESC, docente LIMIT 5", (desde.isoformat(), hoy.isoformat()))
            top_docentes = cur.fetchall()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['concepto', 'valor'])
        writer.writerow(['rango_dias', rango_dias])
        writer.writerow(['desde', desde.isoformat()])
        writer.writerow(['hasta', hoy.isoformat()])
        writer.writerow(['total_minutas', total_minutas])
        writer.writerow(['total_firmas', total_firmas])
        writer.writerow(['total_justificaciones', total_justificaciones])
        writer.writerow(['justificaciones_pendientes', pendientes])
        writer.writerow(['justificaciones_aprobadas', aprobadas])
        writer.writerow(['justificaciones_rechazadas', rechazadas])
        writer.writerow(['aula_mas_activa', aula_mas_activa_txt])
        if top_docentes:
            writer.writerow([])
            writer.writerow(['top_docente', 'firmas'])
            for docente, cnt in top_docentes:
                writer.writerow([docente, cnt])

        response = make_response(output.getvalue())
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.headers['Content-Disposition'] = (
            f'attachment; filename="resumen_ejecutivo_{desde.isoformat()}_a_{hoy.isoformat()}.csv"'
        )
        return response
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# SU — RESTAURACIÓN DESDE BACKUP
# ═══════════════════════════════════════════════════════════════════════════
@app.route('/api/su/restore_backup', methods=['POST'])
def su_restore_backup():
    err = _exigir_su(request)
    if err: return err
    if 'file' not in request.files:
        return jsonify({'error':'Adjunte un archivo .json de backup'}), 400
    f = request.files['file']
    try:
        data = json.loads(f.read().decode('utf-8'))
    except Exception as e:
        return jsonify({'error': f'JSON inválido: {e}'}), 400

    if 'tablas' not in data:
        return jsonify({'error':'Backup mal formado: falta clave "tablas"'}), 400

    conn = get_db()
    resumen = []
    errores_fila = []
    try:
        with conn.cursor() as cur:
            # Orden importante: padres antes que hijos (FKs cascadean, igual)
            orden = ['cronograma_maestro','aspirantes','docentes','minutas',
                     'firmas_docentes','justificaciones_ausencia','config_sistema',
                     'usuarios_admin','pin_overrides','audit_log','failed_logins','system_log',
                     'cronograma_versiones','bedeles_telegram','bedel_link_tokens',
                     'recordatorios_telegram','bot_comando_log']
            # Truncar SOLO las tablas que vienen en este backup (whitelist = orden).
            # Así, restaurar un backup viejo (sin Telegram/versiones) no borra esas tablas.
            presentes = [t for t in orden
                         if isinstance(data['tablas'].get(t), dict)
                         and 'filas' in data['tablas'][t]]
            if presentes:
                cur.execute("TRUNCATE TABLE " + ", ".join(presentes) +
                            " RESTART IDENTITY CASCADE")
            for tabla in orden:
                bk = data['tablas'].get(tabla)
                if not bk or 'columnas' not in bk or 'filas' not in bk:
                    continue
                cols = bk['columnas']
                filas = bk['filas']
                if not filas: continue
                placeholders = ','.join(['%s'] * len(cols))
                col_list     = ','.join(cols)
                ok_cnt, err_cnt = 0, 0
                for row in filas:
                    sp = f"sp_{tabla}_{ok_cnt+err_cnt}"
                    try:
                        cur.execute(f"SAVEPOINT {sp}")
                        cur.execute(
                            f"INSERT INTO {tabla} ({col_list}) VALUES ({placeholders}) "
                            f"ON CONFLICT DO NOTHING",
                            row
                        )
                        cur.execute(f"RELEASE SAVEPOINT {sp}")
                        ok_cnt += 1
                    except Exception as ie:
                        cur.execute(f"ROLLBACK TO SAVEPOINT {sp}")
                        err_cnt += 1
                        errores_fila.append(f"{tabla}#{ok_cnt+err_cnt}: {str(ie)[:80]}")
                # Resetear la secuencia al máximo id si la tabla tiene columna 'id'
                if 'id' in cols:
                    try:
                        cur.execute(f"""
                            SELECT setval(
                                pg_get_serial_sequence('{tabla}', 'id'),
                                COALESCE((SELECT MAX(id) FROM {tabla}), 1),
                                true
                            )
                        """)
                    except Exception:
                        pass
                resumen.append(f"{tabla}: {ok_cnt} OK" + (f", {err_cnt} omitidas" if err_cnt else ""))
        conn.commit()
        _log_audit('TIC','super_usuario','RESTORE_BACKUP', None, f.filename,
                   '; '.join(resumen))
        respuesta = {'msj':'Backup restaurado.', 'resumen': resumen}
        if errores_fila:
            respuesta['errores'] = errores_fila[:25]
        return jsonify(respuesta)
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# SU — ARCHIVADO DE CICLOS LECTIVOS
# ═══════════════════════════════════════════════════════════════════════════
@app.route('/api/su/archivar_ciclo', methods=['POST'])
def su_archivar_ciclo():
    """Mueve minutas y firmas de un año a tablas _archivo (solo lectura)."""
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    try:
        anio = int(d.get('anio', 0))
    except (ValueError, TypeError):
        return jsonify({'error':'Año inválido'}), 400
    if anio < 2000 or anio >= datetime.now().year:
        return jsonify({'error': f'Año debe ser anterior al actual ({datetime.now().year})'}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Crear tablas _archivo si no existen
            cur.execute("""
                CREATE TABLE IF NOT EXISTS minutas_archivo (LIKE minutas INCLUDING ALL)
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS firmas_archivo (LIKE firmas_docentes INCLUDING ALL)
            """)
            # Mover (INSERT + DELETE)
            cur.execute("""
                INSERT INTO minutas_archivo SELECT * FROM minutas
                WHERE EXTRACT(YEAR FROM fecha) = %s
                ON CONFLICT DO NOTHING
            """, (anio,))
            mig_min = cur.rowcount
            cur.execute("DELETE FROM minutas WHERE EXTRACT(YEAR FROM fecha) = %s", (anio,))

            cur.execute("""
                INSERT INTO firmas_archivo SELECT * FROM firmas_docentes
                WHERE EXTRACT(YEAR FROM fecha) = %s
                ON CONFLICT DO NOTHING
            """, (anio,))
            mig_fir = cur.rowcount
            cur.execute("DELETE FROM firmas_docentes WHERE EXTRACT(YEAR FROM fecha) = %s", (anio,))

        conn.commit()
        _log_audit('TIC','super_usuario','ARCHIVAR_CICLO', None, f'año={anio}',
                   f'minutas={mig_min}, firmas={mig_fir}')
        return jsonify({
            'msj': f'Ciclo {anio} archivado.',
            'minutas_archivadas': mig_min,
            'firmas_archivadas':  mig_fir,
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# SU — CONSULTA Y EXPORTACIÓN DEL ARCHIVO HISTÓRICO
# ═══════════════════════════════════════════════════════════════════════════
def _archivo_existe(cur, tabla):
    """Devuelve True si la tabla _archivo existe en la BD actual."""
    try:
        cur.execute("""
            SELECT 1 FROM information_schema.tables
            WHERE table_schema = 'public' AND table_name = %s
        """, (tabla,))
        return cur.fetchone() is not None
    except Exception:
        return False


@app.route('/api/su/archivo_resumen', methods=['GET'])
def su_archivo_resumen():
    """Devuelve los años disponibles en las tablas de archivo + conteos."""
    err = _exigir_su(request)
    if err: return err
    conn = get_db()
    try:
        resumen = {'minutas_archivo': {'existe': False, 'anios': []},
                   'firmas_archivo':  {'existe': False, 'anios': []}}
        with conn.cursor() as cur:
            if _archivo_existe(cur, 'minutas_archivo'):
                resumen['minutas_archivo']['existe'] = True
                try:
                    cur.execute("""
                        SELECT EXTRACT(YEAR FROM fecha)::int AS anio,
                               COUNT(*) AS filas
                        FROM minutas_archivo GROUP BY anio ORDER BY anio DESC
                    """)
                    resumen['minutas_archivo']['anios'] = [
                        {'anio': r[0], 'filas': r[1]} for r in cur.fetchall()
                    ]
                except Exception:
                    conn.rollback()

            if _archivo_existe(cur, 'firmas_archivo'):
                resumen['firmas_archivo']['existe'] = True
                try:
                    cur.execute("""
                        SELECT EXTRACT(YEAR FROM fecha)::int AS anio,
                               COUNT(*) AS filas
                        FROM firmas_archivo GROUP BY anio ORDER BY anio DESC
                    """)
                    resumen['firmas_archivo']['anios'] = [
                        {'anio': r[0], 'filas': r[1]} for r in cur.fetchall()
                    ]
                except Exception:
                    conn.rollback()
        return jsonify(resumen)
    finally:
        conn.close()


@app.route('/api/su/archivo_consultar', methods=['GET'])
def su_archivo_consultar():
    """Lista filas del archivo según tipo (minutas|firmas) + filtros."""
    err = _exigir_su(request)
    if err: return err
    tipo  = (request.args.get('tipo') or 'minutas').lower()
    anio  = request.args.get('anio')
    aula  = (request.args.get('aula') or '').strip().upper()
    turno = (request.args.get('turno') or '').strip().upper()
    docente = (request.args.get('docente') or '').strip()
    limit = min(int(request.args.get('limit', 200)), 1000)

    if tipo not in ('minutas', 'firmas'):
        return jsonify({'error': 'tipo inválido (use minutas o firmas)'}), 400

    tabla = 'minutas_archivo' if tipo == 'minutas' else 'firmas_archivo'
    conn = get_db()
    try:
        with conn.cursor() as cur:
            if not _archivo_existe(cur, tabla):
                return jsonify({
                    'filas': [],
                    'mensaje': f'La tabla {tabla} no existe aún. Archive primero un ciclo lectivo desde Configuración → Peligro.'
                })

            filtros = []
            params  = []
            if anio:
                filtros.append('EXTRACT(YEAR FROM fecha) = %s')
                params.append(int(anio))
            if aula:
                filtros.append('aula = %s'); params.append(aula)
            if turno:
                filtros.append('turno = %s'); params.append(turno)
            if docente and tipo == 'firmas':
                filtros.append('docente ILIKE %s'); params.append(f'%{docente}%')
            where = (' WHERE ' + ' AND '.join(filtros)) if filtros else ''

            if tipo == 'minutas':
                cur.execute(f"""
                    SELECT id, aula, fecha::text, turno, bedel, sub_bedel,
                           fe, presentes, cant_ausentes, novedades
                    FROM minutas_archivo {where}
                    ORDER BY fecha DESC, aula
                    LIMIT %s
                """, params + [limit])
            else:
                cur.execute(f"""
                    SELECT id, docente, aula, turno, fecha::text,
                           hora_firma::text, pin_usado
                    FROM firmas_archivo {where}
                    ORDER BY fecha DESC, hora_firma
                    LIMIT %s
                """, params + [limit])
            cols = [c[0] for c in cur.description]
            filas = [dict(zip(cols, r)) for r in cur.fetchall()]
        return jsonify({'filas': filas, 'total': len(filas), 'limit': limit})
    finally:
        conn.close()


@app.route('/api/su/archivo_export', methods=['GET'])
def su_archivo_export():
    """Exporta CSV del archivo histórico de un año dado."""
    err = _exigir_su(request)
    if err: return err
    tipo = (request.args.get('tipo') or 'minutas').lower()
    anio = request.args.get('anio')
    if tipo not in ('minutas', 'firmas'):
        return jsonify({'error': 'tipo inválido'}), 400

    tabla = 'minutas_archivo' if tipo == 'minutas' else 'firmas_archivo'
    conn = get_db()
    try:
        with conn.cursor() as cur:
            if not _archivo_existe(cur, tabla):
                return jsonify({'error': f'{tabla} no existe aún'}), 404
            if tipo == 'minutas':
                where = 'WHERE EXTRACT(YEAR FROM fecha) = %s' if anio else ''
                params = [int(anio)] if anio else []
                cur.execute(f"""
                    SELECT fecha::text, aula, turno, bedel, sub_bedel,
                           fe, presentes, cant_ausentes, novedades
                    FROM minutas_archivo {where}
                    ORDER BY fecha, aula
                """, params)
                headers = ['Fecha','Aula','Turno','Bedel','Sub-Bedel',
                          'FE','Presentes','Ausentes','Novedades']
            else:
                where = 'WHERE EXTRACT(YEAR FROM fecha) = %s' if anio else ''
                params = [int(anio)] if anio else []
                cur.execute(f"""
                    SELECT fecha::text, docente, aula, turno,
                           hora_firma::text, pin_usado
                    FROM firmas_archivo {where}
                    ORDER BY fecha, hora_firma
                """, params)
                headers = ['Fecha','Docente','Aula','Turno','Hora Firma','PIN']
            filas = cur.fetchall()
        si = io.StringIO()
        si.write('﻿')
        writer = csv.writer(si, delimiter=';')
        writer.writerow(headers)
        for r in filas:
            writer.writerow(['' if v is None else v for v in r])
        sufijo = f'_{anio}' if anio else ''
        nombre = f'archivo_{tipo}{sufijo}.csv'
        _log_audit('TIC','super_usuario','EXPORT_ARCHIVO', tabla,
                   f'año={anio or "todos"}', f'{len(filas)} filas')
        return Response(si.getvalue(), mimetype='text/csv; charset=utf-8',
                        headers={'Content-Disposition': f'attachment; filename="{nombre}"'})
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# SU — BACKUP PROGRAMADO (scheduler hilo nativo, sin nuevas deps)
# ═══════════════════════════════════════════════════════════════════════════
# threading ya importado al inicio del archivo

_BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backups')
os.makedirs(_BACKUP_DIR, exist_ok=True)
_SCHEDULER_THREAD = None
_SCHEDULER_RUNNING = False
_LAST_BACKUP_AT = None

def _generar_backup_archivo():
    """Genera backup completo y lo guarda en disco."""
    global _LAST_BACKUP_AT
    tablas = ['cronograma_maestro','aspirantes','docentes','minutas',
              'firmas_docentes','justificaciones_ausencia','config_sistema',
              'usuarios_admin','pin_overrides','audit_log','failed_logins','system_log',
              'cronograma_versiones','bedeles_telegram','bedel_link_tokens',
              'recordatorios_telegram','bot_comando_log']
    out = {'meta': {'fecha_export': datetime.now().isoformat(), 'version_sipa':'GNA-2026'},
           'tablas': {}}
    conn = get_db()
    try:
        with conn.cursor() as cur:
            for t in tablas:
                try:
                    cur.execute(f"SELECT * FROM {t}")
                    cols = [c[0] for c in cur.description]
                    out['tablas'][t] = {
                        'columnas': cols,
                        'filas': [[str(v) if isinstance(v,(date,datetime)) else v for v in r]
                                  for r in cur.fetchall()],
                    }
                except Exception as e:
                    conn.rollback()
                    out['tablas'][t] = {'error': str(e)}
    finally:
        conn.close()
    nombre = f"backup_auto_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path = os.path.join(_BACKUP_DIR, nombre)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2, default=str)
    _LAST_BACKUP_AT = datetime.now()
    _rotar_backups()
    return path


def _rotar_backups():
    """Elimina los backups automáticos más antiguos si superan el límite configurado."""
    try:
        params = _cargar_params()
        max_bk = int(params.get('max_backups', {}).get('valor', '30') or 30)
        archivos = sorted(
            [f for f in os.listdir(_BACKUP_DIR)
             if f.startswith('backup_auto_') and f.endswith('.json')],
            reverse=True  # más recientes primero
        )
        for viejo in archivos[max_bk:]:
            try:
                os.remove(os.path.join(_BACKUP_DIR, viejo))
            except Exception:
                pass
    except Exception:
        pass

_LAST_REPORTE_AT = None

def _enviar_email_reporte(destinatarios, asunto, cuerpo_txt, csv_data=None):
    """Envío por SMTP (config en env). Retorna True si se envió OK."""
    from email.message import EmailMessage
    host = os.getenv('SMTP_HOST', '')
    port = int(os.getenv('SMTP_PORT', '587'))
    user = os.getenv('SMTP_USER', '')
    pwd  = os.getenv('SMTP_PASS', '')
    from_addr = os.getenv('SMTP_FROM', user)
    if not host or not user:
        raise RuntimeError('Falta configurar SMTP en .env (SMTP_HOST, SMTP_USER, SMTP_PASS)')
    msg = EmailMessage()
    msg['Subject'] = asunto
    msg['From']    = from_addr
    msg['To']      = ', '.join(destinatarios if isinstance(destinatarios, list) else [destinatarios])
    msg.set_content(cuerpo_txt)
    if csv_data:
        msg.add_attachment(csv_data.encode('utf-8'),
                           maintype='text', subtype='csv',
                           filename=f'inasistencias_{date.today().isoformat()}.csv')
    ctx = ssl.create_default_context()
    with smtplib.SMTP(host, port) as srv:
        srv.starttls(context=ctx)
        srv.login(user, pwd)
        srv.send_message(msg)
    return True


def _generar_reporte_diario_csv():
    """Genera el CSV de inasistencias de los últimos 7 días para el reporte."""
    desde = (date.today() - timedelta(days=6)).isoformat()
    hasta = date.today().isoformat()
    data, total = _calcular_inasistencias(desde, hasta, incluir_justificadas=True, limite=2000)
    si = io.StringIO()
    si.write('﻿')
    writer = csv.writer(si, delimiter=';')
    writer.writerow(['Fecha','Día','Hora','Turno','Aula','Docente','Materia','Estado','Motivo'])
    for r in data:
        writer.writerow([
            r.get('fecha',''), r.get('dia',''), r.get('hora_clase',''),
            r.get('turno',''), r.get('aula',''), r.get('docente',''),
            r.get('materia',''), r.get('estado',''),
            r.get('motivo','') or '',
        ])
    return si.getvalue(), total


def _limpiar_tokens_expirados():
    """Elimina tokens SU y Admin vencidos de los diccionarios en memoria."""
    ahora = datetime.now()
    su_expirados = [t for t, exp in list(_SU_TOKENS.items()) if exp < ahora]
    for t in su_expirados:
        _SU_TOKENS.pop(t, None)
    admin_expirados = [t for t, v in list(_ADMIN_TOKENS.items())
                       if isinstance(v, datetime) and v < ahora]
    for t in admin_expirados:
        _ADMIN_TOKENS.pop(t, None)
        _ADMIN_TOKENS.pop(t + '__user', None)
        _ADMIN_TOKENS.pop(t + '__impersonacion', None)


def _scheduler_loop():
    """Corre cada minuto. Verifica: (1) backup diario, (2) reporte diario por email, (3) limpieza de tokens."""
    global _SCHEDULER_RUNNING, _LAST_BACKUP_AT, _LAST_REPORTE_AT
    while _SCHEDULER_RUNNING:
        try:
            params = _cargar_params()
            ahora = datetime.now()

            # 0. Limpieza de tokens expirados y rate-limit (liviana, corre siempre)
            try:
                _limpiar_tokens_expirados()
                _rl_limpiar_expirados()
            except Exception:
                pass

            # 1. Backup diario
            hora_bk = (params.get('backup_hora_diaria',{}).get('valor','') or '').strip()
            if hora_bk and re.match(r'^\d{1,2}:\d{2}$', hora_bk):
                hh, mm = hora_bk.split(':')
                if ahora.hour == int(hh) and ahora.minute == int(mm):
                    if (not _LAST_BACKUP_AT or (ahora - _LAST_BACKUP_AT).total_seconds() > 90):
                        # Marcar ANTES de ejecutar para evitar dobles disparos si la operación tarda
                        _LAST_BACKUP_AT = ahora
                        try:
                            path = _generar_backup_archivo()
                            _log_audit('SCHEDULER','sistema','BACKUP_AUTO', None, path)
                            _tg_aviso_backup(True, f"📦 {os.path.basename(path)}")
                        except Exception as e:
                            _log_system('ERROR', f'Backup automático falló: {e}')
                            _tg_aviso_backup(False, str(e))

            # 2. Reporte diario por email
            hora_rep   = (params.get('reporte_diario_hora',{}).get('valor','') or '').strip()
            email_dest = (params.get('reporte_diario_email',{}).get('valor','') or '').strip()
            if hora_rep and email_dest and re.match(r'^\d{1,2}:\d{2}$', hora_rep):
                hh, mm = hora_rep.split(':')
                if ahora.hour == int(hh) and ahora.minute == int(mm):
                    if (not _LAST_REPORTE_AT or (ahora - _LAST_REPORTE_AT).total_seconds() > 90):
                        # Marcar ANTES para evitar reintentos dentro del mismo minuto
                        _LAST_REPORTE_AT = ahora
                        try:
                            csv_data, total = _generar_reporte_diario_csv()
                            destinos = [e.strip() for e in email_dest.split(',') if e.strip()]
                            cuerpo = (f"Reporte automático SIPA — GNA 2026\n"
                                      f"Fecha: {ahora.strftime('%d/%m/%Y %H:%M')}\n\n"
                                      f"Inasistencias detectadas en los últimos 7 días: {total}\n"
                                      f"Adjunto: detalle en CSV.\n\n"
                                      f"-- Sistema Integral de Partes de Aula --")
                            _enviar_email_reporte(destinos,
                                f'SIPA · Reporte diario {ahora.strftime("%d/%m/%Y")}',
                                cuerpo, csv_data)
                            _log_audit('SCHEDULER','sistema','REPORTE_EMAIL_AUTO',
                                       None, ', '.join(destinos), f'{total} inasistencias')
                        except Exception as e:
                            _log_system('ERROR', f'Reporte diario por email falló: {e}')

            # ════ 3. Telegram — Tareas programadas ════
            try:
                global _LAST_TG_RESUMEN_DIARIO, _LAST_TG_RESUMEN_SEMANAL, _LAST_TG_RESUMEN_MENSUAL
                global _LAST_TG_MINUTAS_TM, _LAST_TG_MINUTAS_TT, _LAST_TG_NOFIRMAN_AT
                global _LAST_TG_AUSENT_AT, _LAST_TG_PINS_DIA, _LAST_TG_JUSTIF_PEND
                global _LAST_TG_STATUS_DIARIO

                hh, mn = ahora.hour, ahora.minute
                hoy_iso = ahora.date().isoformat()

                def _ya_disparo(last_at, ventana_s=90):
                    return last_at and (ahora - last_at).total_seconds() < ventana_s

                # 3.1 PINs del día a las 06:00
                if _tg_alert_activa('telegram_alert_pins_dia') and hh == 6 and mn == 0:
                    if not _ya_disparo(_LAST_TG_PINS_DIA, 3600):
                        _LAST_TG_PINS_DIA = ahora
                        _tg_enviar(_tg_pins_del_dia())

                # 3.2 Status diario a las 07:30
                if _tg_alert_activa('telegram_alert_status_diario') and hh == 7 and mn == 30:
                    if not _ya_disparo(_LAST_TG_STATUS_DIARIO, 3600):
                        _LAST_TG_STATUS_DIARIO = ahora
                        _tg_enviar(_tg_status_diario())

                # 3.3 Justificaciones pendientes a las 09:00
                if _tg_alert_activa('telegram_alert_justif_pend') and hh == 9 and mn == 0:
                    if not _ya_disparo(_LAST_TG_JUSTIF_PEND, 3600):
                        _LAST_TG_JUSTIF_PEND = ahora
                        msj = _tg_justif_pendientes()
                        if msj: _tg_enviar(msj)

                # 3.4 Minutas tardías TM a las 13:30
                if _tg_alert_activa('telegram_alert_minutas_tardias') and hh == 13 and mn == 30:
                    if not _ya_disparo(_LAST_TG_MINUTAS_TM, 3600):
                        _LAST_TG_MINUTAS_TM = ahora
                        msj = _tg_alerta_minuta_tardia('TM')
                        if msj: _tg_enviar(msj)

                # 3.5 Minutas tardías TT a las 19:30
                if _tg_alert_activa('telegram_alert_minutas_tardias') and hh == 19 and mn == 30:
                    if not _ya_disparo(_LAST_TG_MINUTAS_TT, 3600):
                        _LAST_TG_MINUTAS_TT = ahora
                        msj = _tg_alerta_minuta_tardia('TT')
                        if msj: _tg_enviar(msj)

                # 3.6 Resumen diario a las 18:00
                if _tg_alert_activa('telegram_alert_resumen_diario') and hh == 18 and mn == 0:
                    if not _ya_disparo(_LAST_TG_RESUMEN_DIARIO, 3600):
                        _LAST_TG_RESUMEN_DIARIO = ahora
                        _tg_enviar(_tg_reporte_diario_consolidado())

                # 3.7 Resumen semanal viernes 18:00
                if _tg_alert_activa('telegram_alert_resumen_diario') and ahora.weekday() == 4 and hh == 18 and mn == 5:
                    if not _ya_disparo(_LAST_TG_RESUMEN_SEMANAL, 3600):
                        _LAST_TG_RESUMEN_SEMANAL = ahora
                        _tg_enviar(_tg_reporte_semanal())

                # 3.8 Resumen mensual último día del mes 23:30
                if _tg_alert_activa('telegram_alert_resumen_diario') and hh == 23 and mn == 30:
                    manana = ahora.date() + timedelta(days=1)
                    if manana.day == 1:  # mañana es día 1 → hoy es el último día del mes
                        if not _ya_disparo(_LAST_TG_RESUMEN_MENSUAL, 3600):
                            _LAST_TG_RESUMEN_MENSUAL = ahora
                            _tg_enviar(_tg_reporte_mensual())

                # 3.9 Detección de docentes que no firmaron — cada 10 min entre 08-22
                if _tg_alert_activa('telegram_alert_docentes_no_firman') and 8 <= hh <= 22 and mn % 10 == 0:
                    if not _ya_disparo(_LAST_TG_NOFIRMAN_AT, 540):  # 9 min
                        _LAST_TG_NOFIRMAN_AT = ahora
                        msj = _tg_alerta_docentes_no_firmaron()
                        if msj: _tg_enviar(msj)

                # 3.10 Ausentismo recurrente — todos los lunes a las 08:00
                if _tg_alert_activa('telegram_alert_ausentismo') and ahora.weekday() == 0 and hh == 8 and mn == 0:
                    if not _ya_disparo(_LAST_TG_AUSENT_AT, 3600):
                        _LAST_TG_AUSENT_AT = ahora
                        msj = _tg_alerta_ausentismo_recurrente()
                        if msj: _tg_enviar(msj)

                # 3.11 Recordatorios programados — chequear cada minuto
                try:
                    conn = get_db()
                    with conn.cursor() as cur:
                        cur.execute("""
                            SELECT id, mensaje FROM recordatorios_telegram
                            WHERE enviado=FALSE AND fecha_objetivo <= NOW()
                            ORDER BY fecha_objetivo LIMIT 10
                        """)
                        pendientes = cur.fetchall()
                        for rid, msj in pendientes:
                            texto = (f"⏰ <b>RECORDATORIO</b>\n"
                                     f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                                     f"{_tg_esc(msj)}\n\n"
                                     f"<i>📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}</i>")
                            if _tg_enviar(texto):
                                cur.execute("""
                                    UPDATE recordatorios_telegram
                                    SET enviado=TRUE, enviado_en=CURRENT_TIMESTAMP
                                    WHERE id=%s
                                """, (rid,))
                    conn.commit()
                    conn.close()
                except Exception:
                    pass
            except Exception as te:
                print(f"[scheduler-telegram] error: {te}")

        except Exception:
            pass
        _time_mod.sleep(45)

def _intentar_adquirir_scheduler_lock():
    """Crea un archivo .lock que indica 'soy yo el que corre el scheduler'.
    Si ya existe y el PID dentro sigue vivo, este proceso NO arranca scheduler.
    Funciona para gunicorn multi-worker, no requiere fcntl (cross-platform)."""
    lock_path = os.path.join(_BACKUP_DIR, '.scheduler.lock')
    try:
        if os.path.exists(lock_path):
            try:
                with open(lock_path) as fh:
                    pid_viejo = int(fh.read().strip())
                # Verificar si ese PID sigue vivo
                try:
                    os.kill(pid_viejo, 0)  # 0 = no envía nada, solo testea
                    return False  # vivo, otro worker ya tiene el lock
                except (ProcessLookupError, OSError):
                    pass  # PID muerto, podemos tomar el lock
            except (ValueError, IOError):
                pass  # lockfile corrupto, lo sobreescribimos
        with open(lock_path, 'w') as fh:
            fh.write(str(os.getpid()))
        return True
    except Exception as e:
        print(f"[scheduler] No se pudo adquirir lock: {e}")
        return True  # Mejor arrancar de más que de menos

def _iniciar_scheduler():
    global _SCHEDULER_THREAD, _SCHEDULER_RUNNING
    if _SCHEDULER_RUNNING: return
    if not _intentar_adquirir_scheduler_lock():
        print("[scheduler] Otro worker ya corre el scheduler. Saltando arranque en este proceso.")
        return
    _SCHEDULER_RUNNING = True
    _SCHEDULER_THREAD = threading.Thread(target=_scheduler_loop, daemon=True)
    _SCHEDULER_THREAD.start()
    print(f"[scheduler] Arrancado en PID {os.getpid()}")
    # Bot de Telegram (polling) — solo en el proceso que tiene el lock del scheduler
    try:
        _iniciar_telegram_bot()
    except Exception as e:
        print(f"[telegram-bot] No se pudo iniciar: {e}")

# Scheduler se arranca cuando PARAMS_DEFAULT ya fue inicializado (más abajo en el módulo)


@app.route('/api/su/backups_listado', methods=['GET'])
def su_backups_listado():
    err = _exigir_su(request)
    if err: return err
    archivos = []
    try:
        for f in sorted(os.listdir(_BACKUP_DIR), reverse=True):
            if not f.endswith('.json'): continue
            full = os.path.join(_BACKUP_DIR, f)
            archivos.append({
                'nombre': f,
                'tamano_kb': round(os.path.getsize(full)/1024, 1),
                'fecha':   datetime.fromtimestamp(os.path.getmtime(full)).isoformat(),
            })
    except Exception:
        pass
    return jsonify({
        'archivos': archivos,
        'directorio': _BACKUP_DIR,
        'ultimo_auto': _LAST_BACKUP_AT.isoformat() if _LAST_BACKUP_AT else None,
    })

@app.route('/api/su/backup_descargar/<nombre>', methods=['GET'])
def su_backup_descargar(nombre):
    err = _exigir_su(request)
    if err: return err
    if not re.match(r'^[A-Za-z0-9_.-]+\.json$', nombre):
        return jsonify({'error':'Nombre inválido'}), 400
    path = os.path.join(_BACKUP_DIR, nombre)
    if not os.path.isfile(path):
        return jsonify({'error':'No existe'}), 404
    return send_file(path, as_attachment=True, mimetype='application/json', download_name=nombre)


# ═══════════════════════════════════════════════════════════════════════════
# SU — IMPERSONACIÓN ("MODO DIOS")
# ═══════════════════════════════════════════════════════════════════════════
@app.route('/api/su/impersonar', methods=['POST'])
def su_impersonar():
    """Emite un token temporal que el SU puede usar como si fuese un docente
       específico, para reproducir y depurar errores que reportan los usuarios."""
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    rol     = (d.get('rol') or '').strip().lower()
    sujeto  = (d.get('sujeto') or '').strip()  # email del docente o usuario admin
    motivo  = (d.get('motivo') or '').strip()
    if rol not in ('docente','admin'):
        return jsonify({'error':'rol debe ser "docente" o "admin"'}), 400
    if not sujeto:
        return jsonify({'error':'sujeto requerido'}), 400
    if not motivo or len(motivo) < 5:
        return jsonify({'error':'Motivo de impersonación requerido (mínimo 5 caracteres). Queda auditado.'}), 400

    conn = get_db()
    try:
        if rol == 'docente':
            with conn.cursor() as cur:
                cur.execute("SELECT nombre FROM docentes WHERE email=%s", (sujeto.lower(),))
                row = cur.fetchone()
            if not row:
                return jsonify({'error': f'Docente con email "{sujeto}" no existe.'}), 404
            nombre_persona = row[0]
            payload = {'rol':'docente','nombre': row[0], 'email': sujeto.lower(), 'impersonado': True}
        else:
            with conn.cursor() as cur:
                cur.execute("SELECT id, nombre FROM usuarios_admin WHERE usuario=%s", (sujeto.lower(),))
                row = cur.fetchone()
            if not row:
                return jsonify({'error': f'Usuario admin "{sujeto}" no existe.'}), 404
            nombre_persona = row[1]
            payload = {'rol':'plana_mayor','nombre': row[1], 'usuario': sujeto.lower(), 'impersonado': True}
    finally:
        conn.close()

    tok = secrets.token_urlsafe(20)
    # Tokens de impersonación duran solo 30 minutos
    _ADMIN_TOKENS[tok] = datetime.now() + timedelta(minutes=30)
    _ADMIN_TOKENS[tok+'__user'] = payload
    _ADMIN_TOKENS[tok+'__impersonacion'] = {
        'sujeto_rol': rol, 'sujeto': sujeto, 'motivo': motivo,
        'iniciado': datetime.now().isoformat(),
    }
    _log_audit('TIC','super_usuario','IMPERSONAR_INICIO',
               None, f'{rol}:{sujeto}', f'motivo={motivo}')
    return jsonify({
        'token': tok, 'rol': rol, 'persona': nombre_persona, 'sujeto': sujeto,
        'duracion_min': 30, 'msj': f'Sesión de impersonación abierta como {nombre_persona} (30 min).'
    })

@app.route('/api/su/impersonar_fin', methods=['POST'])
def su_impersonar_fin():
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    tok = d.get('token','')
    info = _ADMIN_TOKENS.pop(tok+'__impersonacion', None)
    _ADMIN_TOKENS.pop(tok, None)
    _ADMIN_TOKENS.pop(tok+'__user', None)
    if info:
        _log_audit('TIC','super_usuario','IMPERSONAR_FIN',
                   None, f'{info["sujeto_rol"]}:{info["sujeto"]}',
                   f'iniciado={info["iniciado"]}')
    return jsonify({'msj':'Sesión de impersonación cerrada.'})


# ─── LIMPIAR SISTEMA ──────────────────────────────────────────────────────

@app.route('/api/limpiar_sistema', methods=['POST'])
def limpiar_sistema():
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    confirmacion = (d.get('confirmacion') or '').strip()
    if confirmacion != 'CONFIRMAR FORMATEO INSTITUCIONAL':
        return jsonify({'error': 'Frase incorrecta. Debe escribir exactamente: CONFIRMAR FORMATEO INSTITUCIONAL'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "TRUNCATE TABLE firmas_docentes, minutas, aspirantes, "
                "docentes, cronograma_maestro, justificaciones_ausencia, "
                "pin_overrides RESTART IDENTITY CASCADE"
            )
        conn.commit()
        _log_audit('TIC', 'super_usuario', 'FORMATEO_SISTEMA',
                   None, 'todas las tablas operativas', 'Confirmado con frase oficial')
        return jsonify({'msj': 'Sistema formateado. Todas las tablas vaciadas.'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# SUPER USUARIO — Módulos 3-4: Seguridad/PINes + Parámetros + Backup
# ═══════════════════════════════════════════════════════════════════════════

# ─── PARÁMETROS DEL SISTEMA ───────────────────────────────────────────────
PARAMS_DEFAULT = {
    'tolerancia_antes_min':         {'valor':'15', 'descripcion':'Minutos ANTES del inicio en que se habilita la firma.'},
    'tolerancia_despues_min':       {'valor':'10', 'descripcion':'Minutos DESPUÉS del fin durante los cuales aún se puede firmar.'},
    'limite_justif_retroactiva_h':  {'valor':'48', 'descripcion':'Horas hábiles máximas para justificar una clase pasada.'},
    'dias_pendientes_alerta':       {'valor':'7',  'descripcion':'Días hacia atrás que el portal docente busca clases sin regularizar.'},
    'ocultar_finalizados_min':      {'valor':'45', 'descripcion':'Minutos tras los cuales un bloque finalizado se oculta del monitor.'},
    'modo_mantenimiento':           {'valor':'0',  'descripcion':'Cuando vale 1, bloquea el acceso de Plana Mayor, Bedeles y Docentes (solo TIC opera).'},
    'backup_hora_diaria':           {'valor':'23:55', 'descripcion':'Hora (HH:MM, 24h) en que se genera backup automático. Vacío = sin backup auto.'},
    'reporte_diario_hora':          {'valor':'',   'descripcion':'Hora (HH:MM) en que se envía el reporte de inasistencias por email. Vacío = sin envío.'},
    'reporte_diario_email':         {'valor':'',   'descripcion':'Destinatario(s) del reporte diario (varios separados por coma).'},
    'max_backups':                  {'valor':'30', 'descripcion':'Cantidad máxima de backups automáticos a conservar en disco. Los más antiguos se eliminan automáticamente.'},
    'institucion_lat':              {'valor':'',   'descripcion':'Latitud del punto de referencia institucional para validar firmas.'},
    'institucion_lng':              {'valor':'',   'descripcion':'Longitud del punto de referencia institucional para validar firmas.'},
    'radio_geolocalizacion_m':      {'valor':'100', 'descripcion':'Radio permitido en metros para clasificar una firma como dentro de la institución.'},
    'adelantos_horario_activo':     {'valor':'0',   'descripcion':'Cuando vale 1, permite adelantos de horario aplicados automáticamente y registrados para revisión posterior.'},
    # ── Integración Telegram ──
    'telegram_bot_token':           {'valor':'',   'descripcion':'Token del bot de Telegram obtenido de @BotFather.'},
    'telegram_chat_id':             {'valor':'',   'descripcion':'ID del grupo/canal de Telegram donde se envían las minutas (formato -100xxxx para grupos).'},
    'telegram_activo':              {'valor':'0',  'descripcion':'Cuando vale 1, envía automáticamente cada minuta nueva al grupo de Telegram.'},
    'telegram_bot_interactivo':     {'valor':'0',  'descripcion':'Cuando vale 1, el bot escucha comandos /aula /hoy /ausentes /pins /justif /estado /ayuda en el grupo.'},
    'telegram_bedel_login_activo':  {'valor':'0',  'descripcion':'Cuando vale 1, habilita toda la integración privada de Telegram para Bedelía (vinculación, comandos y enlace mágico). Cuando vale 0, se oculta y bloquea; el PIN diario sigue disponible.'},
    # ── Alertas y reportes automáticos ──
    'telegram_alert_resumen_diario':    {'valor':'0', 'descripcion':'Cuando vale 1, envía resumen diario (18:00), semanal (viernes 18:00) y mensual (último día 23:30).'},
    'telegram_alert_minutas_tardias':   {'valor':'0', 'descripcion':'Cuando vale 1, avisa si un Bedel no cargó la minuta antes de 13:30 (TM) o 19:30 (TT).'},
    'telegram_alert_docentes_no_firman':{'valor':'0', 'descripcion':'Cuando vale 1, avisa al cerrar la ventana de firma si el docente no firmó su clase.'},
    'telegram_alert_ausentismo':        {'valor':'0', 'descripcion':'Cuando vale 1, alerta si un docente acumula 3+ clases sin firmar en 7 días.'},
    'telegram_alert_pins_dia':          {'valor':'0', 'descripcion':'Cuando vale 1, envía los PINs del día cada mañana a las 06:00.'},
    'telegram_alert_justif_pend':       {'valor':'0', 'descripcion':'Cuando vale 1, envía cada mañana a las 09:00 cuántas justificaciones esperan revisión.'},
    'telegram_alert_baja_asistencia':   {'valor':'0', 'descripcion':'Cuando vale 1, alerta si una minuta se guarda con menos del 70% de presentes.'},
    'telegram_alert_login_sospechoso':  {'valor':'0', 'descripcion':'Cuando vale 1, alerta si hay 5+ intentos de login fallidos en menos de 10 minutos.'},
    'telegram_alert_cronograma':        {'valor':'0', 'descripcion':'Cuando vale 1, avisa al grupo cuando se sube un nuevo cronograma desde TIC.'},
    'telegram_alert_backup':            {'valor':'0', 'descripcion':'Cuando vale 1, notifica al grupo cuando termina el backup automático (éxito o falla).'},
    'telegram_alert_status_diario':     {'valor':'0', 'descripcion':'Cuando vale 1, envía un status diario del sistema a las 07:30.'},
}


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRACIÓN TELEGRAM — envío automático de minutas al grupo de Plana Mayor
# ═══════════════════════════════════════════════════════════════════════════

import urllib.request as _urlreq
import urllib.parse   as _urlparse
import urllib.error   as _urlerr

_TELEGRAM_TIMEOUT_S = 8


def _telegram_config_actual() -> dict[str, str | bool] | None:
    """Lee config de Telegram desde config_sistema. Cero llamadas a Telegram si está incompleto."""
    try:
        p = _cargar_params()
    except Exception:
        return None
    token   = (p.get('telegram_bot_token', {}).get('valor') or '').strip()
    chat_id = (p.get('telegram_chat_id',   {}).get('valor') or '').strip()
    activo  = (p.get('telegram_activo',    {}).get('valor') or '0').strip() == '1'
    if not token or not chat_id:
        return None
    return {'token': token, 'chat_id': chat_id, 'activo': activo}


def _telegram_post(token: str, chat_id: str, texto: str, parse_mode: str = 'HTML') -> tuple[bool, str]:
    """POST a la API de Telegram. Retorna (ok, msg)."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': texto[:4096],  # límite duro de Telegram
        'parse_mode': parse_mode,
        'disable_web_page_preview': 'true',
    }
    data = _urlparse.urlencode(payload).encode('utf-8')
    req = _urlreq.Request(url, data=data, method='POST')
    try:
        with _urlreq.urlopen(req, timeout=_TELEGRAM_TIMEOUT_S) as resp:
            body = resp.read().decode('utf-8', errors='ignore')
            ok = '"ok":true' in body
            return (ok, 'enviado' if ok else f'respuesta inesperada: {body[:200]}')
    except _urlerr.HTTPError as he:
        try:    detalle = he.read().decode('utf-8', errors='ignore')[:200]
        except Exception: detalle = str(he)
        return (False, f'HTTP {he.code}: {detalle}')
    except Exception as e:
        return (False, f'error: {e}')


def _formatear_minuta_telegram(m: dict) -> str:
    """Arma el mensaje de texto (HTML) que se envía al grupo."""
    aula  = m.get('aula', '?')
    turno = m.get('turno', '?')
    fecha = m.get('fecha', '')
    # Fecha legible en español
    try:
        dt = datetime.strptime(str(fecha)[:10], '%Y-%m-%d')
        dias = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']
        fecha_str = f"{dias[dt.weekday()]} {dt.strftime('%d/%m/%Y')}"
    except Exception:
        fecha_str = str(fecha)

    fe        = m.get('fe', 0)
    presentes = m.get('presentes', 0)
    ausentes  = m.get('cant_ausentes', 0)
    bedel     = (m.get('bedel') or '—').strip() or '—'
    sub_bedel = (m.get('sub_bedel') or '—').strip() or '—'
    novedades = (m.get('novedades') or '').strip()

    # Lista de ausentes (máximo 15 para no pasar el límite de 4096 chars)
    ausentes_list = m.get('ausentes') or []
    bloque_aus = ''
    if isinstance(ausentes_list, list) and ausentes_list:
        items = []
        for a in ausentes_list[:15]:
            if not isinstance(a, dict):
                continue
            tipo   = (a.get('tipo')  or '').strip()
            nombre = (a.get('nombre') or '').strip()
            causa  = (a.get('causa')  or 'Sin justificar').strip()
            prefix = f"{_tg_esc(tipo)} " if tipo else ''
            items.append(f"  • {prefix}{_tg_esc(nombre)} — <i>{_tg_esc(causa)}</i>")
        bloque_aus = '\n'.join(items)
        if len(ausentes_list) > 15:
            bloque_aus += f"\n  …y {len(ausentes_list)-15} más"

    # Construcción del mensaje (HTML que Telegram entiende)
    partes = [
        f"📋 <b>MINUTA AULA {_tg_esc(aula)} ({_tg_esc(turno)})</b>",
        f"📅 {fecha_str}",
        "",
        f"👤 <b>Bedel:</b> {_tg_esc(bedel)}",
        f"👤 <b>Sub:</b>   {_tg_esc(sub_bedel)}",
        "",
        "📊 <b>ASISTENCIA</b>",
        f"   F.E.       <b>{fe}</b>",
        f"   Presentes  <b>{presentes}</b>  ✅",
        f"   Ausentes   <b>{ausentes}</b>  {'❌' if ausentes else '✅'}",
    ]
    if bloque_aus:
        partes.append("")
        partes.append("❌ <b>AUSENTES</b>")
        partes.append(bloque_aus)
    partes.append("")
    partes.append("📝 <b>NOVEDADES</b>")
    partes.append(f"   {_tg_esc(novedades) if novedades else '<i>Sin novedades.</i>'}")
    partes.append("")
    partes.append("<i>— S.I.P.A. · Escuela Cbo. Cuello —</i>")
    return '\n'.join(partes)


def _enviar_minuta_telegram(minuta_dict: dict, forzar: bool = False) -> tuple[bool, str]:
    """
    Envía la minuta al grupo configurado. Si forzar=False, respeta el toggle 'telegram_activo'.
    No bloquea ni propaga excepciones — diseñado para llamarse en un thread daemon.
    Retorna (ok, mensaje) para casos de test/reenvío manual.
    """
    try:
        cfg = _telegram_config_actual()
        if not cfg:
            return (False, 'Telegram no configurado (falta token o chat_id)')
        if not cfg['activo'] and not forzar:
            return (False, 'Envío automático deshabilitado (telegram_activo=0)')
        texto = _formatear_minuta_telegram(minuta_dict)
        ok, msg = _telegram_post(cfg['token'], cfg['chat_id'], texto, parse_mode='HTML')
        try:
            _log_system(
                'INFO' if ok else 'WARN',
                f"[telegram] Minuta aula={minuta_dict.get('aula')} turno={minuta_dict.get('turno')} fecha={minuta_dict.get('fecha')}: {msg}"
            )
        except Exception:
            pass
        return (ok, msg)
    except Exception as e:
        try:    _log_system('ERROR', f'[telegram] Excepción al enviar: {e}')
        except Exception: pass
        return (False, f'excepción: {e}')


# ─── Endpoints SU para Telegram ───────────────────────────────────────────

@app.route('/api/su/telegram/config', methods=['GET'])
def su_telegram_get_config():
    """Devuelve config actual (token ocultado)."""
    if not _su_token_valido(request):
        return jsonify({'error': 'Token SU inválido'}), 403
    p = _cargar_params()
    token = (p.get('telegram_bot_token', {}).get('valor') or '')
    # Ocultamos el token: solo mostramos últimos 4 caracteres si existe
    token_mask = ('•' * max(0, len(token) - 4) + token[-4:]) if token else ''
    # Lista de todos los toggles de alertas
    alert_keys = [
        'telegram_alert_resumen_diario',
        'telegram_alert_minutas_tardias',
        'telegram_alert_docentes_no_firman',
        'telegram_alert_ausentismo',
        'telegram_alert_baja_asistencia',
        'telegram_alert_login_sospechoso',
        'telegram_alert_pins_dia',
        'telegram_alert_justif_pend',
        'telegram_alert_cronograma',
        'telegram_alert_backup',
        'telegram_alert_status_diario',
    ]
    alerts = {k: (p.get(k, {}).get('valor') or '0') == '1' for k in alert_keys}
    return jsonify({
        'token_mask': token_mask,
        'token_configurado': bool(token),
        'chat_id':   p.get('telegram_chat_id', {}).get('valor') or '',
        'activo':    (p.get('telegram_activo', {}).get('valor') or '0') == '1',
        'bot_interactivo': (p.get('telegram_bot_interactivo', {}).get('valor') or '0') == '1',
        'alerts': alerts,
    })


@app.route('/api/su/telegram/config', methods=['POST'])
def su_telegram_set_config():
    """Guarda token/chat_id/toggle. Si token llega vacío, conserva el anterior."""
    if not _su_token_valido(request):
        return jsonify({'error': 'Token SU inválido'}), 403
    d = request.json or {}
    token        = (d.get('token')   or '').strip()
    chat_id      = (d.get('chat_id') or '').strip()
    activo       = '1' if d.get('activo') else '0'
    bot_interact = '1' if d.get('bot_interactivo') else '0'
    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Solo actualizamos el token si vino uno nuevo (no sobrescribir con vacío)
            if token:
                cur.execute("""
                    INSERT INTO config_sistema (clave, valor, descripcion, actualizado)
                    VALUES ('telegram_bot_token', %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, actualizado = CURRENT_TIMESTAMP
                """, (token, PARAMS_DEFAULT['telegram_bot_token']['descripcion']))
            cur.execute("""
                INSERT INTO config_sistema (clave, valor, descripcion, actualizado)
                VALUES ('telegram_chat_id', %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, actualizado = CURRENT_TIMESTAMP
            """, (chat_id, PARAMS_DEFAULT['telegram_chat_id']['descripcion']))
            cur.execute("""
                INSERT INTO config_sistema (clave, valor, descripcion, actualizado)
                VALUES ('telegram_activo', %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, actualizado = CURRENT_TIMESTAMP
            """, (activo, PARAMS_DEFAULT['telegram_activo']['descripcion']))
            cur.execute("""
                INSERT INTO config_sistema (clave, valor, descripcion, actualizado)
                VALUES ('telegram_bot_interactivo', %s, %s, CURRENT_TIMESTAMP)
                ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, actualizado = CURRENT_TIMESTAMP
            """, (bot_interact, PARAMS_DEFAULT['telegram_bot_interactivo']['descripcion']))
            # Guardar los 11 toggles de alertas
            alerts = d.get('alerts') or {}
            alert_keys = [
                'telegram_alert_resumen_diario',
                'telegram_alert_minutas_tardias',
                'telegram_alert_docentes_no_firman',
                'telegram_alert_ausentismo',
                'telegram_alert_baja_asistencia',
                'telegram_alert_login_sospechoso',
                'telegram_alert_pins_dia',
                'telegram_alert_justif_pend',
                'telegram_alert_cronograma',
                'telegram_alert_backup',
                'telegram_alert_status_diario',
            ]
            for k in alert_keys:
                v = '1' if alerts.get(k) else '0'
                cur.execute("""
                    INSERT INTO config_sistema (clave, valor, descripcion, actualizado)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor, actualizado = CURRENT_TIMESTAMP
                """, (k, v, PARAMS_DEFAULT.get(k, {}).get('descripcion', '')))
        conn.commit()
        _log_audit('TIC', 'tic', 'TELEGRAM_CONFIG', 'config_sistema', 'telegram',
                   f'activo={activo} bot_interactivo={bot_interact}')
        return jsonify({'msj': 'Configuración guardada'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/su/telegram/enviar_manual', methods=['POST'])
def su_telegram_enviar_manual():
    """Permite a TIC disparar manualmente cualquier reporte sin esperar al cron."""
    if not _su_token_valido(request):
        return jsonify({'error': 'Token SU inválido'}), 403
    cfg = _telegram_config_actual()
    if not cfg:
        return jsonify({'ok': False, 'msj': 'Telegram no configurado'}), 400
    tipo = (request.json or {}).get('tipo', '').strip().lower()
    GENERADORES = {
        'resumen_diario':       _tg_reporte_diario_consolidado,
        'resumen_semanal':      _tg_reporte_semanal,
        'resumen_mensual':      _tg_reporte_mensual,
        'minutas_tardias_tm':   lambda: _tg_alerta_minuta_tardia('TM') or '✅ No hay minutas tardías TM.',
        'minutas_tardias_tt':   lambda: _tg_alerta_minuta_tardia('TT') or '✅ No hay minutas tardías TT.',
        'docentes_no_firman':   lambda: _tg_alerta_docentes_no_firmaron() or '✅ Todos los docentes firmaron en la última ventana.',
        'ausentismo':           lambda: _tg_alerta_ausentismo_recurrente() or '✅ Sin patrones de ausentismo recurrente.',
        'pins_dia':             _tg_pins_del_dia,
        'justif_pend':          lambda: _tg_justif_pendientes() or '✅ No hay justificaciones pendientes.',
        'status_diario':        _tg_status_diario,
    }
    if tipo not in GENERADORES:
        return jsonify({'ok': False, 'msj': f'Tipo "{tipo}" desconocido'}), 400
    try:
        texto = GENERADORES[tipo]()
        ok, msg = _telegram_post(cfg['token'], cfg['chat_id'], texto)
        _log_audit('TIC', 'tic', 'TELEGRAM_MANUAL', None, tipo, msg)
        return jsonify({'ok': ok, 'msj': msg})
    except Exception as e:
        return jsonify({'ok': False, 'msj': str(e)}), 500


@app.route('/api/su/telegram/stats', methods=['GET'])
def su_telegram_stats():
    """Estadísticas de uso del bot (mensajes enviados, comandos recibidos, errores)."""
    if not _su_token_valido(request):
        return jsonify({'error': 'Token SU inválido'}), 403
    try:
        conn = get_db()
        with conn.cursor() as cur:
            # Eventos del system_log relacionados a telegram
            cur.execute("""
                SELECT COUNT(*) FILTER (WHERE nivel='INFO'  AND mensaje LIKE '[telegram]%'),
                       COUNT(*) FILTER (WHERE nivel='WARN'  AND mensaje LIKE '[telegram]%'),
                       COUNT(*) FILTER (WHERE nivel='ERROR' AND mensaje LIKE '[telegram]%')
                FROM system_log WHERE fecha >= NOW() - INTERVAL '7 days'
            """)
            r = cur.fetchone() or (0,0,0)
            cur.execute("""
                SELECT mensaje, fecha
                FROM system_log
                WHERE mensaje LIKE '[telegram]%'
                ORDER BY fecha DESC LIMIT 10
            """)
            recientes = [{'mensaje': m[:200], 'fecha': str(f)} for m, f in cur.fetchall()]
        conn.close()
        return jsonify({
            'ok': True,
            'exitos_7d':  r[0] or 0,
            'warnings_7d':r[1] or 0,
            'errores_7d': r[2] or 0,
            'recientes':  recientes,
        })
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route('/api/su/telegram/test', methods=['POST'])
def su_telegram_test():
    """Envía un mensaje de prueba para verificar que la config funciona."""
    if not _su_token_valido(request):
        return jsonify({'error': 'Token SU inválido'}), 403
    cfg = _telegram_config_actual()
    if not cfg:
        return jsonify({'ok': False, 'msj': 'Falta token o chat_id. Guardá la configuración primero.'}), 400
    texto = (
        "🧪 <b>PRUEBA DE CONEXIÓN — S.I.P.A.</b>\n\n"
        f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
        "Si ves este mensaje, el bot está configurado correctamente.\n"
        "Las próximas minutas se enviarán automáticamente.\n\n"
        "<i>— Escuela Cbo. Cuello —</i>"
    )
    ok, msg = _telegram_post(cfg['token'], cfg['chat_id'], texto, parse_mode='HTML')
    return jsonify({'ok': ok, 'msj': msg})


# ═══════════════════════════════════════════════════════════════════════════
# BOT INTERACTIVO — responde comandos /aula /hoy /ausentes /pins /justif /...
# ═══════════════════════════════════════════════════════════════════════════

_BOT_LOOP_RUNNING = False
_BOT_LOOP_THREAD  = None
_BOT_OFFSET       = 0  # último update_id procesado

# Flags para evitar disparos duplicados de alertas programadas
_LAST_TG_RESUMEN_DIARIO   = None
_LAST_TG_RESUMEN_SEMANAL  = None
_LAST_TG_RESUMEN_MENSUAL  = None
_LAST_TG_MINUTAS_TM       = None
_LAST_TG_MINUTAS_TT       = None
_LAST_TG_NOFIRMAN_AT      = None
_LAST_TG_AUSENT_AT        = None
_LAST_TG_PINS_DIA         = None
_LAST_TG_JUSTIF_PEND      = None
_LAST_TG_STATUS_DIARIO    = None
_LAST_TG_LOGIN_SOSP_AT    = None  # antiflood: una alerta cada N minutos máximo


def _tg_enviar(texto: str, parse_mode: str = 'HTML') -> bool:
    """Helper genérico: envía un mensaje al grupo configurado, ignorando si Telegram no está activo."""
    try:
        cfg = _telegram_config_actual()
        if not cfg:
            return False
        ok, _ = _telegram_post(cfg['token'], cfg['chat_id'], texto, parse_mode=parse_mode)
        return ok
    except Exception:
        return False


def _tg_alert_activa(clave: str) -> bool:
    """True si la alerta indicada está activa en config_sistema."""
    try:
        p = _cargar_params()
        return (p.get(clave, {}).get('valor') or '0') == '1'
    except Exception:
        return False


# ─── Generadores de reportes y alertas ────────────────────────────────────

def _tg_reporte_diario_consolidado() -> str:
    """Resumen del día con todas las minutas (18:00)."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT aula, turno, fe, presentes, cant_ausentes, bedel, ausentes_json
                FROM minutas WHERE fecha::date = CURRENT_DATE
                ORDER BY aula, turno
            """)
            filas = cur.fetchall()
            cur.execute("""
                SELECT COUNT(*) FROM firmas_docentes WHERE fecha::date = CURRENT_DATE
            """)
            firmas = cur.fetchone()[0]
        conn.close()
        fecha = datetime.now().strftime('%d/%m/%Y')
        if not filas:
            return f"🌅 <b>RESUMEN DEL DÍA</b> — {fecha}\n\n<i>No se cargaron minutas hoy.</i>"
        total_fe = sum(r[2] or 0 for r in filas)
        total_pr = sum(r[3] or 0 for r in filas)
        total_au = sum(r[4] or 0 for r in filas)
        lineas = [f"🌅 <b>RESUMEN DEL DÍA</b> — {fecha}", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
        lineas.append(f"🏫 <b>{len(filas)}</b> aulas operativas")
        lineas.append(f"👥 F.E. total: <b>{total_fe}</b> · Presentes: <b>{total_pr}</b> · Ausentes: <b>{total_au}</b>")
        lineas.append(f"👨‍🏫 Firmas docentes registradas: <b>{firmas}</b>\n")
        lineas.append("📋 <b>Por aula:</b>")
        for aula, turno, fe, pr, au, bed, _ in filas:
            icono = '✅' if (au or 0) == 0 else '⚠️'
            lineas.append(f"  • Aula {aula} ({turno}) — {fe}/{pr}/{au} {icono}")
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error generando resumen diario: {e}"


def _tg_reporte_semanal() -> str:
    """Resumen semanal (viernes 18:00) — últimas 7 jornadas."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                  COUNT(DISTINCT (aula, turno, fecha)) as total_minutas,
                  SUM(fe::int)         as total_fe,
                  SUM(presentes::int)  as total_pres,
                  SUM(cant_ausentes::int) as total_aus
                FROM minutas WHERE fecha::date >= CURRENT_DATE - 6 AND fecha::date <= CURRENT_DATE
            """)
            tot = cur.fetchone()
            cur.execute("""
                SELECT docente, COUNT(*) as cant
                FROM firmas_docentes WHERE fecha::date >= CURRENT_DATE - 6 AND fecha::date <= CURRENT_DATE
                GROUP BY docente ORDER BY cant DESC LIMIT 5
            """)
            top_doc = cur.fetchall()
        conn.close()
        rango = f"{(date.today() - timedelta(days=6)).strftime('%d/%m')} – {date.today().strftime('%d/%m')}"
        lineas = [f"📅 <b>REPORTE SEMANAL</b> — {rango}", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
        lineas.append(f"📋 Minutas cargadas:   <b>{tot[0] or 0}</b>")
        lineas.append(f"👥 F.E. acumulada:     <b>{tot[1] or 0}</b>")
        lineas.append(f"✅ Presentes:           <b>{tot[2] or 0}</b>")
        lineas.append(f"❌ Ausentes:            <b>{tot[3] or 0}</b>")
        if (tot[1] or 0) > 0:
            pct = round(100.0 * (tot[2] or 0) / (tot[1] or 1), 1)
            lineas.append(f"📊 Tasa de asistencia: <b>{pct}%</b>")
        if top_doc:
            lineas.append("\n👨‍🏫 <b>Top 5 docentes con más firmas:</b>")
            for d, c in top_doc:
                lineas.append(f"  • {d} — {c}")
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error generando reporte semanal: {e}"


def _tg_reporte_mensual() -> str:
    """Resumen mensual (último día del mes 23:30)."""
    try:
        hoy = date.today()
        primer = hoy.replace(day=1)
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*), SUM(fe::int), SUM(presentes::int), SUM(cant_ausentes::int)
                FROM minutas WHERE fecha::date >= %s AND fecha::date <= %s
            """, (primer, hoy))
            tot = cur.fetchone()
            cur.execute("""
                SELECT aula, COUNT(*) as cant
                FROM minutas WHERE fecha::date >= %s AND fecha::date <= %s
                GROUP BY aula ORDER BY cant DESC LIMIT 5
            """, (primer, hoy))
            top_aulas = cur.fetchall()
        conn.close()
        mes_str = primer.strftime('%B %Y')
        lineas = [f"📈 <b>REPORTE MENSUAL</b> — {mes_str}", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
        lineas.append(f"📋 Minutas del mes:    <b>{tot[0] or 0}</b>")
        lineas.append(f"👥 F.E. acumulada:     <b>{tot[1] or 0}</b>")
        lineas.append(f"✅ Presentes:           <b>{tot[2] or 0}</b>")
        lineas.append(f"❌ Ausentes:            <b>{tot[3] or 0}</b>")
        if (tot[1] or 0) > 0:
            pct = round(100.0 * (tot[2] or 0) / (tot[1] or 1), 1)
            lineas.append(f"📊 Tasa de asistencia: <b>{pct}%</b>")
        if top_aulas:
            lineas.append("\n🏫 <b>Top 5 aulas más activas:</b>")
            for a, c in top_aulas:
                lineas.append(f"  • Aula {a} — {c} minutas")
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error generando reporte mensual: {e}"


def _tg_alerta_minuta_tardia(turno: str) -> str:
    """Si pasada cierta hora un Bedel no entregó la minuta del turno."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            # Aulas que tienen cronograma para hoy + ese turno pero NO tienen minuta
            cur.execute("""
                SELECT DISTINCT cm.aula
                FROM cronograma_maestro cm
                WHERE cm.turno = %s
                AND cm.aula NOT IN (
                    SELECT aula FROM minutas
                    WHERE fecha::date = CURRENT_DATE AND turno = %s
                )
                ORDER BY cm.aula
            """, (turno, turno))
            aulas_sin = [r[0] for r in cur.fetchall()]
        conn.close()
        if not aulas_sin:
            return ''  # No alertar si no hay nada que alertar
        return (
            f"⏰ <b>MINUTAS PENDIENTES — Turno {turno}</b>\n\n"
            f"Las siguientes aulas no entregaron la minuta de hoy:\n\n"
            + '\n'.join(f"  • Aula <b>{a}</b>" for a in aulas_sin)
            + f"\n\n📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        )
    except Exception as e:
        return f"❌ Error verificando minutas tardías: {e}"


def _tg_alerta_docentes_no_firmaron() -> str:
    """Detecta clases que terminaron hace más de N minutos y el docente no firmó."""
    try:
        # Tolerancia configurable (default 10 min)
        p = _cargar_params()
        tol = int(p.get('tolerancia_despues_min', {}).get('valor', '10') or '10')
        ahora = datetime.now()
        hoy   = ahora.date().isoformat()
        # Limite: clase cuyo fin fue hace AL MENOS tol minutos pero NO MÁS de tol+20 (ventana de detección)
        # Para evitar inundar el grupo con todas las clases del día anteriores
        from_min = tol
        to_min   = tol + 20
        candidatos = []
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT aula, turno, config_json FROM cronograma_maestro
                WHERE config_json IS NOT NULL
            """)
            for aula, turno, cfg in cur.fetchall():
                if isinstance(cfg, str):
                    try:    cfg = json.loads(cfg)
                    except: continue
                if not isinstance(cfg, list): continue
                dia_actual = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo'][ahora.weekday()]
                for b in cfg:
                    if not isinstance(b, dict): continue
                    if (b.get('dia') or '').strip().lower() != dia_actual.lower(): continue
                    hora_str = (b.get('hora') or '').strip()
                    doc      = (b.get('doc')  or '').strip()
                    if not hora_str or not doc: continue
                    # hora_str formato: "HH:MM-HH:MM"
                    try:
                        ini_str, fin_str = hora_str.split('-')
                        fin_hh, fin_mm = fin_str.split(':')
                        fin_dt = ahora.replace(hour=int(fin_hh), minute=int(fin_mm), second=0, microsecond=0)
                        diff = (ahora - fin_dt).total_seconds() / 60.0
                        if not (from_min <= diff <= to_min): continue
                    except Exception:
                        continue
                    # ¿Firmó?
                    cur.execute("""
                        SELECT 1 FROM firmas_docentes
                        WHERE LOWER(docente)=LOWER(%s) AND aula=%s AND turno=%s AND fecha::date=%s
                    """, (doc, aula, turno, hoy))
                    if cur.fetchone():
                        continue
                    candidatos.append({
                        'docente': doc, 'aula': aula, 'turno': turno,
                        'hora': hora_str, 'materia': (b.get('asig') or '—').strip(),
                    })
        conn.close()
        if not candidatos:
            return ''
        lineas = ["🚨 <b>DOCENTES QUE NO FIRMARON</b>", ""]
        for c in candidatos[:15]:
            lineas.append(f"👨‍🏫 <b>{_tg_esc(c['docente'])}</b>")
            lineas.append(f"   🏫 Aula {_tg_esc(c['aula'])} ({_tg_esc(c['turno'])}) · {_tg_esc(c['hora'])}")
            lineas.append(f"   📚 {_tg_esc(c['materia'])}\n")
        return '\n'.join(lineas).rstrip()
    except Exception as e:
        return f"❌ Error detectando faltas: {e}"


def _tg_alerta_ausentismo_recurrente() -> str:
    """Docentes con 3+ clases sin firmar en últimos 7 días."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            # Cuento clases programadas vs firmadas para cada docente
            cur.execute("""
                WITH clases_semana AS (
                    SELECT cm.aula, cm.turno,
                           b->>'doc'  as docente,
                           b->>'hora' as hora,
                           b->>'dia'  as dia_sem
                    FROM cronograma_maestro cm, jsonb_array_elements(cm.config_json::jsonb) b
                    WHERE b->>'doc' != ''
                ),
                firmas_recientes AS (
                    SELECT docente, COUNT(*) as cant
                    FROM firmas_docentes
                    WHERE fecha::date >= CURRENT_DATE - 6
                    GROUP BY docente
                )
                SELECT cs.docente, COUNT(*) as clases_prog, COALESCE(fr.cant, 0) as firmadas
                FROM clases_semana cs
                LEFT JOIN firmas_recientes fr ON LOWER(cs.docente) = LOWER(fr.docente)
                GROUP BY cs.docente, fr.cant
                HAVING COUNT(*) - COALESCE(fr.cant, 0) >= 3
                ORDER BY 2 DESC LIMIT 10
            """)
            filas = cur.fetchall()
        conn.close()
        if not filas:
            return ''
        lineas = ["⚠️ <b>PATRÓN DE AUSENTISMO</b>", "<i>Docentes con 3+ clases sin firmar en últimos 7 días</i>", ""]
        for doc, prog, firm in filas:
            faltan = prog - firm
            lineas.append(f"  • <b>{_tg_esc(doc)}</b> — {faltan} sin firmar / {prog} programadas")
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error: {e}"


def _tg_pins_del_dia() -> str:
    """PINs operativos del día por aula (06:00)."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT aula, turno FROM cronograma_maestro
                WHERE config_json IS NOT NULL ORDER BY aula, turno
            """)
            aulas_turnos = cur.fetchall()
            cur.execute("""
                SELECT aula, turno FROM pin_overrides
                WHERE fecha::date = CURRENT_DATE
            """)
            overrides = {(a, t) for a, t in cur.fetchall()}
        conn.close()
        fecha_str = datetime.now().strftime('%A %d/%m/%Y').capitalize()
        if not aulas_turnos:
            return f"🌅 <b>BUENOS DÍAS</b>\n📅 {fecha_str}\n\n<i>Sin cronograma cargado.</i>"
        lineas = [
            "🌅 <b>BUENOS DÍAS — PINs DEL DÍA</b>",
            f"📅 {fecha_str}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]
        por_turno = {'TM': [], 'TT': []}
        for aula, turno in aulas_turnos:
            pin = generar_pin_diario(aula, turno)
            por_turno.setdefault(turno, []).append((aula, pin, (aula, turno) in overrides))
        for turno in ['TM', 'TT']:
            items = por_turno.get(turno, [])
            if not items: continue
            ico = '🌅' if turno == 'TM' else '🌇'
            label = 'Turno Mañana' if turno == 'TM' else 'Turno Tarde'
            lineas.append(f"{ico} <b>{label} ({turno})</b>")
            for aula, pin, es_ov in items:
                tag = ' 🔧' if es_ov else ''
                lineas.append(f"   🏫 Aula <b>{aula}</b> → <code>{pin}</code>{tag}")
            lineas.append("")
        if overrides:
            lineas.append("🔧 = PIN sobrescrito por TIC")
            lineas.append("")
        lineas.append("💡 Compartir con los Bedeles y Docentes correspondientes.")
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error: {e}"


def _tg_justif_pendientes() -> str:
    """Resumen de justificaciones pendientes (09:00)."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM justificaciones_ausencia WHERE estado='pendiente'")
            total = cur.fetchone()[0]
            cur.execute("""
                SELECT MIN(creado_en::date) FROM justificaciones_ausencia
                WHERE estado='pendiente'
            """)
            mas_vieja = cur.fetchone()[0]
        conn.close()
        if not total:
            return ''  # silencio si no hay nada que avisar
        dias = (date.today() - mas_vieja).days if mas_vieja else 0
        return (
            f"📋 <b>JUSTIFICACIONES PENDIENTES</b>\n\n"
            f"🔢 <b>{total}</b> nuevas para revisar\n"
            f"⏰ Más antigua: hace <b>{dias}</b> día(s)\n\n"
            f"🔗 Revisar en S.I.P.A. → Auditoría → Inasistencias"
        )
    except Exception as e:
        return f"❌ Error: {e}"


def _tg_status_diario() -> str:
    """Status del sistema cada mañana (07:30)."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM firmas_docentes")
            firmas_tot = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM minutas")
            minutas_tot = cur.fetchone()[0]
        conn.close()
        # Disco libre (Windows)
        try:
            import shutil
            uso = shutil.disk_usage('.')
            disco_pct = round(100.0 * uso.free / uso.total, 1)
        except Exception:
            disco_pct = None
        lineas = [
            f"☀️ <b>SISTEMA OPERATIVO</b>",
            f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            "",
            "🔌 PostgreSQL: ✅",
            "🌐 Flask: ✅",
            "📡 SSE: ✅",
            f"📋 Total minutas: <b>{minutas_tot}</b>",
            f"👨‍🏫 Total firmas: <b>{firmas_tot}</b>",
        ]
        if disco_pct is not None:
            lineas.append(f"💾 Disco libre: <b>{disco_pct}%</b>")
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error: {e}"


def _tg_check_login_sospechoso() -> None:
    """Se llama desde el endpoint de login fallido. Throttle: 1 alerta cada 30 min."""
    global _LAST_TG_LOGIN_SOSP_AT
    if not _tg_alert_activa('telegram_alert_login_sospechoso'):
        return
    ahora = datetime.now()
    if _LAST_TG_LOGIN_SOSP_AT and (ahora - _LAST_TG_LOGIN_SOSP_AT).total_seconds() < 1800:
        return
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT tipo, ip, COUNT(*) as cant
                FROM failed_logins
                WHERE fecha >= NOW() - INTERVAL '10 minutes'
                GROUP BY tipo, ip
                HAVING COUNT(*) >= 5
                ORDER BY cant DESC LIMIT 5
            """)
            sospechosos = cur.fetchall()
        conn.close()
        if not sospechosos:
            return
        _LAST_TG_LOGIN_SOSP_AT = ahora
        lineas = ["🚨 <b>ALERTA DE SEGURIDAD</b>", "<i>5+ intentos de login fallidos en 10 min</i>", ""]
        for tipo, ip, c in sospechosos:
            lineas.append(f"  🎯 Tipo: <code>{tipo or '—'}</code>")
            lineas.append(f"  🌍 IP:   <code>{ip or '—'}</code>")
            lineas.append(f"  🔢 Intentos: <b>{c}</b>\n")
        _tg_enviar('\n'.join(lineas).rstrip())
    except Exception:
        pass


def _tg_check_baja_asistencia(minuta: dict) -> None:
    """Se llama desde guardar_minuta. Alerta si presentes/FE < 70%."""
    if not _tg_alert_activa('telegram_alert_baja_asistencia'):
        return
    fe = (minuta.get('fe') or 0)
    pr = (minuta.get('presentes') or 0)
    if fe <= 0:
        return
    pct = 100.0 * pr / fe
    if pct >= 70.0:
        return
    texto = (
        f"🚨 <b>BAJA ASISTENCIA</b>\n\n"
        f"🏫 Aula <b>{minuta.get('aula')}</b> ({minuta.get('turno')})\n"
        f"📅 {minuta.get('fecha')}\n\n"
        f"📊 F.E.: <b>{fe}</b> | Presentes: <b>{pr}</b> ({pct:.1f}%) ❌\n"
        f"👤 Bedel: {minuta.get('bedel') or '—'}"
    )
    _tg_enviar(texto)


def _tg_aviso_backup(ok: bool, detalle: str = '') -> None:
    """Llamada desde el scheduler tras backup automático."""
    if not _tg_alert_activa('telegram_alert_backup'):
        return
    if ok:
        texto = (
            f"💾 <b>BACKUP DIARIO COMPLETADO</b>\n\n"
            f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
            f"✅ Sin errores\n"
            f"{detalle}"
        )
    else:
        texto = (
            f"❌ <b>BACKUP DIARIO FALLÓ</b>\n\n"
            f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
            f"⚠️ {detalle[:200]}"
        )
    _tg_enviar(texto)


def _tg_notificar_justificacion_nueva(justif_id, docente, aula, turno, fecha, motivo, coment):
    """Push al grupo cuando un docente envía una nueva justificación.
    Incluye botones inline [✅ Aprobar] [❌ Rechazar]."""
    try:
        cfg = _telegram_config_actual()
        if not cfg:
            return
        texto = (
            f"📋 <b>NUEVA JUSTIFICACIÓN PENDIENTE</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👨‍🏫 <b>{_tg_esc(docente)}</b>\n"
            f"🏫 Aula {_tg_esc(aula)} ({_tg_esc(turno)})\n"
            f"📅 {fecha}\n\n"
            f"📝 <b>Motivo:</b> {_tg_esc(motivo)}\n"
        )
        if coment and coment.strip():
            texto += f"💬 <i>{_tg_esc(coment.strip()[:200])}</i>\n"
        texto += "\n<i>Tocá un botón para resolver:</i>"
        botones = [[
            {'text': '✅ Aprobar',  'callback_data': f'justif_ok:{justif_id}'},
            {'text': '❌ Rechazar', 'callback_data': f'justif_no:{justif_id}'},
        ]]
        _bot_responder(cfg['token'], cfg['chat_id'], texto, botones=botones)
    except Exception:
        pass


def _aplicar_decision_justif(justif_id: int, decision: str) -> str:
    """Aplica aprobar/rechazar a una justificación. decision: 'aprobada' o 'rechazada'."""
    if decision not in ('aprobada', 'rechazada'):
        return "❌ Decisión inválida."
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE justificaciones_ausencia
                SET estado=%s, revisado_por='TELEGRAM', revisado_en=CURRENT_TIMESTAMP
                WHERE id=%s
                RETURNING docente, aula, turno, fecha::text, estado
            """, (decision, justif_id))
            row = cur.fetchone()
        conn.commit()
        conn.close()
        if not row:
            return "❌ Justificación no encontrada (puede haber sido borrada)."
        doc, aula, turno, fecha, est = row
        _log_audit('TELEGRAM', 'plana_mayor', f'JUSTIF_{decision.upper()}',
                   'justificaciones_ausencia', f'id={justif_id}', doc)
        ico = '✅' if decision == 'aprobada' else '❌'
        return (
            f"{ico} <b>JUSTIFICACIÓN {decision.upper()}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👨‍🏫 <b>{_tg_esc(doc)}</b>\n"
            f"🏫 Aula {_tg_esc(aula)} ({_tg_esc(turno)})\n"
            f"📅 {fecha}\n\n"
            f"🕐 Resuelto: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        )
    except Exception as e:
        return f"❌ Error: {e}"


def _tg_aviso_cronograma_subido(usuario: str, aulas_afect: int, bloques: int) -> None:
    """Llamada cuando alguien sube un cronograma desde TIC."""
    if not _tg_alert_activa('telegram_alert_cronograma'):
        return
    texto = (
        f"📁 <b>CRONOGRAMA ACTUALIZADO</b>\n\n"
        f"👤 Subido por: <b>{usuario}</b>\n"
        f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
        f"📊 <b>{aulas_afect}</b> aulas afectadas · <b>{bloques}</b> bloques\n"
        f"🔄 Reversible desde S.I.P.A. → Versiones"
    )
    _tg_enviar(texto)



def _telegram_get_updates(token: str, offset: int = 0, timeout: int = 25) -> list:
    """Long-polling: pide updates al bot. Retorna lista (vacía si no hay)."""
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    payload = {
        'offset': offset, 'timeout': timeout,
        'allowed_updates': '["message","callback_query"]'  # ahora también callbacks de botones
    }
    data = _urlparse.urlencode(payload).encode('utf-8')
    req = _urlreq.Request(url, data=data, method='POST')
    try:
        # Timeout HTTP = timeout long-poll + 5s de margen
        with _urlreq.urlopen(req, timeout=timeout + 5) as resp:
            body = resp.read().decode('utf-8', errors='ignore')
            parsed = json.loads(body)
            if parsed.get('ok'):
                return parsed.get('result') or []
    except Exception as e:
        # Errores transitorios son normales (red, timeout); el loop reintenta
        pass
    return []


def _bot_responder(token: str, chat_id, texto: str, reply_to_msg_id=None, botones=None):
    """Envía respuesta del bot. Acepta reply_to y botones inline opcionales.
    botones: lista de listas, donde cada botón es {'text': str, 'callback_data': str}
    """
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': str(chat_id),
        'text': texto[:4096],
        'parse_mode': 'HTML',
        'disable_web_page_preview': 'true',
    }
    if reply_to_msg_id:
        payload['reply_to_message_id'] = str(reply_to_msg_id)
    if botones:
        payload['reply_markup'] = json.dumps({'inline_keyboard': botones})
    data = _urlparse.urlencode(payload).encode('utf-8')
    req = _urlreq.Request(url, data=data, method='POST')
    try:
        _urlreq.urlopen(req, timeout=_TELEGRAM_TIMEOUT_S).read()
    except Exception:
        pass


def _bot_editar(token: str, chat_id, message_id: int, texto: str, botones=None):
    """Edita un mensaje existente del bot (para actualizar menús sin spam)."""
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    payload = {
        'chat_id': str(chat_id),
        'message_id': str(message_id),
        'text': texto[:4096],
        'parse_mode': 'HTML',
        'disable_web_page_preview': 'true',
    }
    if botones:
        payload['reply_markup'] = json.dumps({'inline_keyboard': botones})
    data = _urlparse.urlencode(payload).encode('utf-8')
    req = _urlreq.Request(url, data=data, method='POST')
    try:
        _urlreq.urlopen(req, timeout=_TELEGRAM_TIMEOUT_S).read()
    except Exception:
        pass


def _bot_answer_callback(token: str, callback_id: str, texto: str = ''):
    """Confirma un callback (quita el spinner en el botón)."""
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    payload = {'callback_query_id': callback_id, 'text': texto[:200]}
    data = _urlparse.urlencode(payload).encode('utf-8')
    req = _urlreq.Request(url, data=data, method='POST')
    try:
        _urlreq.urlopen(req, timeout=5).read()
    except Exception:
        pass


# ─── HELPERS VISUALES ─────────────────────────────────────────────────────

def _tg_esc(s) -> str:
    """Escapa caracteres especiales de HTML para que Telegram no rompa el parseo.
    Telegram parse_mode='HTML' falla si hay `<`, `>` o `&` sueltos en el texto.
    Usar SIEMPRE sobre strings que vienen de la DB o del usuario antes de meterlos
    dentro de tags como <b>...</b>, <i>...</i>, <code>...</code>.
    """
    if s is None:
        return ''
    return (str(s)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;'))


def _sparkline(valores: list, ancho: int = 8) -> str:
    """Genera mini-gráfico ASCII tipo ▁▃▅▇█."""
    if not valores: return ''
    bloques = '▁▂▃▄▅▆▇█'
    mn = min(valores); mx = max(valores)
    rng = mx - mn or 1
    return ''.join(bloques[min(7, max(0, int((v - mn) / rng * 7)))] for v in valores[:ancho])


def _barra_progreso(porcentaje: float, ancho: int = 10) -> str:
    """Barra de progreso ASCII: ████████░░ 80%"""
    porcentaje = max(0, min(100, porcentaje))
    llenos = int(porcentaje / 100 * ancho)
    return '█' * llenos + '░' * (ancho - llenos) + f' {porcentaje:.0f}%'


def _icono_asistencia(pct: float) -> str:
    """Devuelve emoji según porcentaje de asistencia."""
    if pct >= 90:  return '🟢'
    if pct >= 75:  return '🟡'
    if pct >= 60:  return '🟠'
    return '🔴'


def _menu_principal_botones() -> list:
    """Layout de botones del menú principal (expandido con todas las funciones)."""
    return [
        [{'text': '📊 Hoy',         'callback_data': 'cmd:hoy'},
         {'text': '❌ Ausentes',    'callback_data': 'cmd:ausentes'}],
        [{'text': '📅 Semana',      'callback_data': 'cmd:semana'},
         {'text': '📈 Mes',         'callback_data': 'cmd:mes'}],
        [{'text': '🔑 PINs',        'callback_data': 'cmd:pins'},
         {'text': '📋 Justif.',     'callback_data': 'cmd:justif'}],
        [{'text': '🏫 Bedeles',     'callback_data': 'cmd:bedeles'},
         {'text': '📈 Cobertura',   'callback_data': 'cmd:cobertura'}],
        [{'text': '🏆 Ranking',     'callback_data': 'cmd:ranking'},
         {'text': '📜 Auditoría',   'callback_data': 'cmd:auditoria'}],
        [{'text': '📡 Estado',      'callback_data': 'cmd:estado'},
         {'text': '❔ Ayuda',       'callback_data': 'cmd:ayuda'}],
    ]


def _cmd_ayuda() -> str:
    return (
        "🤖 <b>S.I.P.A. BOT — Manual de uso</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<i>Sistema Integral de Partes de Aula</i>\n"
        "<i>Escuela Cbo. Raúl R. Cuello · GNA</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⭐ <b>EMPEZÁ ACÁ</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🎮 <code>/menu</code>\n"
        "   <i>Menú interactivo con botones.\n"
        "   Recomendado para uso diario.</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📊 <b>CONSULTAS DEL DÍA</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📅 <code>/hoy</code>\n"
        "   Resumen de minutas + asistencia general.\n\n"
        "❌ <code>/ausentes</code>\n"
        "   Quién faltó hoy + causa de cada uno.\n\n"
        "👥 <code>/bedeles</code>\n"
        "   Quién está de bedel en cada aula.\n\n"
        "🔑 <code>/pins</code>\n"
        "   <b>PINs operativos del día por aula</b>.\n"
        "   <i>Cambian todos los días.</i>\n\n"
        "📋 <code>/justif</code>\n"
        "   Justificaciones esperando aprobación.\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "🏫 <b>INFO POR AULA</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<code>/aula 25</code> — últimas minutas\n"
        "<code>/aula 25 TM</code> — solo turno mañana\n"
        "<code>/historial 25</code> — últimas 10\n"
        "<code>/cronograma 25 TM</code> — semana entera\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "👨‍🏫 <b>BÚSQUEDA DE DOCENTES</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔎 <code>/buscar GARCIA</code>\n"
        "   <i>Busca por apellido (parcial).</i>\n\n"
        "👤 <code>/docente LOPEZ</code>\n"
        "   <i>Perfil + firmas + ausencias + aulas.</i>\n\n"
        "✍️ <code>/foja LOPEZ</code>\n"
        "   <i>Últimas 10 firmas del docente.</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📈 <b>REPORTES Y RANKINGS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📅 <code>/semana</code> — últimos 7 días\n"
        "📈 <code>/mes</code> — mes actual\n"
        "🏆 <code>/ranking</code> — top docentes/aulas\n"
        "📊 <code>/cobertura</code> — % por aula\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📜 <b>SISTEMA</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📡 <code>/estado</code> — salud del sistema\n"
        "📜 <code>/auditoria</code> — últimas acciones\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "📢 <b>AVISOS Y CONTROL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📣 <code>/notif TEXTO</code>\n"
        "   <i>Publica un anuncio al grupo.\n"
        "   Ej: /notif Mañana feriado.</i>\n\n"
        "🔕 <code>/silenciar</code>\n"
        "   <i>Pausa TODAS las alertas automáticas.</i>\n\n"
        "🔔 <code>/activar</code>\n"
        "   <i>Reactiva las alertas esenciales.</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "⚡ <b>ACCIONES (TIC/PM)</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "🔐 <code>/pin_temp 25 TM</code>\n"
        "   <i>PIN temporal para un aula.</i>\n\n"
        "🛠️ <code>/mantenimiento</code>\n"
        "   <i>Activa/desactiva modo mantto.</i>\n\n"
        "💾 <code>/backup</code>\n"
        "   <i>Genera respaldo manual.</i>\n\n"
        "🔓 <code>/reset_doc email</code>\n"
        "   <i>Reset password de un docente.</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "💡 <b>TIPS</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "• Usá <code>/menu</code> para no recordar comandos.\n"
        "• Los comandos NO distinguen mayúsculas.\n"
        "• En grupos podés escribir <code>/comando</code> o\n"
        "  <code>/comando@sipa_cuello_bot</code> (Telegram\n"
        "  agrega el @nombre solo).\n"
        "• Si te equivocás de comando, el bot\n"
        "  ignora silenciosamente. Probá <code>/ayuda</code>.\n\n"
        "<i>— S.I.P.A. · Escuela Cbo. Cuello —</i>"
    )


def _cmd_menu() -> tuple:
    """Menú principal con botones interactivos. Retorna (texto, botones)."""
    fecha = datetime.now().strftime('%A %d/%m/%Y · %H:%M').capitalize()
    texto = (
        "🤖 <b>S.I.P.A. — Menú Principal</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📅 {fecha}\n\n"
        "👇 <b>Tocá una opción:</b>\n\n"
        "📊 <i>Hoy</i> — minutas y asistencia del día\n"
        "❌ <i>Ausentes</i> — quién faltó hoy\n"
        "📅 <i>Semana</i> — reporte últimos 7 días\n"
        "📈 <i>Mes</i> — reporte del mes\n"
        "🔑 <i>PINs</i> — códigos del día por aula\n"
        "📋 <i>Justif.</i> — justificaciones pendientes\n"
        "🏫 <i>Bedeles</i> — quién está hoy\n"
        "📊 <i>Cobertura</i> — % asistencia por aula\n"
        "🏆 <i>Ranking</i> — top docentes y aulas\n"
        "📜 <i>Auditoría</i> — últimas acciones\n"
        "📡 <i>Estado</i> — salud del sistema\n"
        "❔ <i>Ayuda</i> — manual completo\n\n"
        "💡 <i>También podés escribir comandos. Probá <code>/ayuda</code></i>"
    )
    return texto, _menu_principal_botones()


def _cmd_estado() -> str:
    """Estado general del sistema (visual y didáctico)."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            pg_ver = (cur.fetchone()[0] or '').split(',')[0]
            cur.execute("SELECT COUNT(*) FROM minutas WHERE fecha::date = CURRENT_DATE")
            minutas_hoy = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM firmas_docentes WHERE fecha::date = CURRENT_DATE")
            firmas_hoy = cur.fetchone()[0]
            try:
                cur.execute("SELECT COUNT(*) FROM justificaciones_ausencia WHERE estado='pendiente'")
                justif_pend = cur.fetchone()[0]
            except Exception:
                justif_pend = 0
            cur.execute("SELECT COUNT(*) FROM docentes")
            docentes_tot = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM cronograma_maestro")
            aulas_tot = cur.fetchone()[0]
        conn.close()
        # Disco libre
        try:
            import shutil
            uso = shutil.disk_usage('.')
            disco_pct = round(100.0 * uso.free / uso.total, 1)
            disco_txt = f"{disco_pct}% libre"
        except Exception:
            disco_txt = '—'
        return (
            "📡 <b>ESTADO DEL SISTEMA</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🟢 <b>Servicios</b>\n"
            f"   🗄️ PostgreSQL: ✅ activo\n"
            f"   🌐 Flask:      ✅ activo\n"
            f"   📡 SSE:        ✅ activo\n"
            f"   🤖 Bot:        ✅ respondiendo\n\n"
            "📊 <b>Operativa de hoy</b>\n"
            f"   📋 Minutas:        <b>{minutas_hoy}</b>\n"
            f"   ✍️ Firmas:         <b>{firmas_hoy}</b>\n"
            f"   📝 Justif. pend.:  <b>{justif_pend}</b>\n\n"
            "🏫 <b>Recursos cargados</b>\n"
            f"   👨‍🏫 Docentes:       <b>{docentes_tot}</b>\n"
            f"   🏫 Aulas:           <b>{aulas_tot}</b>\n\n"
            "💾 <b>Sistema</b>\n"
            f"   Disco: {disco_txt}\n"
            f"   PG: <code>{pg_ver[:40]}</code>\n\n"
            f"🕐 {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}"
        )
    except Exception as e:
        return f"❌ Error al consultar estado: {e}"


def _cmd_hoy() -> str:
    """Resumen de minutas del día (con gráficos ASCII)."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT aula, turno, fe, presentes, cant_ausentes, bedel
                FROM minutas WHERE fecha::date = CURRENT_DATE
                ORDER BY aula, turno
            """)
            filas = cur.fetchall()
        conn.close()
        if not filas:
            return "📅 <b>HOY</b>\n\n<i>No hay minutas cargadas todavía.</i>"
        total_fe = sum(r[2] or 0 for r in filas)
        total_pr = sum(r[3] or 0 for r in filas)
        total_au = sum(r[4] or 0 for r in filas)
        pct = (100.0 * total_pr / total_fe) if total_fe else 0
        lineas = [
            f"📅 <b>RESUMEN DE HOY</b> — {datetime.now().strftime('%d/%m/%Y')}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"🏫 <b>{len(filas)}</b> aulas operativas",
            f"👥 F.E.: <b>{total_fe}</b> · Pres.: <b>{total_pr}</b> · Aus.: <b>{total_au}</b>",
            "",
            f"📊 Asistencia general:",
            f"<code>{_barra_progreso(pct, 20)}</code>",
            "",
            "📋 <b>Por aula:</b>",
        ]
        for aula, turno, fe, pres, aus, bedel in filas:
            pct_aula = (100.0 * pres / fe) if fe else 0
            icono = _icono_asistencia(pct_aula)
            lineas.append(f"  {icono} Aula {aula} ({turno}) — <b>{pres}/{fe}</b> · {pct_aula:.0f}%")
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_semana() -> str:
    """Reporte semanal on-demand con sparkline de asistencia diaria."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            # Asistencia diaria de los últimos 7 días
            cur.execute("""
                SELECT fecha::date, SUM(fe::int), SUM(presentes::int)
                FROM minutas
                WHERE fecha::date >= CURRENT_DATE - 6 AND fecha::date <= CURRENT_DATE
                GROUP BY fecha::date ORDER BY fecha::date
            """)
            por_dia = cur.fetchall()
            cur.execute("""
                SELECT SUM(fe::int), SUM(presentes::int), SUM(cant_ausentes::int), COUNT(*)
                FROM minutas
                WHERE fecha::date >= CURRENT_DATE - 6 AND fecha::date <= CURRENT_DATE
            """)
            tot = cur.fetchone()
            cur.execute("""
                SELECT docente, COUNT(*) FROM firmas_docentes
                WHERE fecha::date >= CURRENT_DATE - 6 AND fecha::date <= CURRENT_DATE
                GROUP BY docente ORDER BY 2 DESC LIMIT 5
            """)
            top_doc = cur.fetchall()
        conn.close()
        rango = f"{(date.today() - timedelta(days=6)).strftime('%d/%m')} – {date.today().strftime('%d/%m')}"
        # Generar sparkline de presentes diarios
        valores = [(p or 0) for _, _, p in por_dia]
        spark = _sparkline(valores) if valores else '—'
        pct = (100.0 * (tot[1] or 0) / (tot[0] or 1)) if (tot[0] or 0) > 0 else 0
        lineas = [
            f"📅 <b>REPORTE SEMANAL</b> — {rango}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"📋 Minutas:      <b>{tot[3] or 0}</b>",
            f"👥 F.E. total:   <b>{tot[0] or 0}</b>",
            f"✅ Presentes:    <b>{tot[1] or 0}</b>",
            f"❌ Ausentes:     <b>{tot[2] or 0}</b>",
            "",
            f"📊 Asistencia: <code>{_barra_progreso(pct, 20)}</code>",
            f"📈 Tendencia diaria: <code>{spark}</code>",
        ]
        if top_doc:
            lineas.append("\n🏆 <b>Top 5 docentes con más firmas:</b>")
            for d, c in top_doc:
                lineas.append(f"  • {_tg_esc(d)} — <b>{c}</b>")
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_mes() -> str:
    """Reporte mensual on-demand."""
    try:
        hoy = date.today()
        primer = hoy.replace(day=1)
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*), SUM(fe::int), SUM(presentes::int), SUM(cant_ausentes::int)
                FROM minutas WHERE fecha::date >= %s AND fecha::date <= %s
            """, (primer, hoy))
            tot = cur.fetchone()
            cur.execute("""
                SELECT aula, COUNT(*) FROM minutas
                WHERE fecha::date >= %s AND fecha::date <= %s
                GROUP BY aula ORDER BY 2 DESC LIMIT 5
            """, (primer, hoy))
            top_aulas = cur.fetchall()
        conn.close()
        meses = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                 'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
        mes_str = f"{meses[primer.month-1]} {primer.year}"
        pct = (100.0 * (tot[2] or 0) / (tot[1] or 1)) if (tot[1] or 0) > 0 else 0
        lineas = [
            f"📈 <b>REPORTE MENSUAL</b> — {mes_str}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"📋 Minutas:    <b>{tot[0] or 0}</b>",
            f"👥 F.E.:        <b>{tot[1] or 0}</b>",
            f"✅ Presentes:   <b>{tot[2] or 0}</b>",
            f"❌ Ausentes:    <b>{tot[3] or 0}</b>",
            "",
            f"📊 Asistencia: <code>{_barra_progreso(pct, 20)}</code>",
        ]
        if top_aulas:
            lineas.append("\n🏫 <b>Top 5 aulas más activas:</b>")
            for a, c in top_aulas:
                lineas.append(f"  • Aula {_tg_esc(a)} — <b>{c}</b> minutas")
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_buscar(arg: str) -> str:
    """Búsqueda fuzzy de docentes por apellido."""
    q = arg.strip().upper()
    if len(q) < 2:
        return "❓ Uso: <code>/buscar APELLIDO</code>  (mínimo 2 caracteres)"
    try:
        conn = get_db()
        with conn.cursor() as cur:
            # Buscar en docentes registrados
            cur.execute("""
                SELECT DISTINCT nombre, email FROM docentes
                WHERE UPPER(nombre) LIKE %s ORDER BY nombre LIMIT 15
            """, (f'%{q}%',))
            reg = cur.fetchall()
            # Buscar también en cronograma
            cur.execute("""
                SELECT DISTINCT b->>'doc' as doc
                FROM cronograma_maestro c, jsonb_array_elements(c.config_json::jsonb) b
                WHERE UPPER(b->>'doc') LIKE %s AND b->>'doc' != ''
                ORDER BY doc LIMIT 15
            """, (f'%{q}%',))
            cron = [r[0] for r in cur.fetchall()]
        conn.close()
        lineas = [f"🔎 <b>BÚSQUEDA: {_tg_esc(q)}</b>\n"]
        if reg:
            lineas.append("👨‍🏫 <b>Docentes registrados:</b>")
            for nom, email in reg[:10]:
                lineas.append(f"  • {_tg_esc(nom)}" + (f" · <i>{_tg_esc(email)}</i>" if email else ''))
        if cron:
            lineas.append(f"\n📋 <b>En cronograma:</b>")
            for d in cron[:10]:
                lineas.append(f"  • {_tg_esc(d)}")
        if not reg and not cron:
            return f"🔎 Sin resultados para <b>{_tg_esc(q)}</b>"
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_bedeles() -> str:
    """Bedeles asignados a las minutas de hoy."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT aula, turno, bedel, sub_bedel
                FROM minutas WHERE fecha::date = CURRENT_DATE
                ORDER BY aula, turno
            """)
            filas = cur.fetchall()
        conn.close()
        if not filas:
            return "🏫 <b>BEDELES HOY</b>\n\n<i>No hay minutas cargadas todavía.</i>"
        lineas = [f"👥 <b>BEDELES DE HOY</b> — {datetime.now().strftime('%d/%m/%Y')}\n"]
        for aula, turno, bed, sub in filas:
            lineas.append(f"🏫 <b>Aula {_tg_esc(aula)} ({_tg_esc(turno)})</b>")
            lineas.append(f"   👤 Bedel: {_tg_esc(bed) if bed else '—'}")
            if sub: lineas.append(f"   👤 Sub:   {_tg_esc(sub)}")
            lineas.append("")
        return '\n'.join(lineas).rstrip()
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_historial(arg: str) -> str:
    """Historial de las últimas 10 minutas de un aula."""
    partes = arg.strip().upper().split()
    if not partes:
        return "❓ Uso: <code>/historial AULA</code>  (ej: <code>/historial 25</code>)"
    aula = partes[0]
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha::text, turno, fe, presentes, cant_ausentes
                FROM minutas WHERE aula=%s
                ORDER BY fecha DESC, turno DESC LIMIT 10
            """, (aula,))
            filas = cur.fetchall()
        conn.close()
        if not filas:
            return f"🏫 Aula <b>{_tg_esc(aula)}</b>: sin historial."
        # Sparkline de tendencia de asistencia
        pcts = [(100.0 * (p or 0) / fe) if fe else 0 for _, _, fe, p, _ in reversed(filas)]
        spark = _sparkline(pcts, 10) if len(pcts) > 1 else ''
        lineas = [f"📚 <b>HISTORIAL AULA {_tg_esc(aula)}</b> — últimas 10\n"]
        if spark:
            lineas.append(f"📈 Tendencia: <code>{spark}</code>\n")
        for fecha, turno, fe, pr, au in filas:
            pct = (100.0 * (pr or 0) / fe) if fe else 0
            icono = _icono_asistencia(pct)
            lineas.append(f"  {icono} {fecha} {turno} — {pr}/{fe} ({pct:.0f}%)")
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_docente(arg: str) -> str:
    """Perfil completo de un docente: firmas, ausencias, materias, aulas."""
    q = arg.strip().upper()
    if len(q) < 2:
        return "❓ Uso: <code>/docente APELLIDO</code>  (mínimo 2 caracteres)"
    try:
        conn = get_db()
        with conn.cursor() as cur:
            # Datos del docente registrado
            cur.execute("""
                SELECT nombre, email, dni, creado_en::text
                FROM docentes WHERE UPPER(nombre) LIKE %s LIMIT 1
            """, (f'%{q}%',))
            reg = cur.fetchone()

            # Firmas totales y de los últimos 7 días
            cur.execute("""
                SELECT COUNT(*), COUNT(*) FILTER (WHERE fecha::date >= CURRENT_DATE - 6),
                       MAX(fecha::text), MIN(fecha::text)
                FROM firmas_docentes WHERE UPPER(docente) LIKE %s
            """, (f'%{q}%',))
            firmas = cur.fetchone() or (0, 0, None, None)

            # Justificaciones
            cur.execute("""
                SELECT COUNT(*), COUNT(*) FILTER (WHERE estado='pendiente')
                FROM justificaciones_ausencia WHERE UPPER(docente) LIKE %s
            """, (f'%{q}%',))
            justif = cur.fetchone() or (0, 0)

            # Aulas donde firmó
            cur.execute("""
                SELECT aula, turno, COUNT(*) as cant
                FROM firmas_docentes WHERE UPPER(docente) LIKE %s
                GROUP BY aula, turno ORDER BY cant DESC LIMIT 5
            """, (f'%{q}%',))
            aulas = cur.fetchall()
        conn.close()

        if not reg and firmas[0] == 0:
            return f"🔎 No se encontró ningún docente que coincida con <b>{_tg_esc(q)}</b>."

        lineas = [f"👨‍🏫 <b>PERFIL DOCENTE: {_tg_esc(q)}</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
        if reg:
            nom, email, dni, creado = reg
            lineas.append(f"📛 Nombre:  <b>{_tg_esc(nom)}</b>")
            lineas.append(f"📧 Email:   {_tg_esc(email) if email else '—'}")
            lineas.append(f"🆔 DNI:     {_tg_esc(dni) if dni else '—'}")
            lineas.append(f"📅 Registrado: {(creado or '')[:10]}")
            lineas.append("")
        else:
            lineas.append("<i>⚠️ Sin cuenta registrada en S.I.P.A.</i>\n")

        lineas.append("✍️ <b>Asistencia</b>")
        lineas.append(f"   Firmas totales:   <b>{firmas[0]}</b>")
        lineas.append(f"   Últimos 7 días:    <b>{firmas[1]}</b>")
        if firmas[2]:
            lineas.append(f"   Última firma:      {firmas[2]}")
        if firmas[3]:
            lineas.append(f"   Primera firma:     {firmas[3]}")
        lineas.append("")
        lineas.append("📋 <b>Justificaciones</b>")
        lineas.append(f"   Total:              <b>{justif[0]}</b>")
        lineas.append(f"   Pendientes:         <b>{justif[1]}</b>")
        if aulas:
            lineas.append("\n🏫 <b>Top aulas donde firma:</b>")
            for aula, turno, cant in aulas:
                lineas.append(f"   • Aula {_tg_esc(aula)} ({_tg_esc(turno)}) — {cant} firmas")
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_cronograma(arg: str) -> str:
    """Cronograma semanal de un aula. Uso: /cronograma 25 TM"""
    partes = arg.strip().upper().split()
    if not partes:
        return "❓ Uso: <code>/cronograma AULA TURNO</code>  (ej: <code>/cronograma 25 TM</code>)"
    aula = partes[0]
    turno = partes[1] if len(partes) > 1 else 'TM'
    if turno not in ('TM', 'TT'):
        turno = 'TM'
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT config_json FROM cronograma_maestro
                WHERE aula=%s AND turno=%s
            """, (aula, turno))
            row = cur.fetchone()
        conn.close()
        if not row or not row[0]:
            return f"🏫 Aula <b>{aula}</b> ({turno}): sin cronograma cargado."
        cfg = row[0]
        if isinstance(cfg, str):
            try:    cfg = json.loads(cfg)
            except: return f"❌ Error parseando cronograma."
        if not isinstance(cfg, list) or not cfg:
            return f"🏫 Aula <b>{aula}</b> ({turno}): cronograma vacío."

        # Agrupar por día
        por_dia = {}
        orden_dias = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']
        for b in cfg:
            if not isinstance(b, dict): continue
            dia = (b.get('dia') or '').strip()
            por_dia.setdefault(dia, []).append(b)

        lineas = [f"📅 <b>CRONOGRAMA AULA {_tg_esc(aula)} ({_tg_esc(turno)})</b>", ""]
        for dia in orden_dias:
            if dia not in por_dia: continue
            bloques = sorted(por_dia[dia], key=lambda x: x.get('hora') or '')
            lineas.append(f"<b>📌 {dia}</b>")
            for b in bloques:
                hora = (b.get('hora') or '—').strip()
                asig = (b.get('asig') or '—').strip()[:35]
                doc  = (b.get('doc')  or '—').strip()[:35]
                lineas.append(f"  🕐 <code>{_tg_esc(hora)}</code> · {_tg_esc(asig)}")
                lineas.append(f"     👨‍🏫 {_tg_esc(doc)}")
            lineas.append("")
        return '\n'.join(lineas).rstrip()
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_ranking() -> str:
    """Ranking de docentes con más firmas + aulas más activas (últimos 30 días)."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT docente, COUNT(*) as cant
                FROM firmas_docentes WHERE fecha::date >= CURRENT_DATE - 29
                GROUP BY docente ORDER BY cant DESC LIMIT 10
            """)
            top_doc = cur.fetchall()
            cur.execute("""
                SELECT aula, SUM(presentes::int) as pres, SUM(fe::int) as fe
                FROM minutas WHERE fecha::date >= CURRENT_DATE - 29
                GROUP BY aula ORDER BY pres DESC LIMIT 10
            """)
            top_aulas = cur.fetchall()
        conn.close()
        lineas = ["🏆 <b>RANKING — Últimos 30 días</b>", "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
        if top_doc:
            lineas.append("👨‍🏫 <b>Top 10 docentes con más firmas:</b>")
            medallas = ['🥇','🥈','🥉'] + ['  '] * 7
            for i, (d, c) in enumerate(top_doc):
                lineas.append(f"  {medallas[i]} <b>{c}</b> · {_tg_esc((d or '')[:40])}")
            lineas.append("")
        if top_aulas:
            lineas.append("🏫 <b>Top 10 aulas más activas:</b>")
            for aula, pres, fe in top_aulas:
                pct = (100.0 * (pres or 0) / (fe or 1)) if (fe or 0) > 0 else 0
                icono = _icono_asistencia(pct)
                lineas.append(f"  {icono} Aula {_tg_esc(aula)} — <b>{pres or 0}</b>/{fe or 0} ({pct:.0f}%)")
        return '\n'.join(lineas).rstrip()
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_cobertura() -> str:
    """Cobertura semanal por aula: firmas registradas / clases programadas."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            # Total clases programadas por aula y turno (asume 5 días hábiles)
            cur.execute("""
                SELECT aula, turno, jsonb_array_length(config_json::jsonb) as bloques
                FROM cronograma_maestro WHERE config_json IS NOT NULL
                ORDER BY aula, turno
            """)
            cron = cur.fetchall()
            # Firmas de la semana
            cur.execute("""
                SELECT aula, turno, COUNT(*) as cant
                FROM firmas_docentes
                WHERE fecha::date >= CURRENT_DATE - 6 AND fecha::date <= CURRENT_DATE
                GROUP BY aula, turno
            """)
            firmas = {(a, t): c for a, t, c in cur.fetchall()}
        conn.close()
        if not cron:
            return "📊 <b>COBERTURA SEMANAL</b>\n\n<i>No hay cronograma cargado.</i>"
        lineas = ["📊 <b>COBERTURA SEMANAL POR AULA</b>",
                  f"<i>(últimos 7 días)</i>",
                  "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]
        for aula, turno, bloques in cron:
            firmadas = firmas.get((aula, turno), 0)
            esperadas = bloques or 0
            pct = (100.0 * firmadas / esperadas) if esperadas > 0 else 0
            icono = _icono_asistencia(pct)
            barra = _barra_progreso(pct, 10)
            lineas.append(f"{icono} <b>Aula {_tg_esc(aula)} ({_tg_esc(turno)})</b>")
            lineas.append(f"   {firmadas}/{esperadas} clases")
            lineas.append(f"   <code>{barra}</code>")
            lineas.append("")
        return '\n'.join(lineas).rstrip()
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_auditoria() -> str:
    """Últimas 10 acciones del audit_log."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha::text, usuario, rol, accion, tabla, detalle
                FROM audit_log ORDER BY fecha DESC LIMIT 10
            """)
            filas = cur.fetchall()
        conn.close()
        if not filas:
            return "📜 <b>AUDITORÍA</b>\n\n<i>Sin acciones registradas.</i>"
        lineas = ["📜 <b>AUDITORÍA — últimas 10 acciones</b>\n"]
        for fecha, usu, rol, acc, tab, det in filas:
            ts = (fecha or '')[:19].replace('T', ' ')
            ico = '🛡️' if rol == 'plana_mayor' else '⚙️' if rol == 'tic' else '👨‍🏫' if rol == 'docente' else '👤'
            lineas.append(f"{ico} <code>{ts}</code>")
            lineas.append(f"   <b>{_tg_esc(acc)}</b> · {_tg_esc(usu) if usu else '?'}")
            if tab: lineas.append(f"   📂 {_tg_esc(tab)}")
            if det: lineas.append(f"   <i>{_tg_esc((det or '')[:80])}</i>")
            lineas.append("")
        return '\n'.join(lineas).rstrip()
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_notif(arg: str) -> str:
    """Envía un aviso personalizado al grupo desde el bot.
    Permite agregar emojis, anuncios, recordatorios."""
    texto = arg.strip()
    if len(texto) < 3:
        return "❓ Uso: <code>/notif TEXTO</code>\n\nEj: <code>/notif Mañana es feriado, no hay clases.</code>"
    return (
        f"📢 <b>AVISO DE PLANA MAYOR</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"{_tg_esc(texto[:3000])}\n\n"
        f"<i>📅 {datetime.now().strftime('%d/%m/%Y %H:%M')} · S.I.P.A.</i>"
    )


def _cmd_silenciar() -> str:
    """Desactiva TODAS las alertas automáticas con un solo comando."""
    alert_keys = [
        'telegram_alert_resumen_diario',
        'telegram_alert_minutas_tardias',
        'telegram_alert_docentes_no_firman',
        'telegram_alert_ausentismo',
        'telegram_alert_baja_asistencia',
        'telegram_alert_login_sospechoso',
        'telegram_alert_pins_dia',
        'telegram_alert_justif_pend',
        'telegram_alert_cronograma',
        'telegram_alert_backup',
        'telegram_alert_status_diario',
    ]
    try:
        conn = get_db()
        with conn.cursor() as cur:
            for k in alert_keys:
                cur.execute("""
                    UPDATE config_sistema SET valor='0', actualizado=CURRENT_TIMESTAMP
                    WHERE clave=%s
                """, (k,))
        conn.commit()
        conn.close()
        return (
            "🔕 <b>ALERTAS SILENCIADAS</b>\n\n"
            "Todas las alertas automáticas fueron <b>desactivadas</b>.\n"
            "El bot interactivo y el envío de minutas siguen funcionando.\n\n"
            "Para reactivar: <code>/activar</code>"
        )
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_activar() -> str:
    """Reactiva las alertas más importantes (no todas — algunas son ruidosas)."""
    # Reactivamos las MÁS ÚTILES por defecto
    alert_keys_basicas = [
        'telegram_alert_resumen_diario',
        'telegram_alert_baja_asistencia',
        'telegram_alert_pins_dia',
        'telegram_alert_justif_pend',
        'telegram_alert_minutas_tardias',
    ]
    try:
        conn = get_db()
        with conn.cursor() as cur:
            for k in alert_keys_basicas:
                cur.execute("""
                    INSERT INTO config_sistema (clave, valor, descripcion, actualizado)
                    VALUES (%s, '1', '', CURRENT_TIMESTAMP)
                    ON CONFLICT (clave) DO UPDATE SET valor='1', actualizado=CURRENT_TIMESTAMP
                """, (k,))
        conn.commit()
        conn.close()
        return (
            "🔔 <b>ALERTAS REACTIVADAS</b>\n\n"
            "Se activaron las alertas <b>esenciales</b>:\n"
            "  ✅ Resumen diario (18:00)\n"
            "  ✅ Baja asistencia (&lt;70%)\n"
            "  ✅ PINs del día (06:00)\n"
            "  ✅ Justificaciones pendientes (09:00)\n"
            "  ✅ Minutas tardías\n\n"
            "Para configurar más detalladamente, andá al panel TIC."
        )
    except Exception as e:
        return f"❌ Error: {e}"


# ─── BOT PRIVADO PARA BEDELES (BLOQUE 3) ───────────────────────────────────

def _bedel_telegram_buscar(tg_user_id) -> dict | None:
    """Devuelve {aula, turno} si el Telegram user_id está vinculado, o None."""
    if not tg_user_id or not _telegram_bedel_habilitado():
        return None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT aula, turno, nombre_telegram FROM bedeles_telegram
                WHERE telegram_user_id=%s AND activo=TRUE
            """, (int(tg_user_id),))
            row = cur.fetchone()
            if row:
                cur.execute("""
                    UPDATE bedeles_telegram SET ultimo_acceso=CURRENT_TIMESTAMP
                    WHERE telegram_user_id=%s
                """, (int(tg_user_id),))
        conn.commit()
        conn.close()
        if row:
            return {'aula': row[0], 'turno': row[1], 'nombre': row[2] or ''}
        return None
    except Exception:
        return None


def _asegurar_tablas_bedel_telegram():
    """Crea las tablas del Bloque 3 si no existen. Idempotente.
    Se llama justo antes de generar un código, así no requiere reiniciar Flask."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bedeles_telegram (
                    id                SERIAL PRIMARY KEY,
                    telegram_user_id  BIGINT       UNIQUE NOT NULL,
                    telegram_username VARCHAR(80),
                    nombre_telegram   VARCHAR(150),
                    aula              VARCHAR(50)  NOT NULL,
                    turno             VARCHAR(20)  NOT NULL,
                    vinculado_en      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
                    ultimo_acceso     TIMESTAMP,
                    activo            BOOLEAN      DEFAULT TRUE
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bedel_link_tokens (
                    token       VARCHAR(50) PRIMARY KEY,
                    tipo        VARCHAR(20) NOT NULL,
                    aula        VARCHAR(50),
                    turno       VARCHAR(20),
                    tg_user_id  BIGINT,
                    tg_username VARCHAR(80),
                    creado_en   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    expira_en   TIMESTAMP NOT NULL,
                    usado       BOOLEAN DEFAULT FALSE
                )
            """)
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        try: _log_system('ERROR', f'[bedel_tg] No se pudo crear tablas: {e}')
        except Exception: pass
        return False


def _bedel_generar_codigo_vinculacion(tg_user_id, tg_username, tg_nombre) -> tuple:
    """Genera código de 6 dígitos válido por 10 min para vincular un Bedel.
    Retorna (codigo, mensaje_error). Si codigo='', el segundo elemento explica por qué."""
    if not _telegram_bedel_habilitado():
        return ('', 'La integración de Telegram para Bedelía está desactivada por TIC.')
    # Asegurar que las tablas existen (idempotente, por si Flask no se reinició)
    if not _asegurar_tablas_bedel_telegram():
        return ('', 'No se pudieron crear las tablas. Revisá los permisos de la DB.')
    codigo = f"{secrets.randbelow(1000000):06d}"
    expira = datetime.now() + timedelta(minutes=10)
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("DELETE FROM bedel_link_tokens WHERE tg_user_id=%s AND tipo='vincular'",
                        (int(tg_user_id),))
            cur.execute("""
                INSERT INTO bedel_link_tokens (token, tipo, tg_user_id, tg_username, expira_en)
                VALUES (%s, 'vincular', %s, %s, %s)
            """, (codigo, int(tg_user_id), (tg_username or '')[:80], expira))
        conn.commit()
        conn.close()
        return (codigo, '')
    except Exception as e:
        try: _log_system('ERROR', f'[bedel_tg] generar_codigo falló: {e}')
        except Exception: pass
        return ('', str(e)[:200])


def _bedel_consumir_codigo(codigo: str, aula: str, turno: str) -> tuple:
    """Consume un código de vinculación desde el Portal Bedel.
    Retorna (ok, mensaje, tg_user_id_o_None)."""
    if not _telegram_bedel_habilitado():
        return (False, 'La integración de Telegram para Bedelía está desactivada por TIC.', None)
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT tg_user_id, tg_username, expira_en, usado
                FROM bedel_link_tokens
                WHERE token=%s AND tipo='vincular'
            """, (codigo,))
            row = cur.fetchone()
            if not row:
                return (False, 'Código inválido o expirado.', None)
            tg_uid, tg_user, exp, usado = row
            if usado:
                return (False, 'Código ya utilizado.', None)
            if exp < datetime.now():
                return (False, 'Código expirado (10 min).', None)
            # Vincular en la tabla principal
            cur.execute("""
                INSERT INTO bedeles_telegram (telegram_user_id, telegram_username, aula, turno)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (telegram_user_id) DO UPDATE
                SET telegram_username=EXCLUDED.telegram_username,
                    aula=EXCLUDED.aula, turno=EXCLUDED.turno,
                    activo=TRUE, vinculado_en=CURRENT_TIMESTAMP
            """, (tg_uid, tg_user, aula, turno))
            # Marcar token como usado
            cur.execute("UPDATE bedel_link_tokens SET usado=TRUE WHERE token=%s", (codigo,))
        conn.commit()
        conn.close()
        return (True, f'Vinculado a Aula {aula} ({turno})', tg_uid)
    except Exception as e:
        return (False, f'Error: {e}', None)


def _bedel_generar_token_login(tg_user_id, aula: str, turno: str) -> str:
    """Genera un token de single-sign-on válido por 5 minutos."""
    if not _telegram_bedel_habilitado():
        return ''
    tok = secrets.token_urlsafe(24)
    expira = datetime.now() + timedelta(minutes=5)
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bedel_link_tokens (token, tipo, aula, turno, tg_user_id, expira_en)
                VALUES (%s, 'login', %s, %s, %s, %s)
            """, (tok, aula, turno, int(tg_user_id), expira))
        conn.commit()
        conn.close()
        return tok
    except Exception:
        return ''


# ─── Comandos del bot para Bedeles vinculados ────────────────────────────

def _cmd_bedel_start(tg_user_id, tg_username, tg_nombre) -> tuple:
    """Comando /start o /vincular en chat privado: arranca flujo de vinculación."""
    # Si ya está vinculado, le mostramos su info
    info = _bedel_telegram_buscar(tg_user_id)
    if info:
        return (
            f"✅ <b>Ya estás vinculado</b>\n\n"
            f"🏫 Aula: <b>{_tg_esc(info['aula'])}</b>\n"
            f"⏰ Turno: <b>{_tg_esc(info['turno'])}</b>\n\n"
            f"<b>Comandos disponibles:</b>\n"
            f"  🔑 <code>/mi_pin</code> — PIN del día\n"
            f"  📊 <code>/mi_aula</code> — estado actual\n"
            f"  📚 <code>/mi_padron</code> — listado de aspirantes\n"
            f"  📅 <code>/mi_cronograma</code> — horario semanal\n"
            f"  🔗 <code>/link_pc</code> — login mágico al SIPA\n"
            f"  ❌ <code>/desvincular</code> — desconectar este Telegram",
            None
        )
    # Si no, generamos código de vinculación
    codigo, err = _bedel_generar_codigo_vinculacion(tg_user_id, tg_username, tg_nombre)
    if not codigo:
        return (f"❌ <b>Error al generar el código</b>\n\n<code>{_tg_esc(err)}</code>\n\n<i>Avisale a TIC.</i>", None)
    return (
        f"🔗 <b>VINCULACIÓN DE BEDEL</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Tu código:\n"
        f"<code>{codigo}</code>\n\n"
        f"<b>Pasos:</b>\n"
        f"1️⃣ Abrí el S.I.P.A. en tu PC o cel\n"
        f"2️⃣ Entrá como Bedel con el PIN del día\n"
        f"3️⃣ Buscá la sección \"🔗 Vincular Telegram\"\n"
        f"4️⃣ Ingresá este código: <code>{codigo}</code>\n\n"
        f"⏰ Vence en <b>10 minutos</b>",
        None
    )


def _cmd_bedel_mi_pin(tg_user_id) -> tuple:
    info = _bedel_telegram_buscar(tg_user_id)
    if not info:
        return ("⚠️ No estás vinculado. Mandá <code>/start</code> primero.", None)
    pin = generar_pin_diario(info['aula'], info['turno'])
    fecha_str = datetime.now().strftime('%A %d/%m/%Y').capitalize()
    return (
        f"🔑 <b>TU PIN DE HOY</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"📅 {fecha_str}\n"
        f"🏫 Aula <b>{_tg_esc(info['aula'])}</b> · Turno <b>{_tg_esc(info['turno'])}</b>\n\n"
        f"🔐 PIN: <code>{pin}</code>\n\n"
        f"<i>Compartilo con los docentes para que firmen su asistencia.\n"
        f"Cambia automáticamente cada día.</i>",
        None
    )


def _cmd_bedel_mi_aula(tg_user_id) -> tuple:
    info = _bedel_telegram_buscar(tg_user_id)
    if not info:
        return ("⚠️ No estás vinculado. Mandá <code>/start</code> primero.", None)
    aula, turno = info['aula'], info['turno']
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha::text, fe::int, presentes::int, cant_ausentes::int,
                       bedel, sub_bedel, novedades, ausentes_json
                FROM minutas WHERE aula=%s AND turno=%s
                ORDER BY fecha DESC LIMIT 1
            """, (aula, turno))
            row = cur.fetchone()
            cur.execute("""
                SELECT COUNT(*) FROM firmas_docentes
                WHERE aula=%s AND turno=%s AND fecha::date = CURRENT_DATE
            """, (aula, turno))
            firmas_hoy = cur.fetchone()[0]
        conn.close()
        lineas = [
            f"🏫 <b>TU AULA: {_tg_esc(aula)} ({_tg_esc(turno)})</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]
        if row:
            fecha, fe, pres, aus, bed, sub, nov, ausj = row
            pct = (100.0 * pres / fe) if fe else 0
            ico = _icono_asistencia(pct)
            lineas.append(f"📋 <b>Última minuta: {fecha}</b>")
            lineas.append(f"   F.E.: <b>{fe}</b> · Pres.: <b>{pres}</b> · Aus.: <b>{aus}</b> {ico}")
            lineas.append(f"   📊 {pct:.0f}% de asistencia")
            lineas.append("")
            lineas.append(f"👤 Bedel: {_tg_esc(bed) if bed else '—'}")
            if sub: lineas.append(f"👤 Sub:   {_tg_esc(sub)}")
            if nov and nov.strip():
                lineas.append(f"\n📝 <i>{_tg_esc(nov.strip()[:200])}</i>")
        else:
            lineas.append("<i>Sin minutas cargadas todavía.</i>")
        lineas.append("")
        lineas.append(f"✍️ Firmas docentes HOY: <b>{firmas_hoy}</b>")
        return ('\n'.join(lineas), None)
    except Exception as e:
        return (f"❌ Error: {e}", None)


def _cmd_bedel_mi_padron(tg_user_id) -> tuple:
    info = _bedel_telegram_buscar(tg_user_id)
    if not info:
        return ("⚠️ No estás vinculado. Mandá <code>/start</code> primero.", None)
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT grado, nombre FROM aspirantes
                WHERE aula=%s AND turno=%s ORDER BY nombre
            """, (info['aula'], info['turno']))
            filas = cur.fetchall()
        conn.close()
        if not filas:
            return (f"📋 <b>PADRÓN AULA {_tg_esc(info['aula'])} ({_tg_esc(info['turno'])})</b>\n\n<i>Sin aspirantes cargados.</i>", None)
        lineas = [
            f"📋 <b>PADRÓN AULA {_tg_esc(info['aula'])} ({_tg_esc(info['turno'])})</b>",
            f"Total: <b>{len(filas)}</b> aspirantes",
            "━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]
        for i, (grado, nombre) in enumerate(filas[:60], 1):
            g = f"{_tg_esc(grado)} " if grado else ''
            lineas.append(f"  {i}. {g}{_tg_esc(nombre)}")
        if len(filas) > 60:
            lineas.append(f"\n…y {len(filas) - 60} más.")
        return ('\n'.join(lineas), None)
    except Exception as e:
        return (f"❌ Error: {e}", None)


def _cmd_bedel_mi_cronograma(tg_user_id) -> tuple:
    info = _bedel_telegram_buscar(tg_user_id)
    if not info:
        return ("⚠️ No estás vinculado. Mandá <code>/start</code> primero.", None)
    # Reusamos _cmd_cronograma con su lógica
    texto = _cmd_cronograma(f"{info['aula']} {info['turno']}")
    return (texto, None)


def _cmd_bedel_link_pc(tg_user_id) -> tuple:
    """Genera un token de un solo uso para login automático en PC/celular."""
    if not _telegram_bedel_habilitado():
        return (
            "🔒 <b>Acceso por Telegram desactivado</b>\n\n"
            "Ingresá a Bedelía con el PIN diario del aula. "
            "La consulta del PIN por Telegram sigue disponible con <code>/mi_pin</code>.",
            None,
        )
    info = _bedel_telegram_buscar(tg_user_id)
    if not info:
        return ("⚠️ No estás vinculado. Mandá <code>/start</code> primero.", None)
    tok = _bedel_generar_token_login(tg_user_id, info['aula'], info['turno'])
    if not tok:
        return ("❌ No se pudo generar el token.", None)
    # URL: detectamos host desde request si está disponible
    host = request.host_url.rstrip('/') if request else 'http://192.168.0.10:5000'
    enlace = f"{host}/?bedel_token={tok}"
    return (
        f"🔗 <b>LOGIN MÁGICO</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
        f"Tu enlace de acceso (un solo uso):\n"
        f"{_tg_esc(enlace)}\n\n"
        f"🏫 Aula <b>{_tg_esc(info['aula'])}</b> · <b>{_tg_esc(info['turno'])}</b>\n"
        f"⏰ Vence en <b>5 minutos</b>\n\n"
        f"<i>Tocá el enlace para entrar al S.I.P.A.\n"
        f"sin tipear el PIN.</i>",
        None
    )


def _cmd_bedel_desvincular(tg_user_id) -> tuple:
    """Desvincula la cuenta de Telegram del Bedel."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE bedeles_telegram SET activo=FALSE
                WHERE telegram_user_id=%s
                RETURNING aula, turno
            """, (int(tg_user_id),))
            row = cur.fetchone()
        conn.commit()
        conn.close()
        if not row:
            return ("ℹ️ No estabas vinculado.", None)
        return (
            f"❌ <b>DESVINCULADO</b>\n\n"
            f"Ya no recibirás info de Aula {_tg_esc(row[0])} ({_tg_esc(row[1])}).\n"
            f"Para volver a vincularte: <code>/start</code>",
            None
        )
    except Exception as e:
        return (f"❌ Error: {e}", None)


# ─── HERRAMIENTAS TIC (BLOQUE 4) ────────────────────────────────────────────

def _asegurar_tablas_bloque4():
    """Crea tablas del bloque 4 si no existen (idempotente)."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS recordatorios_telegram (
                    id            SERIAL PRIMARY KEY,
                    fecha_objetivo TIMESTAMP NOT NULL,
                    mensaje       TEXT NOT NULL,
                    creado_por    VARCHAR(150),
                    creado_en     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    enviado       BOOLEAN DEFAULT FALSE,
                    enviado_en    TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS bot_comando_log (
                    id           SERIAL PRIMARY KEY,
                    fecha        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    comando      VARCHAR(60),
                    tg_user_id   BIGINT,
                    chat_id      VARCHAR(40),
                    es_privado   BOOLEAN,
                    ok           BOOLEAN DEFAULT TRUE,
                    error        TEXT
                )
            """)
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


def _log_bot_comando(comando, tg_user_id, chat_id, es_privado, ok=True, error=None):
    """Registra cada comando ejecutado para estadísticas."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO bot_comando_log (comando, tg_user_id, chat_id, es_privado, ok, error)
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (comando[:60], int(tg_user_id) if tg_user_id else None,
                  str(chat_id or '')[:40], bool(es_privado), bool(ok),
                  (error or '')[:500] if error else None))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _cmd_ping() -> str:
    """Test rápido: latencia DB + estado del bot."""
    try:
        t0 = _time_mod.perf_counter()
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchone()
        conn.close()
        db_ms = (_time_mod.perf_counter() - t0) * 1000
        return (
            f"🏓 <b>PONG</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n\n"
            f"⏱️ DB latency: <b>{db_ms:.1f} ms</b>\n"
            f"🤖 Bot: ✅ activo\n"
            f"🌐 Flask: ✅ activo\n"
            f"📡 SSE: ✅ activo\n\n"
            f"🕐 {datetime.now().strftime('%H:%M:%S')}"
        )
    except Exception as e:
        return f"❌ Pong falló: {e}"


def _cmd_logs(arg: str) -> str:
    """Últimos N logs del system_log. Default: nivel=ERROR, N=5."""
    partes = arg.strip().upper().split()
    nivel = 'ERROR'
    n = 5
    for p in partes:
        if p in ('INFO', 'WARN', 'WARNING', 'ERROR'):
            nivel = 'WARN' if p == 'WARNING' else p
        elif p.isdigit():
            n = min(int(p), 20)
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha::text, nivel, endpoint, mensaje
                FROM system_log
                WHERE nivel=%s
                ORDER BY fecha DESC LIMIT %s
            """, (nivel, n))
            filas = cur.fetchall()
        conn.close()
        if not filas:
            return f"📜 <b>LOGS {nivel}</b>\n\n✅ <i>Sin entradas recientes.</i>"
        icos = {'ERROR': '🔴', 'WARN': '🟡', 'INFO': '🔵'}
        ico = icos.get(nivel, '⚪')
        lineas = [f"{ico} <b>ÚLTIMOS {n} LOGS {nivel}</b>", "━━━━━━━━━━━━━━━━━━━━━━━", ""]
        for fecha, niv, ep, msj in filas:
            ts = (fecha or '')[:19].replace('T', ' ')
            lineas.append(f"<code>{ts}</code>")
            if ep: lineas.append(f"   📂 <i>{_tg_esc((ep or '')[:60])}</i>")
            lineas.append(f"   {_tg_esc((msj or '')[:200])}")
            lineas.append("")
        return '\n'.join(lineas).rstrip()
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_stats_bot() -> str:
    """Estadísticas de uso del bot (últimos 7 días)."""
    try:
        _asegurar_tablas_bloque4()
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT COUNT(*),
                       COUNT(*) FILTER (WHERE ok=TRUE),
                       COUNT(*) FILTER (WHERE ok=FALSE),
                       COUNT(DISTINCT tg_user_id)
                FROM bot_comando_log
                WHERE fecha >= NOW() - INTERVAL '7 days'
            """)
            tot, ok, err, usuarios = cur.fetchone() or (0, 0, 0, 0)
            cur.execute("""
                SELECT comando, COUNT(*) as c
                FROM bot_comando_log
                WHERE fecha >= NOW() - INTERVAL '7 days'
                GROUP BY comando ORDER BY c DESC LIMIT 5
            """)
            top = cur.fetchall()
            cur.execute("""
                SELECT COUNT(*) FROM bot_comando_log
                WHERE fecha::date = CURRENT_DATE
            """)
            hoy = cur.fetchone()[0]
        conn.close()
        lineas = [
            "🤖 <b>STATS DEL BOT (7 días)</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"📊 Comandos totales:  <b>{tot}</b>",
            f"✅ Exitosos:           <b>{ok}</b>",
            f"❌ Con error:          <b>{err}</b>",
            f"👥 Usuarios activos:   <b>{usuarios}</b>",
            f"📅 Hoy:                <b>{hoy}</b>",
            "",
        ]
        if top:
            lineas.append("🏆 <b>Top 5 comandos:</b>")
            for cmd, c in top:
                lineas.append(f"  • <code>{_tg_esc(cmd)}</code> — <b>{c}</b>")
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_dni(arg: str) -> str:
    """Búsqueda por DNI exacto."""
    dni = arg.strip()
    if not dni.isdigit() or len(dni) < 7:
        return "❓ Uso: <code>/dni 12345678</code>"
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT nombre, email, creado_en::text FROM docentes WHERE dni=%s
            """, (dni,))
            row = cur.fetchone()
        conn.close()
        if not row:
            return f"🔎 No se encontró ningún docente con DNI <code>{_tg_esc(dni)}</code>"
        nom, email, creado = row
        return (
            f"👤 <b>ENCONTRADO</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📛 {_tg_esc(nom)}\n"
            f"🆔 DNI: <code>{_tg_esc(dni)}</code>\n"
            f"📧 {_tg_esc(email) if email else '—'}\n"
            f"📅 Registrado: {(creado or '')[:10]}\n\n"
            f"<i>Para perfil completo:</i>\n"
            f"<code>/docente {_tg_esc(nom.split()[0] if nom else '')}</code>"
        )
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_dia(arg: str) -> str:
    """Resumen de un día específico. Formato: DD/MM/AAAA o YYYY-MM-DD."""
    s = arg.strip()
    fecha = None
    for fmt in ('%d/%m/%Y', '%Y-%m-%d', '%d-%m-%Y'):
        try:
            fecha = datetime.strptime(s, fmt).date()
            break
        except Exception:
            continue
    if not fecha:
        return "❓ Uso: <code>/dia DD/MM/AAAA</code>\nEj: <code>/dia 25/05/2026</code>"
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT aula, turno, fe::int, presentes::int, cant_ausentes::int, bedel
                FROM minutas WHERE fecha::date = %s
                ORDER BY aula, turno
            """, (fecha,))
            filas = cur.fetchall()
            cur.execute("""
                SELECT COUNT(*) FROM firmas_docentes WHERE fecha::date = %s
            """, (fecha,))
            firmas = cur.fetchone()[0]
        conn.close()
        dias = ['Lunes','Martes','Miércoles','Jueves','Viernes','Sábado','Domingo']
        fecha_str = f"{dias[fecha.weekday()]} {fecha.strftime('%d/%m/%Y')}"
        if not filas:
            return f"📅 <b>{fecha_str}</b>\n\n<i>Sin minutas cargadas ese día.</i>\n✍️ Firmas: <b>{firmas}</b>"
        total_fe = sum(r[2] or 0 for r in filas)
        total_pr = sum(r[3] or 0 for r in filas)
        total_au = sum(r[4] or 0 for r in filas)
        pct = (100.0 * total_pr / total_fe) if total_fe else 0
        lineas = [
            f"📅 <b>{fecha_str}</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"🏫 <b>{len(filas)}</b> aulas operativas",
            f"👥 F.E.: <b>{total_fe}</b> · Pres.: <b>{total_pr}</b> · Aus.: <b>{total_au}</b>",
            f"📊 Asistencia: <code>{_barra_progreso(pct, 16)}</code>",
            f"✍️ Firmas docentes: <b>{firmas}</b>",
            "",
            "📋 <b>Por aula:</b>",
        ]
        for aula, turno, fe, pr, au, bed in filas:
            pct_a = (100.0 * pr / fe) if fe else 0
            ico = _icono_asistencia(pct_a)
            lineas.append(f"  {ico} {_tg_esc(aula)} ({_tg_esc(turno)}) — <b>{pr}/{fe}</b> ({pct_a:.0f}%)")
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_buscar_novedad(arg: str) -> str:
    """Busca texto en las novedades de las minutas."""
    q = arg.strip()
    if len(q) < 3:
        return "❓ Uso: <code>/buscar_novedad TEXTO</code> (mínimo 3 caracteres)"
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT aula, turno, fecha::text, novedades
                FROM minutas
                WHERE novedades ILIKE %s
                ORDER BY fecha DESC LIMIT 10
            """, (f'%{q}%',))
            filas = cur.fetchall()
        conn.close()
        if not filas:
            return f"🔎 Sin resultados para <b>{_tg_esc(q)}</b> en las novedades."
        lineas = [f"🔎 <b>NOVEDADES con: {_tg_esc(q)}</b>", "━━━━━━━━━━━━━━━━━━━━━━━", ""]
        for aula, turno, fecha, nov in filas:
            lineas.append(f"📅 <b>{fecha}</b> · Aula {_tg_esc(aula)} ({_tg_esc(turno)})")
            # Resaltar el match (simple: muestra los 100 chars alrededor)
            n = (nov or '').strip()
            idx = n.lower().find(q.lower())
            if idx >= 0:
                ini = max(0, idx - 30)
                fin = min(len(n), idx + len(q) + 70)
                fragmento = ('…' if ini > 0 else '') + n[ini:fin] + ('…' if fin < len(n) else '')
                lineas.append(f"   <i>{_tg_esc(fragmento)}</i>")
            lineas.append("")
        return '\n'.join(lineas).rstrip()
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_recordar(arg: str) -> str:
    """Programa un recordatorio. Formato:
       /recordar DD/MM HH:MM Texto del recordatorio"""
    s = arg.strip()
    if not s:
        return (
            "❓ Uso: <code>/recordar DD/MM HH:MM TEXTO</code>\n\n"
            "Ej: <code>/recordar 05/06 09:00 Reunión PM</code>\n"
            "Ej: <code>/recordar mañana 08:00 Verificar PINs</code>"
        )
    # Parseo: primera y segunda token son fecha y hora, resto es mensaje
    partes = s.split(maxsplit=2)
    if len(partes) < 3:
        return "❓ Faltan argumentos. Usá: <code>/recordar DD/MM HH:MM TEXTO</code>"
    fecha_str, hora_str, mensaje = partes[0], partes[1], partes[2]
    hoy = date.today()
    fecha_obj = None
    if fecha_str.lower() in ('hoy', 'today'):
        fecha_obj = hoy
    elif fecha_str.lower() in ('mañana', 'manana', 'tomorrow'):
        fecha_obj = hoy + timedelta(days=1)
    else:
        for fmt in ('%d/%m', '%d/%m/%Y', '%Y-%m-%d', '%d-%m'):
            try:
                tmp = datetime.strptime(fecha_str, fmt).date()
                # Si el formato no tiene año, asumimos año actual
                if '%Y' not in fmt:
                    tmp = tmp.replace(year=hoy.year)
                fecha_obj = tmp
                break
            except Exception:
                continue
    if not fecha_obj:
        return f"❓ Fecha inválida: <code>{_tg_esc(fecha_str)}</code>"
    try:
        hora_obj = datetime.strptime(hora_str, '%H:%M').time()
    except Exception:
        return f"❓ Hora inválida: <code>{_tg_esc(hora_str)}</code>. Usá HH:MM (24h)."
    fecha_objetivo = datetime.combine(fecha_obj, hora_obj)
    if fecha_objetivo <= datetime.now():
        return "❓ La fecha/hora debe ser futura."
    try:
        _asegurar_tablas_bloque4()
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO recordatorios_telegram (fecha_objetivo, mensaje, creado_por)
                VALUES (%s, %s, 'TELEGRAM') RETURNING id
            """, (fecha_objetivo, mensaje[:1000]))
            rid = cur.fetchone()[0]
        conn.commit()
        conn.close()
        return (
            f"⏰ <b>RECORDATORIO PROGRAMADO</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🆔 <code>#{rid}</code>\n"
            f"📅 {fecha_objetivo.strftime('%A %d/%m/%Y · %H:%M')}\n"
            f"📝 <i>{_tg_esc(mensaje[:300])}</i>\n\n"
            f"<i>Te aviso por este grupo a la hora indicada.</i>"
        )
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_recordatorios() -> str:
    """Lista recordatorios pendientes."""
    try:
        _asegurar_tablas_bloque4()
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, fecha_objetivo::text, mensaje
                FROM recordatorios_telegram
                WHERE enviado=FALSE AND fecha_objetivo > NOW()
                ORDER BY fecha_objetivo LIMIT 10
            """)
            filas = cur.fetchall()
        conn.close()
        if not filas:
            return "⏰ <b>RECORDATORIOS PENDIENTES</b>\n\n<i>No hay recordatorios programados.</i>"
        lineas = ["⏰ <b>RECORDATORIOS PENDIENTES</b>", "━━━━━━━━━━━━━━━━━━━━━━━", ""]
        for rid, fobj, msj in filas:
            lineas.append(f"  <code>#{rid}</code> · <b>{(fobj or '')[:16].replace('T', ' ')}</b>")
            lineas.append(f"     <i>{_tg_esc((msj or '')[:120])}</i>")
            lineas.append("")
        lineas.append("<i>Para cancelar uno: <code>/cancelar_recordatorio N</code></i>")
        return '\n'.join(lineas).rstrip()
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_cancelar_recordatorio(arg: str) -> str:
    """Cancela un recordatorio por ID."""
    arg = arg.strip().lstrip('#')
    if not arg.isdigit():
        return "❓ Uso: <code>/cancelar_recordatorio N</code>"
    rid = int(arg)
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM recordatorios_telegram
                WHERE id=%s AND enviado=FALSE
                RETURNING mensaje
            """, (rid,))
            row = cur.fetchone()
        conn.commit()
        conn.close()
        if not row:
            return f"⚠️ No hay un recordatorio pendiente con ID <code>#{rid}</code>."
        return f"❌ Recordatorio <code>#{rid}</code> cancelado.\n<i>{_tg_esc((row[0] or '')[:100])}</i>"
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_plantillas() -> tuple:
    """Lista de plantillas de mensajes frecuentes con botones."""
    texto = (
        "📋 <b>PLANTILLAS DE MENSAJES</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "Tocá una plantilla para enviarla al grupo:"
    )
    botones = [
        [{'text': '🌧️ Aviso lluvia',     'callback_data': 'plant:lluvia'}],
        [{'text': '📅 Feriado mañana',   'callback_data': 'plant:feriado'}],
        [{'text': '🏆 Acto/ceremonia',   'callback_data': 'plant:acto'}],
        [{'text': '🛠️ Sin servicios',    'callback_data': 'plant:sin_serv'}],
        [{'text': '👮 Inspección',       'callback_data': 'plant:inspec'}],
        [{'text': '✅ Operativa normal', 'callback_data': 'plant:normal'}],
    ]
    return (texto, botones)


_PLANTILLAS_TEXTOS = {
    'lluvia':   ("🌧️ <b>AVISO POR LLUVIA</b>\n\nPor mal tiempo, los aspirantes permanecen en sus aulas durante el receso. "
                 "Solicito a los Bedeles reforzar el control de asistencia."),
    'feriado':  ("📅 <b>FERIADO MAÑANA</b>\n\nRecordatorio: mañana es feriado nacional. "
                 "No hay clases programadas. Bedeles y Plana Mayor: no es necesario presentarse."),
    'acto':     ("🏆 <b>ACTO/CEREMONIA</b>\n\nSe convoca a Plana Mayor y Bedeles para la formación. "
                 "Uniforme de gala. Presentación 30 min antes."),
    'sin_serv': ("🛠️ <b>SIN SERVICIOS</b>\n\nPor mantenimiento, el sistema estará INACTIVO. "
                 "Los Bedeles deben registrar la asistencia en papel y cargarla al volver la conexión."),
    'inspec':   ("👮 <b>INSPECCIÓN PROGRAMADA</b>\n\nSe realizará inspección. "
                 "Bedeles: tener al día las firmas y novedades."),
    'normal':   ("✅ <b>OPERATIVA NORMAL</b>\n\nSistemas operativos al 100%. Sin novedades.\nBuen turno a todos."),
}


def _cmd_perfil(tg_user_id, tg_username, tg_nombre, chat_type) -> str:
    """Muestra info del usuario que envió el comando."""
    try:
        info_bedel = _bedel_telegram_buscar(tg_user_id)
        rol = "🎓 <b>Bedel vinculado</b>" if info_bedel else "👤 Usuario sin vincular"
        contexto = "🔒 Privado" if chat_type == 'private' else "👥 Grupo Plana Mayor"
        lineas = [
            "👤 <b>TU PERFIL</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"📛 Nombre TG:  <b>{_tg_esc(tg_nombre or '—')}</b>",
            f"🔖 Username:   <b>@{_tg_esc(tg_username) if tg_username else '—'}</b>",
            f"🆔 User ID:    <code>{tg_user_id}</code>",
            f"🎯 Rol:        {rol}",
            f"📍 Contexto:   {contexto}",
        ]
        if info_bedel:
            lineas.append("")
            lineas.append(f"🏫 Tu aula: <b>{_tg_esc(info_bedel['aula'])} ({_tg_esc(info_bedel['turno'])})</b>")
        # Stats de comandos del usuario
        try:
            conn = get_db()
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT COUNT(*) FROM bot_comando_log
                    WHERE tg_user_id=%s AND fecha >= NOW() - INTERVAL '7 days'
                """, (int(tg_user_id),))
                cnt = cur.fetchone()[0]
            conn.close()
            lineas.append(f"\n📊 Tus comandos (7d): <b>{cnt}</b>")
        except Exception:
            pass
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error: {e}"


# ─── HELPERS DE GRÁFICOS PNG (BLOQUE 2) ────────────────────────────────────

def _bot_enviar_foto(token: str, chat_id, png_bytes: bytes, caption: str = '') -> bool:
    """Sube una imagen PNG al chat configurado con caption opcional. Usa multipart/form-data."""
    try:
        boundary = '----SIPA' + secrets.token_hex(8)
        sep = f'--{boundary}\r\n'.encode()
        body = b''
        body += sep + b'Content-Disposition: form-data; name="chat_id"\r\n\r\n' + str(chat_id).encode() + b'\r\n'
        body += sep + b'Content-Disposition: form-data; name="parse_mode"\r\n\r\nHTML\r\n'
        if caption:
            body += sep + b'Content-Disposition: form-data; name="caption"\r\n\r\n' + caption[:1024].encode('utf-8') + b'\r\n'
        body += sep + b'Content-Disposition: form-data; name="photo"; filename="grafico.png"\r\n'
        body += b'Content-Type: image/png\r\n\r\n' + png_bytes + b'\r\n'
        body += f'--{boundary}--\r\n'.encode()
        url = f"https://api.telegram.org/bot{token}/sendPhoto"
        req = _urlreq.Request(url, data=body, method='POST',
                              headers={'Content-Type': f'multipart/form-data; boundary={boundary}'})
        with _urlreq.urlopen(req, timeout=15) as resp:
            return b'"ok":true' in resp.read()
    except Exception as e:
        try: _log_system('ERROR', f'[telegram] sendPhoto falló: {e}')
        except Exception: pass
        return False


def _matplotlib_setup():
    """Importa matplotlib en modo headless con configuración consistente."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({
        'font.size': 11,
        'axes.titlesize': 14,
        'axes.labelsize': 11,
        'axes.spines.top': False,
        'axes.spines.right': False,
        'axes.grid': True,
        'grid.alpha': 0.3,
        'figure.facecolor': 'white',
    })
    return plt


def _grafico_semana_png() -> bytes:
    """Gráfico de barras: asistencia por día de la última semana."""
    plt = _matplotlib_setup()
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT fecha::date,
                       COALESCE(SUM(fe::int), 0) as fe,
                       COALESCE(SUM(presentes::int), 0) as pres,
                       COALESCE(SUM(cant_ausentes::int), 0) as aus
                FROM minutas WHERE fecha::date >= CURRENT_DATE - 6
                GROUP BY fecha::date ORDER BY fecha::date
            """)
            filas = cur.fetchall()
        conn.close()
    finally:
        pass

    fechas = [f[0].strftime('%a %d/%m') for f in filas]
    pres   = [f[2] for f in filas]
    aus    = [f[3] for f in filas]
    fig, ax = plt.subplots(figsize=(10, 5.5))
    x = range(len(fechas))
    ax.bar(x, pres, label='Presentes', color='#16a34a', edgecolor='white')
    ax.bar(x, aus, bottom=pres, label='Ausentes', color='#dc2626', edgecolor='white')
    for i, (p, a) in enumerate(zip(pres, aus)):
        if p > 0:
            ax.text(i, p / 2, str(p), ha='center', va='center', color='white', fontweight='bold', fontsize=10)
        if a > 0:
            ax.text(i, p + a / 2, str(a), ha='center', va='center', color='white', fontweight='bold', fontsize=10)
    ax.set_xticks(x)
    ax.set_xticklabels(fechas, rotation=20, ha='right')
    ax.set_title('Asistencia diaria — últimos 7 días\nS.I.P.A. · Escuela Cbo. Cuello',
                 fontweight='bold', pad=14)
    ax.set_ylabel('Cantidad de aspirantes')
    ax.legend(loc='upper left', frameon=False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=110, bbox_inches='tight')
    plt.close(fig)
    return buf.getvalue()


def _grafico_aulas_png() -> bytes:
    """Gráfico horizontal: % asistencia por aula (últimos 30 días)."""
    plt = _matplotlib_setup()
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT aula,
                   COALESCE(SUM(fe::int), 0) as fe,
                   COALESCE(SUM(presentes::int), 0) as pres
            FROM minutas WHERE fecha::date >= CURRENT_DATE - 29
            GROUP BY aula ORDER BY aula
        """)
        filas = cur.fetchall()
    conn.close()

    aulas = [str(f[0]) for f in filas]
    pcts  = [(100.0 * f[2] / f[1]) if f[1] else 0 for f in filas]
    # Color según pct
    colores = ['#dc2626' if p < 60 else '#f59e0b' if p < 75 else '#16a34a' if p < 90 else '#0e7c5a' for p in pcts]

    fig, ax = plt.subplots(figsize=(10, max(4, 0.55 * len(aulas) + 2)))
    bars = ax.barh(aulas, pcts, color=colores, edgecolor='white')
    for bar, p in zip(bars, pcts):
        ax.text(bar.get_width() + 1, bar.get_y() + bar.get_height() / 2,
                f'{p:.0f}%', va='center', fontweight='bold', fontsize=10)
    ax.set_xlim(0, 110)
    ax.set_xlabel('% Asistencia')
    ax.set_ylabel('Aula')
    ax.invert_yaxis()
    ax.set_title('Asistencia por aula — últimos 30 días\nS.I.P.A. · Escuela Cbo. Cuello',
                 fontweight='bold', pad=14)
    ax.axvline(70, color='#ef4444', linestyle='--', alpha=0.4, label='Umbral 70%')
    ax.legend(loc='lower right', frameon=False)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=110, bbox_inches='tight')
    plt.close(fig)
    return buf.getvalue()


def _grafico_mes_png() -> bytes:
    """Línea de tendencia diaria de % asistencia del mes."""
    plt = _matplotlib_setup()
    hoy = date.today()
    primer = hoy.replace(day=1)
    conn = get_db()
    with conn.cursor() as cur:
        cur.execute("""
            SELECT fecha::date,
                   COALESCE(SUM(fe::int), 0) as fe,
                   COALESCE(SUM(presentes::int), 0) as pres
            FROM minutas WHERE fecha::date >= %s AND fecha::date <= %s
            GROUP BY fecha::date ORDER BY fecha::date
        """, (primer, hoy))
        filas = cur.fetchall()
    conn.close()

    fechas = [f[0] for f in filas]
    pcts   = [(100.0 * f[2] / f[1]) if f[1] else 0 for f in filas]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    if fechas:
        ax.plot(fechas, pcts, marker='o', color='#0ea5e9', linewidth=2.4, markersize=7)
        ax.fill_between(fechas, pcts, alpha=0.18, color='#0ea5e9')
        ax.axhline(70, color='#ef4444', linestyle='--', alpha=0.5, label='Umbral 70%')
        ax.axhline(sum(pcts) / len(pcts), color='#16a34a', linestyle=':', alpha=0.5,
                   label=f'Promedio {sum(pcts)/len(pcts):.1f}%')
        ax.legend(loc='lower left', frameon=False)
    ax.set_ylim(0, 105)
    ax.set_ylabel('% Asistencia')
    meses = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
             'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
    ax.set_title(f'Tendencia diaria — {meses[primer.month-1]} {primer.year}\nS.I.P.A. · Escuela Cbo. Cuello',
                 fontweight='bold', pad=14)
    fig.autofmt_xdate(rotation=30)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=110, bbox_inches='tight')
    plt.close(fig)
    return buf.getvalue()


def _cmd_grafico(arg: str) -> tuple:
    """Genera un gráfico PNG y lo envía como imagen al grupo.
    Tipos: semana (default), aulas, mes."""
    tipo = (arg.strip().lower() or 'semana')
    if tipo not in ('semana', 'aulas', 'mes'):
        return ("❓ Uso: <code>/grafico TIPO</code>\nTipos: <code>semana</code>, <code>aulas</code>, <code>mes</code>", None)
    try:
        cfg = _telegram_config_actual()
        if not cfg:
            return ("❌ Telegram no configurado.", None)
        if tipo == 'semana':
            png = _grafico_semana_png()
            cap = "📊 <b>Asistencia diaria — últimos 7 días</b>"
        elif tipo == 'aulas':
            png = _grafico_aulas_png()
            cap = "🏫 <b>% Asistencia por aula — 30 días</b>"
        else:
            png = _grafico_mes_png()
            cap = "📈 <b>Tendencia diaria del mes</b>"
        ok = _bot_enviar_foto(cfg['token'], cfg['chat_id'], png, cap)
        if ok:
            # No retornamos texto: la foto YA fue enviada
            return ('', None)
        else:
            return ("❌ No se pudo enviar la imagen a Telegram.", None)
    except Exception as e:
        return (f"❌ Error generando gráfico: {e}", None)


# ─── COMANDOS COMPARATIVAS Y RANKINGS (BLOQUE 2) ──────────────────────────

def _cmd_comparar(arg: str) -> str:
    """Compara dos aulas lado a lado (últimos 7 días)."""
    partes = arg.strip().upper().split()
    if len(partes) < 2:
        return "❓ Uso: <code>/comparar AULA1 AULA2</code>\n   Ej: <code>/comparar 25 32</code>"
    a1, a2 = partes[0], partes[1]
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT aula,
                       COUNT(*) as minutas,
                       COALESCE(SUM(fe::int), 0)            as fe_tot,
                       COALESCE(SUM(presentes::int), 0)     as pres_tot,
                       COALESCE(SUM(cant_ausentes::int), 0) as aus_tot
                FROM minutas
                WHERE aula IN (%s, %s) AND fecha::date >= CURRENT_DATE - 6
                GROUP BY aula
            """, (a1, a2))
            datos = {r[0]: r for r in cur.fetchall()}
        conn.close()
        d1 = datos.get(a1, (a1, 0, 0, 0, 0))
        d2 = datos.get(a2, (a2, 0, 0, 0, 0))
        pct1 = (100.0 * d1[3] / d1[2]) if d1[2] else 0
        pct2 = (100.0 * d2[3] / d2[2]) if d2[2] else 0
        ico1 = _icono_asistencia(pct1)
        ico2 = _icono_asistencia(pct2)
        # Determinar ganador
        if pct1 > pct2:   veredicto = f"🏆 <b>Aula {_tg_esc(a1)}</b> tiene mejor asistencia"
        elif pct2 > pct1: veredicto = f"🏆 <b>Aula {_tg_esc(a2)}</b> tiene mejor asistencia"
        else:             veredicto = "🤝 Empate"
        return (
            f"⚖️ <b>COMPARATIVA — últimos 7 días</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<pre>"
            f"               Aula {a1:>3}    Aula {a2:>3}\n"
            f"Minutas      {d1[1]:>8}{d2[1]:>12}\n"
            f"F.E. acum.   {d1[2]:>8}{d2[2]:>12}\n"
            f"Presentes    {d1[3]:>8}{d2[3]:>12}\n"
            f"Ausentes     {d1[4]:>8}{d2[4]:>12}\n"
            f"% asist.    {pct1:>7.1f}%{pct2:>11.1f}%\n"
            f"</pre>"
            f"\n{ico1} Aula {_tg_esc(a1)}     {ico2} Aula {_tg_esc(a2)}\n\n"
            f"{veredicto}"
        )
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_vs_mes() -> str:
    """Compara mes actual con mes anterior."""
    try:
        hoy = date.today()
        # Mes actual: día 1 → hoy
        primer_actual = hoy.replace(day=1)
        # Mes anterior: día 1 del mes anterior → último día del mes anterior
        if primer_actual.month == 1:
            primer_anterior = primer_actual.replace(year=primer_actual.year - 1, month=12)
        else:
            primer_anterior = primer_actual.replace(month=primer_actual.month - 1)
        ultimo_anterior = primer_actual - timedelta(days=1)

        conn = get_db()
        with conn.cursor() as cur:
            def stats(desde, hasta):
                cur.execute("""
                    SELECT COUNT(*), COALESCE(SUM(fe::int),0),
                           COALESCE(SUM(presentes::int),0), COALESCE(SUM(cant_ausentes::int),0)
                    FROM minutas WHERE fecha::date BETWEEN %s AND %s
                """, (desde, hasta))
                return cur.fetchone()
            act = stats(primer_actual, hoy)
            ant = stats(primer_anterior, ultimo_anterior)
            # Mejor docente actual
            cur.execute("""
                SELECT docente, COUNT(*) FROM firmas_docentes
                WHERE fecha::date >= %s AND fecha::date <= %s
                GROUP BY docente ORDER BY 2 DESC LIMIT 1
            """, (primer_actual, hoy))
            top_doc = cur.fetchone()
        conn.close()

        meses = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                 'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
        nm_act = meses[primer_actual.month - 1]
        nm_ant = meses[primer_anterior.month - 1]

        def delta(a, b):
            if not b:
                return ('—', '')
            d = a - b
            pct = 100.0 * d / b
            arrow = '⬆️' if d > 0 else '⬇️' if d < 0 else '➡️'
            return (f"{arrow} {pct:+.1f}%", arrow)

        d_min, _ = delta(act[0], ant[0])
        d_pres, _ = delta(act[2], ant[2])
        d_aus,  _ = delta(act[3], ant[3])
        pct_act = (100.0 * act[2] / act[1]) if act[1] else 0
        pct_ant = (100.0 * ant[2] / ant[1]) if ant[1] else 0
        d_pct = pct_act - pct_ant
        arrow_pct = '⬆️' if d_pct > 0 else '⬇️' if d_pct < 0 else '➡️'

        return (
            f"📊 <b>COMPARATIVA MENSUAL</b>\n"
            f"<i>{nm_act} {primer_actual.year} vs {nm_ant} {primer_anterior.year}</i>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"<pre>"
            f"              {nm_ant[:3]:<8}{nm_act[:3]:<8}Δ\n"
            f"Minutas    {ant[0]:>7}{act[0]:>8}  {d_min}\n"
            f"F.E.       {ant[1]:>7}{act[1]:>8}\n"
            f"Presentes  {ant[2]:>7}{act[2]:>8}  {d_pres}\n"
            f"Ausentes   {ant[3]:>7}{act[3]:>8}  {d_aus}\n"
            f"% asist.  {pct_ant:>6.1f}%{pct_act:>7.1f}%  {arrow_pct} {d_pct:+.1f}pp\n"
            f"</pre>"
            + (f"\n🏆 <b>Top docente {nm_act}:</b> {_tg_esc(top_doc[0])} ({top_doc[1]} firmas)" if top_doc else '')
        )
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_heatmap() -> str:
    """Mapa de calor por aula — últimos 30 días."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT aula,
                       COALESCE(SUM(fe::int), 0)        as fe,
                       COALESCE(SUM(presentes::int), 0) as pres,
                       COUNT(*) as minutas
                FROM minutas WHERE fecha::date >= CURRENT_DATE - 29
                GROUP BY aula ORDER BY aula
            """)
            filas = cur.fetchall()
        conn.close()
        if not filas:
            return "🔥 <b>HEATMAP</b>\n\n<i>Sin datos en los últimos 30 días.</i>"
        # Calcular pct y ordenar por peor a mejor para destacar problemas
        registros = []
        for aula, fe, pres, mins in filas:
            pct = (100.0 * pres / fe) if fe else 0
            registros.append((aula, pres, fe, mins, pct))
        registros.sort(key=lambda x: x[4])
        lineas = [
            "🔥 <b>HEATMAP DE ASISTENCIA</b>",
            "<i>Últimos 30 días, peor → mejor</i>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]
        # Aulas problemáticas primero
        criticas = [r for r in registros if r[4] < 70]
        if criticas:
            lineas.append("🚨 <b>CRÍTICAS (&lt; 70%)</b>")
            for aula, pres, fe, mins, pct in criticas:
                barra = _barra_progreso(pct, 12)
                lineas.append(f"  🔴 Aula <b>{_tg_esc(aula)}</b>")
                lineas.append(f"     <code>{barra}</code> ({mins} minutas)")
            lineas.append("")
        # Resto agrupado
        normales = [r for r in registros if r[4] >= 70]
        if normales:
            lineas.append("✅ <b>NORMAL/BUENO (&gt;= 70%)</b>")
            for aula, pres, fe, mins, pct in normales:
                ico = _icono_asistencia(pct)
                barra = _barra_progreso(pct, 12)
                lineas.append(f"  {ico} Aula <b>{_tg_esc(aula)}</b>")
                lineas.append(f"     <code>{barra}</code> ({mins} minutas)")
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_faltas_top() -> str:
    """Top 10 docentes con mayor tasa de ausencias (faltas/programadas)."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                WITH clases_recientes AS (
                    SELECT b->>'doc' as docente, COUNT(*) as programadas
                    FROM cronograma_maestro cm,
                         jsonb_array_elements(cm.config_json::jsonb) b
                    WHERE b->>'doc' != ''
                    GROUP BY b->>'doc'
                ),
                firmas_recientes AS (
                    SELECT docente, COUNT(*) as firmas
                    FROM firmas_docentes
                    WHERE fecha::date >= CURRENT_DATE - 29
                    GROUP BY docente
                )
                SELECT cr.docente,
                       cr.programadas,
                       COALESCE(fr.firmas, 0) as firmadas
                FROM clases_recientes cr
                LEFT JOIN firmas_recientes fr ON LOWER(cr.docente) = LOWER(fr.docente)
                WHERE cr.programadas >= 3
                ORDER BY (cr.programadas - COALESCE(fr.firmas, 0)) DESC,
                         cr.programadas DESC
                LIMIT 10
            """)
            filas = cur.fetchall()
        conn.close()
        if not filas:
            return "📉 <b>TOP AUSENTISMOS</b>\n\n<i>Sin datos disponibles.</i>"
        lineas = [
            "📉 <b>TOP AUSENTISMOS (30 días)</b>",
            "<i>Docentes con más clases sin firmar</i>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
        ]
        medallas = ['🔴','🟠','🟡'] + ['  '] * 7
        for i, (doc, prog, firm) in enumerate(filas):
            faltas = prog - firm
            pct_aus = (100.0 * faltas / prog) if prog else 0
            ico = medallas[i] if i < len(medallas) else '  '
            lineas.append(f"{ico} <b>{_tg_esc((doc or '')[:38])}</b>")
            lineas.append(f"     ❌ <b>{faltas}</b> faltas / {prog} clases ({pct_aus:.0f}%)")
            lineas.append("")
        return '\n'.join(lineas).rstrip()
    except Exception as e:
        return f"❌ Error: {e}"


# ─── COMANDOS DE ACCIÓN (BLOQUE 1) ────────────────────────────────────────

def _cmd_pin_temp(arg: str) -> tuple:
    """Genera un PIN temporal para un aula+turno por 30 minutos."""
    partes = arg.strip().upper().split()
    if len(partes) < 2:
        return ("❓ Uso: <code>/pin_temp AULA TURNO</code>\n   Ej: <code>/pin_temp 25 TM</code>", None)
    aula, turno = partes[0], partes[1]
    if turno not in ('TM', 'TT'):
        return ("⚠️ Turno inválido. Usá TM o TT.", None)
    # Genera PIN de 4 dígitos aleatorio
    pin = str(secrets.randbelow(10000)).zfill(4)
    hoy = date.today().isoformat()
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO pin_overrides (aula, turno, fecha, pin_nuevo, motivo)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (aula, turno, fecha) DO UPDATE
                SET pin_nuevo = EXCLUDED.pin_nuevo, motivo = EXCLUDED.motivo
            """, (aula, turno, hoy, pin, 'PIN temporal desde Telegram'))
        conn.commit()
        conn.close()
        _log_audit('TELEGRAM', 'tic', 'PIN_TEMP', 'pin_overrides',
                   f'aula={aula} turno={turno}', f'pin={pin}')
        texto = (
            f"🔐 <b>PIN TEMPORAL GENERADO</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🏫 Aula: <b>{_tg_esc(aula)}</b>\n"
            f"⏰ Turno: <b>{_tg_esc(turno)}</b>\n"
            f"🔑 Código: <code>{pin}</code>\n\n"
            f"📅 Hoy {datetime.now().strftime('%H:%M')}\n"
            f"⚠️ Sobrescribe el PIN automático del día."
        )
        return (texto, None)
    except Exception as e:
        return (f"❌ Error: {e}", None)


def _cmd_mantenimiento(arg: str) -> tuple:
    """Activa o desactiva el modo mantenimiento."""
    accion = arg.strip().lower()
    if accion not in ('on', 'off', 'activar', 'desactivar'):
        # Si no se pasa argumento, mostramos estado actual con botones
        try:
            p = _cargar_params()
            activo = (p.get('modo_mantenimiento', {}).get('valor') or '0') == '1'
            estado = 'ACTIVADO 🟢' if activo else 'DESACTIVADO 🔴'
            texto = (
                f"🛠️ <b>MODO MANTENIMIENTO</b>\n\n"
                f"Estado actual: <b>{estado}</b>\n\n"
                f"<i>Cuando está activo, bloquea a Plana Mayor, Bedeles y Docentes. Solo TIC opera.</i>"
            )
            if activo:
                botones = [[{'text': '🔓 Desactivar Mantenimiento', 'callback_data': 'mantto_off'}]]
            else:
                botones = [[{'text': '🛠️ Activar Mantenimiento', 'callback_data': 'mantto_on_confirm'}]]
            return (texto, botones)
        except Exception as e:
            return (f"❌ Error: {e}", None)
    nuevo = '1' if accion in ('on', 'activar') else '0'
    return (_aplicar_mantenimiento(nuevo), None)


def _aplicar_mantenimiento(valor: str) -> str:
    """Aplica el cambio de modo mantenimiento."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO config_sistema (clave, valor, descripcion, actualizado)
                VALUES ('modo_mantenimiento', %s, '', CURRENT_TIMESTAMP)
                ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor, actualizado=CURRENT_TIMESTAMP
            """, (valor,))
        conn.commit()
        conn.close()
        _log_audit('TELEGRAM', 'tic', 'MANTENIMIENTO', 'config_sistema',
                   'modo_mantenimiento', f'valor={valor}')
        if valor == '1':
            return (
                "⚠️ <b>MODO MANTENIMIENTO ACTIVADO</b>\n\n"
                "🔒 Bedeles y Docentes BLOQUEADOS.\n"
                "🛡️ Solo TIC opera.\n\n"
                "Para desactivar: <code>/mantenimiento off</code>"
            )
        return (
            "✅ <b>MODO MANTENIMIENTO DESACTIVADO</b>\n\n"
            "🟢 Sistema operativo para todos.\n"
            "🔓 Bedeles y Docentes pueden trabajar."
        )
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_backup_ahora() -> tuple:
    """Genera un backup manual del sistema y lo notifica."""
    try:
        path = _generar_backup_archivo()
        nombre = os.path.basename(path) if path else 'backup.json'
        try:
            tamanio = os.path.getsize(path) / 1024
        except Exception:
            tamanio = 0
        _log_audit('TELEGRAM', 'tic', 'BACKUP_MANUAL', None, nombre)
        return (
            f"💾 <b>BACKUP GENERADO</b>\n\n"
            f"📦 Archivo: <code>{_tg_esc(nombre)}</code>\n"
            f"📏 Tamaño: <b>{tamanio:.1f} KB</b>\n"
            f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n\n"
            f"✅ Guardado en <code>/backups/</code>\n"
            f"<i>Descargá desde el panel TIC → Peligro → Backups.</i>",
            None
        )
    except Exception as e:
        return (f"❌ Error al generar backup: {e}", None)


def _cmd_reset_doc(arg: str) -> tuple:
    """Resetea la contraseña de un docente. Pide confirmación con botones."""
    email = arg.strip().lower()
    if '@' not in email:
        return ("❓ Uso: <code>/reset_doc EMAIL</code>\n   Ej: <code>/reset_doc jlopez@gna.gob.ar</code>", None)
    # Verificar que el docente existe
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT nombre FROM docentes WHERE email=%s", (email,))
            row = cur.fetchone()
        conn.close()
        if not row:
            return (f"🔎 No se encontró ningún docente con email <code>{_tg_esc(email)}</code>.", None)
        nombre = row[0]
        texto = (
            f"⚠️ <b>CONFIRMAR RESET DE PASSWORD</b>\n\n"
            f"👨‍🏫 Docente: <b>{_tg_esc(nombre)}</b>\n"
            f"📧 Email: <code>{_tg_esc(email)}</code>\n\n"
            f"Se generará una nueva contraseña temporal.\n"
            f"<i>El docente deberá avisarse personalmente.</i>"
        )
        botones = [[
            {'text': '✅ Confirmar reset', 'callback_data': f'reset_doc_ok:{email}'},
            {'text': '❌ Cancelar', 'callback_data': 'cancelar'}
        ]]
        return (texto, botones)
    except Exception as e:
        return (f"❌ Error: {e}", None)


def _aplicar_reset_doc(email: str) -> str:
    """Ejecuta el reset de password del docente."""
    try:
        # Generamos password temporal legible: Sipa-XXXX
        nueva = f"Sipa-{secrets.token_hex(3)}"
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE docentes SET password_hash=%s WHERE email=%s
                RETURNING nombre
            """, (hash_password(nueva), email))
            row = cur.fetchone()
        conn.commit()
        conn.close()
        if not row:
            return f"🔎 No se encontró el docente <code>{_tg_esc(email)}</code>."
        _log_audit('TELEGRAM', 'tic', 'RESET_PASSWORD_DOCENTE', 'docentes', email)
        return (
            f"🔓 <b>PASSWORD RESETEADO</b>\n\n"
            f"👨‍🏫 <b>{_tg_esc(row[0])}</b>\n"
            f"📧 <code>{_tg_esc(email)}</code>\n\n"
            f"🔐 Nueva clave temporal:\n"
            f"<code>{_tg_esc(nueva)}</code>\n\n"
            f"⚠️ <i>Avisar al docente. Tendrá que cambiarla.</i>"
        )
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_aula(arg: str) -> str:
    """Info del aula indicada. Acepta '25' o '25 TM'."""
    partes = arg.strip().upper().split()
    if not partes:
        return "❓ Uso: <code>/aula NUMERO</code>  (ej: <code>/aula 25</code>)"
    aula = partes[0]
    turno_filtro = partes[1] if len(partes) > 1 and partes[1] in ('TM','TT') else None
    try:
        conn = get_db()
        with conn.cursor() as cur:
            if turno_filtro:
                cur.execute("""
                    SELECT fecha::text, turno, fe, presentes, cant_ausentes, bedel, sub_bedel, novedades
                    FROM minutas WHERE aula=%s AND turno=%s ORDER BY fecha DESC LIMIT 1
                """, (aula, turno_filtro))
            else:
                cur.execute("""
                    SELECT fecha::text, turno, fe, presentes, cant_ausentes, bedel, sub_bedel, novedades
                    FROM minutas WHERE aula=%s ORDER BY fecha DESC, turno DESC LIMIT 2
                """, (aula,))
            filas = cur.fetchall()
        conn.close()
        if not filas:
            return f"🏫 Aula <b>{aula}</b>: sin minutas registradas."
        lineas = [f"🏫 <b>AULA {_tg_esc(aula)}</b> — últimas minutas\n"]
        for fecha, turno, fe, pr, au, bed, sub, nov in filas:
            icono = '✅' if (au or 0) == 0 else '⚠️'
            lineas.append(f"📅 <b>{fecha} {turno}</b> {icono}")
            lineas.append(f"   F.E. {fe} · Pres. {pr} · Aus. {au}")
            lineas.append(f"   👤 Bedel: {_tg_esc(bed) if bed else '—'}")
            if sub: lineas.append(f"   👤 Sub:   {_tg_esc(sub)}")
            if nov and nov.strip():
                lineas.append(f"   📝 {_tg_esc(nov.strip()[:120])}")
            lineas.append("")
        return '\n'.join(lineas).rstrip()
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_ausentes() -> str:
    """Ausentes de hoy (de todas las aulas)."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT aula, turno, ausentes_json
                FROM minutas WHERE fecha::date = CURRENT_DATE AND cant_ausentes > 0
                ORDER BY aula, turno
            """)
            filas = cur.fetchall()
        conn.close()
        if not filas:
            return "📅 <b>AUSENTES HOY</b>\n\n✅ <i>Sin ausencias registradas.</i>"
        lineas = [f"❌ <b>AUSENTES HOY</b> — {datetime.now().strftime('%d/%m/%Y')}\n"]
        total = 0
        for aula, turno, aus_json in filas:
            if isinstance(aus_json, str):
                try:    aus_json = json.loads(aus_json)
                except: continue
            if not isinstance(aus_json, list) or not aus_json: continue
            lineas.append(f"🏫 <b>Aula {_tg_esc(aula)} ({_tg_esc(turno)})</b>")
            for a in aus_json[:20]:
                if not isinstance(a, dict): continue
                tipo  = (a.get('tipo')  or '').strip()
                nom   = (a.get('nombre') or '').strip()
                causa = (a.get('causa')  or 'Sin justificar').strip()
                pre = f"{_tg_esc(tipo)} " if tipo else ''
                lineas.append(f"  • {pre}{_tg_esc(nom)} — <i>{_tg_esc(causa)}</i>")
                total += 1
            lineas.append("")
        lineas.append(f"📊 <b>Total: {total} ausencias</b>")
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_foja(arg: str) -> str:
    """Foja de asistencia de un docente (últimas 10 firmas)."""
    apellido = arg.strip().upper()
    if not apellido:
        return "❓ Uso: <code>/foja APELLIDO</code>  (ej: <code>/foja LOPEZ</code>)"
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT docente, fecha::text, aula, turno, hora_firma::text
                FROM firmas_docentes
                WHERE UPPER(docente) LIKE %s
                ORDER BY fecha DESC, hora_firma DESC
                LIMIT 10
            """, (f'%{apellido}%',))
            filas = cur.fetchall()
        conn.close()
        if not filas:
            return f"🔎 No se encontraron firmas para <b>{_tg_esc(apellido)}</b>."
        lineas = [f"👨‍🏫 <b>FOJA DE {_tg_esc(apellido)}</b> — últimas 10 firmas\n"]
        for doc, fec, aul, tur, hora in filas:
            hora_str = (hora or '')[:5]
            lineas.append(f"  • {fec} {tur} · Aula {_tg_esc(aul)} · {hora_str}")
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_pins() -> str:
    """PINs operativos del día — TODOS (generados dinámicamente + overrides manuales)."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT aula, turno FROM cronograma_maestro
                WHERE config_json IS NOT NULL
                ORDER BY aula, turno
            """)
            aulas_turnos = cur.fetchall()
            cur.execute("""
                SELECT aula, turno, pin_nuevo, motivo FROM pin_overrides
                WHERE fecha::date = CURRENT_DATE
            """)
            overrides = {(a, t): (p, m) for a, t, p, m in cur.fetchall()}
        conn.close()
        if not aulas_turnos:
            return "🔑 <b>PINs DE HOY</b>\n\n<i>No hay aulas con cronograma cargado.</i>"

        fecha_str = datetime.now().strftime('%A %d/%m/%Y').capitalize()
        lineas = [
            "🔑 <b>PINs OPERATIVOS DEL DÍA</b>",
            f"📅 {fecha_str}",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            "<i>Usá estos PINs para que los docentes firmen su asistencia.</i>",
            "",
        ]
        # Agrupar por turno para que sea más legible
        por_turno = {'TM': [], 'TT': []}
        for aula, turno in aulas_turnos:
            pin = generar_pin_diario(aula, turno)
            es_override = (aula, turno) in overrides
            por_turno.setdefault(turno, []).append((aula, pin, es_override))

        for turno in ['TM', 'TT']:
            items = por_turno.get(turno, [])
            if not items:
                continue
            ico = '🌅' if turno == 'TM' else '🌇'
            label = 'Turno Mañana' if turno == 'TM' else 'Turno Tarde'
            lineas.append(f"{ico} <b>{label} ({turno})</b>")
            for aula, pin, es_ov in items:
                tag = ' 🔧' if es_ov else ''
                lineas.append(f"   🏫 Aula <b>{aula}</b> → <code>{pin}</code>{tag}")
            lineas.append("")

        if overrides:
            lineas.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lineas.append("🔧 = PIN sobrescrito manualmente por TIC")
            lineas.append("")
            for (aula, turno), (pin, mot) in overrides.items():
                if mot:
                    lineas.append(f"   • Aula {aula} ({turno}): <i>{mot[:80]}</i>")

        lineas.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        lineas.append("💡 <b>Cómo usarlo:</b>")
        lineas.append("Los PINs cambian todos los días automáticamente.")
        lineas.append("El docente lo carga en el Portal Docente para firmar su clase.")
        return '\n'.join(lineas)
    except Exception as e:
        return f"❌ Error: {e}"


def _cmd_justif() -> str:
    """Justificaciones pendientes de aprobación."""
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT docente, aula, turno, fecha::text, motivo, creado_en::text
                FROM justificaciones_ausencia
                WHERE estado='pendiente'
                ORDER BY creado_en DESC LIMIT 10
            """)
            filas = cur.fetchall()
            cur.execute("SELECT COUNT(*) FROM justificaciones_ausencia WHERE estado='pendiente'")
            total = cur.fetchone()[0]
        conn.close()
        if not filas:
            return "📋 <b>JUSTIFICACIONES PENDIENTES</b>\n\n✅ <i>No hay justificaciones esperando revisión.</i>"
        lineas = [f"📋 <b>JUSTIFICACIONES PENDIENTES</b> ({total} en total)\n"]
        for doc, aul, tur, fec, mot, fc in filas[:10]:
            lineas.append(f"  • <b>{_tg_esc(doc)}</b>")
            lineas.append(f"    Aula {_tg_esc(aul)} {_tg_esc(tur)} · {fec}")
            lineas.append(f"    📝 {_tg_esc((mot or '').strip()[:100])}")
            lineas.append("")
        if total > 10:
            lineas.append(f"   …y {total-10} más en el panel TIC")
        return '\n'.join(lineas).rstrip()
    except Exception as e:
        return f"❌ Error: {e}"


def _ejecutar_comando(cmd: str, arg: str) -> tuple:
    """Mapea cmd → (texto, botones). botones puede ser None."""
    HANDLERS_SIN_ARG = {
        '/start':      _cmd_ayuda,
        '/help':       _cmd_ayuda,
        '/ayuda':      _cmd_ayuda,
        '/estado':     _cmd_estado,
        '/hoy':        _cmd_hoy,
        '/ausentes':   _cmd_ausentes,
        '/pins':       _cmd_pins,
        '/justif':     _cmd_justif,
        '/semana':     _cmd_semana,
        '/mes':        _cmd_mes,
        '/bedeles':    _cmd_bedeles,
        '/ranking':    _cmd_ranking,
        '/cobertura':  _cmd_cobertura,
        '/auditoria':  _cmd_auditoria,
        '/auditoría':  _cmd_auditoria,
        '/silenciar':  _cmd_silenciar,
        '/activar':    _cmd_activar,
        # BLOQUE 2:
        '/vs_mes':     _cmd_vs_mes,
        '/heatmap':    _cmd_heatmap,
        '/faltas_top': _cmd_faltas_top,
        # BLOQUE 4:
        '/ping':            _cmd_ping,
        '/stats_bot':       _cmd_stats_bot,
        '/recordatorios':   _cmd_recordatorios,
    }
    HANDLERS_CON_ARG = {
        '/aula':       _cmd_aula,
        '/foja':       _cmd_foja,
        '/buscar':     _cmd_buscar,
        '/historial':  _cmd_historial,
        '/docente':    _cmd_docente,
        '/cronograma': _cmd_cronograma,
        '/notif':      _cmd_notif,
        # BLOQUE 2:
        '/comparar':   _cmd_comparar,
        # BLOQUE 4:
        '/logs':                  _cmd_logs,
        '/dni':                   _cmd_dni,
        '/dia':                   _cmd_dia,
        '/día':                   _cmd_dia,
        '/buscar_novedad':        _cmd_buscar_novedad,
        '/recordar':              _cmd_recordar,
        '/cancelar_recordatorio': _cmd_cancelar_recordatorio,
    }
    # Comandos que retornan (texto, botones) directamente
    HANDLERS_CON_BOTONES = {
        '/pin_temp':       _cmd_pin_temp,
        '/mantenimiento':  _cmd_mantenimiento,
        '/mantto':         _cmd_mantenimiento,
        '/reset_doc':      _cmd_reset_doc,
        # BLOQUE 2 (envían foto, retornan ('', None))
        '/grafico':        _cmd_grafico,
        '/gráfico':        _cmd_grafico,
    }
    # BLOQUE 4 — sin arg pero con botones
    if cmd == '/plantillas':
        return _cmd_plantillas()
    HANDLERS_BOTONES_SIN_ARG = {
        '/backup_ahora':   _cmd_backup_ahora,
        '/backup':         _cmd_backup_ahora,
    }
    if cmd == '/menu':
        return _cmd_menu()
    if cmd in HANDLERS_SIN_ARG:
        return HANDLERS_SIN_ARG[cmd](), None
    if cmd in HANDLERS_CON_ARG:
        return HANDLERS_CON_ARG[cmd](arg), None
    if cmd in HANDLERS_CON_BOTONES:
        return HANDLERS_CON_BOTONES[cmd](arg)
    if cmd in HANDLERS_BOTONES_SIN_ARG:
        return HANDLERS_BOTONES_SIN_ARG[cmd]()
    return None, None


def _procesar_mensaje_bot(upd: dict, cfg: dict[str, str | bool]) -> None:  # type: ignore[override]
    """Despacha un mensaje o callback recibido al handler de comando."""
    token: str   = str(cfg['token'])
    chat_id: str = str(cfg['chat_id'])

    # ── 1. Manejo de callbacks (botones inline) ──
    cb = upd.get('callback_query')
    if cb:
        msg = cb.get('message') or {}
        chat_id_msg = str((msg.get('chat') or {}).get('id', ''))
        if chat_id_msg != chat_id:
            return
        data = (cb.get('data') or '').strip()
        cb_id = cb.get('id')
        msg_id: int = int(msg.get('message_id') or 0)
        _bot_answer_callback(token, cb_id)
        try:
            # Comandos del menú (cmd:hoy, cmd:menu, etc.)
            if data.startswith('cmd:'):
                cmd_name = '/' + data.split(':', 1)[1]
                respuesta, botones = _ejecutar_comando(cmd_name, '')
                if respuesta:
                    if cmd_name == '/menu':
                        _bot_editar(token, chat_id, msg_id, respuesta, botones)
                    else:
                        botones_volver = (botones or []) + [[{'text': '🔙 Volver al menú', 'callback_data': 'cmd:menu'}]]
                        _bot_editar(token, chat_id, msg_id, respuesta, botones_volver)
            # Aprobar/rechazar justificación
            elif data.startswith('justif_ok:'):
                jid = int(data.split(':', 1)[1])
                resp = _aplicar_decision_justif(jid, 'aprobada')
                _bot_editar(token, chat_id, msg_id, resp)
            elif data.startswith('justif_no:'):
                jid = int(data.split(':', 1)[1])
                resp = _aplicar_decision_justif(jid, 'rechazada')
                _bot_editar(token, chat_id, msg_id, resp)
            # Confirmar reset de password
            elif data.startswith('reset_doc_ok:'):
                email = data.split(':', 1)[1]
                resp = _aplicar_reset_doc(email)
                _bot_editar(token, chat_id, msg_id, resp)
            # Mantenimiento
            elif data == 'mantto_on_confirm':
                texto = (
                    "⚠️ <b>CONFIRMAR ACTIVACIÓN</b>\n\n"
                    "Esto bloqueará Bedeles y Docentes hasta que lo desactives.\n"
                    "Solo TIC podrá operar.\n\n¿Confirmás?"
                )
                botones = [[
                    {'text': '✅ Sí, activar', 'callback_data': 'mantto_on'},
                    {'text': '❌ Cancelar',    'callback_data': 'cancelar'},
                ]]
                _bot_editar(token, chat_id, msg_id, texto, botones)
            elif data == 'mantto_on':
                resp = _aplicar_mantenimiento('1')
                _bot_editar(token, chat_id, msg_id, resp)
            elif data == 'mantto_off':
                resp = _aplicar_mantenimiento('0')
                _bot_editar(token, chat_id, msg_id, resp)
            # Plantillas: enviar texto de plantilla al grupo
            elif data.startswith('plant:'):
                slug = data.split(':', 1)[1]
                texto_plant = _PLANTILLAS_TEXTOS.get(slug)
                if texto_plant:
                    _bot_editar(token, chat_id, msg_id,
                                texto_plant + "\n\n<i>📢 Enviado al grupo</i>")
                else:
                    _bot_editar(token, chat_id, msg_id, "❌ Plantilla no encontrada.")
            # Cancelar genérico
            elif data == 'cancelar':
                _bot_editar(token, chat_id, msg_id, "❎ Acción cancelada.")
        except Exception as e:
            _bot_responder(token, chat_id, f"❌ Error: {e}")
        return

    # ── 2. Manejo de mensajes normales (con comando) ──
    msg = upd.get('message') or {}
    if not msg:
        return
    chat = msg.get('chat') or {}
    chat_id_msg = str(chat.get('id', ''))
    chat_type   = chat.get('type', '')   # 'private', 'group', 'supergroup'
    from_user   = msg.get('from') or {}
    tg_user_id  = from_user.get('id')
    tg_username = from_user.get('username') or ''
    tg_nombre   = (from_user.get('first_name', '') + ' ' + from_user.get('last_name', '')).strip()
    texto = (msg.get('text') or '').strip()
    if not texto.startswith('/'):
        return
    msg_id = msg.get('message_id')
    partes = texto.split(maxsplit=1)
    cmd_full = partes[0].lower()
    cmd = cmd_full.split('@')[0]
    arg = partes[1] if len(partes) > 1 else ''

    es_grupo_oficial = (chat_id_msg == chat_id)
    es_privado       = (chat_type == 'private')

    # Comando /perfil — funciona en ambos contextos
    if cmd == '/perfil':
        try:
            respuesta = _cmd_perfil(tg_user_id, tg_username, tg_nombre, chat_type)
            _bot_responder(token, chat_id_msg, respuesta, reply_to_msg_id=msg_id)
            _log_bot_comando(cmd, tg_user_id, chat_id_msg, es_privado, ok=True)
        except Exception as e:
            _log_bot_comando(cmd, tg_user_id, chat_id_msg, es_privado, ok=False, error=str(e))
        return

    # ── Comandos de BEDEL (solo en chat privado) ──
    BEDEL_HANDLERS = {
        '/start':        lambda: _cmd_bedel_start(tg_user_id, tg_username, tg_nombre),
        '/vincular':     lambda: _cmd_bedel_start(tg_user_id, tg_username, tg_nombre),
        '/mi_pin':       lambda: _cmd_bedel_mi_pin(tg_user_id),
        '/mi_aula':      lambda: _cmd_bedel_mi_aula(tg_user_id),
        '/mi_padron':    lambda: _cmd_bedel_mi_padron(tg_user_id),
        '/mi_cronograma':lambda: _cmd_bedel_mi_cronograma(tg_user_id),
        '/link_pc':      lambda: _cmd_bedel_link_pc(tg_user_id),
        '/desvincular':  lambda: _cmd_bedel_desvincular(tg_user_id),
    }
    if es_privado and cmd in BEDEL_HANDLERS:
        if not _telegram_bedel_habilitado():
            _bot_responder(
                token, chat_id_msg,
                "🔒 <b>Telegram para Bedelía está desactivado por TIC.</b>\n\n"
                "Ingresá al sistema con el PIN diario del aula.",
                reply_to_msg_id=msg_id,
            )
            _log_bot_comando(cmd, tg_user_id, chat_id_msg, es_privado, ok=False,
                             error='Integración Telegram Bedelía desactivada')
            return
        try:
            respuesta, botones = BEDEL_HANDLERS[cmd]()
            if respuesta:
                _bot_responder(token, chat_id_msg, respuesta,
                               reply_to_msg_id=msg_id, botones=botones)
            _log_bot_comando(cmd, tg_user_id, chat_id_msg, es_privado, ok=True)
        except Exception as e:
            _bot_responder(token, chat_id_msg,
                           f"❌ Error: {e}", reply_to_msg_id=msg_id)
            _log_bot_comando(cmd, tg_user_id, chat_id_msg, es_privado, ok=False, error=str(e))
        return

    # ── Comandos del grupo oficial ──
    if not es_grupo_oficial:
        # En privado, si no es comando de bedel, le sugerimos /start
        if es_privado:
            _bot_responder(token, chat_id_msg,
                f"👋 Hola! Si sos Bedel, mandá <code>/start</code> para vincularte.\n"
                f"Si querés ayuda: <code>/ayuda</code>",
                reply_to_msg_id=msg_id)
        return

    try:
        respuesta, botones = _ejecutar_comando(cmd, arg)
        if respuesta is None:
            return
        if respuesta == '':
            _log_bot_comando(cmd, tg_user_id, chat_id_msg, es_privado, ok=True)
            return  # comandos como /grafico que ya enviaron foto
        _bot_responder(token, chat_id, respuesta,
                       reply_to_msg_id=msg_id, botones=botones)
        _log_bot_comando(cmd, tg_user_id, chat_id_msg, es_privado, ok=True)
    except Exception as e:
        _bot_responder(token, chat_id,
                       f"❌ Error procesando comando: {e}", reply_to_msg_id=msg_id)
        _log_bot_comando(cmd, tg_user_id, chat_id_msg, es_privado, ok=False, error=str(e))


def _telegram_bot_loop():
    """Loop infinito de polling del bot. Corre en thread daemon."""
    global _BOT_OFFSET
    print(f"[telegram-bot] Loop arrancado en PID {os.getpid()}")
    while _BOT_LOOP_RUNNING:
        try:
            cfg = _telegram_config_actual()
            if cfg is None:
                _time_mod.sleep(30)
                continue
            interactivo = (_cargar_params().get('telegram_bot_interactivo', {}).get('valor') or '0') == '1'
            if not interactivo:
                _time_mod.sleep(30)  # check cada 30s si fue activado
                continue
            updates = _telegram_get_updates(cfg['token'], offset=_BOT_OFFSET, timeout=25)
            for upd in updates:
                uid = upd.get('update_id', 0)
                _BOT_OFFSET = max(_BOT_OFFSET, uid + 1)
                _procesar_mensaje_bot(upd, cfg)
        except Exception as e:
            print(f"[telegram-bot] error en loop: {e}")
            _time_mod.sleep(10)


def _iniciar_telegram_bot():
    """Arranca el thread del bot interactivo. Idempotente."""
    global _BOT_LOOP_RUNNING, _BOT_LOOP_THREAD
    if _BOT_LOOP_RUNNING:
        return
    _BOT_LOOP_RUNNING = True
    _BOT_LOOP_THREAD = threading.Thread(target=_telegram_bot_loop, daemon=True)
    _BOT_LOOP_THREAD.start()
    print(f"[telegram-bot] Thread iniciado.")


@app.route('/api/su/telegram/reenviar', methods=['POST'])
def su_telegram_reenviar():
    """Reenvía manualmente una minuta específica al grupo (ignora el toggle activo)."""
    if not _su_token_valido(request):
        return jsonify({'error': 'Token SU inválido'}), 403
    d     = request.json or {}
    aula  = (d.get('aula')  or '').strip().upper()
    turno = (d.get('turno') or '').strip().upper()
    fecha = (d.get('fecha') or '').strip()
    if not (aula and turno and fecha):
        return jsonify({'ok': False, 'msj': 'Faltan aula, turno y fecha'}), 400
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT aula, fecha::text, turno, bedel, sub_bedel,
                       fe, presentes, cant_ausentes, ausentes_json, novedades
                FROM minutas WHERE aula=%s AND turno=%s AND fecha=%s
            """, (aula, turno, fecha))
            row = cur.fetchone()
            if not row:
                return jsonify({'ok': False, 'msj': 'Minuta no encontrada'}), 404
            aus = row[8]
            if isinstance(aus, str):
                try:    aus = json.loads(aus)
                except: aus = []
            minuta = {
                'aula': row[0], 'fecha': row[1], 'turno': row[2],
                'bedel': row[3] or '', 'sub_bedel': row[4] or '',
                'fe': row[5], 'presentes': row[6], 'cant_ausentes': row[7],
                'ausentes': aus or [],
                'novedades': row[9] or '',
            }
        ok, msg = _enviar_minuta_telegram(minuta, forzar=True)
        return jsonify({'ok': ok, 'msj': msg})
    except Exception as e:
        return jsonify({'ok': False, 'msj': f'Error: {e}'}), 500
    finally:
        conn.close()


def _cargar_params():
    """Devuelve dict con todos los parámetros (default + override de BD)."""
    out = {k: dict(v) for k, v in PARAMS_DEFAULT.items()}
    try:
        conn = get_db()
        with conn.cursor() as cur:
            cur.execute("SELECT clave, valor, descripcion FROM config_sistema")
            for clave, valor, desc in cur.fetchall():
                if clave in out:
                    out[clave]['valor'] = valor
                    if desc: out[clave]['descripcion'] = desc
                else:
                    out[clave] = {'valor': valor, 'descripcion': desc or ''}
        conn.close()
    except Exception:
        pass
    return out


@app.route('/api/su/parametros', methods=['GET'])
def su_get_parametros():
    err = _exigir_su(request)
    if err: return err
    return jsonify(_cargar_params())


@app.route('/api/parametros_publicos', methods=['GET'])
def parametros_publicos():
    """Versión sin token para que el frontend del docente consulte tolerancias."""
    p = _cargar_params()
    # Sólo expone los que necesita el frontend del docente
    publicos = ['tolerancia_antes_min','tolerancia_despues_min',
                'limite_justif_retroactiva_h','dias_pendientes_alerta',
                'adelantos_horario_activo']
    return jsonify({k: p[k]['valor'] for k in publicos if k in p})


@app.route('/api/plana_mayor/adelantos-horario', methods=['GET'])
def plana_mayor_adelantos_horario():
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, docente, aula, turno, materia,
                       fecha_original::text, hora_original,
                       fecha_nueva::text, hora_nueva, estado,
                       creado_en::text, revocado_por, revocado_en::text
                FROM adelantos_horario
                ORDER BY creado_en DESC, id DESC
                LIMIT 500
            """)
            casos = [{
                'id': r[0], 'docente': r[1], 'aula': r[2], 'turno': r[3],
                'materia': r[4], 'fecha_original': r[5], 'hora_original': r[6],
                'fecha_nueva': r[7], 'hora_nueva': r[8], 'estado': r[9],
                'creado_en': r[10], 'revocado_por': r[11], 'revocado_en': r[12],
            } for r in cur.fetchall()]
        activo = _cargar_params().get('adelantos_horario_activo', {}).get('valor') == '1'
        return jsonify({'activo': activo, 'casos': casos})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/su/adelantos-horario', methods=['POST'])
def su_configurar_adelantos_horario():
    err = _exigir_su(request)
    if err:
        return err
    d = request.json or {}
    activo = d.get('activo')
    if activo not in (True, False, 0, 1, '0', '1'):
        return jsonify({'error': 'El estado debe ser activado o desactivado.'}), 400
    valor = '1' if str(activo).lower() in ('true', '1') else '0'
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO config_sistema (clave, valor, descripcion, actualizado)
                VALUES (%s,%s,%s,CURRENT_TIMESTAMP)
                ON CONFLICT (clave) DO UPDATE
                SET valor=EXCLUDED.valor, actualizado=CURRENT_TIMESTAMP
            """, (
                'adelantos_horario_activo', valor,
                PARAMS_DEFAULT['adelantos_horario_activo']['descripcion'],
            ))
        conn.commit()
        _log_audit('TIC', 'super_usuario', 'CONFIGURAR_ADELANTOS_HORARIO',
                   'config_sistema', 'adelantos_horario_activo', f'activo={valor}')
        return jsonify({
            'activo': valor == '1',
            'msj': 'Adelantos automáticos activados.' if valor == '1'
            else 'Adelantos automáticos desactivados.',
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/plana_mayor/adelantos-horario/<int:adelanto_id>/revocar', methods=['POST'])
def revocar_adelanto_horario(adelanto_id):
    if not _admin_token_valido(request) and not _su_token_valido(request):
        return jsonify({'error': 'No autorizado'}), 403
    usuario = _usuario_sesion_actual(request)
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT docente, aula, turno, materia, fecha_original,
                       fecha_nueva, estado
                FROM adelantos_horario WHERE id=%s FOR UPDATE
            """, (adelanto_id,))
            caso = cur.fetchone()
            if not caso or caso[6] != 'aplicado':
                return jsonify({'error': 'El adelanto no existe o ya fue revocado.'}), 409
            if caso[4] < date.today() or caso[5] < date.today():
                return jsonify({'error': 'No se puede revocar un adelanto correspondiente a una fecha pasada.'}), 409
            cur.execute("""
                SELECT 1 FROM minutas
                WHERE aula=%s AND turno=%s AND fecha IN (%s,%s)
                LIMIT 1
            """, (caso[1], caso[2], caso[4], caso[5]))
            if cur.fetchone():
                return jsonify({'error': 'No se puede revocar: ya existe una minuta en una de las fechas afectadas.'}), 409
            cur.execute("""
                SELECT 1 FROM firmas_docentes
                WHERE docente=%s AND aula=%s AND turno=%s AND fecha IN (%s,%s)
                LIMIT 1
            """, (caso[0], caso[1], caso[2], caso[4], caso[5]))
            if cur.fetchone():
                return jsonify({'error': 'No se puede revocar: ya hay una firma registrada en una de las fechas afectadas.'}), 409
            cur.execute("""
                UPDATE adelantos_horario
                SET estado='revocado', revocado_por=%s, revocado_en=CURRENT_TIMESTAMP
                WHERE id=%s AND estado='aplicado'
            """, (usuario, adelanto_id))
        conn.commit()
        _log_audit(usuario, 'plana_mayor', 'REVOCAR_ADELANTO_HORARIO',
                   'adelantos_horario', str(adelanto_id),
                   f'{caso[1]}/{caso[2]} · {caso[3]} · {caso[4]} → {caso[5]}')
        return jsonify({'msj': 'Adelanto revocado; el cronograma habitual vuelve a regir.'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/su/parametros', methods=['POST'])
def su_set_parametros():
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    cambios = d.get('parametros', {})
    if not isinstance(cambios, dict) or not cambios:
        return jsonify({'error': 'No se recibieron parámetros'}), 400
    desconocidos = sorted(set(cambios) - set(PARAMS_DEFAULT))
    if desconocidos:
        return jsonify({'error': f'Parámetro(s) no permitido(s): {", ".join(desconocidos)}'}), 400
    if 'institucion_lat' in cambios:
        valor = str(cambios['institucion_lat']).strip()
        if valor:
            try:
                if not -90 <= float(valor) <= 90:
                    raise ValueError
            except (TypeError, ValueError):
                return jsonify({'error': 'La latitud institucional debe estar entre -90 y 90.'}), 400
    if 'institucion_lng' in cambios:
        valor = str(cambios['institucion_lng']).strip()
        if valor:
            try:
                if not -180 <= float(valor) <= 180:
                    raise ValueError
            except (TypeError, ValueError):
                return jsonify({'error': 'La longitud institucional debe estar entre -180 y 180.'}), 400
    if 'radio_geolocalizacion_m' in cambios:
        try:
            if float(cambios['radio_geolocalizacion_m']) <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return jsonify({'error': 'El radio institucional debe ser mayor que cero.'}), 400

    conn = get_db()
    try:
        with conn.cursor() as cur:
            for clave, valor in cambios.items():
                if not re.match(r'^[a-z_]+$', clave or ''):
                    continue
                cur.execute("""
                    INSERT INTO config_sistema (clave, valor, descripcion, actualizado)
                    VALUES (%s, %s, %s, CURRENT_TIMESTAMP)
                    ON CONFLICT (clave) DO UPDATE
                       SET valor = EXCLUDED.valor,
                           actualizado = CURRENT_TIMESTAMP
                """, (clave, str(valor), PARAMS_DEFAULT.get(clave, {}).get('descripcion', '')))
        conn.commit()
        return jsonify({'msj': f'Parámetros actualizados: {len(cambios)} clave(s).'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ─── PIN BLANQUEO / OVERRIDE ──────────────────────────────────────────────
@app.route('/api/su/pines_hoy', methods=['GET'])
def su_pines_hoy():
    err = _exigir_su(request)
    if err: return err
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT DISTINCT aula, turno FROM cronograma_maestro ORDER BY turno, aula"
            )
            aulas = cur.fetchall()
            # Overrides activos hoy
            cur.execute("""
                SELECT aula, turno, pin_nuevo, motivo, creado_en::text
                FROM pin_overrides WHERE fecha=CURRENT_DATE
            """)
            overrides = {(a, t): {'pin': p, 'motivo': m, 'creado_en': ce}
                         for a, t, p, m, ce in cur.fetchall()}

        result = []
        for aula, turno in aulas:
            ov = overrides.get((aula, turno))
            result.append({
                'aula':      aula,
                'turno':     turno,
                'pin':       (ov['pin'] if ov else generar_pin_diario(aula, turno)),
                'override':  bool(ov),
                'motivo':    ov['motivo']    if ov else None,
                'creado_en': ov['creado_en'] if ov else None,
            })
        return jsonify(result)
    finally:
        conn.close()


@app.route('/api/su/pin_blanquear', methods=['POST'])
def su_pin_blanquear():
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    aula   = (d.get('aula')   or '').strip().upper()
    turno  = (d.get('turno')  or '').strip().upper()
    motivo = (d.get('motivo') or 'Blanqueo por TIC').strip()
    if not aula or not turno:
        return jsonify({'error': 'aula y turno requeridos'}), 400

    # Generar PIN nuevo aleatorio de 4 dígitos
    pin_nuevo = f"{secrets.randbelow(10000):04d}"
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO pin_overrides (aula, turno, fecha, pin_nuevo, motivo)
                VALUES (%s, %s, CURRENT_DATE, %s, %s)
                ON CONFLICT (aula, turno, fecha)
                DO UPDATE SET pin_nuevo = EXCLUDED.pin_nuevo,
                              motivo    = EXCLUDED.motivo,
                              creado_en = CURRENT_TIMESTAMP
            """, (aula, turno, pin_nuevo, motivo))
        conn.commit()
        return jsonify({
            'msj': f'PIN blanqueado para Aula {aula} ({turno}). Nuevo PIN del día: {pin_nuevo}',
            'pin': pin_nuevo, 'aula': aula, 'turno': turno,
        })
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/su/pin_restaurar', methods=['POST'])
def su_pin_restaurar():
    """Quita el override y vuelve al PIN calculado por hash."""
    err = _exigir_su(request)
    if err: return err
    d = request.json or {}
    aula   = (d.get('aula')  or '').strip().upper()
    turno  = (d.get('turno') or '').strip().upper()
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM pin_overrides
                WHERE aula=%s AND turno=%s AND fecha=CURRENT_DATE
            """, (aula, turno))
        conn.commit()
        return jsonify({'msj': f'Override eliminado para Aula {aula} ({turno}).'})
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


# ─── BACKUP ───────────────────────────────────────────────────────────────
@app.route('/api/su/backup', methods=['GET'])
def su_backup():
    """Exporta el contenido de TODAS las tablas operativas como un único JSON descargable."""
    err = _exigir_su(request)
    if err: return err
    tablas = ['aula_catalogo', 'tipos_novedad', 'cronograma_maestro', 'aspirantes', 'docentes', 'minutas',
              'firmas_docentes', 'justificaciones_ausencia', 'config_sistema',
              'usuarios_admin', 'pin_overrides', 'audit_log', 'failed_logins', 'system_log',
              'cronograma_versiones', 'bedeles_telegram', 'bedel_link_tokens',
              'recordatorios_telegram', 'bot_comando_log']
    out = {
        'meta': {
            'fecha_export':  datetime.now().isoformat(),
            'version_sipa':  'GNA-2026',
        },
        'tablas': {},
    }
    conn = get_db()
    try:
        with conn.cursor() as cur:
            for t in tablas:
                try:
                    cur.execute(f"SELECT * FROM {t}")
                    cols = [c[0] for c in cur.description]
                    out['tablas'][t] = {
                        'columnas': cols,
                        'filas': [
                            [str(v) if isinstance(v, (date, datetime)) else v for v in r]
                            for r in cur.fetchall()
                        ],
                    }
                except Exception as e:
                    out['tablas'][t] = {'error': str(e)}
                    conn.rollback()
    finally:
        conn.close()

    nombre = f"sipa_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    return Response(
        json.dumps(out, ensure_ascii=False, indent=2, default=str),
        mimetype='application/json',
        headers={'Content-Disposition': f'attachment; filename="{nombre}"'}
    )


# ═══════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════

# Arrancar el scheduler SOLO en el proceso "main" de Flask para evitar dos
# threads cuando debug=True (Werkzeug spawnea un proceso hijo con auto-reload).
def _debe_iniciar_scheduler() -> bool:
    """
    Determina si este proceso es el que debe correr el scheduler/bot:
      - WSGI (gunicorn/uwsgi): __name__ != '__main__' → arranca normal
      - Dev debug=True: solo el proceso reloaded (WERKZEUG_RUN_MAIN='true') arranca
      - Dev debug=False: el proceso __main__ arranca (no hay reloader)
    """
    if __name__ != '__main__':
        return True
    debug_on = os.getenv('FLASK_DEBUG', '0') == '1'
    if debug_on:
        return os.environ.get('WERKZEUG_RUN_MAIN') == 'true'
    return True

if _debe_iniciar_scheduler():
    _iniciar_scheduler()


if __name__ == '__main__':
    port = int(os.getenv('FLASK_PORT', 5000))
    debug = os.getenv('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug, port=port, host='0.0.0.0')