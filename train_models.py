"""Entrena y guarda los tres modelos del prototipo de créditos."""

from __future__ import annotations

import json
from pathlib import Path

import joblib
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, precision_recall_fscore_support, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_validate, train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler
from sklearn.tree import DecisionTreeClassifier


DIRECTORIO_BASE = Path(__file__).resolve().parent
RUTA_DATASET = DIRECTORIO_BASE / "datos" / "solicitudes_credito.csv"
DIRECTORIO_MODELOS = DIRECTORIO_BASE / "modelos"
SEMILLA_ALEATORIA = 42
PLIEGUES_CV = 5
VERSION_MODELOS = "v1.2-pipeline-cv5"

CARACTERISTICAS_NUMERICAS = [
    "numero_dependientes", "ingreso_anual", "monto_solicitado", "plazo_credito",
    "puntaje_cibil", "valor_activos_residenciales", "valor_activos_comerciales",
    "valor_activos_lujo", "valor_activos_bancarios",
]
CARACTERISTICAS_CATEGORICAS = ["nivel_educativo", "trabajador_independiente"]
CARACTERISTICAS = CARACTERISTICAS_NUMERICAS + CARACTERISTICAS_CATEGORICAS


def cargar_dataset() -> pd.DataFrame:
    if not RUTA_DATASET.exists():
        raise FileNotFoundError(
            f"No se encontró el dataset local en: {RUTA_DATASET}. Ejecute preparar_dataset.py."
        )
    datos = pd.read_csv(RUTA_DATASET)
    datos["estado_aprobacion"] = datos["estado_aprobacion"].map(
        {"Aprobado": 1, "Rechazado": 0}
    )
    if datos["estado_aprobacion"].isna().any():
        raise ValueError("La columna estado_aprobacion contiene etiquetas no reconocidas.")
    return datos


def crear_preprocesador(escalar_numericas: bool) -> ColumnTransformer:
    pasos_numericos = [("imputador", SimpleImputer(strategy="median"))]
    if escalar_numericas:
        pasos_numericos.append(("escalador", StandardScaler()))
    return ColumnTransformer(
        transformers=[
            ("numericas", Pipeline(pasos_numericos), CARACTERISTICAS_NUMERICAS),
            (
                "categoricas",
                Pipeline([
                    ("imputador", SimpleImputer(strategy="most_frequent")),
                    ("codificador", OneHotEncoder(handle_unknown="ignore")),
                ]),
                CARACTERISTICAS_CATEGORICAS,
            ),
        ]
    )


def calcular_metricas(modelo: Pipeline, datos_prueba: pd.DataFrame, etiquetas_prueba: pd.Series) -> dict:
    predicciones = modelo.predict(datos_prueba)
    probabilidades = modelo.predict_proba(datos_prueba)[:, 1]
    precision, sensibilidad, f1, _ = precision_recall_fscore_support(
        etiquetas_prueba, predicciones, average="binary", zero_division=0
    )
    return {
        "exactitud": round(float(accuracy_score(etiquetas_prueba, predicciones)), 4),
        "precision": round(float(precision), 4),
        "sensibilidad": round(float(sensibilidad), 4),
        "f1": round(float(f1), 4),
        "roc_auc": round(float(roc_auc_score(etiquetas_prueba, probabilidades)), 4),
        "matriz_confusion": confusion_matrix(etiquetas_prueba, predicciones).tolist(),
    }


def calcular_validacion_cruzada(
    modelo: Pipeline,
    datos_entrenamiento: pd.DataFrame,
    etiquetas_entrenamiento: pd.Series,
    particiones: StratifiedKFold,
) -> dict:
    """Evalúa el pipeline solo dentro del entrenamiento, reajustándolo en cada pliegue."""
    puntuaciones = cross_validate(
        modelo,
        datos_entrenamiento,
        etiquetas_entrenamiento,
        cv=particiones,
        scoring={
            "exactitud": "accuracy",
            "precision": "precision",
            "sensibilidad": "recall",
            "f1": "f1",
            "roc_auc": "roc_auc",
        },
        n_jobs=1,
        error_score="raise",
    )
    return {
        nombre: {
            "media": round(float(puntuaciones[f"test_{nombre}"].mean()), 4),
            "desviacion": round(float(puntuaciones[f"test_{nombre}"].std(ddof=1)), 4),
        }
        for nombre in ("exactitud", "precision", "sensibilidad", "f1", "roc_auc")
    }


