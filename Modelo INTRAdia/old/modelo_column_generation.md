# Modelo de Generación de Columnas – Programación de Pacientes en Oncología

## Descripción General

El modelo utiliza **Column Generation** (Generación de Columnas):

- **Problema Satélite (subproblema):** genera patrones factibles de un solo paciente. Un patrón = un horario factible para ese paciente. Una columna = un patrón.
- **Problema Maestro (master problem):** elige exactamente un patrón por paciente y verifica que la suma de todos no exceda la capacidad de sillas, farmacia y enfermería en ningún módulo.

---

## 1. PROBLEMA MAESTRO (Master Problem)

### 1.1 Conjuntos

| Símbolo | Descripción |
|---------|-------------|
| `P` | Pacientes del día |
| `M` | Todos los módulos del día |
| `M_n ⊆ M` | Módulos normales |
| `M_e ⊆ M` | Módulos extra |
| `K_p` | Conjunto de patrones (columnas) generados hasta ahora para el paciente `p` |

### 1.2 Parámetros

| Símbolo | Descripción |
|---------|-------------|
| `S` | Número de sillas disponibles |
| `C_f` | Capacidad de farmacia por módulo |
| `E` | Número de enfermeras |
| `I_e` | Capacidad máxima de **inicios** de sesión por módulo por enfermera (`I_e = 1`) |
| `F_e` | Capacidad máxima de **finales** de sesión por módulo por enfermera (`F_e = 1`) |
| `a_{pkm}` | `1` si el patrón `k` del paciente `p` **inicia** sesión en el módulo `m` |
| `b_{pkm}` | `1` si el patrón `k` del paciente `p` **finaliza** sesión en el módulo `m` |
| `d_{pkm}` | `1` si el patrón `k` del paciente `p` **ocupa una silla** en el módulo `m` |
| `g_{pkm}` | `1` si el patrón `k` del paciente `p` **ocupa farmacia** en el módulo `m` |
| `h_{pk}` | Número de módulos **extra** usados por el patrón `k` del paciente `p` |

### 1.3 Variables

| Símbolo | Dominio | Descripción |
|---------|---------|-------------|
| `x_{pk}` | `{0, 1}` | `1` si se selecciona el patrón `k` para el paciente `p` |

> **Nota para implementación:** en la relajación LP del maestro, `x_{pk} ∈ [0, 1]`.

### 1.4 Restricciones

**R1 – Atención única:** cada paciente recibe exactamente un patrón.
```
∑_{k ∈ K_p}  x_{pk} = 1    ∀ p ∈ P
```
*Precio dual asociado: `λ_p`*

**R2 – Límite de sillas:** en cada módulo, la suma de sillas ocupadas no supera `S`.
```
∑_p ∑_{k ∈ K_p}  d_{pkm} · x_{pk} ≤ S    ∀ m ∈ M
```
*Precio dual asociado: `π_m^silla`*

**R3 – Límite de enfermeras:** en cada módulo, la suma de inicios y fines de sesión no supera `E`.
```
∑_p ∑_k  (a_{pkm} · x_{pk}  +  b_{pkm} · x_{pk}) ≤ E    ∀ m ∈ M
```
*Precio dual asociado: `π_m^enf`*

**R4 – Límite de farmacia:** en cada módulo, la ocupación de farmacia no supera `C_f`.
```
∑_p ∑_k  (g_{pkm} · x_{pk}) ≤ C_f    ∀ m ∈ M
```
*Precio dual asociado: `π_m^farm`*

### 1.5 Función Objetivo

Minimizar el total de módulos extra utilizados:
```
min  ∑_k ∑_p  h_{pk} · x_{pk}
```

---

## 2. PROBLEMA SATÉLITE (Subproblema)

Se resuelve **uno por paciente `p`**. Genera el patrón de costo reducido negativo.

### 2.1 Conjuntos

| Símbolo | Descripción |
|---------|-------------|
| `M` | Módulos del día |
| `M_n ⊆ M` | Módulos normales |
| `M_e ⊆ M` | Módulos extra |

### 2.2 Parámetros del paciente `p`

| Símbolo | Descripción |
|---------|-------------|
| `D_p` | Duración de la sesión de tratamiento del paciente `p` (en módulos) |
| `F_p` | Tiempo de preparación del medicamento en farmacia (en módulos) |
| `λ_p` | Precio dual de R1 (restricción de atención única del maestro) |
| `π_m^silla` | Precio dual de R2 (límite de sillas) para el módulo `m` |
| `π_m^enf` | Precio dual de R3 (límite de enfermeras) para el módulo `m` |
| `π_m^farm` | Precio dual de R4 (límite de farmacia) para el módulo `m` |

