# Capstone G15 - Programacion Oncologica Interdia e Intradia

Este proyecto aborda la planificacion de tratamientos oncologicos en un centro de infusion, separando la decision en dos niveles. Primero, el **modelo Interdia** asigna sesiones a dias del horizonte mediante un MILP. Luego, el **modelo Intradia** agenda las sesiones dentro de cada dia mediante generacion de columnas, considerando sillas, farmacia, enfermeria, modulos ordinarios y modulos extraordinarios.

El repositorio tambien incluye un **dashboard Streamlit** para revisar resultados, KPIs, intervalos de confianza y visualizaciones diarias. La forma mas rapida de revisar los resultados actuales es usar la visualizacion oficial o ejecutar el dashboard localmente, porque el repositorio ya incluye outputs generados para 30 replicas.

Visualizacion oficial de los datos:

https://capstoneg15.streamlit.app/

## Estructura del repositorio

```text
CapstoneG15/
+-- Data Inicial/
|   +-- Data G15.xlsx
+-- Modelo Interdia/
|   +-- params.py
|   +-- model_interdia.py
|   +-- generar_intervalos_subcarpeta2.py
|   +-- resultados_30_replicas/
+-- Dashboard/
|   +-- dashboard_intradia_app.py
|   +-- calc_kpi_heuristica.py
|   +-- rewrite_dashboard_script.py
|   +-- solution_heuristica_240.xlsx
|   +-- test-240.xlsx
+-- Modelo INTRAdia/
|   +-- modelo_deldia_v2_adaptado.py
|   +-- heuristica_primera_silla_disponible.py
|   +-- old/
+-- Modelo INTRAdia V2/
|   +-- modelo_intradia_optimizado.py
|   +-- correr_intradia_replicas.py
|   +-- calcular_ic_intradia_replicas.py
|   +-- resultados_intradia_30_replicas/
+-- requirements.txt
```

## Opcion recomendada: abrir el dashboard con resultados actuales

La visualizacion oficial esta publicada en:

https://capstoneg15.streamlit.app/

Desde la raiz del repositorio:

```bash
streamlit run "Dashboard/dashboard_intradia_app.py"
```

El dashboard carga automaticamente:

- El resultado principal intradia desde `Dashboard/test-240.xlsx`.
- El caso base heuristico desde `Dashboard/solution_heuristica_240.xlsx`.
- Los intervalos de confianza desde `Modelo INTRAdia V2/resultados_intradia_30_replicas/`.

En la pestana **IC 95%** se muestran:

- KPIs agregados con promedio, minimo y maximo de las replicas.
- Tablas detalladas de KPIs, replicas, frecuencia del dia mas cargado e intervalos diarios.
- Grafico diario con media, intervalo de confianza y caso base cuando corresponde.

## Flujo completo para regenerar resultados

El flujo completo tiene tres etapas:

1. Generar replicas y resolver el modelo interdia.
2. Resolver el modelo intradia para esas replicas.
3. Calcular intervalos de confianza y abrir el dashboard.

### 1. Generar y resolver replicas Interdia

Desde la carpeta `Modelo Interdia`:

```bash
cd "Modelo Interdia"
python generar_intervalos_subcarpeta2.py --replicas 30 --out-dir resultados_30_replicas --workers 2 --overwrite
```

Este comando genera, para cada replica:

- `DatosV2-i.xlsx`
- `solution_interday-i.xlsx`
- `log_interdia-i.txt`

La carpeta esperada por la etapa intradia es:

```text
Modelo Interdia/resultados_30_replicas/
```

Para una prueba corta, se puede correr menos replicas:

```bash
python generar_intervalos_subcarpeta2.py --replicas 2 --out-dir resultados_prueba --workers 1 --overwrite
```

### 2. Resolver replicas Intradia

Desde la carpeta `Modelo INTRAdia V2`:

```bash
cd "../Modelo INTRAdia V2"
python correr_intradia_replicas.py --replicas 30 --workers-intradia 2 --replica-workers 1 --overwrite
```

Por defecto, este script lee:

```text
../Modelo Interdia/resultados_30_replicas/solution_interday-i.xlsx
```

y escribe:

```text
Modelo INTRAdia V2/resultados_intradia_30_replicas/
```

