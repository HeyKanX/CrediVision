
from __future__ import annotations

from pathlib import Path

import pandas as pd


DIRECTORIO_BASE = Path(__file__).resolve().parent
RUTA_ORIGEN = DIRECTORIO_BASE / "loan_approval_dataset.csv"
RUTA_DESTINO = DIRECTORIO_BASE / "datos" / "solicitudes_credito.csv"

NOMBRES_EN_ESPANOL = {
    "loan_id": "id_solicitud",
    "no_of_dependents": "numero_dependientes",
    "education": "nivel_educativo",
    "self_employed": "trabajador_independiente",
    "income_annum": "ingreso_anual",
    "loan_amount": "monto_solicitado",
    "loan_term": "plazo_credito",
    "cibil_score": "puntaje_cibil",
    "residential_assets_value": "valor_activos_residenciales",
    "commercial_assets_value": "valor_activos_comerciales",
    "luxury_assets_value": "valor_activos_lujo",
    "bank_asset_value": "valor_activos_bancarios",
    "loan_status": "estado_aprobacion",
}

CATEGORIAS_EN_ESPANOL = {
    "nivel_educativo": {"Graduate": "Profesional", "Not Graduate": "No profesional"},
    "trabajador_independiente": {"Yes": "Sí", "No": "No"},
    "estado_aprobacion": {"Approved": "Aprobado", "Rejected": "Rechazado"},
}

CATEGORIAS_VALIDAS = {
    "nivel_educativo": {"Profesional", "No profesional"},
    "trabajador_independiente": {"Sí", "No"},
    "estado_aprobacion": {"Aprobado", "Rechazado"},
}

COLUMNAS_NUMERICAS = [
    "numero_dependientes",
    "ingreso_anual",
    "monto_solicitado",
    "plazo_credito",
    "puntaje_cibil",
    "valor_activos_residenciales",
    "valor_activos_comerciales",
    "valor_activos_lujo",
    "valor_activos_bancarios",
]

COLUMNAS_ENTERAS = {"numero_dependientes", "plazo_credito", "puntaje_cibil"}
RANGOS_VALIDOS = {
    "numero_dependientes": (0, None),
    "ingreso_anual": (0, None),
    "monto_solicitado": (0, None),
    "plazo_credito": (1, None),
    "puntaje_cibil": (300, 900),
    "valor_activos_residenciales": (0, None),
    "valor_activos_comerciales": (0, None),
    "valor_activos_lujo": (0, None),
    "valor_activos_bancarios": (0, None),
}


def contar_nulos(datos: pd.DataFrame) -> dict[str, int]:
    """Devuelve únicamente las columnas que tienen valores faltantes."""
    return {
        columna: int(cantidad)
        for columna, cantidad in datos.isna().sum().items()
        if cantidad
    }


def mostrar_detalle(titulo: str, detalle: dict[str, int]) -> None:
    print(f"\n{titulo}")
    if not detalle:
        print("  Ninguno.")
        return
    for elemento, cantidad in detalle.items():
        print(f"  - {elemento}: {cantidad}")


def validar_estructura(datos: pd.DataFrame) -> list[str]:
    columnas_esperadas = set(NOMBRES_EN_ESPANOL)
    columnas_actuales = set(datos.columns)
    faltantes = sorted(columnas_esperadas - columnas_actuales)
    if faltantes:
        raise ValueError(
            "Faltan columnas requeridas en el dataset fuente: " + ", ".join(faltantes)
        )
    return sorted(columnas_actuales - columnas_esperadas)


def normalizar_textos(datos: pd.DataFrame) -> int:
    """Elimina espacios externos y cuenta cuántas celdas fueron normalizadas."""
    celdas_normalizadas = 0
    for columna in datos.select_dtypes(include=["object", "string"]).columns:
        texto_original = datos[columna]
        texto_limpio = texto_original.astype("string").str.strip()
        celdas_normalizadas += int(
            (texto_original.notna() & (texto_original.astype("string") != texto_limpio)).sum()
        )
        datos[columna] = texto_limpio
    return celdas_normalizadas


def normalizar_categorias(datos: pd.DataFrame) -> tuple[dict[str, int], dict[str, int]]:
    """Traduce categorías y convierte etiquetas no reconocidas en valores faltantes."""
    categorias_traducidas: dict[str, int] = {}
    categorias_no_validas: dict[str, int] = {}

    for columna, equivalencias in CATEGORIAS_EN_ESPANOL.items():
        valores_originales = datos[columna].copy()
        datos[columna] = datos[columna].replace(equivalencias)
        categorias_traducidas[columna] = int(
            (valores_originales.notna() & (valores_originales != datos[columna])).sum()
        )

        no_validas = datos[columna].notna() & ~datos[columna].isin(CATEGORIAS_VALIDAS[columna])
        categorias_no_validas[columna] = int(no_validas.sum())
        datos.loc[no_validas, columna] = pd.NA

    return categorias_traducidas, categorias_no_validas