### 2.3 Variables

| Símbolo | Dominio | Descripción |
|---------|---------|-------------|
| `y_m` | `{0, 1}` | `1` si la preparación en farmacia **comienza** en el módulo `m` |
| `z_m` | `{0, 1}` | `1` si la sesión de tratamiento **comienza** en el módulo `m` |
| `w_m` | `{0, 1}` | `1` si la sesión de tratamiento **termina** en el módulo `m` |
| `v_m` | `{0, 1}` | `1` si se ocupa **farmacia** en el módulo `m` |
| `u_m` | `{0, 1}` | `1` si se ocupa una **silla** en el módulo `m` |
| `q_m` | `{0, 1}` | `1` si se requiere **atención de enfermera** en el módulo `m` (inicio o fin de sesión) |

### 2.4 Restricciones

**S1 – Medicamento listo antes de iniciar sesión:** la sesión no puede comenzar antes de que el medicamento esté preparado.
```
∑_m  m · z_m  ≥  ∑_{t=1}^{M}  t · y_t  +  F_p
```

**S2 – Cada procedimiento ocurre exactamente una vez:**
```
∑_m  y_m = 1
∑_m  z_m = 1
∑_m  w_m = 1
```

**S3 – Relación inicio-fin de sesión:**
```
∑_m  m · w_m  =  ∑_m  m · z_m  +  D_p  -  1
```

**S4 – Ocupación de farmacia:** farmacia está ocupada durante `F_p` módulos consecutivos a partir del inicio de preparación.
```
v_m = ∑_{τ = max(1, m - F_p + 1)}^{m}  y_τ    ∀ m ∈ M
```

**S5 – Ocupación de enfermería:** enfermera requerida en módulos de inicio y fin de sesión.
```
q_m = z_m + w_m    ∀ m ∈ M
```

**S6 – Ocupación de silla:** silla ocupada durante los `D_p` módulos consecutivos de la sesión.
```
u_m = ∑_{τ = max(1, m - D_p + 1)}^{m}  z_τ    ∀ m ∈ M
```

### 2.5 Función Objetivo (costo reducido)

Minimizar el costo reducido del nuevo patrón:
```
min  h_p  -  λ_p  -  ∑_m [ π_m^silla · u_m  +  π_m^farm · v_m  +  π_m^enf · (z_m + w_m) ]
```

Donde `h_p = ∑_{m ∈ M_e} u_m` es el número de módulos extra que ocupa la silla en este patrón (se puede linearizar o calcular como expresión en Gurobi).

> Si el valor óptimo de esta función objetivo es **negativo**, el patrón tiene costo reducido negativo y se añade como columna al maestro. Si no existe ningún patrón con costo reducido negativo, el algoritmo termina (solución óptima de la relajación LP).

---

## 3. ALGORITMO DE COLUMN GENERATION

```
1. Inicializar K_p con patrones factibles iniciales (e.g., uno por paciente)
2. Resolver la relajación LP del Problema Maestro → obtener precios duales λ_p, π_m^silla, π_m^enf, π_m^farm
3. Para cada paciente p:
     a. Resolver el Problema Satélite con los precios duales actuales
     b. Si costo_reducido < 0: agregar el nuevo patrón a K_p
4. Si se agregó al menos un patrón → volver a paso 2
5. Si no se agregó ningún patrón → solución óptima LP encontrada
6. Resolver el Problema Maestro con x_{pk} ∈ {0,1} (MIP final) para obtener solución entera
```

---

## 4. NOTAS DE IMPLEMENTACIÓN PARA GUROBI (PYTHON)

- Usar `gurobipy` con `Model()`.
- Maestro: crear variables `x` como continuas (`GRB.CONTINUOUS`, lb=0, ub=1) para la relajación LP; cambiar a `GRB.BINARY` para el MIP final.
- Recuperar precios duales con `constr.Pi` tras `model.optimize()` con LP.
- Satélite: variables binarias `GRB.BINARY` para `y_m, z_m, w_m, v_m, u_m, q_m`.
- `h_p` en el satélite: expresión lineal `∑_{m ∈ M_e} u_m` (usar `LinExpr` o `quicksum`).
- Las restricciones S4 y S6 son una suma sobre una ventana deslizante; usar `quicksum` con rango `range(max(0, m - F_p), m + 1)` (ajustar índices base-0 vs base-1 según convención elegida).
- Módulos: indexar desde `0` o `1` de forma consistente en todo el código.
- Separar claramente: `solve_master()` y `solve_satellite(p, duals)` como funciones independientes.
