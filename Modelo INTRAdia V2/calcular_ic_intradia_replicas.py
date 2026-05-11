"""
Calcula KPIs e intervalos de confianza desde outputs intradia por replica.

Lee los archivos solution_intradia-i.xlsx disponibles en una carpeta y genera:
  - kpis_intradia_replicas.csv
  - kpis_intradia_ic95.csv
  - kpis_intradia_daily_ic95.csv
  - kpis_intradia_most_loaded_day_freq.csv

No requiere que existan las 30 replicas; usa todas las disponibles.
"""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import numpy as np
import pandas as pd


KPI_LABELS = {
    "sessions": "Sesiones realizadas",
    "unique_patients": "Pacientes unicos",
    "cumplimiento": "Cumplimiento horario regular (%)",
    "total_extra": "Modulos extra totales",
    "days_extra": "Dias con extra",
    "max_wait": "Espera maxima (mod)",
    "avg_wait": "Espera promedio (mod)",
    "util_chairs": "Utilizacion sillas total (%)",
    "util_chairs_reg": "Utilizacion sillas regulares (%)",
    "util_nurses": "Ocupacion enfermeria (%)",
    "util_pharm": "Ocupacion farmacia (%)",
    "postponed_sessions": "Sesiones postponadas",
    "unattended": "Pacientes no atendidos",
}

DAILY_KPI_LABELS = {
    "daily_sessions": "Sesiones por dia",
    "daily_unique_patients": "Pacientes unicos por dia",
    "daily_treatment_modules": "Modulos tratamiento por dia",
    "daily_extra_modules": "Modulos extra por dia",
    "daily_avg_wait": "Espera promedio diaria (mod)",
    "daily_max_wait": "Espera maxima diaria (mod)",
    "daily_peak_chairs": "Peak sillas",
    "daily_peak_nurses": "Peak enfermeria",
    "daily_peak_pharmacy": "Peak farmacia",
}


def t_critical_975(df: int) -> float:
    """Valor t bilateral 95% para grados de libertad habituales."""
    table = {
        1: 12.706,
        2: 4.303,
        3: 3.182,
        4: 2.776,
        5: 2.571,
        6: 2.447,
        7: 2.365,
        8: 2.306,
        9: 2.262,
        10: 2.228,
        11: 2.201,
        12: 2.179,
        13: 2.160,
        14: 2.145,
        15: 2.131,
        16: 2.120,
        17: 2.110,
        18: 2.101,
        19: 2.093,
        20: 2.086,
        21: 2.080,
        22: 2.074,
        23: 2.069,
        24: 2.064,
        25: 2.060,
        26: 2.056,
        27: 2.052,
        28: 2.048,
        29: 2.045,
        30: 2.042,
    }
    if df <= 0:
        return float("nan")
    if df in table:
        return table[df]
    if df <= 40:
        return 2.021
    if df <= 60:
        return 2.000
    if df <= 120:
        return 1.980
    return 1.960


def replica_from_path(path: Path) -> Optional[int]:
    match = re.search(r"solution_intradia-(\d+)\.xlsx$", path.name)
    return int(match.group(1)) if match else None


def read_solution(path: Path):
    xls = pd.ExcelFile(path)
    df_res = xls.parse("Resumen_Dias") if "Resumen_Dias" in xls.sheet_names else pd.DataFrame()
    df_prog = xls.parse("Programacion") if "Programacion" in xls.sheet_names else pd.DataFrame()
    df_ocup = xls.parse("Ocupacion_Modulos") if "Ocupacion_Modulos" in xls.sheet_names else pd.DataFrame()
    df_pend = xls.parse("Pendientes") if "Pendientes" in xls.sheet_names else pd.DataFrame()

    if not df_prog.empty and "wait_after_pharmacy" not in df_prog.columns:
        df_prog["wait_after_pharmacy"] = np.where(
            df_prog["pharmacy_modules"] > 0,
            df_prog["treatment_start"] - df_prog["pharmacy_end"] - 1,
            0,
        )

    return df_res, df_prog, df_ocup, df_pend


def filter_days(df: pd.DataFrame, start_day: Optional[int], end_day: Optional[int]) -> pd.DataFrame:
    if df.empty or "day" not in df.columns:
        return df
    out = df
    if start_day is not None:
        out = out[out["day"] >= start_day]
    if end_day is not None:
        out = out[out["day"] <= end_day]
    return out.copy()


