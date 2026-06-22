# Interdia H450 Farmacia Anticipada con EarlyCap250

## Cambio

Esta variante agrega una restriccion al modelo interdia para evitar que demasiados tratamientos de un mismo dia dependan de farmacia preparada el dia anterior.

Parametro:

```python
EARLY_PREP_TREATMENT_CAP = 250
```

Restriccion agregada para cada dia de tratamiento `t`:

```text
sum(modulos_tratamiento * prep[p, t, c, s, t-1]) <= 250
```

Esto limita los modulos de tratamiento con `pharmacy_offset = -1` en cada dia. La motivacion es que esas sesiones quedan forzadas a iniciar temprano en el intradia por la vigencia de 24h del medicamento.

## Archivos

- `model_interdia_farmacia_anticipada_earlycap250.py`: modelo interdia modificado.
- `params.py`: parametros y nombres de salida propios de esta variante.
- `generar_replicas_farmacia_anticipada_earlycap250.py`: runner de replicas que importa el modelo modificado.

## Salidas

Corrida base:

- `solution_interday_farmacia_anticipada_h450_earlycap250.xlsx`
- `schedule_resultado_farmacia_anticipada_h450_earlycap250.csv`
- `resumen_diario_farmacia_anticipada_h450_earlycap250.csv`

El resumen diario incluye columnas de auditoria:

- `tratamiento_modulos_farmacia_previa`
- `sesiones_farmacia_previa`
- `limite_tratamiento_farmacia_previa`

## Probar una corrida base

```cmd
cd /d "C:\Users\ianma\OneDrive\Escritorio\Codigo Capstone\CapstoneG15\Modelo Interdia Farmacia Anticipada H450 EarlyCap250"
python model_interdia_farmacia_anticipada_earlycap250.py
```

## Probar una replica

```cmd
python generar_replicas_farmacia_anticipada_earlycap250.py --replicas 1 --workers 1 --gurobi-threads 4 --time-limit 1800 --mip-gap 0.01 --overwrite
```

## Correr 30 replicas

```cmd
python generar_replicas_farmacia_anticipada_earlycap250.py --replicas 30 --workers 1 --gurobi-threads 4 --time-limit 1800 --mip-gap 0.01 --overwrite
```

Los outputs de replicas quedan en:

```text
resultados_farmacia_anticipada_h450_earlycap250/
```

Para usarlos en el intradia, apuntar `--interdia-dir` a esa carpeta y `--input-pattern` a:

```text
solution_interday_farmacia_anticipada_h450_earlycap250-{replica}.xlsx
```

