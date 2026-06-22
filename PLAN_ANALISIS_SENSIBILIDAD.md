# Plan de implementacion: analisis de sensibilidad

## Objetivo

Evaluar el comportamiento del sistema bajo 6 escenarios definidos:

| ID | Escenario | Cambio |
|---|---|---|
| S0 | Base | Parametros actuales |
| S1 | Demanda +10% | Multiplicar tasas de llegada por 1.10 |
| S2 | Demanda +20% | Multiplicar tasas de llegada por 1.20 |
| S3 | Una silla menos | `N_SILLAS_OVERRIDE = 14` |
| S4 | Una silla mas | `N_SILLAS_OVERRIDE = 16` |
| S5 | Una enfermera mas | `n_enfermeras = 5` para intradia |
| S6 | Farmacia anticipada mas restrictiva | `EARLY_PREP_TREATMENT_CAP = 200` |

Nota: aunque el usuario quiere elegir 5 o 6 casos, el plan deja los 6 configurados. El escenario base (`S0`) se mantiene como control para comparar.

## Recomendacion de diseno

Conviene crear scripts nuevos de sensibilidad, no duplicar 6 carpetas completas.

Propuesta:

```text
Analisis Sensibilidad/
├── escenarios_sensibilidad.py
├── correr_interdia_sensibilidad.py
├── correr_intradia_sensibilidad.py
├── consolidar_resultados_sensibilidad.py
└── README_SENSIBILIDAD.md
```

Ventajas:

- Se mantiene un unico modelo vigente de Interdia: `Modelo Interdia Farmacia Anticipada H450 EarlyCap250`.
- Se mantiene un unico modelo vigente de Intradia: `Modelo INTRAdia V2 Farmacia Anticipada 24h Farmacia Tardia`.
- Cada escenario queda definido por parametros, no por copias manuales del codigo.
- Los outputs quedan separados por carpeta de escenario, evitando pisar resultados.
- Es mas facil correr solo un escenario o relanzar uno fallido.

## Escenarios

Archivo `escenarios_sensibilidad.py`:

```python
SCENARIOS = [
    {
        "id": "S0_base",
        "label": "Base",
        "arrival_multiplier": 1.0,
        "n_sillas_override": None,
        "n_enfermeras_override": None,
        "early_prep_cap": 250,
    },
    {
        "id": "S1_demanda_110",
        "label": "Demanda +10%",
        "arrival_multiplier": 1.10,
        "n_sillas_override": None,
        "n_enfermeras_override": None,
        "early_prep_cap": 250,
    },
    {
        "id": "S2_demanda_120",
        "label": "Demanda +20%",
        "arrival_multiplier": 1.20,
        "n_sillas_override": None,
        "n_enfermeras_override": None,
        "early_prep_cap": 250,
    },
    {
        "id": "S3_sillas_14",
        "label": "Una silla menos",
        "arrival_multiplier": 1.0,
        "n_sillas_override": 14,
        "n_enfermeras_override": None,
        "early_prep_cap": 250,
    },
    {
        "id": "S4_sillas_16",
        "label": "Una silla mas",
        "arrival_multiplier": 1.0,
        "n_sillas_override": 16,
        "n_enfermeras_override": None,
        "early_prep_cap": 250,
    },
    {
        "id": "S5_enfermeras_5",
        "label": "Una enfermera mas",
        "arrival_multiplier": 1.0,
        "n_sillas_override": None,
        "n_enfermeras_override": 5,
        "early_prep_cap": 250,
    },
    {
        "id": "S6_earlycap_200",
        "label": "Farmacia anticipada cap 200",
        "arrival_multiplier": 1.0,
        "n_sillas_override": None,
        "n_enfermeras_override": None,
        "early_prep_cap": 200,
    },
]
```

## Cambio 1: Interdia de sensibilidad

Crear `correr_interdia_sensibilidad.py`.

Debe reutilizar la logica del runner:

