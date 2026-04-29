# Revision de optimizacion del modelo interdia

## Objetivo

Este documento resume oportunidades para disminuir la cantidad de variables y acelerar la ejecucion del codigo sin cambiar la logica matematica actual del modelo.

El modelo actual usa variables binarias:

```text
x[p,t,c,s] = 1 si el paciente p recibe la sesion s del ciclo c en el dia t
```

La formulacion impone:

```text
Cada sesion se agenda exactamente una vez.
La capacidad diaria no puede superar la capacidad mas holgura.
Las sesiones consecutivas dentro de un ciclo respetan TBS.
Las sesiones equivalentes entre ciclos respetan TBC.
W representa la ocupacion maxima diaria.
```

## Diagnostico de la ejecucion actual

En una corrida con 150 pacientes y horizonte de 365 dias, se observaron aproximadamente:

```text
878.788 variables x binarias
879.154 variables totales
5.848 restricciones
22 segundos de construccion del modelo antes de optimizar
```

Los principales costos de construccion fueron:

```text
Creacion de variables x: 7.39s
Restricciones R4, tiempos entre sesiones: 5.62s
Restricciones R2, capacidad diaria: 2.89s
Restricciones R5, ocupacion maxima: 2.92s
```

El problema principal no es solo el numero de restricciones, sino el numero de variables binarias y el costo de construir repetidamente expresiones sobre esas variables.

## Cambio conservador 1: podar variables temporalmente imposibles

Actualmente se crea `x[p,t,c,s]` para casi todo dia `t >= arrival[p]`.

Sin embargo, muchas de esas variables no pueden pertenecer a ningun calendario completo factible, porque las restricciones de separacion obligan a que las sesiones anteriores y posteriores queden dentro del horizonte.

Para cada paciente `p`, ciclo `c`, sesion `s`, se puede acotar el rango valido de dias `t`.

Sea:

```text
arrival[p] = dia de llegada del paciente p
C[p]       = numero de ciclos
S[p]       = numero de sesiones por ciclo
TBS[p]     = dias entre sesiones consecutivas
TBC[p]     = dias entre ciclos
H          = horizonte de planificacion
```

Para una variable `x[p,t,c,s]`, el dia mas temprano admisible es:

```text
earliest_t = arrival[p] + c*TBC[p] + s*TBS[p]
```

El dia mas tardio admisible es:

```text
latest_t = H - 1 - ((C[p] - 1 - c)*TBC[p] + (S[p] - 1 - s)*TBS[p])
```

Entonces se crean variables solo si:

```text
earliest_t <= t <= latest_t
```

### Por que no cambia la logica

Este cambio no agrega ni elimina soluciones factibles reales. Solo evita crear variables que necesariamente serian cero en cualquier solucion factible, porque no permitirian completar el calendario del paciente dentro del horizonte y respetando las separaciones impuestas por el modelo.

Formalmente, si `x[p,t,c,s] = 1` pero `t < earliest_t`, alguna sesion anterior deberia quedar antes de `arrival[p]`. Si `t > latest_t`, alguna sesion posterior deberia quedar despues de `H - 1`. Por lo tanto, esas variables no pueden participar en una solucion factible.

## Cambio conservador 2: reutilizar la ocupacion diaria

Actualmente las restricciones de capacidad diaria y ocupacion maxima construyen dos veces la misma expresion:

```text
sum(modulos[p] * x[p,t,c,s])
```

Se puede definir una sola vez:

```text
daily_load[t] = sum(modulos[p] * x[p,t,c,s])
```

y luego usar:

```text
daily_load[t] <= capacity + y[t]
daily_load[t] <= W
```

### Por que no cambia la logica

Las restricciones resultantes son algebraicamente iguales a las actuales. Solo cambia la forma de construirlas en codigo.

## Cambio conservador 3: precomputar indices

Actualmente varias restricciones recorren rangos completos y verifican:

```python
if (p, t, c, s) in x
```

Esto genera costo innecesario en Python.

Se recomienda construir estructuras auxiliares al crear variables:

```python
vars_by_session[p, c, s] = [(t, x[p,t,c,s]), ...]
vars_by_day[t] = [(p, c, s, x[p,t,c,s]), ...]
```

Luego:

```text
R1 usa vars_by_session[p,c,s]
R2 y R5 usan vars_by_day[t]
R3 y R4 usan vars_by_session para construir los dias esperados
```

### Por que no cambia la logica

Los indices contienen exactamente las mismas variables que el diccionario `x`, solo organizadas para construir mas rapido las restricciones.

## Cambio conservador 4: extraer la solucion en una sola pasada

Actualmente la solucion se extrae recorriendo todas las variables `x`, y luego la ocupacion diaria se calcula volviendo a recorrer todas las variables para cada dia.

Eso equivale aproximadamente a:

```text
H * cantidad_variables_x
```

Con 365 dias y 878.788 variables, son mas de 300 millones de revisiones.

Se puede hacer en una sola pasada:

```python
daily_occupancy = {t: 0 for t in T}

for (p,t,c,s), var in x.items():
    if var.X > 0.5:
        assignments.append(...)
        daily_occupancy[t] += patient_info[p]["modules"]
```

### Por que no cambia la logica

La ocupacion diaria calculada es la misma. Solo se acumula al mismo tiempo que se leen las asignaciones activas.

## Cambios que no se recomiendan sin validacion matematica

Una reformulacion mas agresiva seria reemplazar `x[p,t,c,s]` por una variable de inicio:

```text
z[p,start_day] = 1 si el paciente p comienza en start_day
```

Eso podria reducir mucho el numero de variables, pero si cambia la formulacion explicita del problema. Solo seria equivalente si el calendario completo del paciente queda completamente determinado por su primer dia.

Como el objetivo actual es no cambiar la logica, esta reformulacion deberia revisarse aparte y compararse contra el modelo actual en instancias pequenas.

## Recomendacion

Implementar primero estos cambios, en este orden:

```text
1. Podar variables x usando earliest_t y latest_t.
2. Crear vars_by_session y vars_by_day.
3. Reutilizar daily_load[t] en R2 y R5.
4. Extraer solucion y ocupacion diaria en una sola pasada.
```

Estos cambios mantienen la logica actual, pero reducen el tamano efectivo del modelo y el tiempo de construccion en Python.

## Criterio de validacion

Para verificar equivalencia practica:

```text
1. Ejecutar modelo original en una instancia pequena con semilla fija.
2. Ejecutar modelo optimizado con los mismos datos.
3. Comparar:
   - valor objetivo
   - W
   - suma de holguras
   - ocupacion diaria
   - asignaciones por paciente
4. Si hay multiples soluciones optimas, aceptar diferencias de asignacion si mantienen el mismo objetivo y cumplen las mismas restricciones.
```

La validacion debe considerar que Gurobi puede devolver soluciones optimas distintas si hay empates.
