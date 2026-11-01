
USE [master];
GO

IF DB_ID(N'credivision') IS NULL
BEGIN
    CREATE DATABASE [credivision];
END;
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.server_principals
    WHERE name = N'credivision_app'
)
BEGIN
    CREATE LOGIN [credivision_app]
        WITH PASSWORD = 'CAMBIAR_PASSWORD',
             CHECK_POLICY = ON,
             CHECK_EXPIRATION = OFF;
END;
GO

USE [credivision];
GO

IF NOT EXISTS (
    SELECT 1
    FROM sys.database_principals
    WHERE name = N'credivision_app'
)
BEGIN
    CREATE USER [credivision_app] FOR LOGIN [credivision_app];
END;
GO

GRANT SELECT, INSERT, UPDATE, DELETE TO [credivision_app];
GO

-- Cuentas que podrán iniciar sesión en la aplicación.
IF OBJECT_ID(N'dbo.usuarios', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.usuarios (
        id BIGINT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
        usuario NVARCHAR(80) NOT NULL,
        email NVARCHAR(254) NOT NULL,
        nombre NVARCHAR(120) NULL,
        contrasena_hash NVARCHAR(255) NOT NULL,
        rol NVARCHAR(20) NOT NULL CONSTRAINT df_usuarios_rol DEFAULT N'usuario',
        activo BIT NOT NULL CONSTRAINT df_usuarios_activo DEFAULT 1,
        fecha_registro DATETIME2 NOT NULL CONSTRAINT df_usuarios_fecha_registro DEFAULT SYSDATETIME(),
        ultimo_acceso DATETIME2 NULL,
        actualizado_en DATETIME2 NOT NULL CONSTRAINT df_usuarios_actualizado_en DEFAULT SYSDATETIME(),
        CONSTRAINT uq_usuarios_usuario UNIQUE (usuario),
        CONSTRAINT uq_usuarios_email UNIQUE (email),
        CONSTRAINT chk_usuarios_rol CHECK (rol IN (N'usuario', N'administrador'))
    );
END;
GO

-- Versiones y métricas de los modelos para conservar trazabilidad y recomendarlos.
IF OBJECT_ID(N'dbo.modelos', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.modelos (
        id BIGINT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
        clave NVARCHAR(80) NOT NULL,
        nombre NVARCHAR(120) NOT NULL,
        version NVARCHAR(80) NOT NULL,
        exactitud DECIMAL(6, 5) NULL,
        precision_modelo DECIMAL(6, 5) NULL,
        sensibilidad DECIMAL(6, 5) NULL,
        f1 DECIMAL(6, 5) NULL,
        roc_auc DECIMAL(6, 5) NULL,
        es_recomendado BIT NOT NULL CONSTRAINT df_modelos_recomendado DEFAULT 0,
        fecha_entrenamiento DATETIME2 NOT NULL CONSTRAINT df_modelos_fecha_entrenamiento DEFAULT SYSDATETIME(),
        CONSTRAINT uq_modelos_clave_version UNIQUE (clave, version),
        CONSTRAINT chk_modelos_exactitud CHECK (exactitud IS NULL OR exactitud BETWEEN 0 AND 1),
        CONSTRAINT chk_modelos_precision CHECK (precision_modelo IS NULL OR precision_modelo BETWEEN 0 AND 1),
        CONSTRAINT chk_modelos_sensibilidad CHECK (sensibilidad IS NULL OR sensibilidad BETWEEN 0 AND 1),
        CONSTRAINT chk_modelos_f1 CHECK (f1 IS NULL OR f1 BETWEEN 0 AND 1),
        CONSTRAINT chk_modelos_roc_auc CHECK (roc_auc IS NULL OR roc_auc BETWEEN 0 AND 1)
    );
END;
GO

-- Cada fila contiene los datos necesarios para el historial y la vista de detalle.
IF OBJECT_ID(N'dbo.predicciones', N'U') IS NULL
BEGIN
    CREATE TABLE dbo.predicciones (
        id BIGINT IDENTITY(1, 1) NOT NULL PRIMARY KEY,
        usuario_id BIGINT NOT NULL,
        modelo_id BIGINT NOT NULL,
        fecha_creacion DATETIME2 NOT NULL CONSTRAINT df_predicciones_fecha_creacion DEFAULT SYSDATETIME(),

        numero_dependientes SMALLINT NOT NULL,
        nivel_educativo NVARCHAR(50) NOT NULL,
        trabajador_independiente NVARCHAR(10) NOT NULL,
        ingreso_anual DECIMAL(15, 2) NOT NULL,
        monto_solicitado DECIMAL(15, 2) NOT NULL,
        plazo_credito SMALLINT NOT NULL,
        puntaje_cibil SMALLINT NOT NULL,
        valor_activos_residenciales DECIMAL(15, 2) NOT NULL,
        valor_activos_comerciales DECIMAL(15, 2) NOT NULL,
        valor_activos_lujo DECIMAL(15, 2) NOT NULL,
        valor_activos_bancarios DECIMAL(15, 2) NOT NULL,

        resultado NVARCHAR(12) NOT NULL,
        probabilidad_aprobacion DECIMAL(6, 5) NOT NULL,

        CONSTRAINT fk_predicciones_usuario
            FOREIGN KEY (usuario_id) REFERENCES dbo.usuarios(id),
        CONSTRAINT fk_predicciones_modelo
            FOREIGN KEY (modelo_id) REFERENCES dbo.modelos(id),
        CONSTRAINT chk_predicciones_dependientes CHECK (numero_dependientes >= 0),
        CONSTRAINT chk_predicciones_ingreso CHECK (ingreso_anual >= 0),
        CONSTRAINT chk_predicciones_monto CHECK (monto_solicitado >= 0),
        CONSTRAINT chk_predicciones_plazo CHECK (plazo_credito >= 1),
        CONSTRAINT chk_predicciones_cibil CHECK (puntaje_cibil BETWEEN 300 AND 900),
        CONSTRAINT chk_predicciones_resultado CHECK (resultado IN (N'Aprobado', N'Rechazado')),
        CONSTRAINT chk_predicciones_probabilidad CHECK (probabilidad_aprobacion BETWEEN 0 AND 1)
    );
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'idx_predicciones_usuario_fecha'
      AND object_id = OBJECT_ID(N'dbo.predicciones')
)
    CREATE INDEX idx_predicciones_usuario_fecha
        ON dbo.predicciones (usuario_id, fecha_creacion DESC);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'idx_predicciones_modelo_fecha'
      AND object_id = OBJECT_ID(N'dbo.predicciones')
)
    CREATE INDEX idx_predicciones_modelo_fecha
        ON dbo.predicciones (modelo_id, fecha_creacion DESC);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'idx_predicciones_resultado_fecha'
      AND object_id = OBJECT_ID(N'dbo.predicciones')
)
    CREATE INDEX idx_predicciones_resultado_fecha
        ON dbo.predicciones (resultado, fecha_creacion DESC);
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
    WHERE name = N'idx_modelos_recomendado_version'
      AND object_id = OBJECT_ID(N'dbo.modelos')
)
    CREATE INDEX idx_modelos_recomendado_version
        ON dbo.modelos (es_recomendado, fecha_entrenamiento DESC);
GO