```text
Modelo Interdia Farmacia Anticipada H450 EarlyCap250/generar_replicas_farmacia_anticipada_earlycap250.py
```

Pero agregando soporte para escenarios.

### Para demanda +10% y +20%

Modificar la generacion de replicas `DatosV2-i.xlsx`:

```python
lam = tasas[tipo_id] * arrival_multiplier
values = rng.poisson(lam=lam, size=len(day_rows))
```

Eso cambia la cantidad simulada de llegadas, manteniendo la estructura de los tipos de pacientes.

### Para sillas +1 / -1

No hay que editar Excel. El runner puede parchear `params.py` en memoria:

```python
P.N_SILLAS_OVERRIDE = 14
```

o:

```python
P.N_SILLAS_OVERRIDE = 16
```

Eso afecta el Interdia porque cambia:

```text
K = n_sillas * modulos_ordinarios
K_ext = n_sillas * modulos_extraordinarios
```

### Para enfermera +1

El Interdia no usa directamente enfermeras en su MIP. Este escenario debe:

- correr Interdia igual que base,
- correr Intradia con `n_enfermeras = 5`.

Para evitar recalcular innecesariamente, hay dos opciones:

1. Correr Interdia propio para S5 igualmente, para mantener todas las carpetas homogeneas.
2. Reutilizar los outputs Interdia de S0 y correr solo Intradia con enfermeras +1.

Recomendacion: usar opcion 1 si se quiere simpleza operacional; opcion 2 si se quiere ahorrar tiempo.

### Para EarlyCap 200

Parchear en memoria:

```python
P.EARLY_PREP_TREATMENT_CAP = 200
```

Esto obliga al Interdia a usar menos farmacia anticipada por dia de tratamiento.

## Cambio 2: Intradia de sensibilidad

Crear `correr_intradia_sensibilidad.py`.

Debe ejecutar:

```text
Modelo INTRAdia V2 Farmacia Anticipada 24h Farmacia Tardia/correr_intradia_replicas_farmacia_tardia_24h.py
```

para cada escenario.

Cada escenario debe apuntar a:

```text
Analisis Sensibilidad/resultados_interdia/{scenario_id}/
```

y guardar outputs en:

```text
Analisis Sensibilidad/resultados_intradia/{scenario_id}/
```

### Para enfermera +1

El modelo Intradia actualmente lee `n_enfermeras` desde `Data G15.xlsx`. Para este escenario hay dos alternativas:

1. Crear una copia temporal de `Data G15.xlsx` con `n_enfermeras = 5` y pasarla con `--base-data`.
2. Agregar argumento nuevo al modelo Intradia:

```bash
--n-enfermeras-override 5
```

Recomendacion tecnica: agregar el argumento `--n-enfermeras-override`. Es mas limpio que editar/copiar Excel y deja trazabilidad en el comando.

Implementacion:

```python
parser.add_argument("--n-enfermeras-override", type=int, default=None)
```

Despues de `load_base_data()`:

```python
if n_enfermeras_override is not None:
    base_data["capacity"]["n_enfermeras"] = n_enfermeras_override
```

El runner de replicas Intradia debe aceptar tambien ese argumento y pasarlo al modelo.

## Cambio 3: estructura de outputs

Propuesta:

```text
Analisis Sensibilidad/
├── resultados_interdia/
│   ├── S0_base/
│   ├── S1_demanda_110/
│   ├── S2_demanda_120/
│   ├── S3_sillas_14/
│   ├── S4_sillas_16/
│   ├── S5_enfermeras_5/
│   └── S6_earlycap_200/
└── resultados_intradia/
    ├── S0_base/
    ├── S1_demanda_110/
    ├── S2_demanda_120/
    ├── S3_sillas_14/
    ├── S4_sillas_16/
    ├── S5_enfermeras_5/
    └── S6_earlycap_200/
```

Cada carpeta Interdia debe contener:

