# CrediVision

Aplicación web en Flask para estimar la aprobación de solicitudes de crédito mediante modelos de Machine Learning. Incluye preparación del dataset, entrenamiento de modelos, comparación de métricas y autenticación de usuarios con SQL Server.

## Funcionalidades

- Registro, inicio y cierre de sesión.
- Predicción de una solicitud de crédito con Regresión Logística, Árbol de Decisión o Random Forest.
- Comparación de exactitud, precisión, sensibilidad, F1 y ROC-AUC.
- Preparación y validación del dataset de origen.
- Conexión a SQL Server mediante autenticación de Windows.

> El historial de predicciones está previsto en la base de datos, pero aún no forma parte de la aplicación web.

## Estructura

```text
web_creditos/
├── app.py                   # Rutas y lógica de Flask
├── db.py                    # Conexión a SQL Server
├── crear_sqlserver.sql      # Esquema de base de datos
├── preparar_dataset.py      # Limpieza y normalización de datos
├── train_models.py          # Entrenamiento y métricas
├── loan_approval_dataset.csv
├── datos/
├── modelos/
├── static/
└── templates/
```

## Requisitos

- Python 3.11 o superior.
- SQL Server 2019 o superior.
- Controlador **ODBC Driver 18 for SQL Server**.

## Instalación

1. Crea y activa un entorno virtual:

   ```powershell
   python -m venv .venv
   .venv\Scripts\Activate.ps1
   ```

2. Instala las dependencias:

   ```powershell
   pip install -r requirements.txt
   ```

3. En SQL Server Management Studio, ejecuta `crear_sqlserver.sql` con una cuenta que pueda crear la base y sus tablas.

4. Copia `.env.example` con el nombre `.env` y ajusta la conexión si es necesario:

   ```powershell
   Copy-Item .env.example .env
   ```

   Para autenticación de Windows, configura por ejemplo:

   ```env
   SQL_AUTHENTICATION=windows
   SQL_SERVER=HEYKAN
   SQL_DATABASE=credivision
   SQL_DRIVER=ODBC Driver 18 for SQL Server
   SQL_ENCRYPT=yes
   SQL_TRUST_SERVER_CERTIFICATE=yes
   ```

5. Si necesitas regenerar los datos procesados y los modelos:

   ```powershell
   python preparar_dataset.py
   python train_models.py
   ```

6. Ejecuta la aplicación:

   ```powershell
   python app.py
   ```

   Abre `http://127.0.0.1:5000`, registra una cuenta e inicia sesión.

## Uso del software

1. **Crear una cuenta.** En la pantalla inicial selecciona **Regístrate**. Completa el nombre, usuario, correo y contraseña. La contraseña se guarda cifrada en SQL Server.

2. **Iniciar sesión.** Ingresa con el usuario o correo electrónico registrado. Las páginas de CrediVision requieren una sesión activa.

3. **Revisar el panel.** El resumen muestra el tamaño del dataset, la distribución de aprobaciones y las métricas principales de los tres modelos.

4. **Generar una predicción.** Abre **Nueva solicitud**, selecciona el modelo que deseas utilizar y completa los campos del perfil, condiciones del crédito y activos declarados. Al enviar el formulario se mostrará la clasificación y la probabilidad estimada de aprobación.

5. **Comparar modelos.** En **Comparar modelos** consulta las métricas de evaluación y la matriz de confusión de Regresión Logística, Árbol de Decisión y Random Forest para elegir el modelo más adecuado.

6. **Reentrenar cuando sea necesario.** Desde el panel puedes pulsar **Reentrenar localmente**. La aplicación vuelve a generar los archivos de modelos y el resumen de métricas usando el dataset procesado actual.

7. **Cerrar sesión.** Utiliza el botón **Cerrar sesión** de la barra lateral al terminar de usar la aplicación.

## Base de datos

El esquema crea las tablas `usuarios`, `modelos` y `predicciones`. Actualmente la aplicación usa `usuarios` para la autenticación. Las tablas de modelos y predicciones están preparadas para una futura implementación del historial.

## Variables de entorno

| Variable | Descripción |
| --- | --- |
| `SQL_AUTHENTICATION` | `windows` para autenticación integrada o `sql` para autenticación SQL. |
| `SQL_SERVER` | Nombre o dirección del servidor SQL Server. |
| `SQL_DATABASE` | Nombre de la base de datos. |
| `SQL_DRIVER` | Controlador ODBC instalado. |
| `SQL_ENCRYPT` | Activa el cifrado de la conexión. |
| `SQL_TRUST_SERVER_CERTIFICATE` | Acepta el certificado del servidor durante el desarrollo local. |
| `FLASK_SECRET_KEY` | Clave usada para firmar sesiones de Flask. |

El archivo `.env` contiene configuración local y no debe subirse al repositorio.
