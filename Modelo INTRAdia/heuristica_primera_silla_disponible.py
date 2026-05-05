import argparse
import time
from pathlib import Path
import pandas as pd
import gurobipy as gp
from gurobipy import GRB
import warnings

warnings.filterwarnings("ignore")

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent

def resolve_existing_path(path_str, candidates, label):
    tried = []
    if path_str:
        raw = Path(path_str)
        candidates_to_try = [raw]
        if not raw.is_absolute():
            candidates_to_try.extend([Path.cwd() / raw, SCRIPT_DIR / raw, PROJECT_DIR / raw])
        for c in candidates_to_try:
            c = c.resolve()
            tried.append(c)
            if c.exists():
                return str(c)
    
    for c in candidates:
        c = c.resolve()
        tried.append(c)
        if c.exists():
            return str(c)
            
    tried_txt = "\n  - ".join(str(x) for x in tried)
    raise FileNotFoundError(f"No se encontró {label}. Rutas probadas:\n  - {tried_txt}")

def default_base_data_path(path=None):
    return resolve_existing_path(
        path,
        [SCRIPT_DIR / "Data G15.xlsx", SCRIPT_DIR / "Data Inicial" / "Data G15.xlsx", PROJECT_DIR / "Data Inicial" / "Data G15.xlsx", Path.cwd() / "Data Inicial" / "Data G15.xlsx"],
        "Data G15.xlsx"
    )

def default_arrivals_path(path=None):
    return resolve_existing_path(
        path,
        [SCRIPT_DIR / "DatosV2.xlsx", PROJECT_DIR / "DatosV2.xlsx", PROJECT_DIR / "Modelo Interdia" / "DatosV2.xlsx", Path.cwd() / "DatosV2.xlsx"],
        "DatosV2.xlsx"
    )

def default_solution_path(path=None):
    return resolve_existing_path(
        path,
        [
            SCRIPT_DIR / "solution_interday.xlsx",
            PROJECT_DIR / "solution_interday.xlsx",
            Path.cwd() / "solution_interday.xlsx",
        ],
        "solution_interday.xlsx"
    )

# ---------------------------------------------------------------------------
# ALTA: Cargar desde solution_interday.xlsx (misma fuente que modelo optimizado)
# ---------------------------------------------------------------------------
def load_interday_sessions(solution_path, base_data_path=None):
    """Lee las asignaciones del modelo interdia y las convierte en sesiones
    con t_min = día asignado por el modelo interdia. Garantiza comparabilidad
    exacta con modelo_deldia_v2_adaptado."""
    sol_path = default_solution_path(solution_path)
    print(f"[INFO] Cargando sesiones desde solution interdia: {sol_path}")
    assignments = pd.read_excel(sol_path, sheet_name="Asignaciones").copy()

    # Normalizar nombre de columna patient_type
    for col in ["patient_type", "patient_type_x", "patient_type_y"]:
        if col in assignments.columns:
            assignments["patient_type"] = assignments[col].astype(int)
            break

    for col in ["patient_id", "day", "cycle", "session", "modules"]:
        assignments[col] = assignments[col].astype(int)

    # Obtener pharmacy_modules desde Data G15
    base_data = load_base_data(base_data_path)
    patient_types = base_data["patient_types"]

    def get_pharm(ptype):
        return int(patient_types.get(int(ptype), {}).get("modulos_lab", 0))

    assignments["pharmacy_modules"] = assignments["patient_type"].map(get_pharm)
    assignments["t_min"] = assignments["day"]  # día asignado = día mínimo factible

    print(
        f"[INFO] Sesiones interdia cargadas: {len(assignments)} sesiones, "
        f"{assignments['patient_id'].nunique()} pacientes, "
        f"días [{assignments['day'].min()}..{assignments['day'].max()}]"
    )
    return assignments, base_data

