from __future__ import annotations

import json
import os
import secrets
from functools import wraps

import joblib
import pandas as pd
import pyodbc
from flask import Flask, flash, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from db import conexion
from train_models import CARACTERISTICAS, CARACTERISTICAS_NUMERICAS, DIRECTORIO_MODELOS, entrenar_modelos


aplicacion = Flask(__name__)
aplicacion.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY") or secrets.token_urlsafe(32)
NOMBRES_MODELOS = {
    "regresion_logistica": "Regresión Logística",
    "arbol_decision": "Árbol de Decisión",
    "bosque_aleatorio": "Random Forest",
}


def garantizar_artefactos() -> dict:
    ruta_metricas = DIRECTORIO_MODELOS / "metricas.json"
    if not ruta_metricas.exists():
        return entrenar_modelos()
    return json.loads(ruta_metricas.read_text(encoding="utf-8"))


def obtener_metricas() -> dict:
    return garantizar_artefactos()


def a_moneda(valor: int | float) -> str:
    return f"S/ {valor:,.0f}".replace(",", " ")


def a_porcentaje(valor: float) -> str:
    return f"{valor * 100:.1f}%"


aplicacion.jinja_env.filters["moneda"] = a_moneda
aplicacion.jinja_env.filters["porcentaje"] = a_porcentaje


def login_required(vista):
    """Redirige al acceso cuando la sesión no contiene un usuario autenticado."""
    @wraps(vista)
    def vista_protegida(*args, **kwargs):
        if "usuario_id" not in session:
            flash("Inicie sesión para acceder a CrediVision.", "error")
            return redirect(url_for("iniciar_sesion"))
        return vista(*args, **kwargs)
    return vista_protegida


@aplicacion.route("/registro", methods=["GET", "POST"])
def registrar_usuario():
    if "usuario_id" in session:
        return redirect(url_for("panel"))

    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        usuario = request.form.get("usuario", "").strip()
        email = request.form.get("email", "").strip().lower()
        contrasena = request.form.get("contrasena", "")
        confirmacion = request.form.get("confirmacion", "")

        if len(usuario) < 3 or len(usuario) > 80:
            flash("El usuario debe tener entre 3 y 80 caracteres.", "error")
        elif "@" not in email or len(email) > 254:
            flash("Ingrese un correo electrónico válido.", "error")
        elif len(contrasena) < 8:
            flash("La contraseña debe tener al menos 8 caracteres.", "error")
        elif contrasena != confirmacion:
            flash("Las contraseñas no coinciden.", "error")
        else:
            try:
                with conexion() as conexion_sql:
                    cursor = conexion_sql.cursor()
                    cursor.execute(
                        """
                        INSERT INTO dbo.usuarios (usuario, email, nombre, contrasena_hash)
                        VALUES (?, ?, ?, ?)
                        """,
                        usuario,
                        email,
                        nombre or None,
                        generate_password_hash(contrasena),
                    )
                flash("Cuenta creada. Ya puede iniciar sesión.", "exito")
                return redirect(url_for("iniciar_sesion"))
            except pyodbc.IntegrityError:
                flash("El usuario o correo electrónico ya está registrado.", "error")
            except (pyodbc.Error, RuntimeError):
                flash("No fue posible conectar con la base de datos. Revise el archivo .env.", "error")

    return render_template("registro.html")


@aplicacion.route("/login", methods=["GET", "POST"])
def iniciar_sesion():
    if "usuario_id" in session:
        return redirect(url_for("panel"))

    if request.method == "POST":
        identificador = request.form.get("identificador", "").strip()
        contrasena = request.form.get("contrasena", "")
        try:
            with conexion() as conexion_sql:
                cursor = conexion_sql.cursor()
                usuario = cursor.execute(
                    """
                    SELECT id, usuario, contrasena_hash, rol, activo
                    FROM dbo.usuarios
                    WHERE usuario = ? OR email = ?
                    """,
                    identificador,
                    identificador.lower(),
                ).fetchone()
        except (pyodbc.Error, RuntimeError):
            flash("No fue posible conectar con la base de datos. Revise el archivo .env.", "error")
            return render_template("login.html")

        if usuario and usuario.activo and check_password_hash(usuario.contrasena_hash, contrasena):
            session.clear()
            session["usuario_id"] = usuario.id
            session["usuario"] = usuario.usuario
            session["rol"] = usuario.rol
            try:
                with conexion() as conexion_sql:
                    conexion_sql.cursor().execute(
                        "UPDATE dbo.usuarios SET ultimo_acceso = SYSDATETIME() WHERE id = ?",
                        usuario.id,
                    )
            except (pyodbc.Error, RuntimeError):
                pass
            return redirect(url_for("panel"))

        flash("Usuario o contraseña incorrectos.", "error")

    return render_template("login.html")


