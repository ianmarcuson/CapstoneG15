from __future__ import annotations
import argparse
import multiprocessing as mp
import os
import time
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
import gurobipy as gp
import numpy as np
import pandas as pd
from gurobipy import GRB

warnings.filterwarnings("ignore")

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent


# ─────────────────────────────────────────────────────────────────────────────
# Resolución de rutas
# ─────────────────────────────────────────────────────────────────────────────

def resolve_existing_path(path: Optional[str], candidates: List[Path], label: str) -> str:
    tried: List[Path] = []
    if path:
        raw = Path(path)
        explicit_candidates = [raw]
        if not raw.is_absolute():
            explicit_candidates.extend([Path.cwd() / raw, SCRIPT_DIR / raw, PROJECT_DIR / raw])
        for candidate in explicit_candidates:
            candidate = candidate.resolve()
            tried.append(candidate)
            if candidate.exists():
                return str(candidate)
    for candidate in candidates:
        candidate = candidate.resolve()
        tried.append(candidate)
        if candidate.exists():
            return str(candidate)
    tried_txt = "\n  - ".join(str(x) for x in tried)
    raise FileNotFoundError(
        f"No se encontró {label}. Rutas probadas:\n  - {tried_txt}\n\n"
        "Revisa que los archivos estén en la estructura esperada, por ejemplo:\n"
        "  CapstoneG15/Modelo Interdia/modelo_deldia_v2.py\n"
        "  CapstoneG15/Modelo Interdia/solution_interday.xlsx\n"
        "  CapstoneG15/Data Inicial/Data G15.xlsx"
    )


def default_solution_path(path: Optional[str] = None) -> str:
    return resolve_existing_path(
        path,
        candidates=[
            SCRIPT_DIR / "solution_interday.xlsx",
            Path.cwd() / "solution_interday.xlsx",
            PROJECT_DIR / "solution_interday.xlsx",
        ],
        label="solution_interday.xlsx",
    )


