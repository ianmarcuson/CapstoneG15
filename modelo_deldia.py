import argparse
import time
import warnings
from dataclasses import dataclass

import gurobipy as gp
from gurobipy import GRB
import pandas as pd

warnings.filterwarnings("ignore")


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


@dataclass(frozen=True)
class Pattern:
    patient_idx: int
    pharmacy_start: int
    treatment_start: int
    treatment_end: int
    a: tuple
    b: tuple
    d: tuple
    g: tuple
    q: tuple
    h: int
    reduced_cost: float = 0.0

    @property
    def signature(self):
        return (self.pharmacy_start, self.treatment_start)


def load_base_data(path="Data G15.xlsx"):
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
        var = str(row["variable"])
        val = row["valor"]
        patient_types.setdefault(pid, {})
        if var == "Ciclos":
            patient_types[pid]["ciclos"] = int(val)
        elif var == "Sesiones":
            patient_types[pid]["sesiones"] = int(val)
        elif var in ("Modulos", "Módulos", "MÃ³dulos"):
            patient_types[pid]["modulos"] = int(val)
        elif var == "TBS":
            patient_types[pid]["tbs"] = int(val)
        elif var == "TBC":
            patient_types[pid]["tbc"] = int(val)
        elif var == "Tasa de Llegada":
            patient_types[pid]["tasa_llegada"] = float(val)
        elif var in ("Modulos Lab.", "Módulos Lab.", "MÃ³dulos Lab."):
            patient_types[pid]["modulos_lab"] = int(val)

    return {"capacity": capacity, "patient_types": patient_types}


def _first_existing_column(df, candidates):
    for col in candidates:
        if col in df.columns:
            return col
    raise ValueError(f"No se encontro ninguna columna entre: {candidates}")


def load_interday_assignments(solution_path="solution_interday.xlsx", base_data_path="Data G15.xlsx"):
    base_data = load_base_data(base_data_path)
    assignments = pd.read_excel(solution_path, sheet_name="Asignaciones")

    type_col = _first_existing_column(assignments, ["patient_type", "patient_type_x", "patient_type_y"])
    required = ["patient_id", "day", "cycle", "session", "modules", "arrival_day", type_col]
    missing = [col for col in required if col not in assignments.columns]
    if missing:
        raise ValueError(f"Faltan columnas en Asignaciones: {missing}")

    assignments = assignments.copy()
    assignments["patient_type"] = assignments[type_col].astype(int)
    assignments["patient_id"] = assignments["patient_id"].astype(int)
    assignments["day"] = assignments["day"].astype(int)
    assignments["cycle"] = assignments["cycle"].astype(int)
    assignments["session"] = assignments["session"].astype(int)
    assignments["modules"] = assignments["modules"].astype(int)

    def prep_modules(patient_type):
        info = base_data["patient_types"].get(int(patient_type), {})
        return int(info.get("modulos_lab", 0))

    assignments["pharmacy_modules"] = assignments["patient_type"].map(prep_modules).astype(int)
    return assignments, base_data


