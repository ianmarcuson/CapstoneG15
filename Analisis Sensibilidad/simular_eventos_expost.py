from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np
import pandas as pd


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
DEFAULT_INTRADIA_ROOT = SCRIPT_DIR / "resultados_intradia"


def _log_step(message: str, start_time: float) -> None:
    elapsed = time.perf_counter() - start_time
    print(f"[S8/S9] {message} | elapsed={elapsed:.1f}s", flush=True)


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
    buffer_modules: int = 0,
    buffer_module: int = 28,
) -> None:
    t0 = time.perf_counter()
    _log_step(f"inicio input={input_xlsx} output={output_csv}", t0)
    _log_step("leyendo hoja Programacion", t0)
    schedule = pd.read_excel(input_xlsx, sheet_name="Programacion")
    _log_step(f"Programacion cargada filas={len(schedule):,}", t0)

    treatments = schedule[
        (schedule.get("task_type", "same_day_session") != "pharmacy_only")
        & (schedule["treatment_modules"].fillna(0).astype(int) > 0)
    ].copy()

    if treatments.empty:
        raise ValueError(f"No hay tratamientos en {input_xlsx}")

    treatments = treatments.sort_values(["service_day", "treatment_start", "treatment_end"]).reset_index(drop=True)
    _log_step(
        f"tratamientos filtrados filas={len(treatments):,} buffer_modules={buffer_modules} buffer_module={buffer_module}",
        t0,
    )

    rng = np.random.default_rng(seed)
    rows = []
    n = len(treatments)
    treatment_start = treatments["treatment_start"].astype(int).to_numpy()
    treatment_end = treatments["treatment_end"].astype(int).to_numpy()
    service_day = treatments["service_day"].astype(int).to_numpy()
    day_indices = [
        (int(day), idx.to_numpy())
        for day, idx in treatments.groupby("service_day", sort=True).groups.items()
    ]

    _log_step(f"iniciando simulaciones n={n_simulations:,}", t0)
    for sim in range(1, n_simulations + 1):
        if sim == 1 or sim % 100 == 0 or sim == n_simulations:
            _log_step(f"simulacion {sim:,}/{n_simulations:,}", t0)

        vomito = rng.random(n) < p_vomito
        vasovagal = rng.random(n) < p_vasovagal
        delay = vomito.astype(int) * vomito_delay + vasovagal.astype(int) * vasovagal_delay

        day_rows = []
        for day, idx in day_indices:
            d = delay[idx]
            v = vomito[idx]
            g = vasovagal[idx]
            starts = treatment_start[idx]
            ends = treatment_end[idx]

            # Modelo propagado: cada evento retrasa a las sesiones posteriores del mismo dia.
            cum_no_buffer = np.cumsum(d)
            effective_no_buffer = ends + cum_no_buffer

            cum = 0
            buffer_applied = False
            absorbed = 0
            residual_after_buffer = 0
            effective_with_buffer = np.empty(len(idx), dtype=int)
            pre_buffer_delay = int(d[starts < buffer_module].sum()) if buffer_modules > 0 else 0

            for j, event_delay in enumerate(d):
                if buffer_modules > 0 and not buffer_applied and starts[j] >= buffer_module:
                    before = cum
                    cum = max(0, cum - buffer_modules)
                    absorbed = before - cum
                    residual_after_buffer = cum
                    buffer_applied = True
                cum += int(event_delay)
                effective_with_buffer[j] = int(ends[j] + cum)

            if buffer_modules > 0 and not buffer_applied:
                before = cum
                cum = max(0, cum - buffer_modules)
                absorbed = before - cum
                residual_after_buffer = cum

            effective = effective_with_buffer if buffer_modules > 0 else effective_no_buffer
            day_rows.append(
                {
                    "service_day": day,
                    "sesiones": len(idx),
                    "eventos_vomito": int(v.sum()),
                    "eventos_vasovagal": int(g.sum()),
                    "modulos_atraso": int(d.sum()),
                    "sesiones_con_atraso": int((d > 0).sum()),
                    "max_delay": int(d.max()) if len(d) else 0,
                    "pre_buffer_delay": pre_buffer_delay,
                    "absorbed_by_buffer": int(absorbed),
                    "residual_pre_buffer_delay": int(residual_after_buffer),
                    "max_effective_end_no_buffer": int(effective_no_buffer.max()) if len(effective_no_buffer) else 0,
                    "sesiones_fuera_regular_no_buffer": int((effective_no_buffer > regular_end_module).sum()),
                    "sesiones_fuera_total_no_buffer": int((effective_no_buffer > total_end_module).sum()),
                    "max_effective_end": int(effective.max()) if len(effective) else 0,
                    "sesiones_fuera_regular": int((effective > regular_end_module).sum()),
                    "sesiones_fuera_total": int((effective > total_end_module).sum()),
                    "simulation": sim,
                }
            )
        rows.append(pd.DataFrame(day_rows))

    _log_step("concatenando resultados", t0)
    result = pd.concat(rows, ignore_index=True)
    result["buffer_modules"] = buffer_modules
    result["buffer_module"] = buffer_module if buffer_modules > 0 else np.nan
    result["termina_fuera_regular"] = result["max_effective_end"] > regular_end_module
    result["termina_fuera_total"] = result["max_effective_end"] > total_end_module
    result["termina_fuera_regular_no_buffer"] = result["max_effective_end_no_buffer"] > regular_end_module
    result["termina_fuera_total_no_buffer"] = result["max_effective_end_no_buffer"] > total_end_module
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    _log_step(f"escribiendo CSV filas={len(result):,}", t0)
    result.to_csv(output_csv, index=False)
    _log_step("fin", t0)


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
    parser.add_argument("--buffer-modules", type=int, default=0)
    parser.add_argument("--buffer-module", type=int, default=28)
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
        buffer_modules=args.buffer_modules,
        buffer_module=args.buffer_module,
    )


if __name__ == "__main__":
    main()