@aplicacion.post("/cerrar-sesion")
def cerrar_sesion():
    session.clear()
    flash("Sesión cerrada correctamente.", "exito")
    return redirect(url_for("iniciar_sesion"))


@aplicacion.route("/")
@login_required
def panel():
    metricas = obtener_metricas()
    modelos = metricas["modelos"]
    mejor_clave = max(modelos, key=lambda clave: modelos[clave]["f1"])
    return render_template(
        "dashboard.html",
        metricas=metricas,
        modelos=modelos,
        mejor_clave=mejor_clave,
        conjunto=metricas["conjunto_datos"],
    )


@aplicacion.route("/solicitud")
@login_required
def nueva_solicitud():
    return render_template("solicitud.html", modelos=NOMBRES_MODELOS, valores={}, mensaje_error=None)


@aplicacion.route("/predecir", methods=["POST"])
@login_required
def predecir():
    clave_modelo = request.form.get("modelo", "")
    valores = request.form.to_dict()
    if clave_modelo not in NOMBRES_MODELOS:
        return render_template(
            "solicitud.html",
            modelos=NOMBRES_MODELOS,
            valores=valores,
            mensaje_error="Seleccione un modelo válido.",
        )

    try:
        solicitud = {
            "numero_dependientes": int(request.form["numero_dependientes"]),
            "nivel_educativo": request.form["nivel_educativo"],
            "trabajador_independiente": request.form["trabajador_independiente"],
            "ingreso_anual": float(request.form["ingreso_anual"]),
            "monto_solicitado": float(request.form["monto_solicitado"]),
            "plazo_credito": int(request.form["plazo_credito"]),
            "puntaje_cibil": int(request.form["puntaje_cibil"]),
            "valor_activos_residenciales": float(request.form["valor_activos_residenciales"]),
            "valor_activos_comerciales": float(request.form["valor_activos_comerciales"]),
            "valor_activos_lujo": float(request.form["valor_activos_lujo"]),
            "valor_activos_bancarios": float(request.form["valor_activos_bancarios"]),
        }
        if solicitud["numero_dependientes"] < 0 or solicitud["plazo_credito"] <= 0:
            raise ValueError
        if not 300 <= solicitud["puntaje_cibil"] <= 900:
            raise ValueError
        if any(solicitud[columna] < 0 for columna in CARACTERISTICAS_NUMERICAS):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return render_template(
            "solicitud.html",
            modelos=NOMBRES_MODELOS,
            valores=valores,
            mensaje_error="Revise los valores: deben ser numéricos, positivos y el puntaje CIBIL debe estar entre 300 y 900.",
        )

    modelo = joblib.load(DIRECTORIO_MODELOS / f"{clave_modelo}.joblib")
    datos = pd.DataFrame([solicitud], columns=CARACTERISTICAS)
    probabilidad = float(modelo.predict_proba(datos)[0][1])
    aprobada = bool(modelo.predict(datos)[0])
    return render_template(
        "resultado.html",
        aprobada=aprobada,
        probabilidad=probabilidad,
        nombre_modelo=NOMBRES_MODELOS[clave_modelo],
        datos=solicitud,
        version_modelo=obtener_metricas()["version"],
    )


@aplicacion.route("/comparacion")
@login_required
def comparacion():
    metricas = obtener_metricas()
    return render_template("comparacion.html", modelos=metricas["modelos"], version=metricas["version"])


@aplicacion.route("/reentrenar", methods=["POST"])
@login_required
def reentrenar():
    entrenar_modelos()
    return redirect(url_for("panel"))


if __name__ == "__main__":
    aplicacion.run(debug=True, use_reloader=False)
