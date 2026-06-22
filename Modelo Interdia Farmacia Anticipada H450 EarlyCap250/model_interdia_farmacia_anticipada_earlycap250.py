"""
=============================================================================
MODELO INTRADIA - PROGRAMACIÓN DE INFUSIONES CENTRO ONCOLÓGICO
=============================================================================
Basado en el modelo matemático de programación de infusiones (PDF adjunto).

Estructura:
  - Se leen parámetros y datos desde params.py y el Excel de simulación.
  - Se genera la población de pacientes a partir del Motor_Arribos.
  - Se resuelve el MIP con Gurobi sobre el horizonte configurado.
  - Se exportan resultados a CSV.

Conjuntos (ver PDF):
  P       → pacientes activos en el horizonte
  T       → días del horizonte
  Cp, Sp  → ciclos y sesiones por paciente (según su tipo)
  A       → asignaciones previas (vacío en primera ejecución)

Variables:
  x[p,t,c,s] ∈ {0,1}  → paciente p asignado al día t, ciclo c, sesión s
  y[t]       ≥ 0       → holgura de capacidad en día t
  W          ≥ 0       → ocupación máxima diaria

Función objetivo:
  min α·W + β·Σ_t y[t] + γ·Σ_p Σ_{t≥Rp} (t-Rp)·x[p,t,1,1]
=============================================================================
"""

import sys
import time
import math
import pandas as pd
import gurobipy as gp
from gurobipy import GRB

# Importar parámetros configurables
import params as P


# =============================================================================
# 1. CARGA DE DATOS
# =============================================================================

def cargar_datos():
    """Lee todas las hojas del Excel y retorna los dataframes necesarios."""
    print("=" * 65)
    print("  MODELO INTRADIA - CENTRO ONCOLÓGICO")
    print("=" * 65)
    print(f"\n[1/4] Cargando datos desde: {P.EXCEL_PATH}")

    df_config  = pd.read_excel(P.EXCEL_PATH, sheet_name=P.SHEET_CONFIG)
    df_params  = pd.read_excel(P.EXCEL_PATH, sheet_name=P.SHEET_PARAMS)
    df_arribos = pd.read_excel(P.EXCEL_PATH, sheet_name=P.SHEET_ARRIBOS)
    df_bajas   = pd.read_excel(P.EXCEL_PATH, sheet_name=P.SHEET_BAJAS)

    print(f"    > Configuración de tipos: {len(df_config)} tipos de paciente")
    print(f"    > Horizonte solicitado:   {P.HORIZONTE_DIAS} días")
    print(f"    > Días en Motor_Arribos:  {len(df_arribos)} días")

    return df_config, df_params, df_arribos, df_bajas


def extraer_parametros_globales(df_params):
    """Extrae parámetros globales del centro (puede ser overrideado en params.py)."""
    param_dict = dict(zip(
        df_params.iloc[:, 0].str.strip(),
        df_params.iloc[:, 1]
    ))

    n_sillas   = int(P.N_SILLAS_OVERRIDE or param_dict.get("n_sillas", 15))
    mod_ord    = int(P.MODULOS_ORDINARIOS_OVERRIDE or param_dict.get("modulos_ordinarios", 48))
    mod_ext    = int(P.MODULOS_EXTRAORDINARIOS_OVERRIDE or param_dict.get("modulos_extraordinarios", 8))

    K = n_sillas * mod_ord          # Capacidad ordinaria total (módulos)
    K_ext = n_sillas * mod_ext       # Capacidad extraordinaria adicional

    mod_farmacia = int(param_dict.get("modulos_farmacia", 20))
    n_farmaceuticos = int(param_dict.get("n_farmaceuticos", 9))
    cap_farmacia = mod_farmacia * n_farmaceuticos

    print(f"\n    Centro oncológico:")
    print(f"      Sillas:              {n_sillas}")
    print(f"      Módulos ordinarios:  {mod_ord}  →  K = {K}")
    print(f"      Módulos extraordinarios: {mod_ext}  →  K_ext = {K_ext}")
    print(f"      Módulos farmacia:    {mod_farmacia}")
    print(f"      N farmacéuticos:     {n_farmaceuticos}  →  Cap. Farmacia = {cap_farmacia}")

    return K, K_ext, cap_farmacia


def construir_tipos(df_config):
    """
    Construye el diccionario de tipos de paciente.
    Retorna dict: tipo_id (1..14) → {ciclos, sesiones, modulos, TBS, TBC, duracion}
    """
    tipos = {}
    for _, row in df_config.iterrows():
        tid = int(row["Id"])
        tipos[tid] = {
            "ciclos":   int(row["Ciclos"]),
            "sesiones": int(row["Sesiones"]),
            "modulos":  int(row["Módulos"]),
            "modulos_farmacia": int(row["Módulos Lab."]) if "Módulos Lab." in row else int(row.get("Modulos Lab.", 0)),
            "TBS":      int(row["TBS"]),
            "TBC":      int(row["TBC"]),
            "duracion": int(row["Duracion (Dias)"]),
        }
    return tipos


def generar_pacientes(df_arribos, df_bajas, tipos, horizonte_dias, dia_inicio):
    """
    Genera la lista de pacientes a partir de Motor_Arribos.
    Cada paciente tiene: id, tipo, dia_derivacion (Rp), ciclos, sesiones, modulos, TBS, TBC.

    Solo se incluyen pacientes cuya primera sesión aún cabe dentro del horizonte.
    """
    pacientes = []
    pid = 0
    max_dia = min(horizonte_dias, len(df_arribos))

    tipo_cols = [c for c in df_arribos.columns if c.startswith("Tipo")]

    for idx, row in df_arribos.iterrows():
        dia = int(row["Dia"])
        if dia < dia_inicio or dia > max_dia:
            continue

        for col in tipo_cols:
            num_tipo = int(col.split()[-1])   # "Tipo 3" → 3
            n_llegadas = int(row[col])
            if n_llegadas == 0:
                continue

            config = tipos[num_tipo]

            for _ in range(n_llegadas):
                pid += 1
                pacientes.append({
                    "id":      pid,
                    "tipo":    num_tipo,
                    "Rp":      dia,                   # día de derivación (1-indexed)
                    "ciclos":  config["ciclos"],
                    "sesiones":config["sesiones"],
                    "modulos": config["modulos"],
                    "modulos_farmacia": config["modulos_farmacia"],
                    "TBS":     config["TBS"],
                    "TBC":     config["TBC"],
                    "duracion":config["duracion"],
                })

    return pacientes


# =============================================================================
# 2. MODELO DE OPTIMIZACIÓN
# =============================================================================

