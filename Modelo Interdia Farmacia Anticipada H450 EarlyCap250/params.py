# =============================================================================
# ARCHIVO DE PARÁMETROS - MODELO INTRADIA CENTRO ONCOLÓGICO
# =============================================================================
# Todos los parámetros configurables del modelo se definen aquí.
# NO modificar el archivo principal model.py para ajustar parámetros.
# =============================================================================

# -----------------------------------------------------------------------------
# RUTAS DE ARCHIVOS
# -----------------------------------------------------------------------------
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
EXCEL_PATH = BASE_DIR.parent / "Modelo Interdia" / "DatosV2.xlsx"

# Nombres de hojas del Excel
SHEET_CONFIG         = "Configuracion"
SHEET_PARAMS         = "Parametros_Globales"
SHEET_ARRIBOS        = "Motor_Arribos"
SHEET_BAJAS          = "Motor_Bajas"
SHEET_PACIENTES_ACT  = "Pacientes_Activos"

# -----------------------------------------------------------------------------
# HORIZONTE DE PLANIFICACIÓN
# -----------------------------------------------------------------------------
# Número de días a optimizar (ventana deslizante desde el día 1)
HORIZONTE_DIAS = 450

# Día de inicio del horizonte (1-indexed, usualmente 1)
DIA_INICIO = 1

# -----------------------------------------------------------------------------
# CAPACIDAD DEL CENTRO ONCOLÓGICO
# -----------------------------------------------------------------------------
# K = n_sillas * modulos_ordinarios
# Estos valores se leen del Excel (Parametros_Globales), pero pueden
# sobreescribirse aquí si se desea un escenario diferente.
# Poner None para usar los valores del Excel.
N_SILLAS_OVERRIDE             = None   # ej: 15
MODULOS_ORDINARIOS_OVERRIDE   = None   # ej: 48
MODULOS_EXTRAORDINARIOS_OVERRIDE = None  # ej: 8

# Limite de modulos de tratamiento que pueden depender de farmacia del dia
# anterior en un mismo dia de tratamiento. Evita concentrar demasiadas sesiones
# con pharmacy_offset=-1, que luego deben iniciar temprano en el intradia.
EARLY_PREP_TREATMENT_CAP = 250

# -----------------------------------------------------------------------------
# PARÁMETROS DE LA FUNCIÓN OBJETIVO
# z = min α·W + β·Σyt + γ·Σ(t - Rp)·xp,t,1,1
# -----------------------------------------------------------------------------
ALPHA = 0.1   # Peso para la ocupación máxima diaria (W)
BETA  = 100.0 # Peso para uso de holgura/capacidad extra (yt)
GAMMA = 1.0   # Peso para el tiempo de espera desde derivación

# -----------------------------------------------------------------------------
# RESTRICCIÓN CLÍNICA DE ESPERA MÁXIMA
# -----------------------------------------------------------------------------
# Número máximo de días que puede esperar un paciente para su PRIMERA sesión
# (contado desde su día de derivación Rp).
# Limita el rango de t para x[p,t,1,1] a [Rp, Rp + MAX_ESPERA].
# Esto reduce drásticamente el número de variables binarias.
MAX_ESPERA = 14

# -----------------------------------------------------------------------------
# PARÁMETROS DEL SOLVER GUROBI
# -----------------------------------------------------------------------------
TIME_LIMIT_SECONDS = 1800     # Tiempo máximo de resolución (segundos)
MIP_GAP            = 0.01    # Gap de optimalidad aceptable (1% - Mínimo viable)
THREADS            = 4       # 0 = usar todos los núcleos disponibles
LOG_TO_CONSOLE     = True    # Mostrar log de Gurobi en consola

# Corte temprano por estancamiento del MIP gap (callback de Gurobi)
STALL_SECONDS = 60
STALL_MIN_RUNTIME = 120
STALL_MIN_GAP_IMPROVEMENT = 1e-4
USE_GAP_STALL_CALLBACK = False

# -----------------------------------------------------------------------------
# CONFIGURACIÓN DE SALIDA
# -----------------------------------------------------------------------------
# Archivo XLSX compatible con el modelo intradía/interdía
OUTPUT_XLSX = "solution_interday_farmacia_anticipada_h450_earlycap250.xlsx"

# Archivo CSV con el schedule resultante
OUTPUT_CSV  = "schedule_resultado_farmacia_anticipada_h450_earlycap250.csv"

# Archivo de resumen por día
OUTPUT_SUMMARY_CSV = "resumen_diario_farmacia_anticipada_h450_earlycap250.csv"

# Mostrar estadísticas detalladas al final
PRINT_STATS = True

# -----------------------------------------------------------------------------
# ESCENARIOS DE PESOS (para pruebas comparativas)
# -----------------------------------------------------------------------------
# Si RUN_ALL_SCENARIOS = False, se ejecutarán todos los escenarios de esta lista
# uno por uno, generando outputs separados y un CSV comparativo.
# Si RUN_ALL_SCENARIOS = False, se usa ALPHA, BETA, GAMMA base (arriba).
RUN_ALL_SCENARIOS = False

# Tiempo límite por escenario (segundos). Se usa en lugar de TIME_LIMIT_SECONDS
# cuando se ejecutan múltiples escenarios.
SCENARIO_TIME_LIMIT_SECONDS = 180

PARAM_SCENARIOS = [
    {
        "name": "S1_a01_b100_g1",
        "ALPHA": 0.1,
        "BETA": 100.0,
        "GAMMA": 1.0,
    },
    {
        "name": "S2_a01_b100_g5",
        "ALPHA": 0.1,
        "BETA": 100.0,
        "GAMMA": 5.0,
    },
]
