from __future__ import annotations

import json
import os
import secrets
from functools import wraps

import joblib
import pandas as pd
import pyodbc
from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
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
CAMPOS_SOLICITUD = [
    "numero_dependientes", "nivel_educativo", "trabajador_independiente",
    "ingreso_anual", "monto_solicitado", "plazo_credito", "puntaje_cibil",
    "valor_activos_residenciales", "valor_activos_comerciales",
    "valor_activos_lujo", "valor_activos_bancarios",
]


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


def obtener_modelo_recomendado(metricas: dict) -> dict:
    """Selecciona el modelo con mejor F1; ROC-AUC resuelve los empates."""
    clave, datos = max(
        metricas["modelos"].items(),
        key=lambda elemento: (elemento[1]["f1"], elemento[1]["roc_auc"]),
    )
    return {"clave": clave, **datos}


def sincronizar_modelos(metricas: dict) -> dict[str, int]:
    """Guarda las métricas y devuelve los identificadores de modelos en SQL Server."""
    recomendado = obtener_modelo_recomendado(metricas)
    ids_modelos: dict[str, int] = {}
    with conexion() as conexion_sql:
        cursor = conexion_sql.cursor()
        cursor.execute("UPDATE dbo.modelos SET es_recomendado = 0")
        for clave, datos in metricas["modelos"].items():
            fila = cursor.execute(
                "SELECT id FROM dbo.modelos WHERE clave = ? AND version = ?",
                clave,
                metricas["version"],
            ).fetchone()
            valores = (
                datos["nombre"], datos["exactitud"], datos["precision"],
                datos["sensibilidad"], datos["f1"], datos["roc_auc"],
                clave == recomendado["clave"],
            )
            if fila:
                cursor.execute(
                    """
                    UPDATE dbo.modelos
                    SET nombre = ?, exactitud = ?, precision_modelo = ?, sensibilidad = ?,
                        f1 = ?, roc_auc = ?, es_recomendado = ?
                    WHERE id = ?
                    """,
                    *valores,
                    fila.id,
                )
                ids_modelos[clave] = int(fila.id)
            else:
                cursor.execute(
                    """
                    INSERT INTO dbo.modelos
                        (clave, nombre, version, exactitud, precision_modelo, sensibilidad, f1, roc_auc, es_recomendado)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    clave,
                    *valores[:1],
                    metricas["version"],
                    *valores[1:],
                )
                fila_nueva = cursor.execute(
                    "SELECT id FROM dbo.modelos WHERE clave = ? AND version = ?",
                    clave,
                    metricas["version"],
                ).fetchone()
                ids_modelos[clave] = int(fila_nueva.id)
    return ids_modelos


def guardar_prediccion(solicitud: dict, modelo_id: int, aprobada: bool, probabilidad: float) -> int:
    """Persiste la solicitud evaluada para el historial del usuario autenticado."""
    with conexion() as conexion_sql:
        cursor = conexion_sql.cursor()
        fila = cursor.execute(
            """
            INSERT INTO dbo.predicciones (
                usuario_id, modelo_id, numero_dependientes, nivel_educativo,
                trabajador_independiente, ingreso_anual, monto_solicitado,
                plazo_credito, puntaje_cibil, valor_activos_residenciales,
                valor_activos_comerciales, valor_activos_lujo, valor_activos_bancarios,
                resultado, probabilidad_aprobacion
            )
            OUTPUT INSERTED.id
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            session["usuario_id"],
            modelo_id,
            *(solicitud[campo] for campo in CAMPOS_SOLICITUD),
            "Aprobado" if aprobada else "Rechazado",
            probabilidad,
        ).fetchone()
        if not fila:
            raise RuntimeError("SQL Server no devolvió el identificador de la predicción guardada.")
    return int(fila[0])