def make_gap_stall_callback(stall_seconds=60, min_runtime=120, min_gap_improvement=1e-4):
    """
    Crea un callback de Gurobi que corta si el MIP gap se estanca.

    Solo evalua el estancamiento cuando ya existe incumbent factible.
    """
    state = {
        "best_gap": None,
        "last_improvement_runtime": None,
        "terminated": False,
    }

    def gap_stall_callback(model, where):
        if where != GRB.Callback.MIP or state["terminated"]:
            return

        runtime = model.cbGet(GRB.Callback.RUNTIME)
        best_obj = model.cbGet(GRB.Callback.MIP_OBJBST)
        best_bound = model.cbGet(GRB.Callback.MIP_OBJBND)

        if not math.isfinite(best_obj) or abs(best_obj) >= GRB.INFINITY * 0.5:
            return
        if not math.isfinite(best_bound):
            return

        gap = abs(best_obj - best_bound) / max(abs(best_obj), 1e-10)

        if state["best_gap"] is None:
            state["best_gap"] = gap
            state["last_improvement_runtime"] = runtime
            return

        if gap < state["best_gap"] - min_gap_improvement:
            state["best_gap"] = gap
            state["last_improvement_runtime"] = runtime
            return

        if runtime < min_runtime:
            return

        elapsed_without_improvement = runtime - state["last_improvement_runtime"]
        if elapsed_without_improvement >= stall_seconds:
            state["terminated"] = True
            print(
                f"[CALLBACK] Corte por estancamiento: {stall_seconds}s sin mejorar gap. "
                f"Best gap={state['best_gap']:.6f} runtime={runtime:.1f}s"
            )
            model.terminate()

    return gap_stall_callback


