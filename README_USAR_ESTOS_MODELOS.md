# Modelos vigentes para farmacia anticipada 24h

Usar estas carpetas para las corridas actuales:

1. Interdia:

```text
Modelo Interdia Farmacia Anticipada H450 EarlyCap250
```

2. Intradia:

```text
Modelo INTRAdia V2 Farmacia Anticipada 24h Farmacia Tardia
```

## Correr 30 replicas interdia

```cmd
cd /d "C:\Users\ianma\OneDrive\Escritorio\Codigo Capstone\CapstoneG15\Modelo Interdia Farmacia Anticipada H450 EarlyCap250"
python generar_replicas_farmacia_anticipada_earlycap250.py --replicas 30 --workers 1 --gurobi-threads 4 --time-limit 1800 --mip-gap 0.01 --overwrite
```

Los outputs quedan en:

```text
Modelo Interdia Farmacia Anticipada H450 EarlyCap250\resultados_farmacia_anticipada_h450_earlycap250
```

## Correr 30 replicas intradia

Ejecutar despues de que existan las 30 replicas interdia:

```cmd
cd /d "C:\Users\ianma\OneDrive\Escritorio\Codigo Capstone\CapstoneG15\Modelo INTRAdia V2 Farmacia Anticipada 24h Farmacia Tardia"
python correr_intradia_replicas_farmacia_tardia_24h.py --replicas 30 --interdia-dir "..\Modelo Interdia Farmacia Anticipada H450 EarlyCap250\resultados_farmacia_anticipada_h450_earlycap250" --input-pattern "solution_interday_farmacia_anticipada_h450_earlycap250-{replica}.xlsx" --workers-intradia 1 --replica-workers 1 --overwrite
```

Mantener `--workers-intradia 1`: el modelo 24h necesita resolver secuencialmente porque el dia `d+1` usa el `pharmacy_end` real calculado en el dia `d`.

