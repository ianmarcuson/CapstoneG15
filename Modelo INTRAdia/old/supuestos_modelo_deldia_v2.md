# Supuestos del modelo intradia V2

## Fuente original

Este documento resume los supuestos usados para `modelo_deldia_v2.py`, tomando como base:

- `modelo_column_generation.md`, que define la estructura maestro-satelite por generacion de columnas.
- `P3 - Planificacion intradia para un centro oncologico (1).pdf`, que describe el problema operacional.
- `solution_interday.xlsx`, que entrega que sesiones se atienden en cada dia.
- `Data G15.xlsx`, que entrega capacidades y parametros por tipo de paciente.

## Supuestos originales mantenidos

1. El modelo intradia recibe como dato fijo el conjunto de pacientes/sesiones de cada dia. No decide en que dia se atiende cada paciente; eso viene del modelo interdia.

2. Un patron corresponde a un horario factible para una sesion de un paciente en un dia. El patron define:

```text
inicio de farmacia
inicio de tratamiento
fin de tratamiento
ocupacion de silla por modulo
ocupacion de farmacia por modulo
uso de enfermeria por modulo
modulos extra usados
```

3. El problema maestro elige exactamente un patron por sesion:

```text
sum_k x_pk = 1
```

4. El maestro respeta capacidad de sillas, farmacia y enfermeria en cada modulo.

5. El maestro se resuelve primero como relajacion LP para obtener precios duales y despues como MIP final con `x_pk` binarias.

6. El pricing calcula patrones de costo reducido negativo usando los duales del maestro LP.

7. La sesion de tratamiento no puede comenzar antes de que la preparacion de farmacia este lista:

```text
treatment_start >= pharmacy_start + F_p
```

8. La silla se ocupa durante `D_p` modulos consecutivos desde el inicio del tratamiento.

9. La farmacia se ocupa durante `F_p` modulos consecutivos desde el inicio de preparacion.

10. La enfermeria se requiere en el modulo de inicio y en el modulo de termino de tratamiento.

11. El objetivo principal se mantiene igual que en la formulacion original:

```text
minimizar modulos extra usados
```

12. `h_p` se interpreta como los modulos extra de silla usados por el patron, consistente con:

```text
h_p = sum_{m in M_e} u_m
```

## Supuestos de datos

1. Cada fila de `solution_interday.xlsx`, hoja `Asignaciones`, representa una sesion que debe programarse intradia.

2. El identificador interno `row_idx` del modelo intradia representa una sesion del dia, no necesariamente un paciente unico global.

3. La duracion de tratamiento `D_p` se toma de la columna `modules` del output interdia.

4. La duracion de preparacion en farmacia `F_p` se toma desde `Módulos Lab.` en `Data G15.xlsx`, asociada al tipo de paciente.

5. Los modulos se indexan desde 0 en el codigo. Esto es consistente internamente aunque la formulacion escrita pueda usar indices desde 1.

6. El horizonte intradia efectivo se toma desde `Data G15.xlsx`:

```text
modulos ordinarios = 48
modulos extraordinarios = 8
total = 56
```

El enunciado P3 menciona una jornada regular de 36 modulos. Para esta implementacion se mantiene el dato del Excel porque es el usado por el resto del proyecto y por el output interdia.

7. La capacidad de sillas `S` se toma de `n_sillas`.

8. La cantidad de enfermeras `E` se toma de `n_enfermeras`.

9. La capacidad de farmacia `C_f` se toma por defecto de `n_farmaceuticos`.

10. Como alternativa, el codigo permite usar `modulos_farmacia` como `C_f` mediante:

```text
--pharmacy-capacity-source modulos_farmacia
```

Esto queda como opcion porque el archivo base trae ambos parametros y la formulacion escrita solo nombra `C_f`.

## Actualizacion V2 aplicada

### 1. Enfermeria agregada por defecto

La V2 queda por defecto en:

```text
--nurse-mode aggregate
```

Esto alinea el codigo con la restriccion R3 del `modelo_column_generation.md`:

```text
sum_p sum_k (a_pkm + b_pkm) x_pk <= E
```

