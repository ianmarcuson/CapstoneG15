# Checklist IC95 Intradia Farmacia Tardia

## Objetivo

Procesar las 30 replicas intradia de farmacia tardia, calcular KPIs e intervalos de confianza al 95%, y dejarlos disponibles para el dashboard.

## Gate 1 - Entrada de archivos

- [x] ZIP recibido en `C:\Users\ianma\Downloads\resultados_intradia_farmacia_tardia_30_replicas.zip`.
- [x] ZIP contiene 30 archivos `solution_intradia-*.xlsx`.
- [x] ZIP contiene 30 archivos `log_intradia-*.txt`.
- [x] ZIP contiene `resumen_intradia_replicas.csv`.
- [x] `resumen_intradia_replicas.csv` reporta 30 replicas con estado `OK`.

## Gate 2 - Ubicacion canonica

- [x] Replicas copiadas a `Modelo INTRAdia V2 Farmacia Anticipada 24h Farmacia Tardia\resultados_intradia_farmacia_tardia_30_replicas`.
- [x] Replicas copiadas a `Analisis Sensibilidad\resultados_intradia\S0_base`.
- [x] `S0_base` queda como caso base para dashboard y sensibilidad.

## Gate 3 - Calculo de IC 95%

- [x] Ejecutado `Modelo INTRAdia V2\calcular_ic_intradia_replicas.py`.
- [x] Input usado: `Analisis Sensibilidad\resultados_intradia\S0_base`.
- [x] Replicas validas procesadas: 30.
- [x] Generado `kpis_intradia_replicas.csv`.
- [x] Generado `kpis_intradia_ic95.csv`.
- [x] Generado `kpis_intradia_daily_replicas.csv`.
- [x] Generado `kpis_intradia_daily_ic95.csv`.
- [x] Generado `kpis_intradia_most_loaded_day_freq.csv`.

## Gate 4 - Disponibilidad para dashboard

- [x] `Dashboard\dashboard_v2_app.py` prioriza `Analisis Sensibilidad\resultados_intradia\S0_base`.
- [x] La pestana `IC 95%` lee los CSV `kpis_intradia_*.csv` desde `S0_base`.
- [x] La pestana de sensibilidad usa `S0_base` como escenario base.
- [x] Los CSV de IC tambien fueron copiados a la carpeta canonica del modelo intradia.

## Gate 5 - Salida esperada

- [x] Dashboard base usa `solution_intradia-1.xlsx` desde `S0_base`.
- [x] Dashboard IC usa las 30 replicas agregadas.
- [x] Caso base listo para comparacion contra escenarios de sensibilidad.

## Comando reproducible

```cmd
cd /d "C:\Users\ianma\OneDrive\Escritorio\Codigo Capstone\CapstoneG15"
python "Modelo INTRAdia V2\calcular_ic_intradia_replicas.py" --input-dir "C:\Users\ianma\OneDrive\Escritorio\Codigo Capstone\CapstoneG15\Analisis Sensibilidad\resultados_intradia\S0_base" --output-dir "C:\Users\ianma\OneDrive\Escritorio\Codigo Capstone\CapstoneG15\Analisis Sensibilidad\resultados_intradia\S0_base"
```
