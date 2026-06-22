# Intradia 24h con farmacia anticipada tardia

## Objetivo

Esta carpeta contiene una variante del modelo intradia 24h que corrige el fallo observado en las replicas de Bea: muchas tareas `pharmacy_only` quedaban preparadas muy temprano en el dia `t`, por lo que el dia `t+1` recibia deadlines de tratamiento demasiado tempranos y podia volverse infactible por capacidad de sillas.

## Cambio principal

Archivo:

- `modelo_intradia_farmacia_anticipada_24h.py`

Cambios:

- Para tareas `pharmacy_only`, el costo del patron penaliza terminar antes del modulo 19.
- La inicializacion del column generation intenta primero patrones `pharmacy_only` con farmacia mas tardia.
- La restriccion de 24h sigue activa: los tratamientos preparados el dia anterior solo pueden empezar hasta el modulo en que termino la farmacia el dia previo.

La idea es que, si un remedio se prepara el dia anterior, quede listo lo mas tarde posible dentro de la ventana operativa de farmacia. Eso relaja el deadline del tratamiento del dia siguiente y evita comprimir demasiados tratamientos al inicio del dia.

## Por que este fix ataca el problema observado

En la replica 1, el dia 42 fallaba porque 16 tratamientos preparados el dia anterior debian empezar muy temprano. Con esos deadlines tempranos, las 15 sillas no alcanzaban. Al probar el mismo dia suponiendo que la farmacia previa terminaba tarde, el problema se volvio factible. Por eso el primer fix debe estar en el intradia, no en el interdia.

## Prueba recomendada antes de correr 30 replicas

Desde esta carpeta:

```bash
python correr_intradia_replicas_farmacia_tardia_24h.py \
  --replicas 5 \
  --workers-intradia 1 \
  --replica-workers 1 \
  --overwrite
```

Luego correr la replica 10, que antes era la unica exitosa, para verificar que no se rompio el caso bueno:

```bash
python correr_intradia_replicas_farmacia_tardia_24h.py \
  --replica-start 10 \
  --replica-end 10 \
  --workers-intradia 1 \
  --replica-workers 1 \
  --overwrite
```

## Corrida completa

```bash
python correr_intradia_replicas_farmacia_tardia_24h.py \
  --replicas 30 \
  --workers-intradia 1 \
  --replica-workers 1 \
  --overwrite
```

Outputs por defecto:

- `resultados_intradia_farmacia_tardia_30_replicas/solution_intradia-i.xlsx`
- `resultados_intradia_farmacia_tardia_30_replicas/log_intradia-i.txt`
- `resultados_intradia_farmacia_tardia_30_replicas/resumen_intradia_replicas.csv`