def construir_y_resolver(pacientes, K, K_ext, cap_farmacia, horizonte_dias, dia_inicio,
                         scenario=None, time_limit_override=None):
    """
    Construye y resuelve el modelo MIP con Gurobi.

    Si scenario es un dict con 'ALPHA', 'BETA', 'GAMMA', usa esos pesos.
    Si es None, usa los pesos base de params.py.
    Si time_limit_override es un número, lo usa en vez de P.TIME_LIMIT_SECONDS.

    Retorna (model, x, y, W) o None si es infactible.
    """
    dias = list(range(dia_inicio, dia_inicio + horizonte_dias))
    T_set = set(dias)

    print(f"\n[2/4] Construyendo modelo Gurobi...")
    print(f"      Pacientes a programar: {len(pacientes)}")
    print(f"      Días en horizonte:     {len(dias)}  [{dias[0]} .. {dias[-1]}]")

    # -------------------------------------------------------------------------
    # Pre-computar las fechas factibles de cada (paciente, ciclo, sesión)
    # La sesión (c, s) del paciente p debe ocurrir en:
    #   t_pcs = Rp + (c-1)*TBC + (s-1)*TBS  (mínimo)
    # y puede retrasarse si hay saturación.
    # Para TBS/TBC estrictos, la sesión s+1 ocurre exactamente TBS días
    # después de la sesión s; y el ciclo c+1 empieza exactamente TBC días
    # después del inicio del ciclo c.
    # Como permitimos atrasos (el paciente puede esperar), modelamos el
    # día asignado de (p,c,s) como variable entera implícita vía x[p,t,c,s].
    # La restricción de timing se mantiene como igualdad en DIFERENCIA:
    #   Σ_t t·x[p,t,c,s+1] - Σ_t t·x[p,t,c,s] = TBS   (sesiones consecutivas)
    #   Σ_t t·x[p,t,c+1,1] - Σ_t t·x[p,t,c,1] = TBC   (inicios de ciclos consecutivos)
    # Esto garantiza espaciado exacto entre sesiones consecutivas una vez
    # que la primera sesión es asignada (en cualquier día ≥ Rp).
    # -------------------------------------------------------------------------

    # Calcular límite superior del día para cada (p,c,s) para reducir variables
    # t_min[p,c,s] = Rp (primera posible); t_max = horizonte (puede no alcanzar)
    # Solo generamos x[p,t,c,s] para t en [t_min_pcs, horizonte]

    def t_min_pcs(pac, c, s):
        """Día mínimo posible para la sesión (c,s) del paciente."""
        # Mínimo: Rp + (c-1)*TBC + (s-1)*TBS
        return pac["Rp"] + (c - 1) * pac["TBC"] + (s - 1) * pac["TBS"]

    # Filtrar pacientes cuyo tratamiento completo cabe dentro del horizonte
    pacientes_validos = []
    for pac in pacientes:
        C = pac["ciclos"]
        S = pac["sesiones"]

        ultimo_dia_minimo = pac["Rp"] + (C - 1) * pac["TBC"] + (S - 1) * pac["TBS"]

        if ultimo_dia_minimo <= dias[-1]:
            pacientes_validos.append(pac)

    eliminados = len(pacientes) - len(pacientes_validos)
    print(f"      Pacientes descartados por tratamiento fuera de horizonte: {eliminados}")
    print(f"      Pacientes en modelo: {len(pacientes_validos)}")

    # -------------------------------------------------------------------------
    # Crear modelo
    # -------------------------------------------------------------------------
    env = gp.Env(empty=True)
    env.setParam("OutputFlag", 1 if P.LOG_TO_CONSOLE else 0)
    env.start()

    model = gp.Model("Intradia_Oncologia", env=env)
    effective_time_limit = time_limit_override if time_limit_override is not None else P.TIME_LIMIT_SECONDS
    model.setParam("TimeLimit", effective_time_limit)
    model.setParam("MIPGap", P.MIP_GAP)
    model.setParam("Threads", P.THREADS)
    # Parámetros de diagnóstico numérico:
    # - DualReductions=0 : desactiva reducciones que pueden ocultar infactibilidades
    # - InfUnbdInfo=1    : pide info de rayo/rayo dual si hay infactibilidad/no-acotado
    # - BarHomogeneous=1 : usa método homogéneo en Barrier (más estable numéricamente)
    # - NumericFocus=3   : máxima precisión numérica (más lento pero más confiable)
    model.setParam("DualReductions", 0)
    model.setParam("InfUnbdInfo",    1)
    model.setParam("BarHomogeneous", 1)
    model.setParam("NumericFocus",   3)
    # Parámetros para priorizar encontrar buenas soluciones factibles:
    # - MIPFocus=1   : priorizar factibilidad sobre probar optimalidad
    # - Heuristics=0.8: dedicar 80% del tiempo a heurísticas
    # - Cuts=2       : nivel agresivo de cortes
    # - RINS=10      : Relaxation Induced Neighborhood Search frecuente
    model.setParam("MIPFocus",    1)
    model.setParam("Heuristics",  0.8)
    model.setParam("Cuts",        2)
    model.setParam("RINS",        10)

    # -------------------------------------------------------------------------
    # Variables de decisión
    # -------------------------------------------------------------------------
    # x[p_id, t, c, s] ∈ {0,1}
    #
    # Restricción clínica MAX_ESPERA (P.MAX_ESPERA días desde derivación):
    #   - Para (c=1, s=1): t ∈ [Rp, Rp + MAX_ESPERA]  (ventana acotada)
    #   - Para (c,s) restantes: t_min fijo por TBS/TBC; t_max = t_min de (1,1)
    #     desplazado por el mismo offset → t_max_pcs = t_min_pcs(c,s) + MAX_ESPERA
    #   Esto mantiene la coherencia: si la 1ª sesión se retrasa como mucho
    #   MAX_ESPERA días, las siguientes también tienen una ventana de MAX_ESPERA.
    x = {}
    for pac in pacientes_validos:
        p = pac["id"]
        for c in range(1, pac["ciclos"] + 1):
            for s in range(1, pac["sesiones"] + 1):
                t_min = t_min_pcs(pac, c, s)
                t_max = t_min + P.MAX_ESPERA   # ventana = MAX_ESPERA días desde mínimo
                for t in dias:
                    if t_min <= t <= t_max:
                        x[p, t, c, s] = model.addVar(
                            vtype=GRB.BINARY,
                            name=f"x[{p},{t},{c},{s}]"
                        )

    prep = {}
    for pac in pacientes_validos:
        p = pac["id"]
        for c in range(1, pac["ciclos"] + 1):
            for s in range(1, pac["sesiones"] + 1):
                for t in dias:
                    if (p, t, c, s) not in x:
                        continue
                    prep[p, t, c, s, t] = model.addVar(
                        vtype=GRB.BINARY,
                        name=f"prep_same[{p},{t},{c},{s}]"
                    )
                    if pac["modulos_farmacia"] > 0 and t - 1 in T_set:
                        prep[p, t, c, s, t - 1] = model.addVar(
                            vtype=GRB.BINARY,
                            name=f"prep_prev[{p},{t},{c},{s}]"
                        )

    # y[t] ∈ [0, K_ext] : módulos extraordinarios usados en día t
    # La cota superior K_ext garantiza: cap_expr <= K + y[t] <= K + K_ext
    y = {}
    for t in dias:
        y[t] = model.addVar(lb=0.0, ub=K_ext, vtype=GRB.CONTINUOUS, name=f"y[{t}]")

    # W ≥ 0 : ocupación máxima diaria
    W = model.addVar(lb=0.0, vtype=GRB.CONTINUOUS, name="W")

    model.update()
    print(f"      Variables binarias x:    {len(x):,}")
    print(f"      Variables binarias prep: {len(prep):,}")
    print(f"      Variables continuas: {len(y) + 1:,}")

    # -------------------------------------------------------------------------
    # Función objetivo
    # z = min α·W + β·Σ_t y[t] + γ·Σ_p Σ_{t≥Rp} (t-Rp)·x[p,t,1,1]
    # -------------------------------------------------------------------------
    alpha = scenario["ALPHA"] if scenario else P.ALPHA
    beta  = scenario["BETA"]  if scenario else P.BETA
    gamma = scenario["GAMMA"] if scenario else P.GAMMA

    espera_expr = gp.LinExpr()
    for pac in pacientes_validos:
        p = pac["id"]
        Rp = pac["Rp"]
        for t in dias:
            if t >= Rp and (p, t, 1, 1) in x:
                espera_expr += (t - Rp) * x[p, t, 1, 1]

    obj = (alpha * W
           + beta  * gp.quicksum(y[t] for t in dias)
           + gamma * espera_expr)

    model.setObjective(obj, GRB.MINIMIZE)

    # -------------------------------------------------------------------------
    # VALIDACIÓN: detectar sesiones sin días factibles antes de agregar restricciones
    # Si alguna sesión de un paciente válido no tiene variables x[p,t,c,s],
    # cualquier restricción sobre esa sesión sería 0 == TBS → infactible.
    # En ese caso se debe eliminar el paciente, no silenciar la restricción.
    # -------------------------------------------------------------------------
    sesiones_sin_vars = []
    for pac in pacientes_validos:
        p = pac["id"]
        for c in range(1, pac["ciclos"] + 1):
            for s in range(1, pac["sesiones"] + 1):
                if not any((p, t, c, s) in x for t in dias):
                    sesiones_sin_vars.append((p, c, s, pac["Rp"], pac["tipo"]))

    if sesiones_sin_vars:
        print(f"\n  ERROR: {len(sesiones_sin_vars)} sesión(es) sin días factibles detectadas:")
        for entry in sesiones_sin_vars[:20]:
            print(f"    Paciente {entry[0]} (tipo {entry[4]}, Rp={entry[3]}): ciclo={entry[1]}, sesión={entry[2]}")
        if len(sesiones_sin_vars) > 20:
            print(f"    ... y {len(sesiones_sin_vars) - 20} más.")
        raise ValueError(
            f"Modelo mal construido: {len(sesiones_sin_vars)} sesión(es) sin días factibles. "
            "Reduzca MAX_ESPERA, amplie HORIZONTE_DIAS, o revise el filtro de pacientes_validos."
        )

    print("      Agregando restricciones...")
    n_r1 = n_r2 = n_r3 = n_r4 = n_r5 = n_rprep = n_rfarm = n_rearly = 0
    early_prep_treatment_cap = int(getattr(P, "EARLY_PREP_TREATMENT_CAP", 250))

    for pac in pacientes_validos:
        p  = pac["id"]
        Rp = pac["Rp"]
        C  = pac["ciclos"]
        S  = pac["sesiones"]

        # (R1) Cada sesión (c,s) se programa en exactamente un día
        for c in range(1, C + 1):
            for s in range(1, S + 1):
                vars_pcs = [x[p, t, c, s] for t in dias if (p, t, c, s) in x]
                if vars_pcs:
                    model.addConstr(
                        gp.quicksum(vars_pcs) == 1,
                        name=f"r1_p{p}_c{c}_s{s}"
                    )
                    n_r1 += 1

                for t in dias:
                    if (p, t, c, s) not in x:
                        continue
                    prep_vars = [
                        prep[p, t, c, s, d]
                        for d in (t - 1, t)
                        if (p, t, c, s, d) in prep
                    ]
                    model.addConstr(
                        gp.quicksum(prep_vars) == x[p, t, c, s],
                        name=f"r_prep_link_p{p}_t{t}_c{c}_s{s}"
                    )
                    n_rprep += 1

        # (R3a) Espaciado exacto entre sesiones consecutivas dentro de un ciclo
        # S_t t·x[p,t,c,s+1] - S_t t·x[p,t,c,s] = TBS
        # Falla explícitamente si alguna sesión no tiene variables (indica bug de construcción).
        for c in range(1, C + 1):
            for s in range(1, S):   # s = 1..S-1
                days_s1 = [t for t in dias if (p, t, c, s)   in x]
                days_s2 = [t for t in dias if (p, t, c, s+1) in x]
                if not days_s1:
                    raise ValueError(
                        f"R3a: paciente {p} (tipo {pac['tipo']}, Rp={Rp}) "
                        f"no tiene variables para ciclo={c}, sesión={s}."
                    )
                if not days_s2:
                    raise ValueError(
                        f"R3a: paciente {p} (tipo {pac['tipo']}, Rp={Rp}) "
                        f"no tiene variables para ciclo={c}, sesión={s+1}."
                    )
                lhs_s1 = gp.quicksum(t * x[p, t, c, s]   for t in days_s1)
                lhs_s2 = gp.quicksum(t * x[p, t, c, s+1] for t in days_s2)
                model.addConstr(lhs_s2 - lhs_s1 == pac["TBS"],
                                name=f"r3a_p{p}_c{c}_s{s}")
                n_r3 += 1

        # (R3b) Espaciado exacto entre inicios de ciclos consecutivos
        # Falla explícitamente si alguna sesión 1 de algún ciclo no tiene variables.
        for c in range(1, C):   # c = 1..C-1
            days_c_actual    = [t for t in dias if (p, t, c,     1) in x]
            days_c_siguiente = [t for t in dias if (p, t, c + 1, 1) in x]
            if not days_c_actual:
                raise ValueError(
                    f"R3b: paciente {p} (tipo {pac['tipo']}, Rp={Rp}) "
                    f"no tiene variables para ciclo={c}, sesión=1."
                )
            if not days_c_siguiente:
                raise ValueError(
                    f"R3b: paciente {p} (tipo {pac['tipo']}, Rp={Rp}) "
                    f"no tiene variables para ciclo={c+1}, sesión=1."
                )
            lhs_c1_actual = gp.quicksum(
                t * x[p, t, c, 1] for t in days_c_actual
            )
            lhs_c1_siguiente = gp.quicksum(
                t * x[p, t, c + 1, 1] for t in days_c_siguiente
            )
            model.addConstr(
                lhs_c1_siguiente - lhs_c1_actual == pac["TBC"],
                name=f"r3b_p{p}_c{c}"
            )
            n_r4 += 1

    # (R2) Capacidad diaria: Σ_p Σ_c Σ_s Mp·x[p,t,c,s] ≤ K + y[t]
    for t in dias:
        cap_expr = gp.quicksum(
            pac["modulos"] * x[pac["id"], t, c, s]
            for pac in pacientes_validos
            for c in range(1, pac["ciclos"] + 1)
            for s in range(1, pac["sesiones"] + 1)
            if (pac["id"], t, c, s) in x
        )
        model.addConstr(cap_expr <= K + y[t], name=f"r2_cap_t{t}")
        n_r2 += 1

        # (R5) Definición de W: ocupación máxima
        model.addConstr(cap_expr <= W, name=f"r5_W_t{t}")
        n_r5 += 1

        # (R_FARMACIA) Capacidad agregada de farmacia por dia de preparacion.
        # Una sesion atendida en t puede usar farmacia en t o en t-1.
        cap_farmacia_expr = gp.quicksum(
            pac["modulos_farmacia"] * prep[pac["id"], treatment_day, c, s, t]
            for pac in pacientes_validos
            for treatment_day in (t, t + 1)
            for c in range(1, pac["ciclos"] + 1)
            for s in range(1, pac["sesiones"] + 1)
            if (pac["id"], treatment_day, c, s, t) in prep
        )
        model.addConstr(cap_farmacia_expr <= cap_farmacia, name=f"r_farmacia_t{t}")
        n_rfarm += 1

        # (R_EARLY_PREP) Carga maxima de tratamientos en t que dependen de
        # farmacia preparada en t-1. En el intradia esas sesiones quedan
        # forzadas a iniciar temprano por la vigencia de 24h del medicamento.
        early_prep_treatment_expr = gp.quicksum(
            pac["modulos"] * prep[pac["id"], t, c, s, t - 1]
            for pac in pacientes_validos
            for c in range(1, pac["ciclos"] + 1)
            for s in range(1, pac["sesiones"] + 1)
            if (pac["id"], t, c, s, t - 1) in prep
        )
        model.addConstr(
            early_prep_treatment_expr <= early_prep_treatment_cap,
            name=f"r_early_prep_treatment_t{t}",
        )
        n_rearly += 1

    # (R4) Límite de inicio: ya garantizado al no crear x[p,t,c,s] para t < t_min

    print(f"      R1 (unicidad sesiones):    {n_r1:,}")
    print(f"      R2 (capacidad diaria):     {n_r2:,}")
    print(f"      R3a (TBS entre sesiones):  {n_r3:,}")
    print(f"      R3b (TBC entre ciclos):    {n_r4:,}")
    print(f"      R5 (def. W máximo):        {n_r5:,}")

    print(f"      Rprep (link farmacia):     {n_rprep:,}")
    print(f"      Rfarm (cap. farmacia):     {n_rfarm:,}")
    print(f"      Rearly (prep previa <= {early_prep_treatment_cap} mod tratamiento): {n_rearly:,}")

    # -------------------------------------------------------------------------
    # Resolver
    # -------------------------------------------------------------------------
    print(f"\n[3/4] Resolviendo con Gurobi...")
    print(f"      Time limit: {effective_time_limit}s  |  MIP gap: {P.MIP_GAP*100:.1f}%")
    print("-" * 65)

    t_start = time.time()
    if getattr(P, "USE_GAP_STALL_CALLBACK", False):
        stall_cb = make_gap_stall_callback(
            stall_seconds=getattr(P, "STALL_SECONDS", 60),
            min_runtime=getattr(P, "STALL_MIN_RUNTIME", 120),
            min_gap_improvement=getattr(P, "STALL_MIN_GAP_IMPROVEMENT", 1e-4),
        )
        model.optimize(stall_cb)
    else:
        model.optimize()
    t_elapsed = time.time() - t_start

    print("-" * 65)
    print(f"      Tiempo de resolución: {t_elapsed:.1f}s")
    print(f"      Status: {model.status} ({_status_str(model.status)})")

    accepted_statuses = (GRB.OPTIMAL, GRB.TIME_LIMIT, GRB.SUBOPTIMAL, GRB.INTERRUPTED)
    if model.status in accepted_statuses and model.SolCount > 0:
        print(f"      Valor objetivo: {model.ObjVal:.4f}")
        print(f"      MIP Gap final:  {model.MIPGap * 100:.2f}%")
        return model, x, y, W, prep, pacientes_validos, dias
    elif model.status in accepted_statuses:
        print("      No se encontro solucion factible.")
        return None
    elif model.status == GRB.INFEASIBLE:
        print(f"      ✗ Modelo INFACTIBLE.")
        print(f"      Computando IIS para identificar restricciones conflictivas...")
        try:
            model.computeIIS()
            iis_path = "modelo_infactible.ilp"
            model.write(iis_path)
            print(f"      IIS escrito en: {iis_path}")
            print(f"      Revise ese archivo para ver qué restricciones son conflictivas.")
        except Exception as e:
            print(f"      No se pudo generar IIS: {e}")
        return None
    else:
        print(f"      ✗ El solver encontró un error o estado inesperado: {_status_str(model.status)}")
        return None


