import argparse
import time
import warnings

import numpy as np
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


def load_base_data(path="Data G15.xlsx"):
    df_params = pd.read_excel(path, sheet_name="Sheet1", header=None)
    capacity = {
        "p_vomito": float(df_params.iloc[0, 1]),
        "p_eventovasovagal": float(df_params.iloc[1, 1]),
        "chairs": int(df_params.iloc[2, 1]),
        "n_enfermeras": int(df_params.iloc[3, 1]),
        "modules_ordinary": int(df_params.iloc[4, 1]),
        "modules_extraordinary": int(df_params.iloc[5, 1]),
        "modulos_farmacia": int(df_params.iloc[6, 1]),
        "n_farmaceuticos": int(df_params.iloc[7, 1]),
    }
    capacity["daily_module_capacity"] = capacity["chairs"] * capacity["modules_ordinary"]

    df_types = pd.read_excel(path, sheet_name="Sheet2")
    patient_types = {}
    for _, row in df_types.iterrows():
        pid = int(row["Id"])
        var = str(row["variable"]).strip()
        val = row["valor"]
        patient_types.setdefault(pid, {})

        if var == "Ciclos":
            patient_types[pid]["cycles"] = int(val)
        elif var == "Sesiones":
            patient_types[pid]["sessions"] = int(val)
        elif var in ("Modulos", "Módulos", "MÃ³dulos", "MÃƒÂ³dulos"):
            patient_types[pid]["modules_per_session"] = int(val)
        elif var == "TBS":
            patient_types[pid]["days_between_sessions"] = int(val)
        elif var == "TBC":
            patient_types[pid]["days_between_cycles"] = int(val)
        elif var == "Tasa de Llegada":
            patient_types[pid]["arrival_rate"] = float(val)
        elif var in ("Modulos Lab.", "Módulos Lab.", "MÃ³dulos Lab.", "MÃƒÂ³dulos Lab."):
            patient_types[pid]["pharmacy_modules"] = int(val)

    required = [
        "cycles",
        "sessions",
        "modules_per_session",
        "days_between_sessions",
        "days_between_cycles",
        "arrival_rate",
        "pharmacy_modules",
    ]
    missing = {
        pid: [key for key in required if key not in info]
        for pid, info in patient_types.items()
        if any(key not in info for key in required)
    }
    if missing:
        raise ValueError(f"Faltan parametros por tipo de paciente: {missing}")

    return {"capacity": capacity, "patient_types": patient_types}


def generate_arrivals(patient_types, arrival_start=0, arrival_end=730, seed=42, max_patients=None):
    """
    Genera llegadas Poisson por tipo en un horizonte largo.

    A diferencia del modelo interdia original, aqui no se corta en 150 pacientes
    por defecto. Esto permite llegar a estado estacionario para analizar dias
    365-730 con pacientes que ya venian en tratamiento.
    """
    rng = np.random.default_rng(seed)
    patients = []
    patient_id = 1

    for day in range(arrival_start, arrival_end + 1):
        for patient_type, info in patient_types.items():
            arrivals_today = rng.poisson(info["arrival_rate"])
            for _ in range(arrivals_today):
                if max_patients is not None and patient_id > max_patients:
                    return pd.DataFrame(patients)
                patients.append(
                    {
                        "patient_id": patient_id,
                        "patient_type": int(patient_type),
                        "arrival_day": int(day),
                        "cycles": int(info["cycles"]),
                        "sessions": int(info["sessions"]),
                        "modules_per_session": int(info["modules_per_session"]),
                        "days_between_sessions": int(info["days_between_sessions"]),
                        "days_between_cycles": int(info["days_between_cycles"]),
                        "pharmacy_modules": int(info["pharmacy_modules"]),
                    }
                )
                patient_id += 1

    return pd.DataFrame(patients)


def build_rule_based_schedule(patients, analysis_start=365, analysis_end=730):
    """
    Construye una agenda interdia por reglas:

    day = arrival_day + cycle*TBC + session*TBS

    Esto respeta la logica de separacion usada por el modelo interdia original,
    pero evita resolver un MIP enorme para el warm-up 1-730.
    """
    rows = []
    for _, patient in patients.iterrows():
        for cycle in range(int(patient["cycles"])):
            for session in range(int(patient["sessions"])):
                day = (
                    int(patient["arrival_day"])
                    + cycle * int(patient["days_between_cycles"])
                    + session * int(patient["days_between_sessions"])
                )
                if analysis_start <= day <= analysis_end:
                    rows.append(
                        {
                            "patient_id": int(patient["patient_id"]),
                            "patient_type": int(patient["patient_type"]),
                            "day": int(day),
                            "cycle": int(cycle),
                            "session": int(session),
                            "modules": int(patient["modules_per_session"]),
                            "arrival_day": int(patient["arrival_day"]),
                            "pharmacy_modules": int(patient["pharmacy_modules"]),
                        }
                    )

    assignments = pd.DataFrame(rows)
    if len(assignments) == 0:
        return pd.DataFrame(
            columns=[
                "patient_id",
                "patient_type",
                "day",
                "cycle",
                "session",
                "modules",
                "arrival_day",
                "pharmacy_modules",
            ]
        )
    return assignments.sort_values(["day", "patient_id", "cycle", "session"]).reset_index(drop=True)