class ExecutionTimer:
    def __init__(self, name):
        self.name = name
        self.start = time.perf_counter()
        self.last = self.start
        print(f"[TIMER] Inicio {name}")

    def lap(self, label):
        now = time.perf_counter()
        print(f"[TIMER] {label}: +{now - self.last:.2f}s | total {now - self.start:.2f}s")
        self.last = now

    def finish(self):
        now = time.perf_counter()
        print(f"[TIMER] Fin {self.name}: total {now - self.start:.2f}s")

def load_base_data(path=None):
    path = default_base_data_path(path)
    print(f"[INFO] Cargando parámetros base desde: {path}")
    df_params = pd.read_excel(path, sheet_name="Sheet1", header=None)
    capacity = {
        "chairs": int(df_params.iloc[2, 1]),
        "n_enfermeras": int(df_params.iloc[3, 1]),
        "modules_ordinary": int(df_params.iloc[4, 1]),
        "modules_extraordinary": int(df_params.iloc[5, 1]),
        "modulos_farmacia": int(df_params.iloc[6, 1]),
        "n_farmaceuticos": int(df_params.iloc[7, 1]),
    }
    capacity["total_modules"] = capacity["modules_ordinary"] + capacity["modules_extraordinary"]

    df_types = pd.read_excel(path, sheet_name="Sheet2")
    patient_types = {}
    for _, row in df_types.iterrows():
        pid = int(row["Id"])
        var = str(row["variable"]).strip()
        val = row["valor"]
        patient_types.setdefault(pid, {})
        if var == "Ciclos": patient_types[pid]["ciclos"] = int(val)
        elif var == "Sesiones": patient_types[pid]["sesiones"] = int(val)
        elif var in ("Modulos", "Módulos", "MÃ³dulos"): patient_types[pid]["modulos"] = int(val)
        elif var == "TBS": patient_types[pid]["tbs"] = int(val)
        elif var == "TBC": patient_types[pid]["tbc"] = int(val)
        elif var in ("Modulos Lab.", "Módulos Lab.", "MÃ³dulos Lab."): patient_types[pid]["modulos_lab"] = int(val)

    return {"capacity": capacity, "patient_types": patient_types}

def generate_sessions(arrivals_path, patient_types, max_days):
    arrivals_path = default_arrivals_path(arrivals_path)
    print(f"[INFO] Cargando llegadas desde: {arrivals_path}")
    df_arribos = pd.read_excel(arrivals_path, sheet_name="Motor_Arribos")
    
    sessions = []
    patient_id_counter = 1
    
    for _, row in df_arribos.iterrows():
        dia = int(row["Dia"])
        if dia > max_days: continue
        
        for col in df_arribos.columns:
            if col.startswith("Tipo "):
                tipo = int(col.split()[-1])
                n_llegadas = int(row[col])
                if n_llegadas > 0 and tipo in patient_types:
                    pt = patient_types[tipo]
                    for _ in range(n_llegadas):
                        ultimo_dia_minimo = dia + (pt["ciclos"] - 1) * pt["tbc"] + (pt["sesiones"] - 1) * pt["tbs"]
                        
                        if ultimo_dia_minimo <= max_days:
                            for c in range(1, pt["ciclos"] + 1):
                                for s in range(1, pt["sesiones"] + 1):
                                    t_min = dia + (c - 1) * pt["tbc"] + (s - 1) * pt["tbs"]
                                    sessions.append({
                                        "patient_id": patient_id_counter,
                                        "patient_type": tipo,
                                        "cycle": c,
                                        "session": s,
                                        "t_min": t_min,
                                        "modules": pt["modulos"],
                                        "pharmacy_modules": pt["modulos_lab"]
                                    })
                        patient_id_counter += 1
                        
    return pd.DataFrame(sessions)