def _status_str(status):
    mapping = {
        GRB.OPTIMAL:    "ÓPTIMO",
        GRB.INFEASIBLE: "INFACTIBLE",
        GRB.TIME_LIMIT: "LÍMITE DE TIEMPO",
        GRB.SUBOPTIMAL: "SUBÓPTIMO",
        GRB.INTERRUPTED: "INTERRUMPIDO POR CALLBACK",
        GRB.UNBOUNDED:  "NO ACOTADO",
    }
    return mapping.get(status, f"código {status}")


# =============================================================================
# 3. EXTRACCIÓN Y EXPORTACIÓN DE RESULTADOS
# =============================================================================

def extraer_resultados(model, x, y, W, prep, pacientes_validos, dias, K, K_ext, cap_farmacia):
    """Extrae la solución y la convierte en DataFrames exportables."""

    print(f"\n[4/4] Extrayendo resultados...")

    # Schedule detallado
    schedule = []
    for pac in pacientes_validos:
        p = pac["id"]
        for c in range(1, pac["ciclos"] + 1):
            for s in range(1, pac["sesiones"] + 1):
                for t in dias:
                    if (p, t, c, s) in x and x[p, t, c, s].X > 0.5:
                        farmacia_dia = t
                        for d in (t - 1, t):
                            if (p, t, c, s, d) in prep and prep[p, t, c, s, d].X > 0.5:
                                farmacia_dia = d
                                break
                        schedule.append({
                            "paciente_id": p,
                            "tipo":        pac["tipo"],
                            "dia_derivacion": pac["Rp"],
                            "dia_asignado":   t,
                            "dia_farmacia":   farmacia_dia,
                            "farmacia_offset": farmacia_dia - t,
                            "espera_dias":    t - pac["Rp"],
                            "ciclo":   c,
                            "sesion":  s,
                            "modulos": pac["modulos"],
                            "modulos_farmacia": pac["modulos_farmacia"],
                        })

    df_schedule = pd.DataFrame(schedule)
    if not df_schedule.empty:
        df_schedule.sort_values(["dia_asignado", "paciente_id", "ciclo", "sesion"],
                                inplace=True)
        df_schedule.reset_index(drop=True, inplace=True)

    # Resumen diario
    K_ext_val = K_ext  # referencia local
    resumen = []
    for t in dias:
        ocupacion = sum(
            pac["modulos"] * x[pac["id"], t, c, s].X
            for pac in pacientes_validos
            for c in range(1, pac["ciclos"] + 1)
            for s in range(1, pac["sesiones"] + 1)
            if (pac["id"], t, c, s) in x
        )
        holgura = y[t].X
        n_sesiones = df_schedule[df_schedule["dia_asignado"] == t].shape[0] if not df_schedule.empty else 0
        farmacia_usada = (
            df_schedule[df_schedule["dia_farmacia"] == t]["modulos_farmacia"].sum()
            if not df_schedule.empty else 0
        )
        if not df_schedule.empty:
            prev_pharmacy_rows = df_schedule[
                (df_schedule["dia_asignado"] == t)
                & (df_schedule["farmacia_offset"] == -1)
            ]
            prev_pharmacy_treatment_modules = prev_pharmacy_rows["modulos"].sum()
            prev_pharmacy_sessions = prev_pharmacy_rows.shape[0]
        else:
            prev_pharmacy_treatment_modules = 0
            prev_pharmacy_sessions = 0
        modulos_extra = max(0.0, ocupacion - K)
        resumen.append({
            "dia":                    t,
            "ocupacion_modulos":      round(ocupacion, 2),
            "farmacia_modulos":       round(float(farmacia_usada), 2),
            "farmacia_capacidad":     cap_farmacia,
            "tratamiento_modulos_farmacia_previa": round(float(prev_pharmacy_treatment_modules), 2),
            "sesiones_farmacia_previa": int(prev_pharmacy_sessions),
            "limite_tratamiento_farmacia_previa": int(getattr(P, "EARLY_PREP_TREATMENT_CAP", 250)),
            "capacidad_ordinaria_K":  K,
            "capacidad_extra_K_ext":  K_ext_val,
            "capacidad_total":        K + K_ext_val,
            "modulos_extra_usados":   round(modulos_extra, 2),
            "holgura_yt":             round(holgura, 4),
            "n_sesiones":             n_sesiones,
            "pct_ocupacion":          round(100 * ocupacion / K, 1) if K > 0 else 0,
            "pct_ocupacion_total":    round(100 * ocupacion / (K + K_ext_val), 1) if (K + K_ext_val) > 0 else 0,
        })

    df_resumen = pd.DataFrame(resumen)

    # -------------------------------------------------------------------------
    # Validación: ninguna jornada supera K + K_ext
    # -------------------------------------------------------------------------
    max_ocup = df_resumen["ocupacion_modulos"].max() if not df_resumen.empty else 0
    cap_total = K + K_ext_val
    if max_ocup > cap_total + 1e-4:
        raise ValueError(
            f"ERROR: La solución excede la capacidad máxima diaria de {cap_total} módulos "
            f"(máximo encontrado: {max_ocup:.1f} módulos)."
        )
    print(f"      > Validación capacidad total: ninguna jornada supera {cap_total} módulos.")

    # -------------------------------------------------------------------------
    # Validación: W del modelo vs ocupación máxima real calculada
    # -------------------------------------------------------------------------
    early_cap = int(getattr(P, "EARLY_PREP_TREATMENT_CAP", 250))
    max_prev_pharmacy_treatment = (
        df_resumen["tratamiento_modulos_farmacia_previa"].max()
        if not df_resumen.empty else 0
    )
    if max_prev_pharmacy_treatment > early_cap + 1e-4:
        raise ValueError(
            "ERROR: La solucion excede el limite de tratamiento con farmacia previa "
            f"({early_cap} modulos). Max encontrado: {max_prev_pharmacy_treatment:.1f}."
        )
    print(
        "      > Validacion farmacia previa: "
        f"max {max_prev_pharmacy_treatment:.1f}/{early_cap} modulos de tratamiento."
    )

    W_val = model.getVarByName("W").X
    print(f"      W del modelo: {W_val:.1f}  |  Máx. ocupación real: {max_ocup:.1f}  |  Diferencia: {W_val - max_ocup:.2f}")
    if W_val + 1e-4 < max_ocup:
        raise ValueError(
            f"ERROR: W ({W_val:.1f}) es menor que la ocupación máxima real ({max_ocup:.1f}); "
            "hay inconsistencia en la solución."
        )
    if W_val > max_ocup + 1e-3:
        print(f"      ADVERTENCIA: W ({W_val:.1f}) es mayor que la ocupación máxima real ({max_ocup:.1f}). "
              "Esto puede pasar si la solución no está cerrada óptimamente o si W no queda apretado por el objetivo.")

    return df_schedule, df_resumen


