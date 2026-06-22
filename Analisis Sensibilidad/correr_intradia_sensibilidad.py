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
EXPOST_SCRIPT = SCRIPT_DIR / "simular_eventos_expost.py"


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
    dry_run: bool,
) -> IntradiaSensitivityResult:
    if scenario.ex_post_events:
        return run_expost_scenario(
            scenario=scenario,
            replicas=replicas,
            replica_start=replica_start,
            overwrite=overwrite,
            dry_run=dry_run,
        )

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
    missing_inputs = [
        interdia_dir / input_pattern.format(replica=replica)
        for replica in range(replica_start, replica_start + replicas)
        if not (interdia_dir / input_pattern.format(replica=replica)).exists()
    ]
    if dry_run:
        status = "DRY-RUN" if not missing_inputs else "DRY-RUN-MISSING-INPUT"
        return IntradiaSensitivityResult(
            scenario_id=scenario.id,
            scenario_label=scenario.label,
            interdia_source_scenario=source,
            returncode=0 if not missing_inputs else 1,
            status=status,
            elapsed_seconds=0.0,
            output_dir=str(out_dir),
            log_note=(
                f"Command: {' '.join(cmd)}"
                if not missing_inputs
                else f"Missing inputs: {', '.join(str(p) for p in missing_inputs[:5])}"
            ),
        )

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


def run_expost_scenario(
    scenario: SensitivityScenario,
    replicas: int,
    replica_start: int,
    overwrite: bool,
    dry_run: bool,
) -> IntradiaSensitivityResult:
    source = interdia_source(scenario)
    source_dir = OUT_ROOT / source
    out_dir = OUT_ROOT / scenario.id
    out_dir.mkdir(parents=True, exist_ok=True)
    log_file = out_dir / f"log_expost_{scenario.id}.txt"
    missing_inputs = [
        source_dir / f"solution_intradia-{replica}.xlsx"
        for replica in range(replica_start, replica_start + replicas)
        if not (source_dir / f"solution_intradia-{replica}.xlsx").exists()
    ]
    if dry_run:
        status = "DRY-RUN" if not missing_inputs else "DRY-RUN-MISSING-INPUT"
        return IntradiaSensitivityResult(
            scenario_id=scenario.id,
            scenario_label=scenario.label,
            interdia_source_scenario=source,
            returncode=0 if not missing_inputs else 1,
            status=status,
            elapsed_seconds=0.0,
            output_dir=str(out_dir),
            log_note=(
                f"Ex post inputs OK in {source_dir}"
                if not missing_inputs
                else f"Missing inputs: {', '.join(str(p) for p in missing_inputs[:5])}"
            ),
        )

    t0 = time.time()
    returncode = 0
    messages: List[str] = []

    with open(log_file, "w", encoding="utf-8", errors="replace") as log:
        log.write(f"Scenario: {scenario.id} | {scenario.label}\n")
        log.write(f"Source intradia scenario: {source}\n\n")
        for replica in range(replica_start, replica_start + replicas):
            input_xlsx = source_dir / f"solution_intradia-{replica}.xlsx"
            output_csv = out_dir / f"eventos_expost-{replica}.csv"
            if not input_xlsx.exists():
                returncode = 1
                msg = f"Falta input ex post: {input_xlsx}"
                messages.append(msg)
                log.write(msg + "\n")
                continue
            if output_csv.exists() and not overwrite:
                msg = f"SKIP existente: {output_csv}"
                messages.append(msg)
                log.write(msg + "\n")
                continue

            cmd = [
                sys.executable,
                "-X",
                "utf8",
                str(EXPOST_SCRIPT),
                "--input-xlsx",
                str(input_xlsx),
                "--output-csv",
                str(output_csv),
            ]
            log.write(f"Replica {replica}: {' '.join(cmd)}\n")
            log.flush()
            completed = subprocess.run(
                cmd,
                cwd=SCRIPT_DIR,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            if completed.returncode != 0:
                returncode = completed.returncode
                messages.append(f"ERROR replica {replica}")
            else:
                messages.append(f"OK replica {replica}")

    elapsed = round(time.time() - t0, 2)
    return IntradiaSensitivityResult(
        scenario_id=scenario.id,
        scenario_label=scenario.label,
        interdia_source_scenario=source,
        returncode=returncode,
        status="OK" if returncode == 0 else "ERROR",
        elapsed_seconds=elapsed,
        output_dir=str(out_dir),
        log_note=f"{log_file} | {'; '.join(messages[:5])}",
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
    parser.add_argument("--dry-run", action="store_true", help="Valida rutas/comandos sin ejecutar intradia ni ex post.")
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
                args.dry_run,
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