class HeuristicDayScheduler:
    def __init__(self, day, sessions_df, capacity, pharmacy_capacity_source="n_farmaceuticos"):
        self.day = day
        self.sessions = sessions_df.to_dict('records')
        self.capacity = capacity
        self.M = list(range(int(capacity["total_modules"])))
        self.S = int(capacity["chairs"])
        self.E = int(capacity["n_enfermeras"])
        self.Cf = int(capacity[pharmacy_capacity_source])
        
        self.chairs_used = [0] * len(self.M)
        self.pharmacy_used = [0] * len(self.M)
        self.nurse_used = [0] * len(self.M)
        
        self.schedule = []
        self.unplaced = []

    def check_capacity(self, pharm_start, Fp, treat_start, Dp):
        treat_end = treat_start + Dp - 1
        if treat_end >= len(self.M): return False
        if Fp > 0 and pharm_start + Fp > len(self.M): return False
        
        for m in range(treat_start, treat_end + 1):
            if self.chairs_used[m] + 1 > self.S: return False
            
        for m in range(pharm_start, pharm_start + Fp):
            if self.pharmacy_used[m] + 1 > self.Cf: return False
            
        if self.nurse_used[treat_start] + 1 > self.E: return False
        if self.nurse_used[treat_end] + 1 > self.E: return False
        
        return True

    def find_first_feasible_block(self, session):
        Dp = session["modules"]
        Fp = session["pharmacy_modules"]
        M_ord = self.capacity["modules_ordinary"]  # módulo límite ordinario
        M_total = len(self.M)                        # total incluyendo extra
        
        # Buscar primero en módulos ordinarios, luego en extra
        # Esto replica la lógica del modelo optimizado con penalidad por módulos extra
        for treat_start in range(0, M_total - Dp + 1):
            if Fp == 0:
                if self.check_capacity(treat_start, Fp, treat_start, Dp):
                    return treat_start, treat_start
            else:
                # pharm debe terminar ANTES de que empiece el tratamiento
                # y la farmacia cierra en el módulo 20
                for pharm_start in range(0, treat_start - Fp + 1):
                    # Restricción: la farmacia cierra en el módulo 20
                    if pharm_start + Fp - 1 <= 20:
                        if self.check_capacity(pharm_start, Fp, treat_start, Dp):
                            return pharm_start, treat_start
        return None, None

    def assign_session(self, session, pharm_start, treat_start):
        Dp = session["modules"]
        Fp = session["pharmacy_modules"]
        treat_end = treat_start + Dp - 1
        
        for m in range(treat_start, treat_end + 1):
            self.chairs_used[m] += 1
        for m in range(pharm_start, pharm_start + Fp):
            self.pharmacy_used[m] += 1
            
        self.nurse_used[treat_start] += 1
        self.nurse_used[treat_end] += 1
        
        pharm_end = pharm_start + Fp - 1 if Fp > 0 else None
        wait_after_pharmacy = (treat_start - pharm_end - 1) if (Fp > 0 and pharm_end is not None) else 0
        self.schedule.append({
            "day": self.day,
            "patient_id": session["patient_id"],
            "patient_type": session["patient_type"],
            "cycle": session["cycle"],
            "session": session["session"],
            "pharmacy_start": pharm_start,
            "pharmacy_end": pharm_end,
            "treatment_start": treat_start,
            "treatment_end": treat_end,
            "treatment_modules": Dp,
            "pharmacy_modules": Fp,
            "wait_after_pharmacy": wait_after_pharmacy,
            "extra_chair_modules": sum(1 for m in range(treat_start, treat_end + 1) if m >= self.capacity["modules_ordinary"]),
            "due_day": session["t_min"],
            "delay_days": self.day - session["t_min"]
        })

    def run_greedy(self, completed_sessions=None):
        """Ejecuta la asignación greedy.
        
        MEDIA: completed_sessions es un set de tuplas (patient_id, cycle, session)
        que ya fueron programadas en días anteriores. Se bloquea una sesión si
        su predecesora en la secuencia clínica aún no ha sido completada.
        """
        if completed_sessions is None:
            completed_sessions = set()

        self.sessions.sort(key=lambda x: (-(self.day - x["t_min"]), x["patient_type"], x["patient_id"]))
        
        for session in self.sessions:
            pid = session["patient_id"]
            c = session["cycle"]
            s = session["session"]

            # MEDIA: Verificar orden de sesión
            # No programar (c,s) si (c,s-1) no está completada
            if s > 1 and (pid, c, s - 1) not in completed_sessions:
                self.unplaced.append(session)
                continue
            # No programar (c,1) si (c-1, ultima_sesion) no está completada
            # Nota: necesitamos saber cuántas sesiones tiene el ciclo anterior
            # Lo inferimos buscando la sesión máxima del ciclo c-1 para este paciente
            if s == 1 and c > 1:
                max_s_prev = max(
                    (s2 for (p2, c2, s2) in completed_sessions if p2 == pid and c2 == c - 1),
                    default=None
                )
                # Si no hay ninguna sesión completada del ciclo anterior, bloquear
                if max_s_prev is None:
                    self.unplaced.append(session)
                    continue
                # Verificar que la última sesión del ciclo anterior esté completa
                # Buscamos la sesión máxima esperada para ese ciclo en la cola actual
                expected_last_s = max(
                    (sess["session"] for sess in self.sessions if sess["patient_id"] == pid and sess["cycle"] == c - 1),
                    default=max_s_prev
                )
                if (pid, c - 1, expected_last_s) not in completed_sessions:
                    self.unplaced.append(session)
                    continue

            pharm_start, treat_start = self.find_first_feasible_block(session)
            if pharm_start is not None:
                self.assign_session(session, pharm_start, treat_start)
                completed_sessions.add((pid, c, s))
            else:
                self.unplaced.append(session)

    def validate_with_gurobi(self):
        if not self.schedule: return True
        model = gp.Model(f"Validate_day_{self.day}")
        model.setParam("OutputFlag", 0)
        
        x = {}
        for i, s in enumerate(self.schedule):
            x[i] = model.addVar(vtype=GRB.BINARY, name=f"x_{i}")
            model.addConstr(x[i] == 1) 
            
        for m in self.M:
            chairs = sum(1 * x[i] for i, s in enumerate(self.schedule) if s["treatment_start"] <= m <= s["treatment_end"])
            model.addConstr(chairs <= self.S)
            
            pharm = sum(1 * x[i] for i, s in enumerate(self.schedule) if s["pharmacy_modules"] > 0 and s["pharmacy_start"] <= m <= s["pharmacy_end"])
            model.addConstr(pharm <= self.Cf)
            
            nurse = sum(1 * x[i] for i, s in enumerate(self.schedule) if s["treatment_start"] == m or s["treatment_end"] == m)
            model.addConstr(nurse <= self.E)
            
        model.optimize()
        if model.status != GRB.OPTIMAL:
            print(f"[WARNING] Día {self.day} infactible según Gurobi. Revisar restricciones.")
            return False
        return True

    def get_results(self):
        occupancy = []
        for m in self.M:
            occupancy.append({
                "day": self.day,
                "module": m,
                "is_extra": int(m >= self.capacity["modules_ordinary"]),
                "chairs_used": self.chairs_used[m],
                "pharmacy_used": self.pharmacy_used[m],
                "nurse_events": self.nurse_used[m],
                "chair_capacity": self.S,
                "pharmacy_capacity": self.Cf,
                "nurse_capacity": self.E,
            })
        return self.schedule, occupancy, self.unplaced