def imprimir_estadisticas(model, df_schedule, df_resumen, pacientes_validos, K, K_ext):
    """Imprime un resumen ejecutivo de los resultados."""
    if not P.PRINT_STATS:
        return

    cap_total = K + K_ext
    W_val = model.getVarByName("W").X
    status_str = (
        "ÓPTIMO" if model.status == GRB.OPTIMAL
        else "FACTIBLE (límite de tiempo)" if model.status == GRB.TIME_LIMIT and model.SolCount > 0
        else _status_str(model.status)
    )

    print("\n" + "=" * 65)
    print("  RESUMEN DE RESULTADOS")
    print("=" * 65)

    # --- Configuración usada ---
    print(f"  Horizonte:               {P.HORIZONTE_DIAS} días (día {P.DIA_INICIO} .. {P.DIA_INICIO + P.HORIZONTE_DIAS - 1})")
    print(f"  MAX_ESPERA:              {P.MAX_ESPERA} días")
    print(f"  MIP_GAP solicitado:      {P.MIP_GAP*100:.1f}%")
    print(f"  TimeLimit:               {P.TIME_LIMIT_SECONDS}s")
    print(f"  Capacidad: K={K}  K_ext={K_ext}  Total={cap_total}")

    # --- Resultado del solver ---
    print(f"\n  Estado del solver:       {status_str}")
    print(f"  Valor objetivo (z):      {model.ObjVal:.4f}")
    print(f"  MIP Gap final:           {model.MIPGap * 100:.2f}%")
    print(f"  W del modelo:            {W_val:.1f} módulos  "
          f"({100*W_val/K:.1f}% de K  |  {100*W_val/cap_total:.1f}% de cap. total)")

    if not df_resumen.empty:
        max_ocup_real     = df_resumen["ocupacion_modulos"].max()
        dias_con_holgura  = df_resumen[df_resumen["holgura_yt"] > 0]
        dias_con_extra    = df_resumen[df_resumen["modulos_extra_usados"] > 1e-6]
        total_extra       = df_resumen["modulos_extra_usados"].sum()
        max_extra         = df_resumen["modulos_extra_usados"].max()

        print(f"\n  Máxima ocupación real:   {max_ocup_real:.0f} módulos (cap. máx.={cap_total})")
        print(f"  Ocupación promedio:      "
              f"{df_resumen['ocupacion_modulos'].mean():.1f} módulos  "
              f"({df_resumen['pct_ocupacion_total'].mean():.1f}% de cap. total)")
        print(f"  Día de mayor ocupación:  "
              f"día {df_resumen.loc[df_resumen['ocupacion_modulos'].idxmax(), 'dia']}  "
              f"({max_ocup_real:.0f} módulos)")
        print(f"  Días con módulos extra:  {len(dias_con_extra)}  "
              f"(total extra: {total_extra:.0f} mód-día  |  max en un día: {max_extra:.0f}/{K_ext})")
        print(f"  Días con holgura activa: {len(dias_con_holgura)}  "
              f"(total: {df_resumen['holgura_yt'].sum():.1f} módulos-día)")

    if not df_schedule.empty:
        # Filtrar estrictamente ciclo 1, sesión 1 (verdadera primera sesión del tratamiento)
        df_primera = df_schedule[
            (df_schedule["ciclo"] == 1) &
            (df_schedule["sesion"] == 1)
        ]
        print(f"\n  Pacientes programados:   {df_schedule['paciente_id'].nunique()}")
        print(f"  Total sesiones agendadas:{len(df_schedule):>7,}")
        print(f"  Espera promedio (1ª ses):{df_primera['espera_dias'].mean():>7.1f} días  [ciclo=1, sesion=1]")
        print(f"  Espera máxima (1ª ses):  {df_primera['espera_dias'].max():>5.0f} días  [ciclo=1, sesion=1]")

        print(f"\n  Sesiones por tipo de paciente:")
        tipo_resumen = (df_schedule.groupby("tipo")
                        .agg(sesiones=("sesion", "count"),
                             pacientes=("paciente_id", "nunique"),
                             modulos_tot=("modulos", "sum"))
                        .reset_index())
        for _, row in tipo_resumen.iterrows():
            print(f"    Tipo {int(row['tipo']):>2}:  "
                  f"{int(row['pacientes']):>4} pacientes  |  "
                  f"{int(row['sesiones']):>6} sesiones  |  "
                  f"{int(row['modulos_tot']):>8} módulos totales")

    print("=" * 65)