def default_base_data_path(path: Optional[str] = None) -> str:
    return resolve_existing_path(
        path,
        candidates=[
            SCRIPT_DIR / "Data G15.xlsx",
            SCRIPT_DIR / "Data Inicial" / "Data G15.xlsx",
            PROJECT_DIR / "Data Inicial" / "Data G15.xlsx",
            Path.cwd() / "Data Inicial" / "Data G15.xlsx",
            Path.cwd() / "Data G15.xlsx",
        ],
        label="Data G15.xlsx",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Timer
# ─────────────────────────────────────────────────────────────────────────────

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


# ─────────────────────────────────────────────────────────────────────────────
# Dataclass Pattern
# ─────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Pattern:
    patient_idx: int
    pharmacy_start: int
    treatment_start: int
    treatment_end: int
    # Vectores como tuplas para hashabilidad; internamente se usan np.arrays
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

    # ── Accesos numpy cacheados (sin romper frozen=True) ────────────────────
    def d_arr(self) -> np.ndarray:
        return np.array(self.d, dtype=np.float64)

    def g_arr(self) -> np.ndarray:
        return np.array(self.g, dtype=np.float64)

    def a_arr(self) -> np.ndarray:
        return np.array(self.a, dtype=np.float64)

    def b_arr(self) -> np.ndarray:
        return np.array(self.b, dtype=np.float64)


# ─────────────────────────────────────────────────────────────────────────────
# Carga de datos
# ─────────────────────────────────────────────────────────────────────────────

def load_base_data(path: Optional[str] = None) -> Dict:
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


def load_interday_assignments(
    solution_path: Optional[str], base_data_path: Optional[str]
) -> Tuple[pd.DataFrame, Dict]:
    solution_path = default_solution_path(solution_path)
    print(f"[INFO] Cargando asignaciones interdía desde: {solution_path}")
    base_data = load_base_data(base_data_path)
    assignments = pd.read_excel(solution_path, sheet_name="Asignaciones").copy()

    type_col = first_existing_column(assignments, ["patient_type", "patient_type_x", "patient_type_y"])
    required = ["patient_id", "day", "cycle", "session", "modules", "arrival_day", type_col]
    missing = [col for col in required if col not in assignments.columns]
    if missing:
        raise ValueError(f"Faltan columnas en Asignaciones: {missing}")

    if "patient_type_x" in assignments.columns and "patient_type_y" in assignments.columns:
        mismatch = assignments[
            assignments["patient_type_x"].astype(int) != assignments["patient_type_y"].astype(int)
        ]
        if len(mismatch) > 0:
            raise ValueError(
                f"patient_type_x y patient_type_y no coinciden en {len(mismatch)} filas. "
                "Revisar merge del interday antes de resolver intradía."
            )

    assignments["patient_type"] = assignments[type_col].astype(int)
    for col in ["patient_id", "day", "cycle", "session", "modules", "arrival_day"]:
        assignments[col] = assignments[col].astype(int)

    if assignments.empty:
        raise ValueError("La hoja Asignaciones está vacía.")
    if (assignments["modules"] <= 0).any():
        raise ValueError("Hay sesiones con modules <= 0 en solution_interday.xlsx.")

    dup_cols = ["patient_id", "cycle", "session"]
    dup = assignments.duplicated(subset=dup_cols, keep=False)
    if dup.any():
        sample = assignments.loc[dup, dup_cols + ["day", "patient_type"]].head(10)
        raise ValueError(
            "Hay sesiones duplicadas por patient_id/cycle/session en Asignaciones. "
            f"Muestra:\n{sample}"
        )

    print(
        "[INFO] Asignaciones cargadas: "
        f"filas={len(assignments)}, pacientes={assignments['patient_id'].nunique()}, "
        f"días={assignments['day'].nunique()}, "
        f"rango_días=[{assignments['day'].min()}..{assignments['day'].max()}]"
    )

    def prep_modules(patient_type: int) -> int:
        info = base_data["patient_types"].get(int(patient_type), {})
        if "modulos_lab" not in info:
            raise ValueError(f"No hay 'Modulos Lab.' para patient_type={patient_type} en base_data.")
        return int(info["modulos_lab"])

    assignments["pharmacy_modules"] = assignments["patient_type"].map(prep_modules).astype(int)
    return assignments, base_data


# ─────────────────────────────────────────────────────────────────────────────
# Modelo de generación de columnas (optimizado)
# ─────────────────────────────────────────────────────────────────────────────

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
        self.horizon = len(self.M)
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
        self._pattern_signatures: Dict[int, set] = {p: set() for p in range(len(self.assignments))}
        self.solution: Optional[Dict] = None

        # ── OPT 2: estado del modelo incremental ────────────────────────────
        self._master_model: Optional[gp.Model] = None
        self._master_vars: Dict[Tuple[int, int], gp.Var] = {}
        self._assign_constr: Dict[int, gp.Constr] = {}
        self._chair_constr: Dict[int, gp.Constr] = {}
        self._pharmacy_constr: Dict[int, gp.Constr] = {}
        self._nurse_total_constr: Dict[int, gp.Constr] = {}
        self._nurse_start_constr: Dict[int, gp.Constr] = {}
        self._nurse_end_constr: Dict[int, gp.Constr] = {}

        # ── OPT 3: arrays numpy de capacidades (para vectorización) ─────────
        self._M_extra_arr = np.array(self.M_extra, dtype=np.int64)

        # ── OPT 4: caché de patrones factibles por paciente ─────────────────
        # Se llena en run_column_generation() antes de iniciar CG.
        self._feasible_cache: Dict[int, List[Pattern]] = {}

        self._validate_day_data()

    # ── Validación ───────────────────────────────────────────────────────────

    def _validate_day_data(self):
        if len(self.assignments) == 0:
            raise ValueError(f"El día {self.day} no tiene sesiones.")
        bad = self.assignments[
            (self.assignments["modules"] <= 0)
            | (self.assignments["pharmacy_modules"] < 0)
            | (self.assignments["modules"] > self.horizon)
        ]
        if len(bad) > 0:
            raise ValueError(
                f"Hay sesiones con duración inválida para el horizonte del día {self.day}:\n{bad}"
            )

    # ── Utilidades de patrón ─────────────────────────────────────────────────

    def _row_params(self, p: int) -> Tuple[int, int]:
        row = self.assignments.iloc[p]
        return int(row["modules"]), int(row["pharmacy_modules"])

    def _pattern_cost(self, h: int, wait: int, treatment_end: int) -> float:
        return self.extra_weight * h + self.wait_weight * wait + self.end_weight * treatment_end

    def _make_pattern(
        self,
        p: int,
        pharmacy_start: int,
        treatment_start: int,
        reduced_cost: float = 0.0,
        is_artificial: bool = False,
    ) -> Pattern:
        horizon = self.horizon
        if is_artificial:
            zeros = tuple([0] * horizon)
            return Pattern(
                patient_idx=p,
                pharmacy_start=-1,
                treatment_start=-1,
                treatment_end=-1,
                a=zeros, b=zeros, d=zeros, g=zeros,
                h=0, wait=0,
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

        # ── OPT 3: construcción vectorizada de a, b, d, g ───────────────────
        a = np.zeros(horizon, dtype=np.int8)
        b = np.zeros(horizon, dtype=np.int8)
        d = np.zeros(horizon, dtype=np.int8)
        g = np.zeros(horizon, dtype=np.int8)

        a[treatment_start] = 1
        b[treatment_end] = 1
        d[treatment_start : treatment_end + 1] = 1
        if Fp > 0:
            g[pharmacy_start : pharmacy_start + Fp] = 1

        h = int(d[self._M_extra_arr].sum())
        wait = treatment_start - (pharmacy_start + Fp)

        return Pattern(
            patient_idx=p,
            pharmacy_start=int(pharmacy_start),
            treatment_start=int(treatment_start),
            treatment_end=int(treatment_end),
            a=tuple(a.tolist()),
            b=tuple(b.tolist()),
            d=tuple(d.tolist()),
            g=tuple(g.tolist()),
            h=h,
            wait=int(wait),
            base_cost=float(self._pattern_cost(h, wait, treatment_end)),
            reduced_cost=float(reduced_cost),
            is_artificial=False,
        )

    def _add_pattern_if_new(self, pattern: Pattern) -> bool:
        """Agrega patrón si su firma no existe; O(1) gracias al set de firmas."""
        sig = pattern.signature
        p = pattern.patient_idx
        if sig in self._pattern_signatures[p]:
            return False
        self._pattern_signatures[p].add(sig)
        self.patterns[p].append(pattern)
        return True

    # ── OPT 4: generación y caché de patrones factibles ─────────────────────

    def _generate_feasible_patterns(self, p: int) -> List[Pattern]:
        """Genera todos los patrones factibles para el paciente p."""
        Dp, Fp = self._row_params(p)
        result: List[Pattern] = []
        for treatment_start in range(0, self.horizon - Dp + 1):
            latest_pharmacy_start = treatment_start - Fp
            if latest_pharmacy_start < 0:
                continue
            if Fp == 0:
                result.append(self._make_pattern(p, treatment_start, treatment_start))
            else:
                for pharmacy_start in range(0, latest_pharmacy_start + 1):
                    if pharmacy_start + Fp - 1 <= 20:
                        result.append(self._make_pattern(p, pharmacy_start, treatment_start))
        return result

    def _build_feasible_cache(self):
        """OPT 4: pre-computa todos los patrones factibles una sola vez."""
        for p in range(len(self.assignments)):
            self._feasible_cache[p] = self._generate_feasible_patterns(p)

    # ── OPT 5: initialize_patterns con min() en lugar de sort completo ──────

    def initialize_patterns(self):
        """
        Inicializa un patrón factible por paciente.
        Usa min() sobre la caché — O(n_patrones) sin sort completo.
        Las comprobaciones de capacidad son vectorizadas con numpy.
        """
        H = self.horizon
        chairs_used    = np.zeros(H, dtype=np.int32)
        pharmacy_used  = np.zeros(H, dtype=np.int32)
        nurse_start_u  = np.zeros(H, dtype=np.int32)
        nurse_end_u    = np.zeros(H, dtype=np.int32)
        nurse_total_u  = np.zeros(H, dtype=np.int32)

        order = sorted(
            range(len(self.assignments)),
            key=lambda p: self._row_params(p)[0],
            reverse=True,
        )

        for p in order:
            candidates = self._feasible_cache[p]
            placed = False

            # OPT 5: busca el mejor sin sort completo
            for pat in sorted(
                candidates,
                key=lambda pt: (pt.h, pt.treatment_start, pt.wait, pt.pharmacy_start),
            ):
                d = np.array(pat.d, dtype=np.int32)
                g = np.array(pat.g, dtype=np.int32)
                a = np.array(pat.a, dtype=np.int32)
                b = np.array(pat.b, dtype=np.int32)

                # Comprobaciones vectorizadas
                if np.any(chairs_used + d > self.S):
                    continue
                if np.any(pharmacy_used + g > self.Cf):
                    continue
                if self.nurse_mode == "separate":
                    if np.any(nurse_start_u + a > self.E):
                        continue
                    if np.any(nurse_end_u + b > self.E):
                        continue
                else:
                    if np.any(nurse_total_u + a + b > self.E):
                        continue

                self._add_pattern_if_new(pat)
                chairs_used   += d
                pharmacy_used += g
                nurse_start_u += a
                nurse_end_u   += b
                nurse_total_u += a + b
                placed = True
                break

            if not placed:
                if self.use_artificial_columns:
                    self._add_pattern_if_new(self._make_pattern(p, -1, -1, is_artificial=True))
                else:
                    Dp, Fp = self._row_params(p)
                    raise ValueError(
                        f"No se pudo inicializar p={p} en día {self.day}. Dp={Dp}, Fp={Fp}"
                    )

    # ── OPT 2: modelo maestro incremental ───────────────────────────────────

    def _build_master_from_scratch(self, relax: bool) -> None:
        """
        Construye el modelo Gurobi LP/MIP completo por primera vez.
        Guarda referencias a variables y restricciones para reutilización.
        """
        vtype = GRB.CONTINUOUS if relax else GRB.BINARY
        tag = "LP" if relax else "MIP"
        model = gp.Model(f"Master_day_{self.day}_{tag}")
        model.setParam("OutputFlag", 1 if self.print_gurobi else 0)

        for p, pats in self.patterns.items():
            if len(pats) == 0:
                raise RuntimeError(f"Paciente/fila {p} no tiene columnas.")
            for k, pat in enumerate(pats):
                self._master_vars[p, k] = model.addVar(
                    lb=0, ub=1, vtype=vtype,
                    obj=pat.base_cost,
                    name=f"x_{p}_{k}",
                )

        model.update()

        # Restricciones de asignación
        for p, pats in self.patterns.items():
            self._assign_constr[p] = model.addConstr(
                gp.quicksum(self._master_vars[p, k] for k in range(len(pats))) == 1,
                name=f"assign_{p}",
            )

        # Restricciones de capacidad por módulo
        for m in self.M:
            self._chair_constr[m] = model.addConstr(
                gp.quicksum(
                    pat.d[m] * self._master_vars[p, k]
                    for p, pats in self.patterns.items()
                    for k, pat in enumerate(pats)
                ) <= self.S,
                name=f"chair_{m}",
            )
            self._pharmacy_constr[m] = model.addConstr(
                gp.quicksum(
                    pat.g[m] * self._master_vars[p, k]
                    for p, pats in self.patterns.items()
                    for k, pat in enumerate(pats)
                ) <= self.Cf,
                name=f"pharmacy_{m}",
            )
            if self.nurse_mode == "aggregate":
                self._nurse_total_constr[m] = model.addConstr(
                    gp.quicksum(
                        (pat.a[m] + pat.b[m]) * self._master_vars[p, k]
                        for p, pats in self.patterns.items()
                        for k, pat in enumerate(pats)
                    ) <= self.E,
                    name=f"nurse_total_{m}",
                )
            else:
                self._nurse_start_constr[m] = model.addConstr(
                    gp.quicksum(
                        pat.a[m] * self._master_vars[p, k]
                        for p, pats in self.patterns.items()
                        for k, pat in enumerate(pats)
                    ) <= self.E,
                    name=f"nurse_start_{m}",
                )
                self._nurse_end_constr[m] = model.addConstr(
                    gp.quicksum(
                        pat.b[m] * self._master_vars[p, k]
                        for p, pats in self.patterns.items()
                        for k, pat in enumerate(pats)
                    ) <= self.E,
                    name=f"nurse_end_{m}",
                )

        model.ModelSense = GRB.MINIMIZE
        self._master_model = model

    def _add_columns_to_master(self, new_by_p: Dict[int, List[Tuple[int, Pattern]]]) -> None:
        """
        OPT 2: agrega solo las columnas nuevas al modelo existente.
        new_by_p: {p: [(k, pattern), ...]}
        """
        model = self._master_model
        for p, pk_list in new_by_p.items():
            for k, pat in pk_list:
                # Columna con coeficientes en todas las restricciones relevantes
                col = gp.Column()
                col.addTerms(1.0, self._assign_constr[p])
                for m in self.M:
                    if pat.d[m]:
                        col.addTerms(float(pat.d[m]), self._chair_constr[m])
                    if pat.g[m]:
                        col.addTerms(float(pat.g[m]), self._pharmacy_constr[m])
                    if self.nurse_mode == "aggregate":
                        ev = pat.a[m] + pat.b[m]
                        if ev:
                            col.addTerms(float(ev), self._nurse_total_constr[m])
                    else:
                        if pat.a[m]:
                            col.addTerms(float(pat.a[m]), self._nurse_start_constr[m])
                        if pat.b[m]:
                            col.addTerms(float(pat.b[m]), self._nurse_end_constr[m])

                var = model.addVar(
                    lb=0, ub=1,
                    vtype=GRB.CONTINUOUS,
                    obj=pat.base_cost,
                    name=f"x_{p}_{k}",
                    column=col,
                )
                self._master_vars[p, k] = var

    def _solve_lp_master(self) -> Dict:
        """Optimiza el LP maestro actual y devuelve objetivo y duales."""
        model = self._master_model
        model.optimize()

        if model.status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL, GRB.TIME_LIMIT):
            raise RuntimeError(f"Maestro LP no resuelto. Status={model.status}")
        if model.SolCount == 0:
            raise RuntimeError(f"Maestro LP sin solución. Status={model.status}")

        duals = None
        if model.status == GRB.OPTIMAL:
            duals = {
                "lambda": {p: c.Pi for p, c in self._assign_constr.items()},
                "chair":  {m: c.Pi for m, c in self._chair_constr.items()},
                "pharmacy": {m: c.Pi for m, c in self._pharmacy_constr.items()},
                "nurse_mode": self.nurse_mode,
            }
            if self.nurse_mode == "aggregate":
                duals["nurse_total"] = {m: c.Pi for m, c in self._nurse_total_constr.items()}
                # OPT 3: arrays numpy de duales para dot products
                duals["_chair_arr"]    = np.array([duals["chair"][m] for m in self.M])
                duals["_pharmacy_arr"] = np.array([duals["pharmacy"][m] for m in self.M])
                duals["_nurse_arr"]    = np.array([duals["nurse_total"][m] for m in self.M])
            else:
                duals["nurse_start"] = {m: c.Pi for m, c in self._nurse_start_constr.items()}
                duals["nurse_end"]   = {m: c.Pi for m, c in self._nurse_end_constr.items()}
                duals["_chair_arr"]       = np.array([duals["chair"][m] for m in self.M])
                duals["_pharmacy_arr"]    = np.array([duals["pharmacy"][m] for m in self.M])
                duals["_nurse_start_arr"] = np.array([duals["nurse_start"][m] for m in self.M])
                duals["_nurse_end_arr"]   = np.array([duals["nurse_end"][m] for m in self.M])

        return {"obj": model.ObjVal, "duals": duals, "status": model.status}

    def _solve_mip_master(self) -> Dict:
        """
        Resuelve el MIP final convirtiendo las variables a binarias.
        Reutiliza el grafo del modelo LP pero cambia vtype.
        """
        model = self._master_model
        for var in self._master_vars.values():
            var.vtype = GRB.BINARY
        model.update()
        model.optimize()

        if model.status not in (GRB.OPTIMAL, GRB.SUBOPTIMAL, GRB.TIME_LIMIT):
            raise RuntimeError(f"Maestro MIP no resuelto. Status={model.status}")
        if model.SolCount == 0:
            raise RuntimeError(f"Maestro MIP sin solución. Status={model.status}")

        selected = {(p, k): var.X for (p, k), var in self._master_vars.items()}
        return {
            "obj": model.ObjVal,
            "selected": selected,
            "status": model.status,
            "runtime": model.Runtime,
        }

    # ── OPT 3: reduced_cost vectorizado ─────────────────────────────────────

    def reduced_cost(self, pat: Pattern, duals: Dict) -> float:
        """Calcula el reduced cost usando np.dot (vectorizado)."""
        rc = pat.base_cost - duals["lambda"][pat.patient_idx]
        d = np.array(pat.d, dtype=np.float64)
        g = np.array(pat.g, dtype=np.float64)
        rc -= np.dot(duals["_chair_arr"], d)
        rc -= np.dot(duals["_pharmacy_arr"], g)
        if self.nurse_mode == "aggregate":
            a = np.array(pat.a, dtype=np.float64)
            b = np.array(pat.b, dtype=np.float64)
            rc -= np.dot(duals["_nurse_arr"], a + b)
        else:
            a = np.array(pat.a, dtype=np.float64)
            b = np.array(pat.b, dtype=np.float64)
            rc -= np.dot(duals["_nurse_start_arr"], a)
            rc -= np.dot(duals["_nurse_end_arr"], b)
        return float(rc)

    # ── Pricing ──────────────────────────────────────────────────────────────

    def price_patient(self, p: int, duals: Dict) -> List[Pattern]:
        """
        Evalúa la caché de patrones factibles (OPT 4) con reduced_cost
        vectorizado (OPT 3). Devuelve hasta pricing_top_n patrones negativos.
        """
        existing = self._pattern_signatures[p]
        priced: List[Pattern] = []
        for pat in self._feasible_cache[p]:
            if pat.signature in existing:
                continue
            rc = self.reduced_cost(pat, duals)
            if rc < -self.reduced_cost_tol:
                priced.append(
                    self._make_pattern(
                        p, pat.pharmacy_start, pat.treatment_start, reduced_cost=rc
                    )
                )
        priced.sort(key=lambda pt: pt.reduced_cost)
        return priced[: max(1, self.pricing_top_n)]

    # ── Bucle principal de generación de columnas ────────────────────────────

    def run_column_generation(self) -> Dict:
        timer = ExecutionTimer(f"CG optimizado día {self.day}")

        # OPT 4: construir caché de patrones factibles una sola vez
        self._build_feasible_cache()
        timer.lap("caché de patrones factibles")

        self.initialize_patterns()
        timer.lap(f"patrones iniciales: {sum(len(v) for v in self.patterns.values())}")

        # OPT 2: construir el modelo LP maestro por primera vez
        self._build_master_from_scratch(relax=True)
        timer.lap("modelo LP maestro construido")

        history = []
        for iteration in range(1, self.max_iterations + 1):
            lp_result = self._solve_lp_master()
            duals = lp_result["duals"]
            if duals is None:
                raise RuntimeError("No se pudieron recuperar duales del maestro LP.")

            added = 0
            best_rc = float("inf")
            negative_candidates = 0
            duplicate_guarded = 0
            new_by_p: Dict[int, List[Tuple[int, Pattern]]] = {}

            for p in range(len(self.assignments)):
                new_patterns = self.price_patient(p, duals)
                if new_patterns:
                    best_rc = min(best_rc, new_patterns[0].reduced_cost)
                for pat in new_patterns:
                    negative_candidates += 1
                    if self._add_pattern_if_new(pat):
                        k = len(self.patterns[p]) - 1
                        new_by_p.setdefault(p, []).append((k, pat))
                        added += 1
                    else:
                        duplicate_guarded += 1

            # OPT 2: agregar solo las columnas nuevas al modelo existente
            if new_by_p:
                self._add_columns_to_master(new_by_p)

            total_patterns = sum(len(v) for v in self.patterns.values())
            history.append(
                {
                    "iteration": iteration,
                    "master_lp_obj": lp_result["obj"],
                    "added_patterns": added,
                    "negative_candidates": negative_candidates,
                    "duplicate_guarded": duplicate_guarded,
                    "best_reduced_cost": None if best_rc == float("inf") else best_rc,
                    "total_patterns": total_patterns,
                }
            )

            print(
                f"[CG] día={self.day} iter={iteration} lp_obj={lp_result['obj']:.6f} "
                f"best_rc={0 if best_rc == float('inf') else best_rc:.8f} "
                f"neg={negative_candidates} added={added} patterns={total_patterns}"
            )

            if added == 0:
                break

        # Resolver MIP final
        final_master = self._solve_mip_master()
        self._extract_solution(final_master, history)
        self._validate_solution()
        timer.lap(f"MIP final obj={final_master['obj']:.6f}")
        timer.finish()
        return self.solution

    # ── Extracción de solución ───────────────────────────────────────────────

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
                "Esto indica que las columnas reales no bastan o el día es infactible."
            )

        schedule = []
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

        occupancy = []
        for m in self.M:
            chairs_used  = sum(pat.d[m] for pat in selected_patterns.values())
            pharmacy_used = sum(pat.g[m] for pat in selected_patterns.values())
            starts = sum(pat.a[m] for pat in selected_patterns.values())
            ends   = sum(pat.b[m] for pat in selected_patterns.values())
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


