from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SensitivityScenario:
    id: str
    label: str
    arrival_multiplier: float = 1.0
    treatment_duration_multiplier: float = 1.0
    n_sillas_override: Optional[int] = None
    n_enfermeras_override: Optional[int] = None
    early_prep_cap: int = 250
    run_interdia: bool = True
    interdia_source_scenario: Optional[str] = None
    ex_post_events: bool = False
    ex_post_buffer_modules: int = 0
    ex_post_buffer_module: int = 28


SCENARIOS = [
    SensitivityScenario("S0_base", "Base"),
    SensitivityScenario("S1_demanda_110", "Demanda +10%", arrival_multiplier=1.10),
    SensitivityScenario("S2_demanda_120", "Demanda +20%", arrival_multiplier=1.20),
    SensitivityScenario("S3_sillas_14", "Una silla menos", n_sillas_override=14),
    SensitivityScenario("S4_sillas_16", "Una silla mas", n_sillas_override=16),
    SensitivityScenario(
        "S5_enfermeras_5",
        "Una enfermera mas",
        n_enfermeras_override=5,
        run_interdia=False,
        interdia_source_scenario="S0_base",
    ),
    SensitivityScenario("S6_earlycap_200", "Farmacia anticipada cap 200", early_prep_cap=200),
    SensitivityScenario("S7_duracion_110", "Tratamientos +10%", treatment_duration_multiplier=1.10),
    SensitivityScenario(
        "S8_eventos_expost",
        "Eventos clinicos ex post",
        run_interdia=False,
        interdia_source_scenario="S0_base",
        ex_post_events=True,
    ),
    SensitivityScenario(
        "S9_buffer_6",
        "Eventos ex post con buffer 6 modulos",
        run_interdia=False,
        interdia_source_scenario="S0_base",
        ex_post_events=True,
        ex_post_buffer_modules=6,
        ex_post_buffer_module=28,
    ),
]


def get_scenarios(ids: Optional[list[str]] = None) -> list[SensitivityScenario]:
    if not ids:
        return SCENARIOS
    by_id = {s.id: s for s in SCENARIOS}
    missing = [sid for sid in ids if sid not in by_id]
    if missing:
        raise ValueError(f"Escenarios desconocidos: {missing}. Disponibles: {list(by_id)}")
    return [by_id[sid] for sid in ids]