```text
DatosV2-i.xlsx
solution_interday_{scenario_id}-{replica}.xlsx
log_interdia_{scenario_id}-{replica}.txt
resumen_corridas_{scenario_id}.csv
```

Cada carpeta Intradia debe contener:

```text
solution_intradia-{replica}.xlsx
log_intradia-{replica}.txt
resumen_intradia_replicas.csv
```

## Cambio 4: consolidacion de resultados

Crear `consolidar_resultados_sensibilidad.py`.

Debe producir:

```text
Analisis Sensibilidad/resultados_sensibilidad_resumen.csv
```

Columnas sugeridas:

```text
scenario_id
scenario_label
replica
interdia_status
intradia_status
pacientes_programados
sesiones_agendadas
ocupacion_maxima_interdia
dia_mayor_ocupacion_interdia
modulos_extra_interdia
max_tratamiento_farmacia_previa
utilizacion_sillas_total
utilizacion_sillas_regular
ocupacion_enfermeria
ocupacion_farmacia
dia_mas_ocupado_intradia
```

Si ya existen scripts de KPI Intradia, reutilizarlos en vez de recalcular desde cero.

## Orden recomendado de implementacion

1. Crear carpeta `Analisis Sensibilidad`.
2. Crear `escenarios_sensibilidad.py`.
3. Adaptar/crear runner Interdia de sensibilidad.
4. Agregar soporte `arrival_multiplier`.
5. Agregar parcheo en memoria de:
   - `N_SILLAS_OVERRIDE`
   - `EARLY_PREP_TREATMENT_CAP`
6. Agregar argumento `--n-enfermeras-override` al Intradia y a su runner de replicas.
7. Crear runner Intradia de sensibilidad.
8. Probar con 1 replica y 2 escenarios:
   - `S0_base`
   - `S6_earlycap_200`
9. Probar escenario `S5_enfermeras_5` para validar override de enfermeras.
10. Correr 30 replicas por escenario.
11. Consolidar resultados.

## Comandos esperados

Interdia para todos los escenarios:

```bash
python "Analisis Sensibilidad/correr_interdia_sensibilidad.py" \
  --scenarios S0_base S1_demanda_110 S2_demanda_120 S3_sillas_14 S4_sillas_16 S5_enfermeras_5 S6_earlycap_200 \
  --replicas 30 \
  --workers 1 \
  --gurobi-threads 4 \
  --time-limit 1800 \
  --mip-gap 0.01 \
  --overwrite
```

Intradia para todos los escenarios:

```bash
python "Analisis Sensibilidad/correr_intradia_sensibilidad.py" \
  --scenarios S0_base S1_demanda_110 S2_demanda_120 S3_sillas_14 S4_sillas_16 S5_enfermeras_5 S6_earlycap_200 \
  --replicas 30 \
  --workers-intradia 1 \
  --replica-workers 1 \
  --overwrite
```

Consolidar:

```bash
python "Analisis Sensibilidad/consolidar_resultados_sensibilidad.py"
```

## Riesgos y decisiones

### Costo computacional

7 escenarios incluyendo base por 30 replicas implica:

```text
210 corridas Interdia + 210 corridas Intradia
```

Si el tiempo es acotado, correr:

```text
S1, S2, S3, S4, S5, S6
```

y usar la corrida base ya existente como `S0`.

### Comparabilidad estadistica

Para que los escenarios sean comparables, usar las mismas seeds por replica en todos los escenarios:

```text
replica i usa seed_base + i
```

Asi las diferencias vienen del escenario y no de ruido aleatorio distinto.

### Enfermera +1

Este escenario afecta solo Intradia. Hay que reportarlo como mejora operacional intradia, no como cambio de planificacion interdia.

### EarlyCap 200

Este escenario puede mejorar factibilidad intradia pero reducir flexibilidad interdia. Es probable que:

- baje el uso de farmacia anticipada,
- suba algo la ocupacion o espera,
- reduzca riesgo de dias con deadlines tempranos.