def construir_output_interday(model, df_schedule, df_resumen, pacientes_validos, dias, K):
    """Construye el output compatible con solution_interday.xlsx."""

    offset = min(dias)

    if df_schedule.empty:
        df_asignaciones = pd.DataFrame(columns=[
            "patient_id", "patient_type_x", "day", "cycle", "session",
            "modules", "arrival_day", "patient_type_y", "pharmacy_day",
            "pharmacy_offset", "pharmacy_modules"
        ])
    else:
        df_asignaciones = pd.DataFrame({
            "patient_id":     df_schedule["paciente_id"] - 1,
            "patient_type_x": df_schedule["tipo"],
            "day":            df_schedule["dia_asignado"] - offset,
            "pharmacy_day":   df_schedule["dia_farmacia"] - offset,
            "pharmacy_offset": df_schedule["farmacia_offset"],
            "cycle":          df_schedule["ciclo"] - 1,
            "session":        df_schedule["sesion"] - 1,
            "modules":        df_schedule["modulos"],
            "pharmacy_modules": df_schedule["modulos_farmacia"],
            "arrival_day":    df_schedule["dia_derivacion"] - offset,
            "patient_type_y": df_schedule["tipo"],
        })
        df_asignaciones = df_asignaciones.sort_values(
            ["patient_id", "cycle", "session", "day"]
        ).reset_index(drop=True)

    df_ocupacion = pd.DataFrame({
        "Día": df_resumen["dia"] - offset,
        "Ocupación": df_resumen["ocupacion_modulos"],
    })

    df_ocupacion["Farmacia"] = df_resumen["farmacia_modulos"]
    df_ocupacion["Capacidad Farmacia"] = df_resumen["farmacia_capacidad"]

    ocupacion_maxima = df_resumen["ocupacion_modulos"].max() if not df_resumen.empty else 0
    suma_holguras = df_resumen["holgura_yt"].sum() if not df_resumen.empty else 0

    df_resumen_interday = pd.DataFrame([
        ["Total Pacientes", len(pacientes_validos)],
        ["Pacientes Programados", df_asignaciones["patient_id"].nunique() if not df_asignaciones.empty else 0],
        ["Horizonte (días)", len(dias)],
        ["Capacidad (módulos/día)", K],
        ["Ocupación Máxima", f"{ocupacion_maxima:.0f}"],
        ["Suma de Holguras", f"{suma_holguras:.2f}"],
        ["Valor Función Objetivo", f"{model.ObjVal:.2f}"],
    ], columns=["Métrica", "Valor"])

    return df_asignaciones, df_ocupacion, df_resumen_interday


