# Analisis de sensibilidad

## Escenarios

Los escenarios estan definidos en:

```text
escenarios_sensibilidad.py
```

Incluyen:

- `S0_base`
- `S1_demanda_110`
- `S2_demanda_120`
- `S3_sillas_14`
- `S4_sillas_16`
- `S5_enfermeras_5`
- `S6_earlycap_200`
- `S7_duracion_110`
- `S8_eventos_expost`

## Correr Interdia

Ejemplo para caso base con 1 replica:

```cmd
cd /d "C:\Users\ianma\OneDrive\Escritorio\Codigo Capstone\CapstoneG15"
python "Analisis Sensibilidad\correr_interdia_sensibilidad.py" --scenarios S0_base --replicas 1 --workers 1 --gurobi-threads 6 --time-limit 1800 --mip-gap 0.01 --overwrite
```

Ejemplo para escenarios estructurales:

```cmd
python "Analisis Sensibilidad\correr_interdia_sensibilidad.py" --scenarios S0_base S1_demanda_110 S2_demanda_120 S3_sillas_14 S4_sillas_16 S6_earlycap_200 S7_duracion_110 --replicas 1 --workers 1 --gurobi-threads 6 --time-limit 1800 --mip-gap 0.01 --overwrite
```

Outputs:

```text
Analisis Sensibilidad\resultados_interdia\<scenario_id>\
```

## Correr Intradia

Ejemplo para caso base:

```cmd
python "Analisis Sensibilidad\correr_intradia_sensibilidad.py" --scenarios S0_base --replicas 1 --workers-intradia 1 --replica-workers 1 --overwrite
```

Ejemplo para escenarios con output Interdia propio y enfermera +1:

```cmd
python "Analisis Sensibilidad\correr_intradia_sensibilidad.py" --scenarios S0_base S1_demanda_110 S2_demanda_120 S3_sillas_14 S4_sillas_16 S5_enfermeras_5 S6_earlycap_200 S7_duracion_110 --replicas 1 --workers-intradia 1 --replica-workers 1 --overwrite
```

Outputs:

```text
Analisis Sensibilidad\resultados_intradia\<scenario_id>\
```

## Eventos clinicos ex post

Ejemplo sobre la replica 1 del caso base:

```cmd
python "Analisis Sensibilidad\simular_eventos_expost.py" --input-xlsx "Analisis Sensibilidad\resultados_intradia\S0_base\solution_intradia-1.xlsx" --output-csv "Analisis Sensibilidad\resultados_intradia\S8_eventos_expost\eventos_expost_base_replica1.csv" --simulations 1000
```

Parametros por defecto:

- vomito: probabilidad `0.072`, atraso `+1` modulo.
- vasovagal: probabilidad `0.028`, atraso `+2` modulos.

