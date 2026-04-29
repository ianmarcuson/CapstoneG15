import argparse
import time
import warnings
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple

import gurobipy as gp
from gurobipy import GRB
import pandas as pd

warnings.filterwarnings("ignore")


class ExecutionTimer:
    def __init__(self, name: str):
        self.name = name
        self.start = time.perf_counter()
        self.last = self.start
        print(f"[TIMER] Inicio {name}")

    def lap(self, label: str):
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
    a: Tuple[int, ...]
    b: Tuple[int, ...]
    d: Tuple[int, ...]
    g: Tuple[int, ...]
    h: int
    wait: int
    base_cost: float
    reduced_cost: float = 0.0
    is_artificial: bool = False

    @property
    def signature(self) -> Tuple[int, int, bool]:
        return (self.pharmacy_start, self.treatment_start, self.is_artificial)


def load_base_data(path: str = "Data G15.xlsx") -> Dict:
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
    patient_types: Dict[int, Dict] = {}
    for _, row in df_types.iterrows():
        pid = int(row["Id"])
        var = str(row["variable"]).strip()
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


def first_existing_column(df: pd.DataFrame, candidates: Iterable[str]) -> str:
    for col in candidates:
        if col in df.columns:
            return col
    raise ValueError(f"No se encontró ninguna columna entre: {list(candidates)}")


def load_interday_assignments(solution_path: str, base_data_path: str) -> Tuple[pd.DataFrame, Dict]:
    base_data = load_base_data(base_data_path)
    assignments = pd.read_excel(solution_path, sheet_name="Asignaciones").copy()

    type_col = first_existing_column(assignments, ["patient_type", "patient_type_x", "patient_type_y"])
    required = ["patient_id", "day", "cycle", "session", "modules", "arrival_day", type_col]
    missing = [col for col in required if col not in assignments.columns]
    if missing:
        raise ValueError(f"Faltan columnas en Asignaciones: {missing}")

    if "patient_type_x" in assignments.columns and "patient_type_y" in assignments.columns:
        mismatch = assignments[assignments["patient_type_x"].astype(int) != assignments["patient_type_y"].astype(int)]
        if len(mismatch) > 0:
            raise ValueError(
                f"patient_type_x y patient_type_y no coinciden en {len(mismatch)} filas. "
                "Revisar merge del interday antes de resolver intradía."
            )

    assignments["patient_type"] = assignments[type_col].astype(int)
    for col in ["patient_id", "day", "cycle", "session", "modules", "arrival_day"]:
        assignments[col] = assignments[col].astype(int)

    def prep_modules(patient_type: int) -> int:
        info = base_data["patient_types"].get(int(patient_type), {})
        if "modulos_lab" not in info:
            raise ValueError(f"No hay 'Modulos Lab.' para patient_type={patient_type} en base_data.")
        return int(info["modulos_lab"])

    assignments["pharmacy_modules"] = assignments["patient_type"].map(prep_modules).astype(int)
    return assignments, base_data