def compute_kpis(df_prog: pd.DataFrame, df_ocup: pd.DataFrame, df_res: pd.DataFrame, df_pend: pd.DataFrame) -> Dict:
    total_sessions = len(df_prog)
    unique_patients = df_prog["patient_id"].nunique() if total_sessions > 0 else 0
    cumplimiento = (df_prog["treatment_end"] <= 47).sum() / total_sessions * 100 if total_sessions > 0 else 0.0
    total_extra = df_prog["extra_chair_modules"].sum() if total_sessions > 0 else 0
    days_extra = df_prog[df_prog["extra_chair_modules"] > 0]["day"].nunique() if total_sessions > 0 else 0
    max_wait = int(df_prog["treatment_start"].max()) if total_sessions > 0 else 0
    avg_wait = float(df_prog["treatment_start"].mean()) if total_sessions > 0 else 0.0

    total_chairs_cap = df_ocup["chair_capacity"].sum() if not df_ocup.empty else 0
    util_chairs = df_ocup["chairs_used"].sum() / total_chairs_cap * 100 if total_chairs_cap > 0 else 0.0
    reg_ocup = df_ocup[df_ocup["is_extra"] == 0] if not df_ocup.empty else pd.DataFrame()
    util_chairs_reg = (
        reg_ocup["chairs_used"].sum() / reg_ocup["chair_capacity"].sum() * 100
        if not reg_ocup.empty and reg_ocup["chair_capacity"].sum() > 0
        else 0.0
    )

    if not df_ocup.empty:
        if "nurse_events" in df_ocup.columns:
            nurse_used = df_ocup["nurse_events"].sum()
        elif "nurse_starts" in df_ocup.columns and "nurse_ends" in df_ocup.columns:
            nurse_used = df_ocup["nurse_starts"].sum() + df_ocup["nurse_ends"].sum()
        elif "nurse_starts" in df_ocup.columns:
            nurse_used = df_ocup["nurse_starts"].sum()
        else:
            nurse_used = 0
        util_nurses = nurse_used / df_ocup["nurse_capacity"].sum() * 100 if df_ocup["nurse_capacity"].sum() > 0 else 0.0
        pharm_ops = df_ocup[df_ocup["module"] <= 20]
        util_pharm = (
            pharm_ops["pharmacy_used"].sum() / pharm_ops["pharmacy_capacity"].sum() * 100
            if not pharm_ops.empty and pharm_ops["pharmacy_capacity"].sum() > 0
            else 0.0
        )
    else:
        util_nurses = 0.0
        util_pharm = 0.0

    most_loaded_day = (
        int(df_prog.groupby("day")["treatment_modules"].sum().idxmax())
        if total_sessions > 0
        else None
    )

    postponed_sessions = (
        int(df_res["sessions_postponed"].sum())
        if not df_res.empty and "sessions_postponed" in df_res.columns
        else 0
    )
    unattended = (
        int(df_pend["patient_id"].nunique())
        if not df_pend.empty and "patient_id" in df_pend.columns
        else 0
    )

    return {
        "sessions": int(total_sessions),
        "unique_patients": int(unique_patients),
        "cumplimiento": float(cumplimiento),
        "total_extra": float(total_extra),
        "days_extra": int(days_extra),
        "max_wait": int(max_wait),
        "avg_wait": float(avg_wait),
        "util_chairs": float(util_chairs),
        "util_chairs_reg": float(util_chairs_reg),
        "util_nurses": float(util_nurses),
        "util_pharm": float(util_pharm),
        "most_loaded_day": most_loaded_day,
        "postponed_sessions": int(postponed_sessions),
        "unattended": int(unattended),
    }