class ColumnGenerationDayModel:
    """
    Modelo del dia alineado con modelo_column_generation.md.

    P del maestro corresponde a las sesiones del dia que vienen desde
    solution_interday.xlsx. Cada patron k es un horario factible para una
    sesion: inicio de farmacia, inicio de tratamiento, fin de tratamiento,
    ocupacion de silla, farmacia y enfermeria por modulo.
    """

    def __init__(
        self,
        day,
        day_assignments,
        capacity,
        pharmacy_capacity_source="n_farmaceuticos",
        max_iterations=50,
        reduced_cost_tol=1e-6,
        print_gurobi=False,
    ):
        self.day = int(day)
        self.assignments = day_assignments.reset_index(drop=True).copy()
        self.capacity = capacity
        self.M = list(range(capacity["total_modules"]))
        self.M_normal = list(range(capacity["modules_ordinary"]))
        self.M_extra = list(range(capacity["modules_ordinary"], capacity["total_modules"]))
        self.S = capacity["chairs"]
        self.E = capacity["n_enfermeras"]
        self.Cf = capacity[pharmacy_capacity_source]
        self.max_iterations = max_iterations
        self.reduced_cost_tol = reduced_cost_tol
        self.print_gurobi = print_gurobi
        self.patterns = {p: [] for p in range(len(self.assignments))}
        self.solution = None

    def _row_params(self, p):
        row = self.assignments.iloc[p]
        return int(row["modules"]), int(row["pharmacy_modules"])

    def _make_pattern(self, p, pharmacy_start, treatment_start, reduced_cost=0.0):
        Dp, Fp = self._row_params(p)
        treatment_end = treatment_start + Dp - 1
        horizon = len(self.M)
        if Fp > 0 and pharmacy_start + Fp > horizon:
            raise ValueError("Patron con farmacia fuera del horizonte")
        if treatment_end >= horizon:
            raise ValueError("Patron con tratamiento fuera del horizonte")
        if treatment_start < pharmacy_start + Fp:
            raise ValueError("Patron viola medicamento listo antes de iniciar")

        a = [0] * horizon
        b = [0] * horizon
        d = [0] * horizon
        g = [0] * horizon
        q = [0] * horizon

        a[treatment_start] = 1
        b[treatment_end] = 1
        q[treatment_start] += 1
        q[treatment_end] += 1

        for m in range(treatment_start, treatment_end + 1):
            d[m] = 1
        for m in range(pharmacy_start, pharmacy_start + Fp):
            g[m] = 1

        # Segun el MD: h_p = sum_{m in M_e} u_m. Cuenta modulos extra de silla.
        h = sum(d[m] for m in self.M_extra)
        return Pattern(
            patient_idx=p,
            pharmacy_start=int(pharmacy_start),
            treatment_start=int(treatment_start),
            treatment_end=int(treatment_end),
            a=tuple(a),
            b=tuple(b),
            d=tuple(d),
            g=tuple(g),
            q=tuple(q),
            h=int(h),
            reduced_cost=float(reduced_cost),
        )

    def _add_pattern_if_new(self, pattern):
        existing = {pat.signature for pat in self.patterns[pattern.patient_idx]}
        if pattern.signature in existing:
            return False
        self.patterns[pattern.patient_idx].append(pattern)
        return True

    def initialize_patterns(self):
        """
        Genera una columna inicial factible para cada sesion usando un packing greedy.
        Esto hace que el maestro restringido inicial sea factible.
        """
        chairs_used = [0] * len(self.M)
        pharmacy_used = [0] * len(self.M)
        nurse_used = [0] * len(self.M)

        order = sorted(range(len(self.assignments)), key=lambda p: self._row_params(p)[0], reverse=True)
        for p in order:
            Dp, Fp = self._row_params(p)
            placed = False
            for treatment_start in range(0, len(self.M) - Dp + 1):
                treatment_end = treatment_start + Dp - 1
                if nurse_used[treatment_start] + 1 > self.E or nurse_used[treatment_end] + 1 > self.E:
                    continue
                if any(chairs_used[m] + 1 > self.S for m in range(treatment_start, treatment_end + 1)):
                    continue

                latest_pharmacy_start = treatment_start - Fp
                if latest_pharmacy_start < 0:
                    continue
                for pharmacy_start in range(latest_pharmacy_start, -1, -1):
                    pharmacy_end = pharmacy_start + Fp - 1
                    if any(pharmacy_used[m] + 1 > self.Cf for m in range(pharmacy_start, pharmacy_end + 1)):
                        continue

                    pattern = self._make_pattern(p, pharmacy_start, treatment_start)
                    self._add_pattern_if_new(pattern)
                    for m in range(treatment_start, treatment_end + 1):
                        chairs_used[m] += 1
                    for m in range(pharmacy_start, pharmacy_end + 1):
                        pharmacy_used[m] += 1
                    nurse_used[treatment_start] += 1
                    nurse_used[treatment_end] += 1
                    placed = True
                    break
                if placed:
                    break

            if not placed:
                raise ValueError(
                    f"No se pudo construir patron inicial factible para fila {p} "
                    f"del dia {self.day}. Dp={Dp}, Fp={Fp}"
                )

    def solve_master(self, relax=True):
        model = gp.Model(f"Master_day_{self.day}_{'LP' if relax else 'MIP'}")
        model.setParam("OutputFlag", 1 if self.print_gurobi else 0)

        x = {}
        vtype = GRB.CONTINUOUS if relax else GRB.BINARY
        for p, pats in self.patterns.items():
            for k, _ in enumerate(pats):
                x[p, k] = model.addVar(lb=0, ub=1, vtype=vtype, name=f"x_{p}_{k}")

        assign_constr = {}
        chair_constr = {}
        nurse_constr = {}
        pharmacy_constr = {}

        for p, pats in self.patterns.items():
            assign_constr[p] = model.addConstr(
                gp.quicksum(x[p, k] for k in range(len(pats))) == 1,
                name=f"assign_{p}",
            )

        for m in self.M:
            chair_constr[m] = model.addConstr(
                gp.quicksum(pat.d[m] * x[p, k] for p, pats in self.patterns.items() for k, pat in enumerate(pats))
                <= self.S,
                name=f"chair_{m}",
            )
            nurse_constr[m] = model.addConstr(
                gp.quicksum(
                    (pat.a[m] + pat.b[m]) * x[p, k]
                    for p, pats in self.patterns.items()
                    for k, pat in enumerate(pats)
                )
                <= self.E,
                name=f"nurse_{m}",
            )
            pharmacy_constr[m] = model.addConstr(
                gp.quicksum(pat.g[m] * x[p, k] for p, pats in self.patterns.items() for k, pat in enumerate(pats))
                <= self.Cf,
                name=f"pharmacy_{m}",
            )

        model.setObjective(
            gp.quicksum(pat.h * x[p, k] for p, pats in self.patterns.items() for k, pat in enumerate(pats)),
            GRB.MINIMIZE,
        )
        model.optimize()

        if model.status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL, GRB.TIME_LIMIT):
            raise RuntimeError(f"Maestro no resuelto. Status={model.status}")
        if model.SolCount == 0:
            raise RuntimeError(f"Maestro sin solucion. Status={model.status}")

        duals = None
        if relax and model.status == GRB.OPTIMAL:
            duals = {
                "lambda": {p: constr.Pi for p, constr in assign_constr.items()},
                "chair": {m: constr.Pi for m, constr in chair_constr.items()},
                "nurse": {m: constr.Pi for m, constr in nurse_constr.items()},
                "pharmacy": {m: constr.Pi for m, constr in pharmacy_constr.items()},
            }

        selected = {(p, k): var.X for (p, k), var in x.items()}
        return {
            "model": model,
            "obj": model.ObjVal,
            "duals": duals,
            "selected": selected,
            "status": model.status,
            "runtime": model.Runtime,
        }

    def solve_satellite(self, p, duals):
        """
        Subproblema satelite del MD para un paciente/sesion p.
        Devuelve el patron de menor costo reducido.
        """
        Dp, Fp = self._row_params(p)
        model = gp.Model(f"Satellite_day_{self.day}_p_{p}")
        model.setParam("OutputFlag", 1 if self.print_gurobi else 0)

        y = {m: model.addVar(vtype=GRB.BINARY, name=f"y_{m}") for m in self.M}
        z = {m: model.addVar(vtype=GRB.BINARY, name=f"z_{m}") for m in self.M}
        w = {m: model.addVar(vtype=GRB.BINARY, name=f"w_{m}") for m in self.M}
        v = {m: model.addVar(vtype=GRB.BINARY, name=f"v_{m}") for m in self.M}
        u = {m: model.addVar(vtype=GRB.BINARY, name=f"u_{m}") for m in self.M}
        q = {m: model.addVar(vtype=GRB.BINARY, name=f"q_{m}") for m in self.M}

        model.addConstr(gp.quicksum(y[m] for m in self.M) == 1, name="one_pharmacy_start")
        model.addConstr(gp.quicksum(z[m] for m in self.M) == 1, name="one_treatment_start")
        model.addConstr(gp.quicksum(w[m] for m in self.M) == 1, name="one_treatment_end")

        model.addConstr(
            gp.quicksum(m * z[m] for m in self.M) >= gp.quicksum(m * y[m] for m in self.M) + Fp,
            name="med_ready",
        )
        model.addConstr(
            gp.quicksum(m * w[m] for m in self.M) == gp.quicksum(m * z[m] for m in self.M) + Dp - 1,
            name="start_end_relation",
        )

        for m in self.M:
            if Fp > 0 and m > len(self.M) - Fp:
                model.addConstr(y[m] == 0, name=f"late_pharmacy_start_{m}")
            if m > len(self.M) - Dp:
                model.addConstr(z[m] == 0, name=f"late_treatment_start_{m}")

            pharmacy_window = range(max(0, m - Fp + 1), m + 1) if Fp > 0 else []
            treatment_window = range(max(0, m - Dp + 1), m + 1)
            model.addConstr(v[m] == gp.quicksum(y[tau] for tau in pharmacy_window), name=f"pharmacy_occ_{m}")
            model.addConstr(u[m] == gp.quicksum(z[tau] for tau in treatment_window), name=f"chair_occ_{m}")
            model.addConstr(q[m] == z[m] + w[m], name=f"nurse_occ_{m}")

        h_expr = gp.quicksum(u[m] for m in self.M_extra)
        reduced_cost_expr = (
            h_expr
            - duals["lambda"][p]
            - gp.quicksum(
                duals["chair"][m] * u[m] + duals["pharmacy"][m] * v[m] + duals["nurse"][m] * q[m]
                for m in self.M
            )
        )
        model.setObjective(reduced_cost_expr, GRB.MINIMIZE)
        model.optimize()

        if model.status != GRB.OPTIMAL:
            raise RuntimeError(f"Satelite no optimo para p={p}. Status={model.status}")

        pharmacy_start = next(m for m in self.M if y[m].X > 0.5)
        treatment_start = next(m for m in self.M if z[m].X > 0.5)
        return self._make_pattern(p, pharmacy_start, treatment_start, reduced_cost=model.ObjVal)

    def run_column_generation(self):
        timer = ExecutionTimer(f"column generation dia {self.day}")
        self.initialize_patterns()
        timer.lap(f"patrones iniciales: {sum(len(v) for v in self.patterns.values())}")

        history = []
        for iteration in range(1, self.max_iterations + 1):
            master_lp = self.solve_master(relax=True)
            duals = master_lp["duals"]
            if duals is None:
                raise RuntimeError("No se pudieron recuperar duales del maestro LP.")

            added = 0
            best_rc = float("inf")
            for p in range(len(self.assignments)):
                pattern = self.solve_satellite(p, duals)
                best_rc = min(best_rc, pattern.reduced_cost)
                if pattern.reduced_cost < -self.reduced_cost_tol and self._add_pattern_if_new(pattern):
                    added += 1

            total_patterns = sum(len(v) for v in self.patterns.values())
            history.append(
                {
                    "iteration": iteration,
                    "master_lp_obj": master_lp["obj"],
                    "added_patterns": added,
                    "best_reduced_cost": best_rc,
                    "total_patterns": total_patterns,
                }
            )
            print(
                f"[CG] dia={self.day} iter={iteration} lp_obj={master_lp['obj']:.4f} "
                f"best_rc={best_rc:.6f} added={added} patterns={total_patterns}"
            )

            if added == 0:
                break

        final_master = self.solve_master(relax=False)
        timer.lap(f"maestro MIP final obj={final_master['obj']:.4f}")
        self._extract_solution(final_master, history)
        timer.finish()
        return self.solution

    def _extract_solution(self, final_master, history):
        schedule = []
        occupancy = []
        selected_patterns = {}

        for (p, k), value in final_master["selected"].items():
            if value > 0.5:
                selected_patterns[p] = self.patterns[p][k]

        if len(selected_patterns) != len(self.assignments):
            raise RuntimeError("El maestro MIP final no selecciono exactamente un patron por sesion.")

        for p, pattern in selected_patterns.items():
            row = self.assignments.iloc[p]
            Fp = int(row["pharmacy_modules"])
            schedule.append(
                {
                    "day": self.day,
                    "row_idx": p,
                    "patient_id": int(row["patient_id"]),
                    "patient_type": int(row["patient_type"]),
                    "cycle": int(row["cycle"]),
                    "session": int(row["session"]),
                    "pharmacy_start": pattern.pharmacy_start,
                    "pharmacy_end": pattern.pharmacy_start + Fp - 1 if Fp > 0 else pattern.pharmacy_start,
                    "treatment_start": pattern.treatment_start,
                    "treatment_end": pattern.treatment_end,
                    "treatment_modules": int(row["modules"]),
                    "pharmacy_modules": Fp,
                    "extra_chair_modules": pattern.h,
                }
            )

        for m in self.M:
            chairs_used = sum(pattern.d[m] for pattern in selected_patterns.values())
            pharmacy_used = sum(pattern.g[m] for pattern in selected_patterns.values())
            nurse_events = sum(pattern.a[m] + pattern.b[m] for pattern in selected_patterns.values())
            occupancy.append(
                {
                    "day": self.day,
                    "module": m,
                    "is_extra": int(m in self.M_extra),
                    "chairs_used": chairs_used,
                    "pharmacy_used": pharmacy_used,
                    "nurse_events": nurse_events,
                    "chair_capacity": self.S,
                    "pharmacy_capacity": self.Cf,
                    "nurse_capacity": self.E,
                }
            )

        self.solution = {
            "day": self.day,
            "status": final_master["status"],
            "obj_value": final_master["obj"],
            "runtime": final_master["runtime"],
            "schedule": schedule,
            "occupancy": occupancy,
            "history": history,
            "total_patterns": sum(len(v) for v in self.patterns.values()),
            "total_extra_chair_modules": sum(row["extra_chair_modules"] for row in schedule),
        }