class ColumnGenerationDayModelV2:
    def __init__(
        self,
        day: int,
        day_assignments: pd.DataFrame,
        capacity: Dict,
        pharmacy_capacity_source: str = "n_farmaceuticos",
        max_iterations: int = 100,
        reduced_cost_tol: float = 1e-7,
        pricing_top_n: int = 3,
        print_gurobi: bool = False,
        nurse_mode: str = "aggregate",
        extra_weight: float = 1.0,
        wait_weight: float = 1e-4,
        end_weight: float = 1e-6,
        use_artificial_columns: bool = True,
    ):
        if nurse_mode not in {"separate", "aggregate"}:
            raise ValueError("nurse_mode debe ser 'separate' o 'aggregate'.")
        if pharmacy_capacity_source not in {"n_farmaceuticos", "modulos_farmacia"}:
            raise ValueError("pharmacy_capacity_source inválido.")

        self.day = int(day)
        self.assignments = day_assignments.reset_index(drop=True).copy()
        self.capacity = capacity
        self.M = list(range(int(capacity["total_modules"])))
        self.M_normal = list(range(int(capacity["modules_ordinary"])))
        self.M_extra = list(range(int(capacity["modules_ordinary"]), int(capacity["total_modules"])))
        self.S = int(capacity["chairs"])
        self.E = int(capacity["n_enfermeras"])
        self.Cf = int(capacity[pharmacy_capacity_source])
        self.max_iterations = int(max_iterations)
        self.reduced_cost_tol = float(reduced_cost_tol)
        self.pricing_top_n = int(pricing_top_n)
        self.print_gurobi = bool(print_gurobi)
        self.nurse_mode = nurse_mode
        self.extra_weight = float(extra_weight)
        self.wait_weight = float(wait_weight)
        self.end_weight = float(end_weight)
        self.use_artificial_columns = bool(use_artificial_columns)
        self.big_m_artificial = 1_000_000.0
        self.patterns: Dict[int, List[Pattern]] = {p: [] for p in range(len(self.assignments))}
        self.solution: Optional[Dict] = None
        self._validate_day_data()

    def _validate_day_data(self):
        if len(self.assignments) == 0:
            raise ValueError(f"El día {self.day} no tiene sesiones.")
        horizon = len(self.M)
        bad = self.assignments[
            (self.assignments["modules"] <= 0)
            | (self.assignments["pharmacy_modules"] < 0)
            | (self.assignments["modules"] > horizon)
        ]
        if len(bad) > 0:
            raise ValueError(f"Hay sesiones con duración inválida para el horizonte del día {self.day}:\n{bad}")

    def _row_params(self, p: int) -> Tuple[int, int]:
        row = self.assignments.iloc[p]
        return int(row["modules"]), int(row["pharmacy_modules"])

    def _pattern_cost(self, h: int, wait: int, treatment_end: int) -> float:
        # Objetivo primario: modulos extra de silla.
        # wait_weight y end_weight son desempates pequenos: ordenan soluciones
        # con igual h sin cambiar el sentido original del modelo.
        return self.extra_weight * h + self.wait_weight * wait + self.end_weight * treatment_end

    def _make_pattern(
        self,
        p: int,
        pharmacy_start: int,
        treatment_start: int,
        reduced_cost: float = 0.0,
        is_artificial: bool = False,
    ) -> Pattern:
        horizon = len(self.M)
        if is_artificial:
            return Pattern(
                patient_idx=p,
                pharmacy_start=-1,
                treatment_start=-1,
                treatment_end=-1,
                a=tuple([0] * horizon),
                b=tuple([0] * horizon),
                d=tuple([0] * horizon),
                g=tuple([0] * horizon),
                h=0,
                wait=0,
                base_cost=self.big_m_artificial,
                reduced_cost=reduced_cost,
                is_artificial=True,
            )

        Dp, Fp = self._row_params(p)
        treatment_end = treatment_start + Dp - 1
        if pharmacy_start < 0 or treatment_start < 0:
            raise ValueError("Inicio negativo en patrón real.")
        if Fp > 0 and pharmacy_start + Fp > horizon:
            raise ValueError("Patrón con farmacia fuera del horizonte.")
        if treatment_end >= horizon:
            raise ValueError("Patrón con tratamiento fuera del horizonte.")
        if treatment_start < pharmacy_start + Fp:
            raise ValueError("Patrón viola medicamento listo antes de iniciar.")

        a = [0] * horizon
        b = [0] * horizon
        d = [0] * horizon
        g = [0] * horizon

        a[treatment_start] = 1
        b[treatment_end] = 1

        for m in range(treatment_start, treatment_end + 1):
            d[m] = 1
        for m in range(pharmacy_start, pharmacy_start + Fp):
            g[m] = 1

        h = sum(d[m] for m in self.M_extra)
        wait = treatment_start - (pharmacy_start + Fp)
        return Pattern(
            patient_idx=p,
            pharmacy_start=int(pharmacy_start),
            treatment_start=int(treatment_start),
            treatment_end=int(treatment_end),
            a=tuple(a),
            b=tuple(b),
            d=tuple(d),
            g=tuple(g),
            h=int(h),
            wait=int(wait),
            base_cost=float(self._pattern_cost(h, wait, treatment_end)),
            reduced_cost=float(reduced_cost),
            is_artificial=False,
        )

    def _add_pattern_if_new(self, pattern: Pattern) -> bool:
        existing = {pat.signature for pat in self.patterns[pattern.patient_idx]}
        if pattern.signature in existing:
            return False
        self.patterns[pattern.patient_idx].append(pattern)
        return True

    def feasible_patterns_for_patient(self, p: int) -> Iterable[Pattern]:
        Dp, Fp = self._row_params(p)
        horizon = len(self.M)
        for treatment_start in range(0, horizon - Dp + 1):
            latest_pharmacy_start = treatment_start - Fp
            if latest_pharmacy_start < 0:
                continue
            if Fp == 0:
                yield self._make_pattern(p, treatment_start, treatment_start)
            else:
                for pharmacy_start in range(0, latest_pharmacy_start + 1):
                    yield self._make_pattern(p, pharmacy_start, treatment_start)

    def initialize_patterns(self):
        chairs_used = [0] * len(self.M)
        pharmacy_used = [0] * len(self.M)
        nurse_start_used = [0] * len(self.M)
        nurse_end_used = [0] * len(self.M)
        nurse_total_used = [0] * len(self.M)

        order = sorted(range(len(self.assignments)), key=lambda p: self._row_params(p)[0], reverse=True)
        for p in order:
            placed = False
            candidates = sorted(
                self.feasible_patterns_for_patient(p),
                key=lambda pat: (pat.h, pat.treatment_start, pat.wait, pat.pharmacy_start),
            )
            for pat in candidates:
                if any(chairs_used[m] + pat.d[m] > self.S for m in self.M):
                    continue
                if any(pharmacy_used[m] + pat.g[m] > self.Cf for m in self.M):
                    continue
                if self.nurse_mode == "separate":
                    if any(nurse_start_used[m] + pat.a[m] > self.E for m in self.M):
                        continue
                    if any(nurse_end_used[m] + pat.b[m] > self.E for m in self.M):
                        continue
                else:
                    if any(nurse_total_used[m] + pat.a[m] + pat.b[m] > self.E for m in self.M):
                        continue

                self._add_pattern_if_new(pat)
                for m in self.M:
                    chairs_used[m] += pat.d[m]
                    pharmacy_used[m] += pat.g[m]
                    nurse_start_used[m] += pat.a[m]
                    nurse_end_used[m] += pat.b[m]
                    nurse_total_used[m] += pat.a[m] + pat.b[m]
                placed = True
                break

            if not placed:
                if self.use_artificial_columns:
                    self._add_pattern_if_new(self._make_pattern(p, -1, -1, is_artificial=True))
                else:
                    Dp, Fp = self._row_params(p)
                    raise ValueError(f"No se pudo inicializar p={p} en día {self.day}. Dp={Dp}, Fp={Fp}")

    def solve_master(self, relax: bool = True) -> Dict:
        model = gp.Model(f"MasterV2_day_{self.day}_{'LP' if relax else 'MIP'}")
        model.setParam("OutputFlag", 1 if self.print_gurobi else 0)

        x = {}
        vtype = GRB.CONTINUOUS if relax else GRB.BINARY
        for p, pats in self.patterns.items():
            if len(pats) == 0:
                raise RuntimeError(f"Paciente/fila {p} no tiene columnas.")
            for k, _ in enumerate(pats):
                x[p, k] = model.addVar(lb=0, ub=1, vtype=vtype, name=f"x_{p}_{k}")

        assign_constr = {}
        chair_constr = {}
        pharmacy_constr = {}
        nurse_total_constr = {}
        nurse_start_constr = {}
        nurse_end_constr = {}

        for p, pats in self.patterns.items():
            assign_constr[p] = model.addConstr(gp.quicksum(x[p, k] for k in range(len(pats))) == 1, name=f"assign_{p}")

        for m in self.M:
            chair_constr[m] = model.addConstr(
                gp.quicksum(pat.d[m] * x[p, k] for p, pats in self.patterns.items() for k, pat in enumerate(pats)) <= self.S,
                name=f"chair_{m}",
            )
            pharmacy_constr[m] = model.addConstr(
                gp.quicksum(pat.g[m] * x[p, k] for p, pats in self.patterns.items() for k, pat in enumerate(pats)) <= self.Cf,
                name=f"pharmacy_{m}",
            )
            if self.nurse_mode == "aggregate":
                nurse_total_constr[m] = model.addConstr(
                    gp.quicksum((pat.a[m] + pat.b[m]) * x[p, k] for p, pats in self.patterns.items() for k, pat in enumerate(pats)) <= self.E,
                    name=f"nurse_total_{m}",
                )
            else:
                nurse_start_constr[m] = model.addConstr(
                    gp.quicksum(pat.a[m] * x[p, k] for p, pats in self.patterns.items() for k, pat in enumerate(pats)) <= self.E,
                    name=f"nurse_start_{m}",
                )
                nurse_end_constr[m] = model.addConstr(
                    gp.quicksum(pat.b[m] * x[p, k] for p, pats in self.patterns.items() for k, pat in enumerate(pats)) <= self.E,
                    name=f"nurse_end_{m}",
                )

        model.setObjective(
            gp.quicksum(pat.base_cost * x[p, k] for p, pats in self.patterns.items() for k, pat in enumerate(pats)),
            GRB.MINIMIZE,
        )
        model.optimize()

        if model.status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL, GRB.TIME_LIMIT):
            raise RuntimeError(f"Maestro no resuelto. Status={model.status}")
        if model.SolCount == 0:
            raise RuntimeError(f"Maestro sin solución. Status={model.status}")

        duals = None
        if relax and model.status == GRB.OPTIMAL:
            duals = {
                "lambda": {p: constr.Pi for p, constr in assign_constr.items()},
                "chair": {m: constr.Pi for m, constr in chair_constr.items()},
                "pharmacy": {m: constr.Pi for m, constr in pharmacy_constr.items()},
                "nurse_mode": self.nurse_mode,
            }
            if self.nurse_mode == "aggregate":
                duals["nurse_total"] = {m: constr.Pi for m, constr in nurse_total_constr.items()}
            else:
                duals["nurse_start"] = {m: constr.Pi for m, constr in nurse_start_constr.items()}
                duals["nurse_end"] = {m: constr.Pi for m, constr in nurse_end_constr.items()}

        selected = {(p, k): var.X for (p, k), var in x.items()}
        return {"model": model, "obj": model.ObjVal, "duals": duals, "selected": selected, "status": model.status, "runtime": model.Runtime}

    def reduced_cost(self, pat: Pattern, duals: Dict) -> float:
        rc = pat.base_cost - duals["lambda"][pat.patient_idx]
        rc -= sum(duals["chair"][m] * pat.d[m] for m in self.M)
        rc -= sum(duals["pharmacy"][m] * pat.g[m] for m in self.M)
        if self.nurse_mode == "aggregate":
            rc -= sum(duals["nurse_total"][m] * (pat.a[m] + pat.b[m]) for m in self.M)
        else:
            rc -= sum(duals["nurse_start"][m] * pat.a[m] + duals["nurse_end"][m] * pat.b[m] for m in self.M)
        return float(rc)

    def price_patient(self, p: int, duals: Dict) -> List[Pattern]:
        existing = {pat.signature for pat in self.patterns[p]}
        priced = []
        for pat in self.feasible_patterns_for_patient(p):
            if pat.signature in existing:
                continue
            rc = self.reduced_cost(pat, duals)
            if rc < -self.reduced_cost_tol:
                priced.append(self._make_pattern(p, pat.pharmacy_start, pat.treatment_start, reduced_cost=rc))
        priced.sort(key=lambda pat: pat.reduced_cost)
        return priced[: max(1, self.pricing_top_n)]

    def run_column_generation(self) -> Dict:
        timer = ExecutionTimer(f"column generation V2 día {self.day}")
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
            negative_candidates = 0
            duplicate_guarded = 0

            for p in range(len(self.assignments)):
                new_patterns = self.price_patient(p, duals)
                if new_patterns:
                    best_rc = min(best_rc, new_patterns[0].reduced_cost)
                for pat in new_patterns:
                    negative_candidates += 1
                    if self._add_pattern_if_new(pat):
                        added += 1
                    else:
                        duplicate_guarded += 1

            total_patterns = sum(len(v) for v in self.patterns.values())
            history.append(
                {
                    "iteration": iteration,
                    "master_lp_obj": master_lp["obj"],
                    "added_patterns": added,
                    "negative_candidates": negative_candidates,
                    "duplicate_guarded": duplicate_guarded,
                    "best_reduced_cost": None if best_rc == float("inf") else best_rc,
                    "total_patterns": total_patterns,
                }
            )

            print(
                f"[CG-V2] día={self.day} iter={iteration} lp_obj={master_lp['obj']:.6f} "
                f"best_rc={0 if best_rc == float('inf') else best_rc:.8f} "
                f"neg={negative_candidates} added={added} patterns={total_patterns}"
            )

            if added == 0:
                break

        final_master = self.solve_master(relax=False)
        self._extract_solution(final_master, history)
        self._validate_solution()
        timer.lap(f"maestro MIP final obj={final_master['obj']:.6f}")
        timer.finish()
        return self.solution

    def _extract_solution(self, final_master: Dict, history: List[Dict]):
        selected_patterns: Dict[int, Pattern] = {}
        for (p, k), value in final_master["selected"].items():
            if value > 0.5:
                selected_patterns[p] = self.patterns[p][k]

        if len(selected_patterns) != len(self.assignments):
            raise RuntimeError("El maestro MIP final no seleccionó exactamente un patrón por sesión.")

        artificial_selected = [p for p, pat in selected_patterns.items() if pat.is_artificial]
        if artificial_selected:
            raise RuntimeError(
                f"Solución final usa columnas artificiales para filas {artificial_selected}. "
                "Esto indica que las columnas reales no bastan o el día es infactible con las capacidades dadas."
            )

        schedule = []
        occupancy = []
        for p, pat in selected_patterns.items():
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
                    "pharmacy_start": pat.pharmacy_start,
                    "pharmacy_end": pat.pharmacy_start + Fp - 1 if Fp > 0 else None,
                    "treatment_start": pat.treatment_start,
                    "treatment_end": pat.treatment_end,
                    "treatment_modules": int(row["modules"]),
                    "pharmacy_modules": Fp,
                    "wait_after_pharmacy": pat.wait,
                    "extra_chair_modules": pat.h,
                    "pattern_cost": pat.base_cost,
                }
            )

        for m in self.M:
            chairs_used = sum(pat.d[m] for pat in selected_patterns.values())
            pharmacy_used = sum(pat.g[m] for pat in selected_patterns.values())
            starts = sum(pat.a[m] for pat in selected_patterns.values())
            ends = sum(pat.b[m] for pat in selected_patterns.values())
            occupancy.append(
                {
                    "day": self.day,
                    "module": m,
                    "is_extra": int(m in self.M_extra),
                    "chairs_used": chairs_used,
                    "pharmacy_used": pharmacy_used,
                    "nurse_starts": starts,
                    "nurse_ends": ends,
                    "nurse_events": starts + ends,
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
            "total_wait_after_pharmacy": sum(row["wait_after_pharmacy"] for row in schedule),
            "nurse_mode": self.nurse_mode,
            "extra_weight": self.extra_weight,
            "wait_weight": self.wait_weight,
            "end_weight": self.end_weight,
        }

    def _validate_solution(self):
        assert self.solution is not None
        violations = []
        for row in self.solution["occupancy"]:
            m = row["module"]
            if row["chairs_used"] > row["chair_capacity"]:
                violations.append(f"m={m}: chairs {row['chairs_used']} > {row['chair_capacity']}")
            if row["pharmacy_used"] > row["pharmacy_capacity"]:
                violations.append(f"m={m}: pharmacy {row['pharmacy_used']} > {row['pharmacy_capacity']}")
            if self.nurse_mode == "aggregate" and row["nurse_events"] > row["nurse_capacity"]:
                violations.append(f"m={m}: nurse_events {row['nurse_events']} > {row['nurse_capacity']}")
            if self.nurse_mode == "separate":
                if row["nurse_starts"] > row["nurse_capacity"]:
                    violations.append(f"m={m}: nurse_starts {row['nurse_starts']} > {row['nurse_capacity']}")
                if row["nurse_ends"] > row["nurse_capacity"]:
                    violations.append(f"m={m}: nurse_ends {row['nurse_ends']} > {row['nurse_capacity']}")
        if violations:
            raise RuntimeError("Violaciones de capacidad detectadas:\n" + "\n".join(violations[:20]))


def solve_days(
    solution_path: str = "solution_interday.xlsx",
    base_data_path: str = "Data G15.xlsx",
    output_path: str = "solution_deldia_v2.xlsx",
    selected_days: Optional[List[int]] = None,
    all_days: bool = False,
    max_days: int = 1,
    max_iterations: int = 100,
    pricing_top_n: int = 3,
    print_gurobi: bool = False,
    pharmacy_capacity_source: str = "n_farmaceuticos",
    nurse_mode: str = "aggregate",
    extra_weight: float = 1.0,
    wait_weight: float = 1e-4,
    end_weight: float = 1e-6,
) -> Dict[str, pd.DataFrame]:
    timer = ExecutionTimer("modelo del día V2 column generation")
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
        raise ValueError("No hay días para resolver con los filtros entregados.")

    print(f"[INFO] Días a resolver: {days_to_solve}")
    print(
        "[INFO] Capacidades: "
        f"S={capacity['chairs']}, E={capacity['n_enfermeras']}, "
        f"Cf={capacity[pharmacy_capacity_source]} ({pharmacy_capacity_source}), "
        f"M={capacity['total_modules']}, M_extra={capacity['modules_extraordinary']}, "
        f"nurse_mode={nurse_mode}, weights=(extra={extra_weight}, wait={wait_weight}, end={end_weight})"
    )
    timer.lap("datos cargados y validados")

    all_schedule, all_occupancy, all_history, summaries = [], [], [], []

    for idx, day in enumerate(days_to_solve, start=1):
        day_assignments = assignments[assignments["day"] == day].copy()
        print("\n" + "=" * 80)
        print(f"[INFO] Resolviendo día {day} ({idx}/{len(days_to_solve)}) | sesiones={len(day_assignments)} | módulos={int(day_assignments['modules'].sum())}")

        model = ColumnGenerationDayModelV2(
            day=day,
            day_assignments=day_assignments,
            capacity=capacity,
            pharmacy_capacity_source=pharmacy_capacity_source,
            max_iterations=max_iterations,
            pricing_top_n=pricing_top_n,
            print_gurobi=print_gurobi,
            nurse_mode=nurse_mode,
            extra_weight=extra_weight,
            wait_weight=wait_weight,
            end_weight=end_weight,
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
                "input_treatment_modules": int(day_assignments["modules"].sum()),
                "status": int(solution["status"]),
                "obj_value": float(solution["obj_value"]),
                "total_extra_chair_modules": int(solution["total_extra_chair_modules"]),
                "total_wait_after_pharmacy": int(solution["total_wait_after_pharmacy"]),
                "total_patterns": int(solution["total_patterns"]),
                "cg_iterations": int(len(solution["history"])),
                "runtime_final_master": float(solution["runtime"]),
                "max_chairs_used": max(row["chairs_used"] for row in solution["occupancy"]),
                "max_pharmacy_used": max(row["pharmacy_used"] for row in solution["occupancy"]),
                "max_nurse_starts": max(row["nurse_starts"] for row in solution["occupancy"]),
                "max_nurse_ends": max(row["nurse_ends"] for row in solution["occupancy"]),
                "max_nurse_events": max(row["nurse_events"] for row in solution["occupancy"]),
                "nurse_mode": solution["nurse_mode"],
                "extra_weight": solution["extra_weight"],
                "wait_weight": solution["wait_weight"],
                "end_weight": solution["end_weight"],
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
    parser = argparse.ArgumentParser(description="Modelo del día V2 con generación de columnas")
    parser.add_argument("--solution", default="solution_interday.xlsx", help="Excel de salida del modelo interday")
    parser.add_argument("--base-data", default="Data G15.xlsx", help="Excel con parámetros base")
    parser.add_argument("--output", default="solution_deldia_v2.xlsx", help="Excel de salida")
    parser.add_argument("--day", type=int, action="append", help="Día específico a resolver. Puede repetirse.")
    parser.add_argument("--all-days", action="store_true", help="Resolver todos los días con sesiones")
    parser.add_argument("--max-days", type=int, default=1, help="Cantidad de días iniciales si no se usa --day")
    parser.add_argument("--max-iterations", type=int, default=100)
    parser.add_argument("--pricing-top-n", type=int, default=3, help="Columnas negativas máximas a agregar por paciente e iteración")
    parser.add_argument("--pharmacy-capacity-source", choices=["n_farmaceuticos", "modulos_farmacia"], default="n_farmaceuticos")
    parser.add_argument("--nurse-mode", choices=["separate", "aggregate"], default="aggregate")
    parser.add_argument("--extra-weight", type=float, default=1.0)
    parser.add_argument("--wait-weight", type=float, default=1e-4, help="Desempate epsilon: penaliza espera entre farmacia lista e inicio de tratamiento")
    parser.add_argument("--end-weight", type=float, default=1e-6, help="Desempate epsilon: penaliza terminar tarde")
    parser.add_argument("--gurobi-output", action="store_true")
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
        pricing_top_n=args.pricing_top_n,
        print_gurobi=args.gurobi_output,
        pharmacy_capacity_source=args.pharmacy_capacity_source,
        nurse_mode=args.nurse_mode,
        extra_weight=args.extra_weight,
        wait_weight=args.wait_weight,
        end_weight=args.end_weight,
    )


if __name__ == "__main__":
    main()