def compute_daily_kpis(replica: int, df_prog: pd.DataFrame, df_ocup: pd.DataFrame) -> List[Dict]:
    rows = []
    days = sorted(set(df_prog["day"].unique()) | set(df_ocup["day"].unique()))
    for day in days:
        day_prog = df_prog[df_prog["day"] == day]
        day_ocup = df_ocup[df_ocup["day"] == day]
        reg_ocup = day_ocup[day_ocup["is_extra"] == 0] if not day_ocup.empty and "is_extra" in day_ocup.columns else pd.DataFrame()
        pharm_ops = day_ocup[day_ocup["module"] <= 20] if not day_ocup.empty and "module" in day_ocup.columns else pd.DataFrame()
        if "nurse_events" in day_ocup.columns:
            nurse_series = day_ocup["nurse_events"]
        elif "nurse_starts" in day_ocup.columns and "nurse_ends" in day_ocup.columns:
            nurse_series = day_ocup["nurse_starts"] + day_ocup["nurse_ends"]
        elif "nurse_starts" in day_ocup.columns:
            nurse_series = day_ocup["nurse_starts"]
        else:
            nurse_series = pd.Series(dtype=float)

        rows.append(
            {
                "replica": replica,
                "day": int(day),
                "daily_sessions": int(len(day_prog)),
                "daily_unique_patients": int(day_prog["patient_id"].nunique()) if not day_prog.empty else 0,
                "daily_patient_ids": "|".join(map(str, sorted(day_prog["patient_id"].dropna().unique()))) if not day_prog.empty else "",
                "daily_treatment_modules": float(day_prog["treatment_modules"].sum()) if not day_prog.empty else 0.0,
                "daily_extra_modules": float(day_prog["extra_chair_modules"].sum()) if not day_prog.empty else 0.0,
                "daily_avg_wait": float(day_prog["treatment_start"].mean()) if not day_prog.empty else 0.0,
                "daily_max_wait": float(day_prog["treatment_start"].max()) if not day_prog.empty else 0.0,
                "daily_peak_chairs": float(day_ocup["chairs_used"].max()) if not day_ocup.empty else 0.0,
                "daily_peak_nurses": float(nurse_series.max()) if not nurse_series.empty else 0.0,
                "daily_peak_pharmacy": float(day_ocup["pharmacy_used"].max()) if not day_ocup.empty else 0.0,
                "daily_ontime_sessions": int((day_prog["treatment_end"] <= 47).sum()) if not day_prog.empty else 0,
                "daily_chairs_used_sum": float(day_ocup["chairs_used"].sum()) if not day_ocup.empty else 0.0,
                "daily_chairs_capacity_sum": float(day_ocup["chair_capacity"].sum()) if not day_ocup.empty else 0.0,
                "daily_chairs_reg_used_sum": float(reg_ocup["chairs_used"].sum()) if not reg_ocup.empty else 0.0,
                "daily_chairs_reg_capacity_sum": float(reg_ocup["chair_capacity"].sum()) if not reg_ocup.empty else 0.0,
                "daily_nurse_used_sum": float(nurse_series.sum()) if not nurse_series.empty else 0.0,
                "daily_nurse_capacity_sum": float(day_ocup["nurse_capacity"].sum()) if not day_ocup.empty else 0.0,
                "daily_pharmacy_used_0_20_sum": float(pharm_ops["pharmacy_used"].sum()) if not pharm_ops.empty else 0.0,
                "daily_pharmacy_capacity_0_20_sum": float(pharm_ops["pharmacy_capacity"].sum()) if not pharm_ops.empty else 0.0,
            }
        )
    return rows


def summarize_values(values: Iterable[float]) -> Dict:
    s = pd.Series(list(values), dtype="float64").dropna()
    n = int(s.size)
    mean = float(s.mean()) if n else float("nan")
    std = float(s.std(ddof=1)) if n > 1 else 0.0
    se = std / math.sqrt(n) if n > 1 else 0.0
    margin = t_critical_975(n - 1) * se if n > 1 else 0.0
    return {
        "n": n,
        "min": float(s.min()) if n else float("nan"),
        "max": float(s.max()) if n else float("nan"),
        "mean": mean,
        "std": std,
        "se": se,
        "ci95_low": mean - margin if n else float("nan"),
        "ci95_high": mean + margin if n else float("nan"),
    }


