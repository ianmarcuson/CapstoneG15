from __future__ import annotations

import argparse
import csv
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

from escenarios_sensibilidad import SensitivityScenario, get_scenarios


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
INTRADIA_DIR = PROJECT_DIR / "Modelo INTRAdia V2 Farmacia Anticipada 24h Farmacia Tardia"
INTRADIA_RUNNER = INTRADIA_DIR / "correr_intradia_replicas_farmacia_tardia_24h.py"
INTERDIA_ROOT = SCRIPT_DIR / "resultados_interdia"
OUT_ROOT = SCRIPT_DIR / "resultados_intradia"


@dataclass
class IntradiaSensitivityResult:
    scenario_id: str
    scenario_label: str
    interdia_source_scenario: str
    returncode: int
    status: str
    elapsed_seconds: float
    output_dir: str
    log_note: str


def interdia_source(scenario: SensitivityScenario) -> str:
    return scenario.interdia_source_scenario or scenario.id


def run_scenario(
    scenario: SensitivityScenario,
    replicas: int,
    replica_start: int,
    workers_intradia: int,
    replica_workers: int,
    overwrite: bool,
) -> IntradiaSensitivityResult:
    source = interdia_source(scenario)
    interdia_dir = INTERDIA_ROOT / source
    out_dir = OUT_ROOT / scenario.id
    input_pattern = f"solution_interday_{source}-{{replica}}.xlsx"

    cmd = [
        sys.executable,
        "-X",
        "utf8",
        str(INTRADIA_RUNNER),
        "--replica-start",
        str(replica_start),
        "--replica-end",
        str(replica_start + replicas - 1),
        "--interdia-dir",
        str(interdia_dir),
        "--input-pattern",
        input_pattern,
        "--out-dir",
        str(out_dir),
        "--workers-intradia",
        str(workers_intradia),
        "--replica-workers",
        str(replica_workers),
    ]
    if scenario.n_sillas_override is not None:
        cmd.extend(["--n-sillas-override", str(scenario.n_sillas_override)])
    if scenario.n_enfermeras_override is not None:
        cmd.extend(["--n-enfermeras-override", str(scenario.n_enfermeras_override)])
    if overwrite:
        cmd.append("--overwrite")

    out_dir.mkdir(parents=True, exist_ok=True)
    log_file = out_dir / f"log_runner_intradia_{scenario.id}.txt"
    t0 = time.time()
    with open(log_file, "w", encoding="utf-8", errors="replace") as log:
        log.write(f"Scenario: {scenario.id} | {scenario.label}\n")
        log.write(f"Interdia source: {source}\n")
        log.write(f"Command: {' '.join(cmd)}\n\n")
        log.flush()
        completed = subprocess.run(
            cmd,
            cwd=INTRADIA_DIR,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
        )
    elapsed = round(time.time() - t0, 2)
    return IntradiaSensitivityResult(
        scenario_id=scenario.id,
        scenario_label=scenario.label,
        interdia_source_scenario=source,
        returncode=completed.returncode,
        status="OK" if completed.returncode == 0 else "ERROR",
        elapsed_seconds=elapsed,
        output_dir=str(out_dir),
        log_note=str(log_file),
    )


def write_summary(path: Path, rows: List[IntradiaSensitivityResult]) -> None:
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(rows[0]).keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Corre escenarios de sensibilidad del modelo intradia.")
    parser.add_argument("--scenarios", nargs="*", default=None)
    parser.add_argument("--replicas", type=int, default=1)
    parser.add_argument("--start-replica", type=int, default=1)
    parser.add_argument("--workers-intradia", type=int, default=1)
    parser.add_argument("--replica-workers", type=int, default=1)
    parser.add_argument("--scenario-workers", type=int, default=1)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--include-expost",
        action="store_true",
        help="Incluye escenarios ex post si ya existe una agenda intradia fuente.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    scenarios = get_scenarios(args.scenarios)
    if not args.include_expost:
        scenarios = [s for s in scenarios if not s.ex_post_events]

    results: List[IntradiaSensitivityResult] = []
    with ThreadPoolExecutor(max_workers=args.scenario_workers) as executor:
        futures = [
            executor.submit(
                run_scenario,
                scenario,
                args.replicas,
                args.start_replica,
                args.workers_intradia,
                args.replica_workers,
                args.overwrite,
            )
            for scenario in scenarios
        ]
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(f"[{result.scenario_id}] {result.status} | {result.elapsed_seconds:.1f}s")

    results.sort(key=lambda r: r.scenario_id)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    write_summary(OUT_ROOT / "resumen_intradia_sensibilidad.csv", results)
    if any(r.status == "ERROR" for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