def obtener_resumen_personal(usuario_id: int) -> dict:
    """Calcula los indicadores personales mostrados en Mi actividad."""
    with conexion() as conexion_sql:
        cursor = conexion_sql.cursor()
        totales = cursor.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN resultado = N'Aprobado' THEN 1 ELSE 0 END) AS aprobadas,
                   SUM(CASE WHEN resultado = N'Rechazado' THEN 1 ELSE 0 END) AS rechazadas,
                   MAX(fecha_creacion) AS ultima_prediccion
            FROM dbo.predicciones
            WHERE usuario_id = ?
            """,
            usuario_id,
        ).fetchone()
        modelo_frecuente = cursor.execute(
            """
            SELECT TOP 1 m.nombre
            FROM dbo.predicciones p
            INNER JOIN dbo.modelos m ON m.id = p.modelo_id
            WHERE p.usuario_id = ?
            GROUP BY m.nombre
            ORDER BY COUNT(*) DESC, m.nombre
            """,
            usuario_id,
        ).fetchone()
    return {
        "total": int(totales.total or 0),
        "aprobadas": int(totales.aprobadas or 0),
        "rechazadas": int(totales.rechazadas or 0),
        "ultima_prediccion": totales.ultima_prediccion,
        "modelo_frecuente": modelo_frecuente.nombre if modelo_frecuente else "Sin predicciones",
    }


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


@aplicacion.route("/mi-actividad")
@login_required
def mi_panel():
    metricas = obtener_metricas()
    recomendado = obtener_modelo_recomendado(metricas)
    sincronizar_modelos(metricas)
    resumen = obtener_resumen_personal(session["usuario_id"])
    return render_template(
        "mi_panel.html",
        resumen=resumen,
        modelo_recomendado=recomendado,
    )


@aplicacion.route("/solicitud")
@login_required
def nueva_solicitud():
    metricas = obtener_metricas()
    return render_template(
        "solicitud.html",
        modelos=NOMBRES_MODELOS,
        valores={},
        mensaje_error=None,
        modelo_recomendado=obtener_modelo_recomendado(metricas),
    )


@aplicacion.route("/predecir", methods=["POST"])
@login_required
def predecir():
    clave_modelo = request.form.get("modelo", "")
    valores = request.form.to_dict()
    if clave_modelo not in NOMBRES_MODELOS:
        metricas = obtener_metricas()
        return render_template(
            "solicitud.html",
            modelos=NOMBRES_MODELOS,
            valores=valores,
            mensaje_error="Seleccione un modelo válido.",
            modelo_recomendado=obtener_modelo_recomendado(metricas),
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
        metricas = obtener_metricas()
        return render_template(
            "solicitud.html",
            modelos=NOMBRES_MODELOS,
            valores=valores,
            mensaje_error="Revise los valores: deben ser numéricos, positivos y el puntaje CIBIL debe estar entre 300 y 900.",
            modelo_recomendado=obtener_modelo_recomendado(metricas),
        )

    modelo = joblib.load(DIRECTORIO_MODELOS / f"{clave_modelo}.joblib")
    datos = pd.DataFrame([solicitud], columns=CARACTERISTICAS)
    probabilidad = float(modelo.predict_proba(datos)[0][1])
    aprobada = bool(modelo.predict(datos)[0])
    metricas = obtener_metricas()
    ids_modelos = sincronizar_modelos(metricas)
    prediccion_id = guardar_prediccion(solicitud, ids_modelos[clave_modelo], aprobada, probabilidad)
    return render_template(
        "resultado.html",
        aprobada=aprobada,
        probabilidad=probabilidad,
        nombre_modelo=NOMBRES_MODELOS[clave_modelo],
        datos=solicitud,
        version_modelo=metricas["version"],
        prediccion_id=prediccion_id,
    )


@aplicacion.route("/historial")
@login_required
def historial():
    resultado = request.args.get("resultado", "")
    modelo = request.args.get("modelo", "")
    filtros = ["p.usuario_id = ?"]
    parametros: list = [session["usuario_id"]]
    if resultado in {"Aprobado", "Rechazado"}:
        filtros.append("p.resultado = ?")
        parametros.append(resultado)
    if modelo:
        filtros.append("m.clave = ?")
        parametros.append(modelo)

    with conexion() as conexion_sql:
        cursor = conexion_sql.cursor()
        predicciones = cursor.execute(
            f"""
            SELECT p.id AS prediccion_id, p.fecha_creacion, p.resultado, p.probabilidad_aprobacion,
                   m.clave AS modelo_clave, m.nombre AS modelo_nombre, m.version AS modelo_version,
                   m.f1, m.roc_auc, m.es_recomendado
            FROM dbo.predicciones p
            INNER JOIN dbo.modelos m ON m.id = p.modelo_id
            WHERE {' AND '.join(filtros)}
            ORDER BY p.fecha_creacion DESC, p.id DESC
            """,
            *parametros,
        ).fetchall()
        modelos = cursor.execute(
            """
            SELECT DISTINCT m.clave, m.nombre
            FROM dbo.predicciones p
            INNER JOIN dbo.modelos m ON m.id = p.modelo_id
            WHERE p.usuario_id = ?
            ORDER BY m.nombre
            """,
            session["usuario_id"],
        ).fetchall()
    return render_template(
        "historial.html",
        predicciones=predicciones,
        modelos=modelos,
        filtros={"resultado": resultado, "modelo": modelo},
    )


@aplicacion.route("/historial/<int:prediccion_id>")
@login_required
def detalle_prediccion(prediccion_id: int):
    with conexion() as conexion_sql:
        prediccion = conexion_sql.cursor().execute(
            """
            SELECT p.id AS prediccion_id, p.fecha_creacion, p.resultado, p.probabilidad_aprobacion,
                   p.numero_dependientes, p.nivel_educativo, p.trabajador_independiente,
                   p.ingreso_anual, p.monto_solicitado, p.plazo_credito, p.puntaje_cibil,
                   p.valor_activos_residenciales, p.valor_activos_comerciales,
                   p.valor_activos_lujo, p.valor_activos_bancarios,
                   m.nombre AS modelo_nombre, m.version AS modelo_version,
                   m.exactitud, m.precision_modelo, m.sensibilidad, m.f1, m.roc_auc,
                   m.es_recomendado
            FROM dbo.predicciones p
            INNER JOIN dbo.modelos m ON m.id = p.modelo_id
            WHERE p.id = ? AND p.usuario_id = ?
            """,
            prediccion_id,
            session["usuario_id"],
        ).fetchone()
    if not prediccion:
        abort(404)
    return render_template("detalle_prediccion.html", prediccion=prediccion)


@aplicacion.post("/historial/comparar")
@login_required
def comparar_predicciones():
    try:
        ids = list(dict.fromkeys(int(valor) for valor in request.form.getlist("prediccion_id")))
    except ValueError:
        ids = []
    if not 2 <= len(ids) <= 3:
        flash("Seleccione dos o tres predicciones para compararlas.", "error")
        return redirect(url_for("historial"))

    marcadores = ", ".join("?" for _ in ids)
    with conexion() as conexion_sql:
        predicciones = conexion_sql.cursor().execute(
            f"""
            SELECT p.id AS prediccion_id, p.fecha_creacion, p.resultado, p.probabilidad_aprobacion,
                   p.numero_dependientes, p.nivel_educativo, p.trabajador_independiente,
                   p.ingreso_anual, p.monto_solicitado, p.plazo_credito, p.puntaje_cibil,
                   p.valor_activos_residenciales, p.valor_activos_comerciales,
                   p.valor_activos_lujo, p.valor_activos_bancarios,
                   m.nombre AS modelo_nombre, m.version AS modelo_version,
                   m.f1, m.roc_auc
            FROM dbo.predicciones p
            INNER JOIN dbo.modelos m ON m.id = p.modelo_id
            WHERE p.usuario_id = ? AND p.id IN ({marcadores})
            ORDER BY p.fecha_creacion DESC, p.id DESC
            """,
            session["usuario_id"],
            *ids,
        ).fetchall()
    if len(predicciones) != len(ids):
        abort(404)

    mismo_caso = all(
        tuple(getattr(prediccion, campo) for campo in CAMPOS_SOLICITUD)
        == tuple(getattr(predicciones[0], campo) for campo in CAMPOS_SOLICITUD)
        for prediccion in predicciones[1:]
    )
    recomendada = max(predicciones, key=lambda item: (float(item.f1), float(item.roc_auc)))
    return render_template(
        "comparar_predicciones.html",
        predicciones=predicciones,
        mismo_caso=mismo_caso,
        recomendada_id=recomendada.prediccion_id,
        modelo_recomendado_nombre=recomendada.modelo_nombre,
    )


@aplicacion.route("/comparacion")
@login_required
def comparacion():
    metricas = obtener_metricas()
    return render_template("comparacion.html", modelos=metricas["modelos"], version=metricas["version"])


@aplicacion.route("/reentrenar", methods=["POST"])
@login_required
def reentrenar():
    metricas = entrenar_modelos()
    sincronizar_modelos(metricas)
    return redirect(url_for("panel"))


if __name__ == "__main__":
    aplicacion.run(debug=True, use_reloader=False)