def exportar_resultados(model, df_schedule, df_resumen, pacientes_validos, dias, K,
                        suffix=""):
    """Guarda resultados en CSV y en XLSX compatible con el modelo intradía."""

    # Generar nombres con sufijo opcional (para escenarios)
    csv_path     = P.OUTPUT_CSV.replace(".csv", f"{suffix}.csv") if suffix else P.OUTPUT_CSV
    summary_path = P.OUTPUT_SUMMARY_CSV.replace(".csv", f"{suffix}.csv") if suffix else P.OUTPUT_SUMMARY_CSV
    xlsx_path    = P.OUTPUT_XLSX.replace(".xlsx", f"{suffix}.xlsx") if suffix else P.OUTPUT_XLSX

    if csv_path:
        df_schedule.to_csv(csv_path, index=False)
    if summary_path:
        df_resumen.to_csv(summary_path, index=False)

    df_asignaciones, df_ocupacion, df_resumen_interday = construir_output_interday(
        model, df_schedule, df_resumen, pacientes_validos, dias, K
    )

    with pd.ExcelWriter(xlsx_path) as writer:
        df_asignaciones.to_excel(writer, sheet_name="Asignaciones", index=False)
        df_ocupacion.to_excel(writer, sheet_name="Ocupación Diaria", index=False)
        df_resumen_interday.to_excel(writer, sheet_name="Resumen", index=False)

    print(f"\n  > Schedule exportado a:  {csv_path}")
    print(f"  > Resumen exportado a:   {summary_path}")
    print(f"  > Output intradía XLSX:  {xlsx_path}")

    return xlsx_path  # retorna path para el CSV comparativo


# =============================================================================
# 4. MAIN
# =============================================================================

def _run_single(pacientes, K, K_ext, cap_farmacia, scenario=None, suffix="",
                time_limit_override=None):
    """
    Ejecuta una corrida completa del modelo con los pesos dados.
    Retorna dict con métricas para el CSV comparativo.
    Nunca lanza excepciones: si falla, retorna fila con solution_found=False.
    """
    scenario_name = scenario["name"] if scenario else "base"
    alpha = scenario["ALPHA"] if scenario else P.ALPHA
    beta  = scenario["BETA"]  if scenario else P.BETA
    gamma = scenario["GAMMA"] if scenario else P.GAMMA
    cap_total = 840  # K + K_ext, referencia para el print
    effective_tl = time_limit_override if time_limit_override is not None else P.TIME_LIMIT_SECONDS

    # --- Pre-solución: imprimir cabecera del escenario ---
    print("\n" + "=" * 65)
    print(f"  ESCENARIO: {scenario_name}")
    print(f"  ALPHA = {alpha}")
    print(f"  BETA  = {beta}")
    print(f"  GAMMA = {gamma}")
    print(f"  TimeLimit escenario = {effective_tl} segundos")
    print("=" * 65)

    # Fila base de métricas (se completa si hay solución)
    row = {
        "scenario_name":                  scenario_name,
        "ALPHA":                          alpha,
        "BETA":                           beta,
        "GAMMA":                          gamma,
        "status_code":                    None,
        "status_text":                    None,
        "solution_found":                 False,
        "objective_value":                None,
        "best_bound":                     None,
        "mip_gap_final":                  None,
        "runtime_solver_seconds":         None,
        "pacientes_programados":          0,
        "sesiones_agendadas":             0,
        "max_ocupacion_diaria":           None,
        "capacidad_total":                cap_total,
        "dias_con_modulos_extra":         0,
        "total_modulos_extra":            0,
        "max_modulos_extra_dia":          0,
        "espera_promedio_primera_sesion": None,
        "espera_maxima_primera_sesion":   None,
        "W_modelo":                       None,
        "max_ocupacion_real":             None,
        "diferencia_W_max_ocupacion":     None,
        "output_xlsx":                    None,
    }

    try:
        resultado = construir_y_resolver(
            pacientes, K, K_ext, cap_farmacia,
            horizonte_dias=P.HORIZONTE_DIAS,
            dia_inicio=P.DIA_INICIO,
            scenario=scenario,
            time_limit_override=time_limit_override
        )
    except Exception as e:
        print(f"\n  ✗ Error al construir/resolver escenario '{scenario_name}': {e}")
        row["status_text"] = f"ERROR: {e}"
        return row

    if resultado is None:
        print(f"\n  ✗ No se pudo obtener solución factible para '{scenario_name}'.")
        row["status_text"] = "SIN_SOLUCION_FACTIBLE"
        return row

    model, x, y, W, prep, pacientes_validos, dias = resultado

    # Registrar info del solver
    row["status_code"]            = model.status
    row["status_text"]            = _status_str(model.status)
    row["solution_found"]         = True
    row["objective_value"]        = round(model.ObjVal, 4)
    row["best_bound"]             = round(model.ObjBound, 4) if hasattr(model, 'ObjBound') else None
    row["mip_gap_final"]          = round(model.MIPGap * 100, 2)
    row["runtime_solver_seconds"] = round(model.Runtime, 1)

    # --- Extraer resultados ---
    try:
        df_schedule, df_resumen = extraer_resultados(
            model, x, y, W, prep, pacientes_validos, dias, K, K_ext, cap_farmacia
        )
    except ValueError as e:
        print(f"\n  ✗ Validación falló para '{scenario_name}': {e}")
        row["status_text"] = f"INVALID: {e}"
        row["solution_found"] = False
        return row

    imprimir_estadisticas(model, df_schedule, df_resumen, pacientes_validos, K, K_ext)
    xlsx_path = exportar_resultados(
        model, df_schedule, df_resumen, pacientes_validos, dias, K, suffix=suffix
    )

    # --- Calcular métricas operacionales ---
    W_val = model.getVarByName("W").X
    max_ocup_real = df_resumen["ocupacion_modulos"].max() if not df_resumen.empty else 0

    df_primera = (
        df_schedule[
            (df_schedule["ciclo"] == 1) & (df_schedule["sesion"] == 1)
        ] if not df_schedule.empty else pd.DataFrame(columns=["espera_dias"])
    )

    row["pacientes_programados"]          = df_schedule["paciente_id"].nunique() if not df_schedule.empty else 0
    row["sesiones_agendadas"]             = len(df_schedule)
    row["max_ocupacion_diaria"]           = round(max_ocup_real, 1)
    row["dias_con_modulos_extra"]         = len(df_resumen[df_resumen["modulos_extra_usados"] > 1e-6]) if not df_resumen.empty else 0
    row["total_modulos_extra"]            = round(df_resumen["modulos_extra_usados"].sum(), 1) if not df_resumen.empty else 0
    row["max_modulos_extra_dia"]          = round(df_resumen["modulos_extra_usados"].max(), 1) if not df_resumen.empty else 0
    row["espera_promedio_primera_sesion"] = round(df_primera["espera_dias"].mean(), 1) if not df_primera.empty else None
    row["espera_maxima_primera_sesion"]   = int(df_primera["espera_dias"].max()) if not df_primera.empty else None
    row["W_modelo"]                       = round(W_val, 1)
    row["max_ocupacion_real"]             = round(max_ocup_real, 1)
    row["diferencia_W_max_ocupacion"]     = round(W_val - max_ocup_real, 2)
    row["output_xlsx"]                    = xlsx_path

    # --- Post-solución: imprimir diagnóstico detallado ---
    print(f"\n  --- Diagnóstico escenario: {scenario_name} ---")
    print(f"  Status Gurobi:           {row['status_code']} ({row['status_text']})")
    print(f"  Solución factible:       Sí")
    print(f"  Objective value:         {row['objective_value']}")
    print(f"  Best bound:              {row['best_bound']}")
    print(f"  Gap final:               {row['mip_gap_final']}%")
    print(f"  Runtime solver:          {row['runtime_solver_seconds']}s")
    print(f"  Pacientes programados:   {row['pacientes_programados']}")
    print(f"  Sesiones agendadas:      {row['sesiones_agendadas']}")
    print(f"  Máx. ocupación diaria:  {row['max_ocupacion_diaria']}")
    print(f"  Días con módulos extra:  {row['dias_con_modulos_extra']}")
    print(f"  Total módulos extra:     {row['total_modulos_extra']}")
    print(f"  Máx. módulos extra/día: {row['max_modulos_extra_dia']}")
    print(f"  Espera promedio 1ª ses:  {row['espera_promedio_primera_sesion']}")
    print(f"  Espera máxima 1ª ses:    {row['espera_maxima_primera_sesion']}")
    print(f"  W del modelo:            {row['W_modelo']}")
    print(f"  Máx. ocupación real:     {row['max_ocupacion_real']}")
    print(f"  Diferencia W - max_ocup: {row['diferencia_W_max_ocupacion']}")

    return row


