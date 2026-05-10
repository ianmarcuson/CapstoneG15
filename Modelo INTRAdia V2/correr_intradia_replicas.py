#py correr_intradia_replicas.py --replicas 1 --workers-intradia 2 --replica-workers 1 --no-all-days --max-days 100 --overwrite


"""
correr_intradia_replicas.py

Ejecuta modelo_intradia_optimizado.py para multiples outputs del modelo interdia,
por ejemplo:
    Modelo Interdia/resultados_10_replicas/solution_interday-1.xlsx
    Modelo Interdia/resultados_10_replicas/solution_interday-2.xlsx
    ...

y guarda outputs/logs intradia separados por replica.

Uso tipico desde la carpeta:
    CapstoneG15/Modelo INTRAdia V2

    py correr_intradia_replicas.py --replicas 10 --workers-intradia 2

Supuestos por defecto:
    - Este script esta en CapstoneG15/Modelo INTRAdia V2
    - modelo_intradia_optimizado.py esta en la misma carpeta
    - Los outputs interdia estan en ../Modelo Interdia/resultados_10_replicas
    - El archivo base de parametros esta en ../Data Inicial/Data G15.xlsx
"""

from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class IntradiaRunResult:
    replica: int
    input_solution: str
    output_xlsx: str
    log_file: str
    returncode: int
    status: str
    elapsed_seconds: float


def _resolve_path(path_str: str, base_dir: Path) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _safe_print(msg: str) -> None:
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode("ascii"))


def validate_base_files(script_dir: Path, model_file: Path, base_data: Path) -> None:
    missing = []
    if not model_file.exists():
        missing.append(str(model_file))
    if not base_data.exists():
        missing.append(str(base_data))
    if missing:
        raise FileNotFoundError("Faltan archivos requeridos:\n  - " + "\n  - ".join(missing))


def run_intradia_for_replica(
    replica: int,
    python_exe: str,
    script_dir: Path,
    model_file: Path,
    interdia_dir: Path,
    base_data: Path,
    out_dir: Path,
    workers_intradia: int,
    all_days: bool,
    max_days: Optional[int],
    max_iterations: Optional[int],
    pricing_top_n: Optional[int],
    gurobi_output: bool,
    overwrite: bool,
    start_day: Optional[int] = None,
    end_day: Optional[int] = None,
) -> IntradiaRunResult:
    input_solution = interdia_dir / f"solution_interday-{replica}.xlsx"
    output_xlsx = out_dir / f"solution_intradia-{replica}.xlsx"
    log_file = out_dir / f"log_intradia-{replica}.txt"

    if not input_solution.exists():
        raise FileNotFoundError(f"No existe input interdía para réplica {replica}: {input_solution}")

    if output_xlsx.exists() and not overwrite:
        return IntradiaRunResult(
            replica=replica,
            input_solution=str(input_solution),
            output_xlsx=str(output_xlsx),
            log_file=str(log_file),
            returncode=0,
            status="SKIPPED_EXISTS",
            elapsed_seconds=0.0,
        )

    cmd = [
        python_exe,
        "-X",
        "utf8",
        str(model_file),
        "--solution",
        str(input_solution),
        "--base-data",
        str(base_data),
        "--output",
        str(output_xlsx),
        "--workers",
        str(workers_intradia),
    ]

    if all_days:
        cmd.append("--all-days")
    elif start_day is not None and end_day is not None:
        for d in range(start_day, end_day + 1):
            cmd.extend(["--day", str(d)])
    elif max_days is not None:
        cmd.extend(["--max-days", str(max_days)])

    if max_iterations is not None:
        cmd.extend(["--max-iterations", str(max_iterations)])
    if pricing_top_n is not None:
        cmd.extend(["--pricing-top-n", str(pricing_top_n)])
    if gurobi_output:
        cmd.append("--gurobi-output")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    _safe_print(f">>> [Replica {replica}] Iniciando ejecución...")
    t0 = time.time()
    
    process = subprocess.Popen(
        cmd,
        cwd=script_dir,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        bufsize=1,
    )

    last_heartbeat = t0
    # Leer el output en tiempo real y guardarlo en el log
    with open(log_file, "w", encoding="utf-8", errors="replace") as f_log:
        f_log.write(f"Replica: {replica}\n")
        f_log.write(f"Input solution: {input_solution}\n")
        f_log.write(f"Output XLSX: {output_xlsx}\n")
        f_log.write(f"Comando: {' '.join(cmd)}\n")
        f_log.write("\n--- INICIO MODELO INTRADIA ---\n\n")
        f_log.flush()

        while True:
            line = process.stdout.readline()
            if not line and process.poll() is not None:
                break
            
            if line:
                f_log.write(line)
                f_log.flush()
                clean_line = line.strip()
                # Filtrar solo líneas de interés para el usuario
                if "[TIMER] Inicio CG optimizado día" in clean_line:
                    day_num = clean_line.split("día")[-1].strip()
                    _safe_print(f"    [Replica {replica}] >>> Resolviendo Día {day_num}...")
                elif "[TIMER] Fin CG optimizado día" in clean_line:
                    # El modelo ya calcula el tiempo total del día, lo mostramos
                    _safe_print(f"    [Replica {replica}] {clean_line}")
                
                # Reset heartbeat timer since we got activity
                last_heartbeat = time.time()
            else:
                # Si no hay líneas, verificamos el heartbeat cada segundo
                time.sleep(1)
                now = time.time()
                if now - last_heartbeat >= 30:
                    elapsed = int(now - t0)
                    _safe_print(f"    ... [Replica {replica}] sigue trabajando ({elapsed}s)")
                    last_heartbeat = now

    retcode = process.wait()
    elapsed = round(time.time() - t0, 2)
    status = "OK" if retcode == 0 else "ERROR"

    return IntradiaRunResult(
        replica=replica,
        input_solution=str(input_solution),
        output_xlsx=str(output_xlsx),
        log_file=str(log_file),
        returncode=retcode,
        status=status,
        elapsed_seconds=elapsed,
    )