def run_heuristic(base_data_path, arrivals_path, max_days, output_path, enable_repack, solution_path=None):
    timer = ExecutionTimer("Heurística Primera Silla Disponible")

    # ALTA: Usar solution_interday como fuente si se proporciona
    if solution_path:
        all_sessions_df, base_data = load_interday_sessions(solution_path, base_data_path)
        capacity = base_data["capacity"]
        # Con interdia, el horizonte lo fija el rango de días de la solución
        first_day = int(all_sessions_df["t_min"].min())
        last_day = int(all_sessions_df["t_min"].max()) + 1
        print(f"[INFO] Modo interdia: resolviendo días {first_day} a {last_day - 1}")
    else:
        base_data = load_base_data(base_data_path)
        capacity = base_data["capacity"]
        all_sessions_df = generate_sessions(arrivals_path, base_data["patient_types"], max_days)
        first_day = int(all_sessions_df["t_min"].min()) if not all_sessions_df.empty else 0
        last_day = first_day + max_days
        print(f"[INFO] Modo DatosV2: resolviendo días {first_day} a {last_day - 1}")

    print(f"[INFO] Total de sesiones: {len(all_sessions_df)}")

    all_schedule = []
    all_occupancy = []
    summaries = []
    pending_sessions = pd.DataFrame()
    # MEDIA: set global de sesiones completadas para respetar orden clínico
    completed_sessions = set()

    for day in range(first_day, last_day):
        print(f"\n[INFO] Resolviendo día {day}")

        # Sesiones cuyo t_min es este día (llegadas nuevas)
        day_sessions = all_sessions_df[all_sessions_df["t_min"] == day]
        # Incorporar sesiones postergadas de días anteriores
        if not pending_sessions.empty:
            day_sessions = pd.concat([day_sessions, pending_sessions])

        scheduler = HeuristicDayScheduler(day, day_sessions, capacity)
        scheduler.run_greedy(completed_sessions)
        # Actualizar set global con las sesiones programadas hoy
        for s in scheduler.schedule:
            completed_sessions.add((s["patient_id"], s["cycle"], s["session"]))

        if not scheduler.validate_with_gurobi():
            print(f"[ERROR] Falló validación de Gurobi en el día {day}")

        schedule, occupancy, unplaced = scheduler.get_results()

        all_schedule.extend(schedule)
        all_occupancy.extend(occupancy)
        pending_sessions = pd.DataFrame(unplaced)

        summaries.append({
            "day": day,
            "sessions_attempted": len(day_sessions),
            "sessions_scheduled": len(schedule),
            "sessions_postponed": len(unplaced),
            "total_extra_chair_modules": sum(s["extra_chair_modules"] for s in schedule),
            "max_chairs_used": max(o["chairs_used"] for o in occupancy) if occupancy else 0
        })

        
    print(f"\n[INFO] Simulacion finalizada. {len(pending_sessions)} sesiones pendientes al final del horizonte.")
    
    if not pending_sessions.empty:
        # delay = cuántos días pasaron desde el t_min hasta el último día del horizonte
        pending_sessions["delay_days"] = (last_day - 1) - pending_sessions["t_min"]
        
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        pd.DataFrame(summaries).to_excel(writer, sheet_name="Resumen_Dias", index=False)
        pd.DataFrame(all_schedule).to_excel(writer, sheet_name="Programacion", index=False)
        pd.DataFrame(all_occupancy).to_excel(writer, sheet_name="Ocupacion_Modulos", index=False)
        if not pending_sessions.empty:
            pending_sessions.to_excel(writer, sheet_name="Pendientes", index=False)
            
    timer.finish()
    print(f"[INFO] Resultados guardados en {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-data", default=None)
    parser.add_argument("--arrivals", default=None)
    parser.add_argument("--solution", default=None, help="Ruta a solution_interday.xlsx (modo comparable con modelo optimizado)")
    parser.add_argument("--max-days", type=int, default=240, help="Horizonte (solo aplica en modo DatosV2, ignorado si --solution está activo)")
    parser.add_argument("--output", default="solution_heuristica.xlsx")
    parser.add_argument("--enable-gurobi-repack", action="store_true")
    args = parser.parse_args()
    
    run_heuristic(args.base_data, args.arrivals, args.max_days, args.output, args.enable_gurobi_repack, solution_path=args.solution)