def build_daily_occupancy(assignments, analysis_start, analysis_end):
    days = pd.DataFrame({"day": list(range(analysis_start, analysis_end + 1))})
    if len(assignments) == 0:
        days["occupancy"] = 0
        days["sessions"] = 0
        days["patients"] = 0
        return days

    grouped = (
        assignments.groupby("day")
        .agg(
            occupancy=("modules", "sum"),
            sessions=("patient_id", "size"),
            patients=("patient_id", "nunique"),
        )
        .reset_index()
    )
    return days.merge(grouped, on="day", how="left").fillna(0).astype(
        {"day": int, "occupancy": int, "sessions": int, "patients": int}
    )


def write_solution(output_path, patients, assignments, occupancy, capacity, args):
    total_days = len(occupancy)
    active_days = int((occupancy["sessions"] > 0).sum())
    daily_capacity = int(capacity["daily_module_capacity"])
    max_occupancy = int(occupancy["occupancy"].max()) if len(occupancy) else 0
    avg_occupancy = float(occupancy["occupancy"].mean()) if len(occupancy) else 0.0
    avg_active_occupancy = (
        float(occupancy.loc[occupancy["sessions"] > 0, "occupancy"].mean()) if active_days > 0 else 0.0
    )

    summary = pd.DataFrame(
        [
            ("Modo", "steady_state_rule_based"),
            ("Seed", args.seed),
            ("Arrival start", args.arrival_start),
            ("Arrival end", args.arrival_end),
            ("Analysis start", args.analysis_start),
            ("Analysis end", args.analysis_end),
            ("Analysis days", total_days),
            ("Patients generated", len(patients)),
            ("Patients appearing in analysis window", assignments["patient_id"].nunique() if len(assignments) else 0),
            ("Assignments in analysis window", len(assignments)),
            ("Active days in analysis window", active_days),
            ("Daily capacity modules", daily_capacity),
            ("Max occupancy modules", max_occupancy),
            ("Avg occupancy modules", round(avg_occupancy, 2)),
            ("Avg active-day occupancy modules", round(avg_active_occupancy, 2)),
            ("Max utilization", round(max_occupancy / daily_capacity, 4) if daily_capacity else 0),
            ("Avg utilization", round(avg_occupancy / daily_capacity, 4) if daily_capacity else 0),
        ],
        columns=["Metric", "Value"],
    )

    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        assignments.to_excel(writer, sheet_name="Asignaciones", index=False)
        occupancy.rename(
            columns={
                "day": "Día",
                "occupancy": "Ocupación",
                "sessions": "Sesiones",
                "patients": "Pacientes",
            }
        ).to_excel(writer, sheet_name="Ocupación Diaria", index=False)
        summary.to_excel(writer, sheet_name="Resumen", index=False)
        patients.to_excel(writer, sheet_name="Pacientes_Generados", index=False)


def run(args):
    timer = ExecutionTimer("modelo interdia V2 steady-state")
    base = load_base_data(args.base_data)
    timer.lap("datos base cargados")

    patients = generate_arrivals(
        base["patient_types"],
        arrival_start=args.arrival_start,
        arrival_end=args.arrival_end,
        seed=args.seed,
        max_patients=args.max_patients,
    )
    timer.lap(f"pacientes generados: {len(patients)}")

    assignments = build_rule_based_schedule(
        patients,
        analysis_start=args.analysis_start,
        analysis_end=args.analysis_end,
    )
    timer.lap(f"asignaciones en ventana de analisis: {len(assignments)}")

    occupancy = build_daily_occupancy(assignments, args.analysis_start, args.analysis_end)
    timer.lap("ocupacion diaria calculada")

    write_solution(args.output, patients, assignments, occupancy, base["capacity"], args)
    timer.lap(f"resultados guardados en {args.output}")

    daily_capacity = base["capacity"]["daily_module_capacity"]
    print("\n" + "=" * 72)
    print("RESUMEN INTERDIA V2")
    print("=" * 72)
    print(f"Pacientes generados: {len(patients)}")
    print(f"Asignaciones ventana {args.analysis_start}-{args.analysis_end}: {len(assignments)}")
    print(f"Dias activos: {int((occupancy['sessions'] > 0).sum())}/{len(occupancy)}")
    print(f"Ocupacion maxima: {int(occupancy['occupancy'].max())}/{daily_capacity}")
    print(f"Utilizacion maxima: {occupancy['occupancy'].max() / daily_capacity:.1%}")
    print(f"Ocupacion promedio: {occupancy['occupancy'].mean():.1f}/{daily_capacity}")
    print(f"Utilizacion promedio: {occupancy['occupancy'].mean() / daily_capacity:.1%}")
    print("=" * 72)

    timer.finish()
    return {"patients": patients, "assignments": assignments, "occupancy": occupancy}


def parse_args():
    parser = argparse.ArgumentParser(
        description="Modelo interdia V2: genera warm-up largo y exporta ventana steady-state."
    )
    parser.add_argument("--base-data", default="Data G15.xlsx")
    parser.add_argument("--output", default="solution_interday_v2_steady.xlsx")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--arrival-start", type=int, default=0)
    parser.add_argument("--arrival-end", type=int, default=730)
    parser.add_argument("--analysis-start", type=int, default=365)
    parser.add_argument("--analysis-end", type=int, default=730)
    parser.add_argument("--max-patients", type=int, default=None)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
