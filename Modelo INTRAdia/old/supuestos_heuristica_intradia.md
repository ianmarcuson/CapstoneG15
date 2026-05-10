# Supuestos y Condiciones del Caso Base (Heurística "Primera Silla Disponible")

Este documento detalla todas las reglas de negocio, supuestos operacionales y lógicas algorítmicas implementadas en el script `heuristica_primera_silla_disponible.py`. Este modelo sirve como un **caso base reactivo** (baseline) para contrastar los resultados del modelo matemático de optimización intradía.

## 1. Naturaleza del Modelo (Reactivo vs. Proactivo)
- **Cero Anticipación (Miopía algorítmica):** El algoritmo es puramente reactivo y codicioso (greedy). Toma decisiones sesión por sesión en orden estricto de prioridad, asignando el primer bloque horario en el que la sesión cabe.
- **Sin Optimización Global:** No se realiza generación de columnas ni se busca el "bien común" de la agenda diaria. Una vez que se asigna una silla a un paciente, esa decisión es inamovible para esa iteración, incluso si bloquea a pacientes posteriores de manera ineficiente.

## 2. Generación de Demanda (Llegadas y Citas)
- **Llegadas Reales (Sin Poisson):** Las llegadas de pacientes nuevos se leen de forma determinista y exacta desde la hoja `Motor_Arribos` del archivo `DatosV2.xlsx`.
- **Día Mínimo Factible (`t_min`):** Cuando un paciente ingresa al sistema en el día `Rp`, sus sesiones se pre-calculan utilizando las duraciones clínicas (TBS y TBC). El día mínimo en el que la sesión `s` del ciclo `c` puede ocurrir se fija como: `t_min = Rp + (c-1)*TBC + (s-1)*TBS`.
- **Independencia del Interdía:** A diferencia del modelo optimizado intradía (que recibe el día exacto de atención asignado por el modelo interdía), la heurística gestiona su propia cola. Solo observa el `t_min` de la sesión y avanza día a día intentando acomodarla.

## 3. Criterio de Prioridad (Orden de Atención)
En cada día `t`, las sesiones elegibles (`t_min <= t`) compiten por los recursos. Se ordenan y atienden bajo el siguiente criterio estricto:
1. **Pendientes antiguos (Mayor atraso):** Se priorizan las sesiones que debieron ocurrir en días anteriores pero fueron postergadas porque no cupieron. Se ordena por `delay_days = t - t_min` de forma descendente.
2. **Sesiones al día:** Las sesiones cuyo `t_min` es exactamente igual a `t` entran en segundo lugar.
3. **Desempate clínico/lógico:** A igual nivel de atraso, se prioriza por Tipo de Paciente (numéricamente) y luego por ID del Paciente (orden de llegada al sistema).

## 4. Reglas de Asignación Intradía
- **Primera Silla Disponible:** El algoritmo busca el primer módulo de tratamiento `m` (desde `m = 0` en adelante) donde el tratamiento completo (`Dp` módulos) se pueda realizar sin violar las capacidades de sillas ni de enfermería.
- **Farmacia en la Mañana (Mismo Día):** 
  - La preparación de los medicamentos (`Fp` módulos) ocurre estrictamente **el mismo día** de la infusión.
  - El modelo busca el primer espacio factible en la farmacia tal que termine *antes o justo a tiempo* para el inicio del tratamiento (`pharmacy_end < treatment_start`).
  - Al buscar desde el módulo `0` en adelante, naturalmente prioriza y agrupa la farmacia en la mañana ("lo antes posible"). No se permite que un paciente sea preparado el día anterior.
- **Enfermería Agregada:** El control de enfermería se realiza en modo "aggregate". Se suma 1 evento al inicio del tratamiento y 1 evento al final del tratamiento. Si la suma de inicios y términos en un módulo `m` supera la capacidad de enfermeras (`E`), ese bloque horario se descarta.

## 5. Póstergación de Sesiones (Atrasos)
- Si una sesión de la cola no logra encontrar un bloque donde las sillas, farmacia y enfermeras calcen simultáneamente, **se posterga (se pasa al día siguiente `t+1`)**.
- Esto rompe el ciclo ideal clínico, generando un atraso real en el paciente, el cual se registra en la métrica `delay_days`.
- Las sesiones que no logran completarse al final del horizonte de simulación (ej. el último día) se registran en una hoja especial llamada `Pendientes`.

## 6. Validación de Capacidades (Gurobi como Validador)
- Gurobi no toma decisiones sobre en qué silla o a qué hora va un paciente.
- Al final de cada día, Gurobi se utiliza simplemente para "auditar" la agenda generada por la heurística. Se formula un MIP fijo para comprobar que efectivamente no se violó en ningún módulo la capacidad de Sillas (`S`), Farmacéuticos (`Cf`) y Enfermeras (`E`).

## 7. Repack Opcional (Re-Optimización)
- Para mantener la naturaleza reactiva, cualquier intento de que el sistema "re-acomode" pacientes como si fuera un tetris perfecto está **apagado por defecto** (`--enable-gurobi-repack = False`).
- Si se activa (para efectos experimentales), las sesiones que la regla reactiva dejó fuera se le entregan a Gurobi en un MIP simple para ver si logra encajarlas en los "huecos" dejados por la heurística, pero este no es el comportamiento por defecto del baseline operacional.