def summarize_kpis(df: pd.DataFrame, labels: Dict[str, str]) -> pd.DataFrame:
    rows = []
    for kpi, label in labels.items():
        if kpi not in df.columns:
            continue
        row = {"kpi": kpi, "label": label}
        row.update(summarize_values(df[kpi]))
        rows.append(row)
    return pd.DataFrame(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Calcula IC 95% de KPIs intradia desde replicas disponibles.")
    parser.add_argument("--input-dir", default="resultados_intradia_30_replicas", help="Carpeta con solution_intradia-i.xlsx.")
    parser.add_argument("--output-dir", default=None, help="Carpeta para CSV. Default: input-dir.")
    parser.add_argument("--start-day", type=int, default=None, help="Dia inicial opcional.")
    parser.add_argument("--end-day", type=int, default=None, help="Dia final opcional.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    input_dir = Path(args.input_dir)
    if not input_dir.is_absolute():
        input_dir = script_dir / input_dir
    input_dir = input_dir.resolve()

    output_dir = Path(args.output_dir) if args.output_dir else input_dir
    if not output_dir.is_absolute():
        output_dir = script_dir / output_dir
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(input_dir.glob("solution_intradia-*.xlsx"), key=lambda p: replica_from_path(p) or 10**9)
    if not files:
        raise FileNotFoundError(f"No se encontraron solution_intradia-*.xlsx en {input_dir}")

    replica_rows = []
    daily_rows = []
    errors = []

    for path in files:
        replica = replica_from_path(path)
        if replica is None:
            continue
        try:
            df_res, df_prog, df_ocup, df_pend = read_solution(path)
            df_res = filter_days(df_res, args.start_day, args.end_day)
            df_prog = filter_days(df_prog, args.start_day, args.end_day)
            df_ocup = filter_days(df_ocup, args.start_day, args.end_day)
            if df_prog.empty:
                errors.append({"replica": replica, "file": str(path), "error": "Programacion vacia en rango."})
                continue

            row = {
                "replica": replica,
                "file": str(path),
                "start_day": args.start_day,
                "end_day": args.end_day,
            }
            row.update(compute_kpis(df_prog, df_ocup, df_res, df_pend))
            replica_rows.append(row)
            daily_rows.extend(compute_daily_kpis(replica, df_prog, df_ocup))
        except Exception as exc:
            errors.append({"replica": replica, "file": str(path), "error": str(exc)})

    if not replica_rows:
        raise RuntimeError("No hay replicas validas para calcular KPIs.")

    df_replicas = pd.DataFrame(replica_rows).sort_values("replica")
    df_ic = summarize_kpis(df_replicas, KPI_LABELS)

    df_daily = pd.DataFrame(daily_rows)
    daily_summary_rows = []
    if not df_daily.empty:
        for day, day_df in df_daily.groupby("day"):
            for kpi, label in DAILY_KPI_LABELS.items():
                row = {"day": int(day), "kpi": kpi, "label": label}
                row.update(summarize_values(day_df[kpi]))
                daily_summary_rows.append(row)
    df_daily_ic = pd.DataFrame(daily_summary_rows)

    freq = (
        df_replicas["most_loaded_day"]
        .dropna()
        .astype(int)
        .value_counts()
        .rename_axis("day")
        .reset_index(name="count")
    )
    freq["pct"] = freq["count"] / len(df_replicas) * 100
    freq = freq.sort_values(["count", "day"], ascending=[False, True])

    df_replicas.to_csv(output_dir / "kpis_intradia_replicas.csv", index=False)
    df_ic.to_csv(output_dir / "kpis_intradia_ic95.csv", index=False)
    df_daily.to_csv(output_dir / "kpis_intradia_daily_replicas.csv", index=False)
    df_daily_ic.to_csv(output_dir / "kpis_intradia_daily_ic95.csv", index=False)
    freq.to_csv(output_dir / "kpis_intradia_most_loaded_day_freq.csv", index=False)
    if errors:
        pd.DataFrame(errors).to_csv(output_dir / "kpis_intradia_errores.csv", index=False)

    print(f"Replicas validas: {len(df_replicas)}")
    print(f"CSV generados en: {output_dir}")
    print("  - kpis_intradia_replicas.csv")
    print("  - kpis_intradia_ic95.csv")
    print("  - kpis_intradia_daily_replicas.csv")
    print("  - kpis_intradia_daily_ic95.csv")
    print("  - kpis_intradia_most_loaded_day_freq.csv")
    if errors:
        print("  - kpis_intradia_errores.csv")


if __name__ == "__main__":
    main()