La version anterior usaba por defecto `separate`, que imponia dos restricciones separadas:

```text
inicios <= E
finales <= E
```

Ese modo sigue disponible para experimentos:

```text
--nurse-mode separate
```

pero no es el default porque se aleja mas de la formulacion manual.

### 2. Desempates epsilon en el objetivo

La formulacion original minimiza solo modulos extra. En instancias holgadas, muchas soluciones tienen costo 0 y el modelo queda indiferente entre horarios muy distintos.

Para evitar esa indiferencia sin cambiar el objetivo principal, V2 usa por defecto:

```text
extra_weight = 1.0
wait_weight  = 0.0001
end_weight   = 0.000001
```

El costo de un patron queda:

```text
base_cost = extra_weight * h + wait_weight * wait + end_weight * treatment_end
```

donde:

```text
h = modulos extra de silla
wait = espera entre farmacia lista e inicio de tratamiento
treatment_end = modulo de termino del tratamiento
```

Interpretacion:

- `h` sigue siendo el objetivo primario.
- `wait` y `treatment_end` solo ordenan soluciones con igual uso de modulos extra.
- Los pesos son pequenos para no cambiar el rumbo del modelo.

Si se quiere reproducir exactamente el objetivo original, se puede correr:

```text
--wait-weight 0 --end-weight 0
```

### 3. Pricing por enumeracion completa de patrones

El `modelo_column_generation.md` describe el satelite como un MIP con variables `y, z, w, v, u, q`.

En V2, el pricing se implementa enumerando todos los pares factibles:

```text
(pharmacy_start, treatment_start)
```

para cada sesion y calculando su costo reducido.

Esto no cambia el conjunto de patrones posibles bajo los supuestos actuales, porque:

- el horizonte diario es pequeno;
- una sesion queda completamente determinada por `pharmacy_start` y `treatment_start`;
- `w, v, u, q` se derivan deterministamente.

Es una mejora computacional, no un cambio de modelado.

### 4. Columnas artificiales solo para inicializacion

La V2 permite columnas artificiales con costo muy alto para evitar que el maestro inicial sea infactible.

Supuesto:

- pueden ayudar a iniciar el algoritmo;
- no son aceptadas en la solucion final;
- si una columna artificial queda seleccionada al final, el codigo levanta error.

## Supuestos no incorporados todavia

1. La incertidumbre clinica descrita en P3 no esta modelada todavia:

```text
vomitos: posible extension de 1 modulo
evento vasovagal: posible extension de 2 modulos
```

La V2 es deterministica y usa la duracion base de tratamiento.

2. No se modela preparacion de farmacia el dia anterior. Toda preparacion debe comenzar y terminar dentro del mismo dia.

3. No se modelan descansos, turnos, ventanas preferentes ni prioridades clinicas intradia.

4. No se modela un costo explicito por uso de farmacia en modulo extra; el costo original `h_p` considera modulos extra de silla.

5. No se fuerza balance de carga dentro del dia, salvo por los desempates epsilon.

## Criterio de alineacion

La actualizacion V2 se considera alineada con el modelo manual porque:

1. Mantiene la estructura maestro-satelite.
2. Mantiene generacion de columnas.
3. Mantiene `x_pk` continuo en LP y binario en el MIP final.
4. Mantiene los duales del maestro para pricing.
5. Mantiene como objetivo principal minimizar modulos extra.
6. Cambia el default de enfermeria a la restriccion agregada escrita en el MD.
7. Agrega desempates pequenos, no un nuevo objetivo principal.

## Comandos recomendados

Caso base de un dia:

```text
py -3.11 modelo_deldia_v2.py --day 14 --output solution_deldia_v2_day14.xlsx
```

Dias 14 a 20:

```text
py -3.11 modelo_deldia_v2.py --day 14 --day 15 --day 16 --day 17 --day 18 --day 19 --day 20 --output solution_deldia_v2_days14_20.xlsx
```

Reproducir objetivo original sin desempates:

```text
py -3.11 modelo_deldia_v2.py --day 14 --wait-weight 0 --end-weight 0
```
