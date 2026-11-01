from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

import pyodbc
from dotenv import load_dotenv


DIRECTORIO_BASE = Path(__file__).resolve().parent
load_dotenv(DIRECTORIO_BASE / ".env")


def obtener_conexion() -> pyodbc.Connection:
    configuracion = {
        "DRIVER": os.getenv("SQL_DRIVER", "ODBC Driver 18 for SQL Server"),
        "SERVER": os.getenv("SQL_SERVER", "localhost"),
        "DATABASE": os.getenv("SQL_DATABASE", "credivision"),
        "Encrypt": os.getenv("SQL_ENCRYPT", "yes"),
        "TrustServerCertificate": os.getenv("SQL_TRUST_SERVER_CERTIFICATE", "yes"),
    }
    autenticacion = os.getenv("SQL_AUTHENTICATION", "windows").lower()
    if autenticacion == "windows":
        configuracion["Trusted_Connection"] = "yes"
    elif autenticacion == "sql":
        usuario = os.getenv("SQL_USER")
        contrasena = os.getenv("SQL_PASSWORD")
        if not usuario or not contrasena:
            raise RuntimeError("Faltan SQL_USER o SQL_PASSWORD para la autenticación SQL.")
        configuracion["UID"] = usuario
        configuracion["PWD"] = contrasena
    else:
        raise RuntimeError("SQL_AUTHENTICATION debe ser 'windows' o 'sql'.")

    cadena = ";".join(f"{clave}={{{valor}}}" if clave == "DRIVER" else f"{clave}={valor}" for clave, valor in configuracion.items())
    return pyodbc.connect(cadena, timeout=5)


@contextmanager
def conexion() -> Iterator[pyodbc.Connection]:
    conexion_sql = obtener_conexion()
    try:
        yield conexion_sql
        conexion_sql.commit()
    except Exception:
        conexion_sql.rollback()
        raise
    finally:
        conexion_sql.close()