Cada replica genera:

- `solution_intradia-i.xlsx`
- `log_intradia-i.txt`
- resumen de ejecucion de replicas

Para una prueba corta:

```bash
python correr_intradia_replicas.py --replicas 2 --workers-intradia 1 --replica-workers 1 --no-all-days --max-days 10 --overwrite
```

Si se quiere resolver solo un rango de dias:

```bash
python correr_intradia_replicas.py --replicas 2 --workers-intradia 1 --replica-workers 1 --no-all-days --start-day 1 --end-day 30 --overwrite
```

### 3. Calcular intervalos de confianza

Desde `Modelo INTRAdia V2`:

```bash
python calcular_ic_intradia_replicas.py --input-dir resultados_intradia_30_replicas
```

Este comando genera:

- `kpis_intradia_replicas.csv`
- `kpis_intradia_ic95.csv`
- `kpis_intradia_daily_ic95.csv`
- `kpis_intradia_most_loaded_day_freq.csv`
- `kpis_intradia_errores.csv`, solo si hubo errores

Luego se puede volver a abrir el dashboard:

```bash
cd ..
streamlit run "Dashboard/dashboard_intradia_app.py"
```

## Ejecutar un solo modelo Interdia

Si no se necesitan replicas, se puede ejecutar el modelo interdia base desde `Modelo Interdia`:

```bash
cd "Modelo Interdia"
python model_interdia.py
```

Los parametros principales se configuran en:

```text
Modelo Interdia/params.py
```

Ese archivo define:

- archivo de entrada `DatosV2.xlsx`
- horizonte de planificacion
- capacidad ordinaria y extraordinaria
- pesos de la funcion objetivo
- limite de tiempo y gap del solver
- nombres de outputs

## Ejecutar un solo modelo Intradia

Desde `Modelo INTRAdia V2`:

```powershell
python modelo_intradia_optimizado.py ^
  --solution "../Modelo Interdia/resultados_30_replicas/solution_interday-1.xlsx" ^
  --base-data "../Data Inicial/Data G15.xlsx" ^
  --output "solution_intradia_prueba.xlsx" ^
  --all-days ^
  --workers 1
```

En PowerShell tambien se puede escribir en una sola linea:

```bash
python modelo_intradia_optimizado.py --solution "../Modelo Interdia/resultados_30_replicas/solution_interday-1.xlsx" --base-data "../Data Inicial/Data G15.xlsx" --output "solution_intradia_prueba.xlsx" --all-days --workers 1
```

Argumentos utiles:

- `--day N`: resuelve solo el dia `N`. Puede repetirse.
- `--all-days`: resuelve todos los dias con sesiones.
- `--max-days N`: resuelve los primeros `N` dias si no se usa `--all-days`.
- `--workers 1`: ejecuta la resolucion intradia en modo secuencial.
- `--extra-weight`: peso por modulo extraordinario.
- `--wait-weight`: peso por espera entre farmacia lista e inicio de tratamiento.
- `--end-weight`: peso por terminar mas tarde dentro del dia.

## Outputs principales

### Modelo Interdia

El output clave para el modelo intradia es:

```text
solution_interday-i.xlsx
```

Contiene la asignacion de sesiones a dias.

### Modelo Intradia

El output clave es:

```text
solution_intradia-i.xlsx
```

Hojas importantes:

- `Programacion`: agenda de pacientes, inicio/fin de farmacia, inicio/fin de tratamiento, espera y modulos extra.
- `Ocupacion_Modulos`: ocupacion por modulo del dia para sillas, farmacia y enfermeria.
- `Resumen_Dias`: KPIs agregados por dia.
- `Pendientes`: pacientes o sesiones no atendidas, si existen.

### Intervalos de confianza

Los CSV de la carpeta `resultados_intradia_30_replicas` resumen la variabilidad entre replicas:

- `kpis_intradia_ic95.csv`: KPIs agregados con media, minimo, maximo e IC 95%.
- `kpis_intradia_daily_ic95.csv`: KPIs por dia con media, minimo, maximo e IC 95%.
- `kpis_intradia_replicas.csv`: una fila por replica.
- `kpis_intradia_most_loaded_day_freq.csv`: frecuencia del dia mas cargado.