def write_summary_csv(path: Path, results: List[IntradiaRunResult]) -> None:
    if not results:
        return
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(asdict(results[0]).keys()))
        writer.writeheader()
        for result in results:
            writer.writerow(asdict(result))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ejecuta modelo_intradia_optimizado.py para todas las replicas solution_interday-i.xlsx."
    )
    parser.add_argument("--replicas", type=int, default=10, help="Cantidad de replicas a correr.")
    parser.add_argument(
        "--interdia-dir",
        type=str,
        default="../Modelo Interdia/resultados_30_replicas",
        help="Carpeta con solution_interday-i.xlsx.",
    )
    parser.add_argument(
        "--out-dir",
        type=str,
        default="resultados_intradia_30_replicas",
        help="Carpeta donde se guardan solution_intradia-i.xlsx, logs y resumen.",
    )
    parser.add_argument(
        "--base-data",
        type=str,
        default="../Data Inicial/Data G15.xlsx",
        help="Archivo Data G15.xlsx con parametros base del modelo intradia.",
    )
    parser.add_argument(
        "--model-file",
        type=str,
        default="modelo_intradia_optimizado.py",
        help="Archivo .py del modelo intradia a ejecutar.",
    )
    parser.add_argument(
        "--workers-intradia",
        type=int,
        default=2,
        help="Workers internos que usara cada corrida intradia para resolver dias.",
    )
    parser.add_argument(
        "--replica-workers",
        type=int,
        default=1,
        help="Cantidad de replicas intradia en paralelo. Recomendado: 1, porque cada replica ya usa workers internos.",
    )
    parser.add_argument("--all-days", action="store_true", default=True, help="Resolver todos los dias con sesiones. Default: True.")
    parser.add_argument("--no-all-days", dest="all_days", action="store_false", help="No usar --all-days; usa --max-days o --start-day/--end-day.")
    parser.add_argument("--max-days", type=int, default=None, help="Cantidad de dias si no se usa --all-days.")
    parser.add_argument("--start-day", type=int, default=None, help="Día de inicio para procesar un rango de días.")
    parser.add_argument("--end-day", type=int, default=None, help="Día de fin para procesar un rango de días.")
    parser.add_argument("--max-iterations", type=int, default=None, help="Opcional: sobrescribe max iterations del CG.")
    parser.add_argument("--pricing-top-n", type=int, default=None, help="Opcional: columnas negativas maximas por paciente/iteracion.")
    parser.add_argument("--gurobi-output", action="store_true", help="Muestra output interno de Gurobi en logs.")
    parser.add_argument("--overwrite", action="store_true", help="Sobrescribe outputs existentes.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.replicas <= 0:
        raise ValueError("--replicas debe ser >= 1")
    if args.workers_intradia <= 0:
        raise ValueError("--workers-intradia debe ser >= 1")
    if args.replica_workers <= 0:
        raise ValueError("--replica-workers debe ser >= 1")

    script_dir = Path(__file__).resolve().parent
    interdia_dir = _resolve_path(args.interdia_dir, script_dir)
    out_dir = _resolve_path(args.out_dir, script_dir)
    base_data = _resolve_path(args.base_data, script_dir)
    model_file = _resolve_path(args.model_file, script_dir)

    validate_base_files(script_dir, model_file, base_data)
    if not interdia_dir.exists():
        raise FileNotFoundError(f"No existe carpeta interdia: {interdia_dir}")
    out_dir.mkdir(parents=True, exist_ok=True)

    _safe_print("=" * 76)
    _safe_print("EJECUCION INTRADIA PARA REPLICAS INTERDIA")
    _safe_print("=" * 76)
    _safe_print(f"Directorio intradia: {script_dir}")
    _safe_print(f"Modelo intradia:     {model_file}")
    _safe_print(f"Carpeta interdia:    {interdia_dir}")
    _safe_print(f"Base data:           {base_data}")
    _safe_print(f"Carpeta salida:      {out_dir}")
    _safe_print(f"Replicas:            {args.replicas}")
    _safe_print(f"Workers intradia:    {args.workers_intradia}")
    _safe_print(f"Replica workers:     {args.replica_workers}")
    _safe_print("=" * 76)

    # Validar inputs antes de lanzar corridas largas
    missing_inputs = [interdia_dir / f"solution_interday-{i}.xlsx" for i in range(1, args.replicas + 1) if not (interdia_dir / f"solution_interday-{i}.xlsx").exists()]
    if missing_inputs:
        preview = "\n  - ".join(str(p) for p in missing_inputs[:20])
        raise FileNotFoundError(
            "Faltan outputs del modelo interdia. No puedo correr intradia.\n"
            "Archivos faltantes:\n  - " + preview
        )

    results: List[IntradiaRunResult] = []

    with ThreadPoolExecutor(max_workers=args.replica_workers) as executor:
        futures = []
        for i in range(1, args.replicas + 1):
            futures.append(
                executor.submit(
                    run_intradia_for_replica,
                    replica=i,
                    python_exe=sys.executable,
                    script_dir=script_dir,
                    model_file=model_file,
                    interdia_dir=interdia_dir,
                    base_data=base_data,
                    out_dir=out_dir,
                    workers_intradia=args.workers_intradia,
                    all_days=args.all_days,
                    max_days=args.max_days,
                    max_iterations=args.max_iterations,
                    pricing_top_n=args.pricing_top_n,
                    gurobi_output=args.gurobi_output,
                    overwrite=args.overwrite,
                    start_day=args.start_day,
                    end_day=args.end_day,
                )
            )

        for fut in as_completed(futures):
            result = fut.result()
            results.append(result)
            _safe_print(
                f"[Replica {result.replica}] {result.status} | "
                f"returncode={result.returncode} | "
                f"tiempo={result.elapsed_seconds:.1f}s"
            )

    results.sort(key=lambda r: r.replica)
    summary_path = out_dir / "resumen_intradia_replicas.csv"
    # write_summary_csv(summary_path, results)

    n_ok = sum(1 for r in results if r.status in {"OK", "SKIPPED_EXISTS"})
    _safe_print("\n" + "=" * 76)
    _safe_print(f"Finalizado: {n_ok}/{len(results)} replicas OK o ya existentes")
    _safe_print(f"Resultados en: {out_dir}")
    _safe_print("Outputs esperados:")
    _safe_print("  solution_intradia-i.xlsx")
    _safe_print("  log_intradia-i.txt")
    _safe_print("=" * 76)

    if any(r.status == "ERROR" for r in results):
        _safe_print("\nAlgunas replicas fallaron. Revisa los log_intradia-i.txt correspondientes.")
        sys.exit(1)


if __name__ == "__main__":
    main()
