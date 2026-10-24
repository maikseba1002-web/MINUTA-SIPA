-- ==== CATÁLOGO ACADÉMICO DE AULAS ====
CREATE TABLE IF NOT EXISTS aula_catalogo (
    aula VARCHAR(50) NOT NULL,
    turno VARCHAR(20) NOT NULL,
    nombre VARCHAR(150) NOT NULL,
    anio VARCHAR(20),
    especialidad VARCHAR(150),
    curso VARCHAR(150),
    aliases JSONB,
    fuente VARCHAR(250),
    actualizado TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (aula, turno)
);

-- ==== TABLA: MINUTAS DIARIAS ====
CREATE TABLE IF NOT EXISTS minutas (
    id SERIAL PRIMARY KEY,
    aula VARCHAR(50) NOT NULL, 
    fecha DATE NOT NULL, 
    turno VARCHAR(20) NOT NULL,
    bedel VARCHAR(150), 
    sub_bedel VARCHAR(150),
    fe INTEGER, 
    presentes INTEGER, 
    cant_ausentes INTEGER,
    schedule_json JSONB, 
    ausentes_json JSONB, 
    novedades TEXT,
    fecha_carga TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_minutas_aula_fecha_turno
    ON minutas(aula, fecha, turno);

-- ==== TABLA: CRONOGRAMA MAESTRO ====
CREATE TABLE IF NOT EXISTS cronograma_maestro (
    aula VARCHAR(50) NOT NULL,
    turno VARCHAR(20) NOT NULL,
    config_json JSONB,
    PRIMARY KEY (aula, turno)
);

-- ==== TABLA: PADRÓN DE ASPIRANTES ====
CREATE TABLE IF NOT EXISTS aspirantes (
    id SERIAL PRIMARY KEY,
    aula VARCHAR(50) NOT NULL,
    turno VARCHAR(20) NOT NULL,
    grado VARCHAR(50), 
    nombre VARCHAR(150) NOT NULL,
    UNIQUE(aula, turno, nombre)
);

-- Catálogo configurable de causales y criterio administrativo.
CREATE TABLE IF NOT EXISTS tipos_novedad (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(80) UNIQUE NOT NULL,
    permite_justificacion BOOLEAN NOT NULL DEFAULT TRUE,
    justificada_por_defecto BOOLEAN,
    activo BOOLEAN NOT NULL DEFAULT TRUE,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ==== TABLA: DOCENTES ====
CREATE TABLE IF NOT EXISTS docentes (
    id SERIAL PRIMARY KEY,
    nombre VARCHAR(150) NOT NULL,
    email VARCHAR(150) UNIQUE NOT NULL,
    dni VARCHAR(20) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    es_pgnp BOOLEAN NOT NULL DEFAULT FALSE
);

-- Cambios puntuales de horario aplicados automáticamente y auditables.
CREATE TABLE IF NOT EXISTS adelantos_horario (
    id SERIAL PRIMARY KEY,
    docente_id INTEGER NOT NULL REFERENCES docentes(id),
    docente VARCHAR(150) NOT NULL,
    aula VARCHAR(50) NOT NULL,
    turno VARCHAR(20) NOT NULL CHECK (turno IN ('TM', 'TT')),
    materia VARCHAR(150) NOT NULL,
    fecha_original DATE NOT NULL,
    hora_original VARCHAR(40) NOT NULL,
    fecha_nueva DATE NOT NULL,
    hora_nueva VARCHAR(40) NOT NULL,
    estado VARCHAR(20) NOT NULL DEFAULT 'aplicado'
        CHECK (estado IN ('aplicado', 'revocado')),
    creado_en TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revocado_por VARCHAR(150),
    revocado_en TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_adelantos_docente_fecha
    ON adelantos_horario(docente_id, fecha_nueva DESC);
CREATE INDEX IF NOT EXISTS idx_adelantos_fechas_aula
    ON adelantos_horario(fecha_original, fecha_nueva, aula, turno)
    WHERE estado = 'aplicado';

CREATE TABLE IF NOT EXISTS coberturas_docente (
    id SERIAL PRIMARY KEY,
    fecha DATE NOT NULL,
    aula VARCHAR(50) NOT NULL,
    turno VARCHAR(20) NOT NULL CHECK (turno IN ('TM', 'TT')),
    titular VARCHAR(150) NOT NULL,
    materia VARCHAR(150) NOT NULL,
    hora VARCHAR(40) NOT NULL,
    pgnp_id INTEGER REFERENCES docentes(id),
    estado VARCHAR(20) NOT NULL DEFAULT 'pendiente'
        CHECK (estado IN ('solicitada', 'pendiente', 'aprobada', 'rechazada', 'completada', 'cancelada')),
    solicitada_por VARCHAR(150) NOT NULL,
    solicitada_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    motivo_solicitud TEXT,
    revisada_por VARCHAR(150),
    revisada_en TIMESTAMP,
    firmado_en TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_cobertura_docente_horario_solicitada
    ON coberturas_docente(fecha, aula, turno, hora, materia)
    WHERE estado IN ('solicitada', 'pendiente', 'aprobada', 'completada');
CREATE INDEX IF NOT EXISTS idx_cobertura_docente_pgnp_fecha
    ON coberturas_docente(pgnp_id, fecha, estado);

-- ==== FIRMAS DE PRESENTISMO DOCENTE ====
CREATE TABLE IF NOT EXISTS firmas_docentes (
    id SERIAL PRIMARY KEY,
    docente VARCHAR(150) NOT NULL,
    aula VARCHAR(50) NOT NULL,
    turno VARCHAR(20) NOT NULL,
    fecha DATE NOT NULL,
    hora_firma TIME NOT NULL,
    timestamp_utc TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    pin_usado VARCHAR(10),
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    precision_m REAL,
    UNIQUE (docente, aula, turno, fecha)
);

-- ==== JUSTIFICACIONES Y AUDITORÍA ====
CREATE TABLE IF NOT EXISTS justificaciones_ausencia (
    id SERIAL PRIMARY KEY,
    docente VARCHAR(150) NOT NULL,
    aula VARCHAR(50) NOT NULL,
    turno VARCHAR(20) NOT NULL,
    fecha DATE NOT NULL,
    motivo VARCHAR(200) NOT NULL,
    comentario TEXT,
    registrado_por VARCHAR(150),
    estado VARCHAR(20) DEFAULT 'aprobada',
    revisado_por VARCHAR(150),
    revisado_en TIMESTAMP,
    adjunto_nombre VARCHAR(255),
    adjunto_path VARCHAR(500),
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    observacion_revision TEXT,
    UNIQUE (docente, aula, turno, fecha)
);

CREATE TABLE IF NOT EXISTS calendario_no_actividad (
    id SERIAL PRIMARY KEY,
    fecha DATE NOT NULL,
    alcance VARCHAR(20) NOT NULL CHECK (alcance IN ('institucion', 'turno', 'aula')),
    turno VARCHAR(20),
    aula VARCHAR(50),
    motivo VARCHAR(200) NOT NULL,
    estado VARCHAR(20) NOT NULL DEFAULT 'programado'
        CHECK (estado IN ('programado', 'confirmado')),
    excepciones JSONB NOT NULL DEFAULT '[]'::jsonb,
    creado_por VARCHAR(150) NOT NULL,
    creado_en TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    confirmado_por VARCHAR(150),
    confirmado_en TIMESTAMP,
    actualizado TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
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

CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    usuario VARCHAR(150),
    rol VARCHAR(30),
    accion VARCHAR(60) NOT NULL,
    tabla VARCHAR(60),
    registro_ref VARCHAR(200),
    detalle TEXT,
    ip VARCHAR(60)
);
CREATE INDEX IF NOT EXISTS idx_audit_fecha ON audit_log(fecha DESC);

-- Coordenadas opcionales capturadas al firmar presentismo.
ALTER TABLE firmas_docentes ADD COLUMN IF NOT EXISTS lat DOUBLE PRECISION;
ALTER TABLE firmas_docentes ADD COLUMN IF NOT EXISTS lng DOUBLE PRECISION;
ALTER TABLE firmas_docentes ADD COLUMN IF NOT EXISTS precision_m REAL;