def solve_days(
    solution_path="solution_interday.xlsx",
    base_data_path="Data G15.xlsx",
    output_path="solution_deldia.xlsx",
    selected_days=None,
    all_days=False,
    max_days=1,
    max_iterations=50,
    print_gurobi=False,
    pharmacy_capacity_source="n_farmaceuticos",
):
    timer = ExecutionTimer("modelo del dia column generation")
    assignments, base_data = load_interday_assignments(solution_path, base_data_path)
    capacity = base_data["capacity"]
    nonempty_days = sorted(assignments["day"].unique())

    if selected_days:
        requested = {int(day) for day in selected_days}
        days_to_solve = [day for day in nonempty_days if int(day) in requested]
    elif all_days:
        days_to_solve = nonempty_days
    else:
        days_to_solve = nonempty_days[:max_days]

    if not days_to_solve:
        raise ValueError("No hay dias para resolver con los filtros entregados.")

    print(f"[INFO] Dias a resolver: {days_to_solve}")
    print(
        "[INFO] Capacidades: "
        f"S={capacity['chairs']}, E={capacity['n_enfermeras']}, "
        f"Cf={capacity[pharmacy_capacity_source]} ({pharmacy_capacity_source}), "
        f"M={capacity['total_modules']}, M_extra={capacity['modules_extraordinary']}"
    )
    timer.lap("datos cargados")

    all_schedule = []
    all_occupancy = []
    all_history = []
    summaries = []

    for idx, day in enumerate(days_to_solve, start=1):
        day_assignments = assignments[assignments["day"] == day].copy()
        print("\n" + "=" * 80)
        print(f"[INFO] Resolviendo dia {day} ({idx}/{len(days_to_solve)}) | sesiones={len(day_assignments)}")

        model = ColumnGenerationDayModel(
            day=day,
            day_assignments=day_assignments,
            capacity=capacity,
            pharmacy_capacity_source=pharmacy_capacity_source,
            max_iterations=max_iterations,
            print_gurobi=print_gurobi,
        )
        solution = model.run_column_generation()

        all_schedule.extend(solution["schedule"])
        all_occupancy.extend(solution["occupancy"])
        for row in solution["history"]:
            all_history.append({"day": int(day), **row})

        summaries.append(
            {
                "day": int(day),
                "sessions": int(len(day_assignments)),
                "status": int(solution["status"]),
                "obj_value": float(solution["obj_value"]),
                "total_extra_chair_modules": int(solution["total_extra_chair_modules"]),
                "total_patterns": int(solution["total_patterns"]),
                "cg_iterations": int(len(solution["history"])),
                "runtime_final_master": float(solution["runtime"]),
                "max_chairs_used": max(row["chairs_used"] for row in solution["occupancy"]),
                "max_pharmacy_used": max(row["pharmacy_used"] for row in solution["occupancy"]),
                "max_nurse_events": max(row["nurse_events"] for row in solution["occupancy"]),
            }
        )

    summary_df = pd.DataFrame(summaries)
    schedule_df = pd.DataFrame(all_schedule)
    occupancy_df = pd.DataFrame(all_occupancy)
    history_df = pd.DataFrame(all_history)

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="Resumen_Dias", index=False)
        schedule_df.to_excel(writer, sheet_name="Programacion", index=False)
        occupancy_df.to_excel(writer, sheet_name="Ocupacion_Modulos", index=False)
        history_df.to_excel(writer, sheet_name="CG_Historial", index=False)

    timer.lap(f"resultados guardados en {output_path}")
    timer.finish()
    return {"summary": summary_df, "schedule": schedule_df, "occupancy": occupancy_df, "history": history_df}


