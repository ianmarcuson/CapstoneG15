# Plan de casos de sensibilidad

## Escenarios a evaluar

- **Base:** escenario actual del modelo.
  **Cambio:** sin cambios.

- **Demanda +10%:** aumento moderado en llegadas de pacientes.
  **Cambio:** multiplicar tasas de llegada por `1.10`.

- **Demanda +20%:** aumento alto en llegadas de pacientes.
  **Cambio:** multiplicar tasas de llegada por `1.20`.

- **Una silla menos:** menor capacidad fisica de atencion.
  **Cambio:** reducir sillas de `15` a `14`.

- **Una silla mas:** mayor capacidad fisica de atencion.
  **Cambio:** aumentar sillas de `15` a `16`.

- **Una enfermera mas:** mayor capacidad de atencion intradia.
  **Cambio:** aumentar enfermeras de `4` a `5`.

- **Farmacia anticipada mas restrictiva:** menor uso permitido de preparaciones del dia anterior.
  **Cambio:** reducir limite de farmacia anticipada de `250` a `200` modulos de tratamiento por dia.

- **Tratamientos +10%:** tratamientos mas largos, sin cambiar farmacia.
  **Cambio:** multiplicar modulos de tratamiento por `1.10` y redondear hacia arriba.

- **Eventos clinicos ex post:** evaluar robustez de la jornada ya planificada.
  **Cambio:** simular vomito con `7.2%` y `+1` modulo; vasovagal con `2.8%` y `+2` modulos.

## Implementacion recomendada

Separar el analisis en dos familias:

- **Sensibilidad estructural:** demanda, sillas, enfermeras, farmacia anticipada y duracion de tratamientos. Estos escenarios se corren antes de optimizar.
- **Robustez ex post:** eventos clinicos sobre agendas ya planificadas. Este escenario se simula despues de obtener el output intradia.

## Caso base

El caso base debe correrse primero porque sirve como comparador para todos los escenarios.

Flujo:

1. Correr 30 replicas del Interdia EarlyCap250.
2. Con esos outputs, correr 30 replicas del Intradia Farmacia Tardia 24h.
3. Usar los KPIs base como referencia.

