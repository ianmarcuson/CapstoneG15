from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DEFAULT_INTRADIA_ROOT = SCRIPT_DIR / "resultados_intradia"


def simulate_file(
    input_xlsx: Path,
    output_csv: Path,
    n_simulations: int,
    seed: int,
    p_vomito: float,
    p_vasovagal: float,
    vomito_delay: int,
    vasovagal_delay: int,
    regular_end_module: int,
    total_end_module: int,
) -> None:
    schedule = pd.read_excel(input_xlsx, sheet_name="Programacion")
    treatments = schedule[
        (schedule.get("task_type", "same_day_session") != "pharmacy_only")
        & (schedule["treatment_modules"].fillna(0).astype(int) > 0)
    ].copy()

    if treatments.empty:
        raise ValueError(f"No hay tratamientos en {input_xlsx}")

    rng = np.random.default_rng(seed)
    rows = []
    n = len(treatments)
    treatment_end = treatments["treatment_end"].astype(int).to_numpy()
    service_day = treatments["service_day"].astype(int).to_numpy()

    for sim in range(1, n_simulations + 1):
        vomito = rng.random(n) < p_vomito
        vasovagal = rng.random(n) < p_vasovagal
        delay = vomito.astype(int) * vomito_delay + vasovagal.astype(int) * vasovagal_delay
        effective_end = treatment_end + delay

        sim_df = pd.DataFrame(
            {
                "service_day": service_day,
                "delay": delay,
                "effective_end": effective_end,
                "vomito": vomito,
                "vasovagal": vasovagal,
            }
        )
        day_summary = sim_df.groupby("service_day").agg(
            sesiones=("delay", "size"),
            eventos_vomito=("vomito", "sum"),
            eventos_vasovagal=("vasovagal", "sum"),
            modulos_atraso=("delay", "sum"),
            sesiones_con_atraso=("delay", lambda s: int((s > 0).sum())),
            max_delay=("delay", "max"),
            max_effective_end=("effective_end", "max"),
            sesiones_fuera_regular=("effective_end", lambda s: int((s > regular_end_module).sum())),
            sesiones_fuera_total=("effective_end", lambda s: int((s > total_end_module).sum())),
        )
        day_summary["simulation"] = sim
        rows.append(day_summary.reset_index())

    result = pd.concat(rows, ignore_index=True)
    result["termina_fuera_regular"] = result["max_effective_end"] > regular_end_module
    result["termina_fuera_total"] = result["max_effective_end"] > total_end_module
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output_csv, index=False)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simula eventos clinicos ex post sobre output intradia.")
    parser.add_argument("--input-xlsx", type=str, required=True)
    parser.add_argument("--output-csv", type=str, required=True)
    parser.add_argument("--simulations", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=202406)
    parser.add_argument("--p-vomito", type=float, default=0.072)
    parser.add_argument("--p-vasovagal", type=float, default=0.028)
    parser.add_argument("--vomito-delay", type=int, default=1)
    parser.add_argument("--vasovagal-delay", type=int, default=2)
    parser.add_argument("--regular-end-module", type=int, default=47)
    parser.add_argument("--total-end-module", type=int, default=55)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    simulate_file(
        input_xlsx=Path(args.input_xlsx).resolve(),
        output_csv=Path(args.output_csv).resolve(),
        n_simulations=args.simulations,
        seed=args.seed,
        p_vomito=args.p_vomito,
        p_vasovagal=args.p_vasovagal,
        vomito_delay=args.vomito_delay,
        vasovagal_delay=args.vasovagal_delay,
        regular_end_module=args.regular_end_module,
        total_end_module=args.total_end_module,
    )


if __name__ == "__main__":
    main()