def limpiar_numericos(datos: pd.DataFrame) -> tuple[dict[str, int], dict[str, int]]:
    """Convierte números y marca conversiones o rangos inválidos como faltantes."""
    conversiones_invalidas: dict[str, int] = {}
    rangos_invalidos: dict[str, int] = {}

    for columna in COLUMNAS_NUMERICAS:
        valores_originales = datos[columna]
        valores_numericos = pd.to_numeric(valores_originales, errors="coerce")
        conversiones_invalidas[columna] = int(
            (valores_originales.notna() & valores_numericos.isna()).sum()
        )

        minimo, maximo = RANGOS_VALIDOS[columna]
        fuera_de_rango = valores_numericos.notna() & (valores_numericos < minimo)
        if maximo is not None:
            fuera_de_rango |= valores_numericos.notna() & (valores_numericos > maximo)
        if columna in COLUMNAS_ENTERAS:
            fuera_de_rango |= valores_numericos.notna() & (valores_numericos % 1 != 0)

        rangos_invalidos[columna] = int(fuera_de_rango.sum())
        valores_numericos.loc[fuera_de_rango] = pd.NA
        datos[columna] = valores_numericos

    return conversiones_invalidas, rangos_invalidos


def preparar_dataset() -> Path:
    if not RUTA_ORIGEN.exists():
        raise FileNotFoundError(f"No se encontró el dataset fuente: {RUTA_ORIGEN}")

    datos = pd.read_csv(RUTA_ORIGEN)
    datos.columns = datos.columns.str.strip()
    filas_iniciales = len(datos)
    columnas_no_esperadas = validar_estructura(datos)
    datos = datos[list(NOMBRES_EN_ESPANOL)]

    nulos_originales = contar_nulos(datos)
    espacios_eliminados = normalizar_textos(datos)
    duplicados_exactos = int(datos.duplicated().sum())
    datos = datos.drop_duplicates().copy()

    datos = datos.rename(columns=NOMBRES_EN_ESPANOL)
    filas_id_duplicado = int(datos.duplicated(subset="id_solicitud").sum())
    datos = datos.drop_duplicates(subset="id_solicitud", keep="first").copy()

    categorias_traducidas, categorias_no_validas = normalizar_categorias(datos)
    conversiones_invalidas, rangos_invalidos = limpiar_numericos(datos)

    etiquetas_faltantes = int(datos["estado_aprobacion"].isna().sum())
    datos = datos.dropna(subset=["estado_aprobacion"]).copy()
    nulos_preservados = contar_nulos(datos)

    RUTA_DESTINO.parent.mkdir(exist_ok=True)
    datos.to_csv(RUTA_DESTINO, index=False, encoding="utf-8")

    print("=" * 62)
    print("INFORME DE PREPARACIÓN DEL DATASET")
    print("=" * 62)
    print(f"Archivo de origen : {RUTA_ORIGEN}")
    print(f"Filas leídas      : {filas_iniciales}")
    print(f"Columnas leídas   : {len(NOMBRES_EN_ESPANOL)}")
    mostrar_detalle("Nulos encontrados al inicio:", nulos_originales)
    print(f"\nDuplicados exactos eliminados : {duplicados_exactos}")
    print(f"IDs duplicados eliminados       : {filas_id_duplicado}")
    print(f"Celdas con espacios normalizadas: {espacios_eliminados}")
    mostrar_detalle("Categorías traducidas al español:", categorias_traducidas)
    mostrar_detalle("Categorías no válidas detectadas:", {k: v for k, v in categorias_no_validas.items() if v})
    mostrar_detalle("Valores no numéricos detectados:", {k: v for k, v in conversiones_invalidas.items() if v})
    mostrar_detalle("Valores fuera de rango detectados:", {k: v for k, v in rangos_invalidos.items() if v})
    print(f"\nFilas eliminadas por etiqueta inválida o faltante: {etiquetas_faltantes}")
    mostrar_detalle("Valores faltantes preservados para imputar dentro del pipeline:", nulos_preservados)
    if columnas_no_esperadas:
        print("\nColumnas no esperadas excluidas: " + ", ".join(columnas_no_esperadas))
    print("\nRESULTADO FINAL")
    print(f"Filas válidas      : {len(datos)}")
    print(f"Nulos en predictores: {sum(nulos_preservados.values())} (se imputan al entrenar cada partición)")
    print(f"Archivo generado   : {RUTA_DESTINO}")
    print("=" * 62)
    return RUTA_DESTINO


if __name__ == "__main__":
    preparar_dataset()