def parse_args():
    parser = argparse.ArgumentParser(description="Modelo del dia con generacion de columnas")
    parser.add_argument("--solution", default="solution_interday.xlsx", help="Excel de salida del modelo interdia")
    parser.add_argument("--base-data", default="Data G15.xlsx", help="Excel con parametros base")
    parser.add_argument("--output", default="solution_deldia.xlsx", help="Excel de salida")
    parser.add_argument("--day", type=int, action="append", help="Dia especifico a resolver. Puede repetirse.")
    parser.add_argument("--all-days", action="store_true", help="Resolver todos los dias con sesiones")
    parser.add_argument("--max-days", type=int, default=1, help="Caso base: cantidad de dias iniciales si no se usa --day")
    parser.add_argument("--max-iterations", type=int, default=50, help="Maximo de iteraciones de column generation")
    parser.add_argument(
        "--pharmacy-capacity-source",
        choices=["n_farmaceuticos", "modulos_farmacia"],
        default="n_farmaceuticos",
        help="Columna de Sheet1 usada como C_f del maestro",
    )
    parser.add_argument("--gurobi-output", action="store_true", help="Mostrar logs de Gurobi")
    return parser.parse_args()


def main():
    args = parse_args()
    solve_days(
        solution_path=args.solution,
        base_data_path=args.base_data,
        output_path=args.output,
        selected_days=args.day,
        all_days=args.all_days,
        max_days=args.max_days,
        max_iterations=args.max_iterations,
        print_gurobi=args.gurobi_output,
        pharmacy_capacity_source=args.pharmacy_capacity_source,
    )


if __name__ == "__main__":
    main()