def main():
    t0 = time.time()

    # --- Cargar datos ---
    df_config, df_params, df_arribos, df_bajas = cargar_datos()
    K, K_ext, cap_farmacia = extraer_parametros_globales(df_params)
    tipos = construir_tipos(df_config)

    # --- Generar pacientes ---
    pacientes = generar_pacientes(
        df_arribos, df_bajas, tipos,
        horizonte_dias=P.HORIZONTE_DIAS,
        dia_inicio=P.DIA_INICIO
    )
    print(f"    > Pacientes generados (total llegadas): {len(pacientes)}")

    # --- Modo: una corrida o múltiples escenarios ---
    if not P.RUN_ALL_SCENARIOS:
        # Corrida única con pesos base (comportamiento original)
        result = _run_single(pacientes, K, K_ext, cap_farmacia)
        if not result.get("solution_found", False):
            print("\n✗ No se pudo obtener solución. Revise parámetros o amplíe el time limit.")
            sys.exit(1)
    else:
        # Múltiples escenarios
        print(f"\n{'='*65}")
        print(f"  MODO MULTI-ESCENARIO: {len(P.PARAM_SCENARIOS)} escenarios")
        print(f"  TimeLimit por escenario: {P.SCENARIO_TIME_LIMIT_SECONDS}s")
        print(f"{'='*65}")

        resultados = []
        for i, scenario in enumerate(P.PARAM_SCENARIOS, 1):
            print(f"\n{'*'*65}")
            print(f"  [{i}/{len(P.PARAM_SCENARIOS)}] Iniciando escenario: {scenario['name']}")
            print(f"{'*'*65}")

            suffix = f"_{scenario['name']}"
            result = _run_single(
                pacientes, K, K_ext, cap_farmacia,
                scenario=scenario,
                suffix=suffix,
                time_limit_override=P.SCENARIO_TIME_LIMIT_SECONDS
            )
            resultados.append(result)

        # --- Generar CSV comparativo (siempre, incluso si no hay soluciones) ---
        df_comp = pd.DataFrame(resultados)
        comp_path = "resumen_experimentos.csv"
        df_comp.to_csv(comp_path, index=False)

        # --- Tabla comparativa en consola ---
        n_ok = sum(1 for r in resultados if r["solution_found"])
        print(f"\n{'='*65}")
        print(f"  COMPARACIÓN DE ESCENARIOS ({n_ok}/{len(resultados)} con solución)")
        print(f"{'='*65}")
        print(f"  {'Escenario':42s} {'Fact':>4s} {'max_ocup':>8s} {'extra_d':>7s} "
              f"{'tot_ext':>7s} {'esp_prom':>8s} {'esp_max':>7s} {'gap%':>6s} {'t(s)':>5s}")
        print(f"  {'-'*42} {'----':>4s} {'--------':>8s} {'-------':>7s} "
              f"{'-------':>7s} {'--------':>8s} {'-------':>7s} {'------':>6s} {'-----':>5s}")
        for r in resultados:
            fact = ">" if r["solution_found"] else "✗"
            max_o  = f"{r['max_ocupacion_diaria']:.0f}" if r["max_ocupacion_diaria"] is not None else "-"
            ext_d  = f"{r['dias_con_modulos_extra']}"   if r["solution_found"] else "-"
            tot_e  = f"{r['total_modulos_extra']:.0f}"  if r["solution_found"] else "-"
            esp_p  = f"{r['espera_promedio_primera_sesion']:.1f}" if r["espera_promedio_primera_sesion"] is not None else "-"
            esp_m  = f"{r['espera_maxima_primera_sesion']}"       if r["espera_maxima_primera_sesion"] is not None else "-"
            gap    = f"{r['mip_gap_final']:.1f}"                 if r["mip_gap_final"] is not None else "-"
            rt     = f"{r['runtime_solver_seconds']:.0f}"        if r["runtime_solver_seconds"] is not None else "-"
            print(f"  {r['scenario_name']:42s} {fact:>4s} {max_o:>8s} {ext_d:>7s} "
                  f"{tot_e:>7s} {esp_p:>8s} {esp_m:>7s} {gap:>6s} {rt:>5s}")

        print(f"\n  > Resumen comparativo exportado a: {comp_path}")
        print(f"{'='*65}")

        if n_ok == 0:
            print("\n✗ Ningún escenario produjo solución factible.")
            sys.exit(1)

    print(f"\n  Tiempo total de ejecución: {time.time() - t0:.1f}s")
    print("=" * 65)


if __name__ == "__main__":
    main()