def entrenar_modelos() -> dict:
    datos = cargar_dataset()
    variables_entrada = datos[CARACTERISTICAS]
    etiqueta = datos["estado_aprobacion"]
    entrenamiento, prueba, etiquetas_entrenamiento, etiquetas_prueba = train_test_split(
        variables_entrada, etiqueta, test_size=0.2, stratify=etiqueta, random_state=SEMILLA_ALEATORIA
    )
    particiones_cv = StratifiedKFold(
        n_splits=PLIEGUES_CV, shuffle=True, random_state=SEMILLA_ALEATORIA
    )
    definiciones = {
        "regresion_logistica": (
            "Regresión Logística",
            Pipeline([
                ("preprocesamiento", crear_preprocesador(escalar_numericas=True)),
                ("modelo", LogisticRegression(max_iter=1000, class_weight="balanced")),
            ]),
        ),
        "arbol_decision": (
            "Árbol de Decisión",
            Pipeline([
                ("preprocesamiento", crear_preprocesador(escalar_numericas=False)),
                ("modelo", DecisionTreeClassifier(max_depth=5, min_samples_leaf=10, class_weight="balanced", random_state=SEMILLA_ALEATORIA)),
            ]),
        ),
        "bosque_aleatorio": (
            "Random Forest",
            Pipeline([
                ("preprocesamiento", crear_preprocesador(escalar_numericas=False)),
                ("modelo", RandomForestClassifier(n_estimators=250, max_depth=10, min_samples_leaf=3, class_weight="balanced", n_jobs=-1, random_state=SEMILLA_ALEATORIA)),
            ]),
        ),
    }

    DIRECTORIO_MODELOS.mkdir(exist_ok=True)
    metricas_modelos = {}
    for clave, (nombre, modelo) in definiciones.items():
        cv = calcular_validacion_cruzada(
            modelo, entrenamiento, etiquetas_entrenamiento, particiones_cv
        )
        modelo.fit(entrenamiento, etiquetas_entrenamiento)
        joblib.dump(modelo, DIRECTORIO_MODELOS / f"{clave}.joblib")
        metricas_modelos[clave] = {
            "nombre": nombre,
            **calcular_metricas(modelo, prueba, etiquetas_prueba),
            "validacion_cruzada": cv,
        }

    clave_recomendado = max(
        metricas_modelos,
        key=lambda clave: (
            metricas_modelos[clave]["validacion_cruzada"]["f1"]["media"],
            metricas_modelos[clave]["validacion_cruzada"]["roc_auc"]["media"],
        ),
    )

    resumen = {
        "conjunto_datos": {
            "registros": int(len(datos)), "aprobadas": int(etiqueta.sum()),
            "rechazadas": int((1 - etiqueta).sum()), "registros_entrenamiento": int(len(entrenamiento)),
            "registros_prueba": int(len(prueba)),
        },
        "modelos": metricas_modelos,
        "validacion_cruzada": {
            "metodo": "StratifiedKFold",
            "pliegues": PLIEGUES_CV,
            "semilla": SEMILLA_ALEATORIA,
            "conjunto": "entrenamiento",
        },
        "clave_modelo_recomendado": clave_recomendado,
        "version": VERSION_MODELOS,
    }
    (DIRECTORIO_MODELOS / "metricas.json").write_text(
        json.dumps(resumen, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return resumen


if __name__ == "__main__":
    print(json.dumps(entrenar_modelos(), ensure_ascii=False, indent=2))