# ─────────────────────────────────────────────────────────────────────────────
# Worker para multiprocessing (debe ser top-level para pickling)
# ─────────────────────────────────────────────────────────────────────────────

def _solve_day_worker(args: Tuple) -> Tuple[int, Dict]:
    """
    OPT 1: función worker ejecutada en cada proceso paralelo.
    Recibe todos los parámetros necesarios (pickleable) y devuelve
    (day, solution_dict).
    """
    (
        day,
        day_assignments_dict,
        capacity,
        pharmacy_capacity_source,
        max_iterations,
        pricing_top_n,
        print_gurobi,
        nurse_mode,
        extra_weight,
        wait_weight,
        end_weight,
    ) = args

    day_assignments = pd.DataFrame(day_assignments_dict)
    print(
        f"\n{'='*80}\n[INFO] Resolviendo día {day} | "
        f"sesiones={len(day_assignments)} | "
        f"módulos={int(day_assignments['modules'].sum())}"
    )

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
    return day, solution


# ─────────────────────────────────────────────────────────────────────────────
# Orquestador principal
# ─────────────────────────────────────────────────────────────────────────────

def solve_days(
    solution_path: Optional[str] = None,
    base_data_path: Optional[str] = None,
    output_path: str = "solution_intradia_optimizado.xlsx",
    selected_days: Optional[List[int]] = None,
    all_days: bool = False,
    max_days: int = 475,
    max_iterations: int = 100,
    pricing_top_n: int = 3,
    print_gurobi: bool = False,
    pharmacy_capacity_source: str = "n_farmaceuticos",
    nurse_mode: str = "aggregate",
    extra_weight: float = 1.0,
    wait_weight: float = 1e-4,
    end_weight: float = 1e-6,
    n_workers: int = 0,
) -> Dict[str, pd.DataFrame]:
    """
    Resuelve todos los días con Column Generation optimizado.

    n_workers: número de procesos paralelos.
        0  → automático: max(1, cpu_count - 1)
        1  → secuencial (recomendado si la licencia Gurobi es académica)
        N  → N procesos en paralelo
    """
    timer = ExecutionTimer("modelo intradía optimizado")
    assignments, base_data = load_interday_assignments(solution_path, base_data_path)
    capacity = base_data["capacity"]

    nonempty_days = sorted(assignments["day"].unique())
    if selected_days:
        requested = {int(d) for d in selected_days}
        days_to_solve = [d for d in nonempty_days if int(d) in requested]
    elif all_days:
        days_to_solve = nonempty_days
    else:
        days_to_solve = nonempty_days[:max_days]

    if not days_to_solve:
        raise ValueError("No hay días para resolver con los filtros entregados.")

    # OPT 1: detectar número de workers
    if n_workers == 0:
        n_workers = max(1, (os.cpu_count() or 2) - 1)
    n_workers = min(n_workers, len(days_to_solve))

    print(f"[INFO] Días a resolver: {len(days_to_solve)} | workers={n_workers}")
    print(
        "[INFO] Capacidades: "
        f"S={capacity['chairs']}, E={capacity['n_enfermeras']}, "
        f"Cf={capacity[pharmacy_capacity_source]} ({pharmacy_capacity_source}), "
        f"M={capacity['total_modules']}, M_extra={capacity['modules_extraordinary']}, "
        f"nurse_mode={nurse_mode}, weights=(extra={extra_weight}, wait={wait_weight}, end={end_weight})"
    )
    timer.lap("datos cargados y validados")

    # Preparar argumentos para cada worker (DataFrames → dict para pickling)
    worker_args = []
    for day in days_to_solve:
        day_df = assignments[assignments["day"] == day].copy()
        worker_args.append((
            day,
            day_df.to_dict(orient="list"),
            capacity,
            pharmacy_capacity_source,
            max_iterations,
            pricing_top_n,
            print_gurobi,
            nurse_mode,
            extra_weight,
            wait_weight,
            end_weight,
        ))

    # OPT 1: ejecutar en paralelo o secuencial
    results: List[Tuple[int, Dict]] = []
    if n_workers > 1:
        print(f"[INFO] Lanzando pool de {n_workers} procesos...")
        # spawn es seguro en macOS (M3) y Windows
        ctx = mp.get_context("spawn")
        with ctx.Pool(processes=n_workers) as pool:
            results = pool.map(_solve_day_worker, worker_args)
    else:
        print("[INFO] Modo secuencial (n_workers=1).")
        for args in worker_args:
            results.append(_solve_day_worker(args))

    # Ordenar por día (el pool puede devolver en cualquier orden)
    results.sort(key=lambda r: r[0])

    # Consolidar resultados
    all_schedule, all_occupancy, all_history, summaries = [], [], [], []
    for day, solution in results:
        all_schedule.extend(solution["schedule"])
        all_occupancy.extend(solution["occupancy"])
        for row in solution["history"]:
            all_history.append({"day": int(day), **row})
        summaries.append(
            {
                "day": int(day),
                "sessions": int(len(solution["schedule"])),
                "input_treatment_modules": int(
                    sum(r["treatment_modules"] for r in solution["schedule"])
                ),
                "status": int(solution["status"]),
                "obj_value": float(solution["obj_value"]),
                "total_extra_chair_modules": int(solution["total_extra_chair_modules"]),
                "total_wait_after_pharmacy": int(solution["total_wait_after_pharmacy"]),
                "total_patterns": int(solution["total_patterns"]),
                "cg_iterations": int(len(solution["history"])),
                "runtime_final_master": float(solution["runtime"]),
                "max_chairs_used": max(r["chairs_used"] for r in solution["occupancy"]),
                "max_pharmacy_used": max(r["pharmacy_used"] for r in solution["occupancy"]),
                "max_nurse_starts": max(r["nurse_starts"] for r in solution["occupancy"]),
                "max_nurse_ends": max(r["nurse_ends"] for r in solution["occupancy"]),
                "max_nurse_events": max(r["nurse_events"] for r in solution["occupancy"]),
                "nurse_mode": solution["nurse_mode"],
                "extra_weight": solution["extra_weight"],
                "wait_weight": solution["wait_weight"],
                "end_weight": solution["end_weight"],
            }
        )

    summary_df   = pd.DataFrame(summaries)
    schedule_df  = pd.DataFrame(all_schedule)
    occupancy_df = pd.DataFrame(all_occupancy)
    history_df   = pd.DataFrame(all_history)

    output_file = Path(output_path)
    if not output_file.is_absolute():
        output_file = SCRIPT_DIR / output_file
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        summary_df.to_excel(writer,   sheet_name="Resumen_Dias",      index=False)
        schedule_df.to_excel(writer,  sheet_name="Programacion",       index=False)
        occupancy_df.to_excel(writer, sheet_name="Ocupacion_Modulos",  index=False)
        history_df.to_excel(writer,   sheet_name="CG_Historial",       index=False)

    timer.lap(f"resultados guardados en {output_file}")
    timer.finish()
    return {
        "summary": summary_df,
        "schedule": schedule_df,
        "occupancy": occupancy_df,
        "history": history_df,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Modelo intradía optimizado con generación de columnas"
    )
    parser.add_argument("--solution",    default=None,
        help="Excel de salida del modelo interday. Default: solution_interday.xlsx")
    parser.add_argument("--base-data",   default=None,
        help="Excel con parámetros base. Default: ../Data Inicial/Data G15.xlsx")
    parser.add_argument("--output",      default="solution_intradia_optimizado.xlsx",
        help="Excel de salida")
    parser.add_argument("--day",         type=int, action="append",
        help="Día específico a resolver. Puede repetirse.")
    parser.add_argument("--all-days",    action="store_true",
        help="Resolver todos los días con sesiones")
    parser.add_argument("--max-days",    type=int, default=1,
        help="Cantidad de días iniciales si no se usa --day ni --all-days")
    parser.add_argument("--max-iterations", type=int, default=100)
    parser.add_argument("--pricing-top-n",  type=int, default=3,
        help="Columnas negativas máximas a agregar por paciente e iteración")
    parser.add_argument("--pharmacy-capacity-source",
        choices=["n_farmaceuticos", "modulos_farmacia"], default="n_farmaceuticos")
    parser.add_argument("--nurse-mode",
        choices=["separate", "aggregate"], default="aggregate")
    parser.add_argument("--extra-weight", type=float, default=1.0)
    parser.add_argument("--wait-weight",  type=float, default=1e-4,
        help="Penaliza espera entre farmacia lista e inicio de tratamiento")
    parser.add_argument("--end-weight",   type=float, default=1e-6,
        help="Penaliza terminar tarde")
    parser.add_argument("--gurobi-output", action="store_true")
    parser.add_argument(
        "--workers", type=int, default=0,
        help=(
            "Procesos paralelos. 0=automático (cpu_count-1), 1=secuencial. "
            "Usar 1 si la licencia Gurobi es académica."
        ),
    )
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
        n_workers=args.workers,
    )


if __name__ == "__main__":
    # IMPORTANTE: el guard if __name__ == "__main__" es obligatorio en Windows
    # y macOS con spawn para que multiprocessing funcione correctamente.
    main()
