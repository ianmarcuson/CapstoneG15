"""
Dashboard Intradía V2 — Análisis de Sensibilidad
Entrega final Capstone G15.
Pestañas: Resumen Ejecutivo | KPIs Detallados | Día Específico | IC 95% | Sensibilidad | Modelo/CG
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from pathlib import Path

st.set_page_config(
    page_title="Dashboard Intradía — Capstone G15",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded",
)

SCRIPT_DIR = Path(__file__).resolve().parent
BASE_DIR   = SCRIPT_DIR.parent / "Analisis Sensibilidad" / "resultados_intradia"

COLORS = {
    "primary": "#6366f1", "success": "#10b981", "warning": "#f59e0b",
    "danger":  "#ef4444", "info":    "#38bdf8", "purple":  "#8b5cf6",
    "slate":   "#94a3b8", "bg":      "rgba(0,0,0,0)",
}
TASK_COLORS = {
    "same_day_session":        "#6366f1",
    "pharmacy_only":           "#38bdf8",
    "treatment_only_prepared": "#10b981",
}

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
html,body,[class*="css"]{font-family:'Inter',sans-serif;}
.block-container{padding-top:1.2rem;padding-bottom:2rem;}
#MainMenu{visibility:hidden;}footer{visibility:hidden;}
[data-testid="collapsedControl"]{background-color:#18181b!important;color:#fff!important;border-radius:8px!important;opacity:1!important;padding:6px!important;box-shadow:0 2px 8px rgba(0,0,0,.4)!important;z-index:999999!important;}
[data-testid="collapsedControl"]:hover{background-color:#3f3f46!important;}
[data-testid="collapsedControl"] svg{fill:#fff!important;}
[data-testid="stSidebar"]{background:#fafafa;border-right:1px solid #e4e4e7;}
.stTabs [data-baseweb="tab-list"]{gap:4px;border-bottom:2px solid #e4e4e7;padding-bottom:0;}
.stTabs [data-baseweb="tab"]{height:44px;padding:8px 18px;font-weight:600;font-size:14px;background:transparent;border-radius:8px 8px 0 0;color:#71717a;border-bottom:3px solid transparent;}
.stTabs [aria-selected="true"]{color:#6366f1!important;border-bottom:3px solid #6366f1!important;background:#f5f3ff!important;}
[data-testid="stMetric"]{background:#fff;border:1px solid #e4e4e7;border-radius:12px;padding:16px 20px;box-shadow:0 1px 4px rgba(0,0,0,.06);}
[data-testid="stMetricLabel"]{font-size:12px;font-weight:600;color:#71717a;text-transform:uppercase;letter-spacing:.5px;}
[data-testid="stMetricValue"]{font-size:26px;font-weight:700;color:#18181b;}
.section-header{font-size:15px;font-weight:700;color:#3f3f46;border-left:4px solid #6366f1;padding-left:10px;margin:18px 0 10px;}
</style>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════
# CORE FUNCTIONS
# ═══════════════════════════════════════════════════════════

@st.cache_data(show_spinner=False)
def load_data(file_path: str):
    try:
        xls   = pd.ExcelFile(file_path)
        names = xls.sheet_names
        df_res  = xls.parse("Resumen_Dias")     if "Resumen_Dias"     in names else pd.DataFrame()
        df_prog = xls.parse("Programacion")      if "Programacion"     in names else pd.DataFrame()
        df_ocup = xls.parse("Ocupacion_Modulos") if "Ocupacion_Modulos" in names else pd.DataFrame()
        df_cg   = xls.parse("CG_Historial")      if "CG_Historial"     in names else pd.DataFrame()
        if df_prog.empty:
            return None, None, None, None
        for col, default in [
            ("task_type","same_day_session"),("pharmacy_offset",0),
            ("wait_after_pharmacy",0),("delay_days",0),("extra_chair_modules",0),
        ]:
            if col not in df_prog.columns:
                df_prog[col] = default
        for col in ["pharmacy_start","pharmacy_end","treatment_start","treatment_end","pharmacy_modules"]:
            if col not in df_prog.columns:
                df_prog[col] = np.nan
        return df_res, df_prog, df_ocup, df_cg
    except Exception as e:
        st.error(f"Error cargando datos: {e}")
        return None, None, None, None


def assign_chairs(df_prog: pd.DataFrame, n_chairs: int = 15) -> pd.DataFrame:
    if "chair_id" in df_prog.columns:
        return df_prog
    treat    = df_prog[df_prog["task_type"] != "pharmacy_only"].copy()
    no_treat = df_prog[df_prog["task_type"] == "pharmacy_only"].copy()
    no_treat["chair_id"] = np.nan
    rows = []
    for day, ddf in treat.groupby("day"):
        ddf  = ddf.sort_values("treatment_start")
        free = {c: 0.0 for c in range(1, n_chairs + 1)}
        for _, r in ddf.iterrows():
            d  = r.to_dict()
            ts = float(r["treatment_start"]) if not pd.isna(r["treatment_start"]) else 0.0
            tm = float(r["treatment_modules"]) if not pd.isna(r["treatment_modules"]) else 0.0
            ok = False
            for c in range(1, n_chairs + 1):
                if free[c] <= ts:
                    d["chair_id"] = c
                    free[c] = ts + tm
                    ok = True
                    break
            if not ok:
                d["chair_id"] = n_chairs + 1
            rows.append(d)
    combined = pd.concat([pd.DataFrame(rows), no_treat], ignore_index=True)
    return combined.sort_values(["day", "treatment_start"]).reset_index(drop=True)


def _nurse_col(df_ocup: pd.DataFrame) -> pd.Series:
    if df_ocup is None or df_ocup.empty:
        return pd.Series(dtype=float)
    if "nurse_events" in df_ocup.columns:
        return df_ocup["nurse_events"]
    if "nurse_starts" in df_ocup.columns:
        base = df_ocup["nurse_starts"]
        return base + df_ocup["nurse_ends"] if "nurse_ends" in df_ocup.columns else base
    return pd.Series(dtype=float)


def compute_kpis(df_prog, df_ocup, df_res=None) -> dict:
    if df_prog is None or df_prog.empty:
        return {}
    treat = df_prog[df_prog["task_type"] != "pharmacy_only"]
    total = len(treat)

    s_day = treat.groupby("day").size()
    u_day = treat.groupby("day")["patient_id"].nunique()
    ch_day = df_ocup.groupby("day")["chairs_used"].sum() / df_ocup.groupby("day")["chair_capacity"].sum() * 100
    reg_oc = df_ocup[df_ocup["is_extra"] == 0]
    ch_reg_day = reg_oc.groupby("day")["chairs_used"].sum() / reg_oc.groupby("day")["chair_capacity"].sum() * 100 if not reg_oc.empty else pd.Series(0, index=df_ocup["day"].unique())
    n_col = _nurse_col(df_ocup)
    nu_day = df_ocup.groupby("day")[n_col.name].sum() / df_ocup.groupby("day")["nurse_capacity"].sum() * 100
    ph_ops = df_ocup[df_ocup["module"] <= 20]
    ph_day = ph_ops.groupby("day")["pharmacy_used"].sum() / ph_ops.groupby("day")["pharmacy_capacity"].sum() * 100 if not ph_ops.empty else pd.Series(0, index=df_ocup["day"].unique())

    cumpl_day = treat.groupby("day").apply(lambda x: (x["treatment_end"] <= 47).sum() / len(x) * 100 if len(x) > 0 else 0)
    
    perc_ant_day = (treat[treat["task_type"] == "treatment_only_prepared"].groupby("day").size() / treat.groupby("day").size() * 100).fillna(0)
    perc_ant_tot = len(treat[treat["task_type"] == "treatment_only_prepared"]) / len(treat) * 100 if len(treat) > 0 else 0
    extra_day = df_prog.groupby("day")["extra_chair_modules"].sum()


    treat = df_prog[df_prog["task_type"] != "pharmacy_only"]
    total = len(treat)
    cumpl  = (treat["treatment_end"] <= 47).sum() / total * 100 if total > 0 else 0
    espera_pharm = (treat["treatment_start"] - treat["pharmacy_end"]).clip(lower=0)
    inicio_trat = treat["treatment_start"]

    n_col     = _nurse_col(df_ocup)
    total_cc  = df_ocup["chair_capacity"].sum() if not df_ocup.empty else 0
    util_ch   = df_ocup["chairs_used"].sum() / total_cc * 100 if total_cc > 0 else 0
    reg       = df_ocup[df_ocup["is_extra"] == 0] if not df_ocup.empty else pd.DataFrame()
    util_chr  = reg["chairs_used"].sum() / reg["chair_capacity"].sum() * 100 if not reg.empty and reg["chair_capacity"].sum() > 0 else 0
    nurse_u   = n_col.sum() if not df_ocup.empty else 0
    nurse_c   = df_ocup["nurse_capacity"].sum() if not df_ocup.empty else 0
    util_nu   = nurse_u / nurse_c * 100 if nurse_c > 0 else 0
    ph_ops    = df_ocup[df_ocup["module"] <= 20] if not df_ocup.empty else pd.DataFrame()
    util_ph   = ph_ops["pharmacy_used"].sum() / ph_ops["pharmacy_capacity"].sum() * 100 if not ph_ops.empty and ph_ops["pharmacy_capacity"].sum() > 0 else 0

    runtime = df_res["runtime_final_master"].sum() if df_res is not None and "runtime_final_master" in df_res.columns else 0
    tw      = df_prog["wait_after_pharmacy"].sum()  if "wait_after_pharmacy" in df_prog.columns else 0
    ml      = treat.groupby("day")["treatment_modules"].sum().idxmax() if total > 0 else None

    return {
        "sessions": total, "unique_patients": treat["patient_id"].nunique() if total > 0 else 0,
        "cumplimiento": cumpl, "total_extra": int(df_prog["extra_chair_modules"].sum()),
        "days_extra": int((df_prog.groupby("day")["extra_chair_modules"].sum() > 0).sum()),
        "max_wait_pharm": float(espera_pharm.max()) if total > 0 else 0,
        "avg_wait_pharm": float(espera_pharm.mean()) if total > 0 else 0,
        "max_start_time": float(inicio_trat.max()) if total > 0 else 0,
        "avg_start_time": float(inicio_trat.mean()) if total > 0 else 0,
        "total_wait_pharm": float(tw),
        "util_chairs": util_ch, "util_chairs_reg": util_chr,
        "util_nurses": util_nu, "util_pharm": util_ph,
        "most_loaded_day": ml, "runtime_total": float(runtime),
        "s_day": s_day, "u_day": u_day, "ch_day": ch_day, "ch_reg_day": ch_reg_day,
        "nu_day": nu_day, "ph_day": ph_day, "cumpl_day": cumpl_day, "extra_day": extra_day, "perc_ant_tot": perc_ant_tot, "perc_ant_day": perc_ant_day,
    }


def get_critical_days(df_prog, df_ocup):
    if df_prog is None or df_prog.empty:
        return []
    ed = df_prog[df_prog["extra_chair_modules"] > 0]["day"].unique()
    wd = df_prog[df_prog["treatment_start"] > 20]["day"].unique()
    if df_ocup is None or df_ocup.empty:
        return list(set(ed) | set(wd))
    cc = df_ocup[df_ocup["chairs_used"] == df_ocup["chair_capacity"]]["day"].unique()
    ns = _nurse_col(df_ocup)
    nc = df_ocup[ns == df_ocup["nurse_capacity"]]["day"].unique() if not ns.empty else []
    pc = df_ocup[df_ocup["pharmacy_used"] == df_ocup["pharmacy_capacity"]]["day"].unique()
    return list(set(ed) | set(wd) | set(cc) | set(nc) | set(pc))


# ═══════════════════════════════════════════════════════════
# RUTAS
# ═══════════════════════════════════════════════════════════
DEFAULT_PATHS = [
    BASE_DIR / "S0_base" / "solution_intradia-1.xlsx",
    SCRIPT_DIR / "solution_intradia-1.xlsx",
    SCRIPT_DIR / "test-240.xlsx",
]
HEURISTIC_PATHS = [
    SCRIPT_DIR / "solution_heuristica_450.xlsx",
    SCRIPT_DIR / "solution_heuristica.xlsx",
]
REPLICAS_PATHS = [
    BASE_DIR / "S0_base",
    SCRIPT_DIR / "resultados_intradia_30_replicas",
    SCRIPT_DIR.parent / "Modelo INTRAdia V2" / "resultados_intradia_30_replicas",
]
HEUR_MAX_DAY = 450

def _metric_card(col, label, main_val, s_series=None, fmt_main="{}", fmt_sub="{}", is_time=False):
    if s_series is not None and not s_series.empty:
        sub_val = f"Mín: {fmt_sub.format(s_series.min())} | Med: {fmt_sub.format(s_series.median())} | Máx: {fmt_sub.format(s_series.max())}"
    else:
        sub_val = " "
    html = f"""
    <div style='background-color: white; padding: 15px; border-radius: 8px; border: 1px solid #e0e0e0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 10px; height: 115px;'>
        <div style='color: #666; font-size: 13px; font-weight: 600; margin-bottom: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;'>{label}</div>
        <div style='color: #111; font-size: 24px; font-weight: bold; margin-bottom: 2px;'>{fmt_main.format(main_val)}</div>
        <div style='color: #888; font-size: 11px;'>{sub_val}</div>
    </div>
    """
    col.markdown(html, unsafe_allow_html=True)

def _metric_time(col, label, avg_val, min_val, max_val):
    sub_val = f"Mín: {min_val:.0f} | Máx: {max_val:.0f}"
    html = f"""
    <div style='background-color: white; padding: 15px; border-radius: 8px; border: 1px solid #e0e0e0; box-shadow: 0 1px 3px rgba(0,0,0,0.05); margin-bottom: 10px; height: 115px;'>
        <div style='color: #666; font-size: 13px; font-weight: 600; margin-bottom: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;'>{label}</div>
        <div style='color: #111; font-size: 24px; font-weight: bold; margin-bottom: 2px;'>{avg_val:.2f} mód</div>
        <div style='color: #888; font-size: 11px;'>{sub_val}</div>
    </div>
    """
    col.markdown(html, unsafe_allow_html=True)


# ═══════════════════════════════════════════════════════════
# SIDEBAR — Carga de archivo
# ═══════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## 🏥 Capstone G15")
    st.markdown("**Dashboard Intradía V2**")
    st.markdown("---")
    uploaded = st.file_uploader("📂 Cargar Excel (solución)", type=["xlsx"])
    file_to_load = None
    source_label = ""
    if uploaded:
        file_to_load = uploaded
        source_label = f"📎 {uploaded.name}"
    else:
        for p in DEFAULT_PATHS:
            if Path(p).exists():
                file_to_load = str(p)
                source_label = f"📁 {Path(p).name}"
                break
    if file_to_load is None:
        st.error("No se encontró el archivo base. Carga uno manualmente.")
        st.stop()
    st.caption(f"Fuente: {source_label}")
    st.markdown("---")

# Carga de datos
df_res_raw, df_prog_raw, df_ocup_raw, df_cg_raw = load_data(
    file_to_load if isinstance(file_to_load, str) else file_to_load
)
if df_prog_raw is None:
    st.error("Error al cargar el archivo. Verifica que tenga la hoja 'Programacion'.")
    st.stop()

df_prog_raw = assign_chairs(df_prog_raw)

# Heurística base (días 0–240)
df_prog_heur, df_ocup_heur, df_res_heur = None, None, None
for p in HEURISTIC_PATHS:
    if Path(p).exists():
        _, dph, doh, _ = load_data(str(p))
        if dph is not None:
            df_prog_heur = assign_chairs(dph)
            df_ocup_heur = doh
            df_res_heur  = _
        break

with st.sidebar:
    min_d = int(df_prog_raw["day"].min())
    max_d = int(df_prog_raw["day"].max())
    st.markdown("### 📅 Período")
    c1, c2 = st.columns(2)
    start_d = c1.number_input("Día Inicio", min_value=min_d, max_value=max_d, value=min_d)
    end_d   = c2.number_input("Día Fin",    min_value=min_d, max_value=max_d, value=max_d)
    if start_d > end_d:
        st.error("Inicio > Fin"); st.stop()

    st.markdown("### 🎯 Día Específico")
    valid_days_all = sorted([d for d in df_prog_raw["day"].unique() if start_d <= d <= end_d])
    day_opts = [f"Día {d}" for d in valid_days_all]
    if not day_opts:
        st.warning("Sin datos en el rango."); st.stop()
    sel_day_str  = st.selectbox("Selecciona", day_opts)
    selected_day = int(sel_day_str.split()[1])

    with st.expander("⚙️ Filtros avanzados"):
        patient_types = sorted(df_prog_raw["patient_type"].unique())
        sel_types = st.multiselect("Tipos de paciente", patient_types, default=patient_types)
        task_types_all = sorted(df_prog_raw["task_type"].unique())
        sel_tasks  = st.multiselect("Tipo de tarea", task_types_all, default=task_types_all)
        show_extra    = st.checkbox("Solo sesiones con módulos extra")
        show_critical = st.checkbox("Solo días críticos")

# ─── Filtrado global ─────────────────────────────────────────────────────────
df_prog = df_prog_raw[
    (df_prog_raw["day"] >= start_d) & (df_prog_raw["day"] <= end_d) &
    df_prog_raw["patient_type"].isin(sel_types) & df_prog_raw["task_type"].isin(sel_tasks)
].copy()
df_ocup = df_ocup_raw[(df_ocup_raw["day"] >= start_d) & (df_ocup_raw["day"] <= end_d)].copy() \
          if df_ocup_raw is not None else pd.DataFrame()

if show_extra:
    df_prog = df_prog[df_prog["extra_chair_modules"] > 0]
if show_critical:
    crit = get_critical_days(df_prog_raw, df_ocup_raw)
    df_prog = df_prog[df_prog["day"].isin(crit)]
    df_ocup = df_ocup[df_ocup["day"].isin(crit)]
if df_prog.empty:
    st.warning("Sin datos en los filtros seleccionados."); st.stop()

kpis = compute_kpis(df_prog, df_ocup, df_res_raw)

end_h = min(int(end_d), HEUR_MAX_DAY)
kpis_h = (
    compute_kpis(
        df_prog_heur[(df_prog_heur["day"] >= start_d) & (df_prog_heur["day"] <= end_h)],
        df_ocup_heur[(df_ocup_heur["day"] >= start_d) & (df_ocup_heur["day"] <= end_h)],
        df_res_heur,
    ) if df_prog_heur is not None else None
)

# ═══════════════════════════════════════════════════════════
# HEADER
# ═══════════════════════════════════════════════════════════
st.markdown(
    f"# 🏥 Planificación Intradía — Capstone G15\n"
    f"<p style='color:#71717a;font-size:14px;margin-top:-10px'>"
    f"Período: Día {start_d}–{end_d} &nbsp;|&nbsp; "
    f"{df_prog['day'].nunique()} días &nbsp;|&nbsp; "
    f"{kpis.get('sessions', 0):,} sesiones &nbsp;|&nbsp; "
    f"{kpis.get('unique_patients', 0):,} pacientes</p>",
    unsafe_allow_html=True,
)
st.markdown("---")

# ═══════════════════════════════════════════════════════════
# TABS
# ═══════════════════════════════════════════════════════════
tab_res, tab_kpi, tab_dia, tab_ic, tab_sens, tab_cg = st.tabs([
    "📊 Resumen Ejecutivo", "📋 KPIs Detallados", "📅 Día Específico",
    "📈 IC 95%", "🔬 Sensibilidad", "⚙️ Modelo / CG",
])

# ─────────────────────────────────────────────────────────────────────────────
# TAB 1 — RESUMEN EJECUTIVO
# ─────────────────────────────────────────────────────────────────────────────
with tab_res:
    st.markdown("<br>", unsafe_allow_html=True)
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Sesiones",         f"{kpis['sessions']:,}")
    c2.metric("Pacientes Únicos", f"{kpis['unique_patients']:,}")
    c3.metric("Cumpl. Horario",   f"{kpis['cumplimiento']:.1f}%")
    _metric_time(c4, "Espera Real (Prom)", kpis.get("avg_wait_pharm", 0), 0, kpis.get("max_wait_pharm", 0))
    c5.metric("Módulos Extra",    f"{kpis['total_extra']:,}")
    c6.metric("Días con Extra",   f"{kpis['days_extra']}")
    st.markdown("<br>", unsafe_allow_html=True)

    st.markdown('<div class="section-header">Carga diaria del período</div>', unsafe_allow_html=True)
    treat_only = df_prog[df_prog["task_type"] != "pharmacy_only"]
    daily = treat_only.groupby("day").agg(
        Tratamiento=("treatment_modules", "sum"),
        Extra=("extra_chair_modules", "sum"),
        Sesiones=("patient_id", "count"),
    ).reset_index()

    fig_main = go.Figure()
    fig_main.add_trace(go.Bar(x=daily["day"], y=daily["Tratamiento"], name="Tratamiento",
                              marker_color=COLORS["primary"], opacity=.85))
    fig_main.add_trace(go.Bar(x=daily["day"], y=daily["Extra"], name="Extra",
                              marker_color=COLORS["warning"], opacity=.9))
    fig_main.add_trace(go.Scatter(x=daily["day"], y=daily["Sesiones"], name="Sesiones",
                                  mode="lines+markers", yaxis="y2",
                                  line=dict(color=COLORS["success"], width=2), marker=dict(size=3)))
    if not df_ocup.empty:
        lim_reg = df_ocup[df_ocup["is_extra"] == 0].groupby("day")["chair_capacity"].sum().max()
        lim_max = df_ocup.groupby("day")["chair_capacity"].sum().max()
        fig_main.add_trace(go.Scatter(x=daily["day"], y=[lim_reg] * len(daily), name="Límite Regular",
                                      mode="lines", line=dict(color=COLORS["danger"], dash="dash", width=1.5)))
        fig_main.add_trace(go.Scatter(x=daily["day"], y=[lim_max] * len(daily), name="Límite Máx",
                                      mode="lines", line=dict(color="#7f1d1d", dash="dot", width=1.5)))
    for d in range(int(start_d), int(end_d) + 1, 5):
        fig_main.add_vline(x=d, line_width=0.5, line_color="#e4e4e7")
    fig_main.update_layout(
        barmode="stack", plot_bgcolor=COLORS["bg"], paper_bgcolor=COLORS["bg"],
        xaxis=dict(title="Día", gridcolor="#f4f4f5"),
        yaxis=dict(title="Módulos", gridcolor="#f4f4f5"),
        yaxis2=dict(title="Sesiones", overlaying="y", side="right", showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=60, r=60, t=40, b=40), height=340,
    )
    st.plotly_chart(fig_main, width="stretch")

    st.markdown('<div class="section-header">💡 Lectura rápida</div>', unsafe_allow_html=True)
    insights = []
    if kpis["total_extra"] == 0:
        insights.append("✅ No se usaron módulos extraordinarios en el período.")
    else:
        insights.append(f"⚠️ Se usaron **{kpis['total_extra']:,}** módulos extra en **{kpis['days_extra']}** días.")
    if kpis["cumplimiento"] >= 95:
        insights.append(f"✅ Excelente cumplimiento del horario regular ({kpis['cumplimiento']:.1f}%).")
    else:
        insights.append(f"⚠️ Cumplimiento del horario regular: **{kpis['cumplimiento']:.1f}%**.")
    if kpis["max_wait_pharm"] > 6:
        insights.append(f"⚠️ Espera intradía alta (máx: **{kpis['max_wait_pharm']:.0f}** módulos).")
    else:
        insights.append(f"✅ Espera intradía controlada (máx: **{kpis['max_wait_pharm']:.0f}** módulos).")
    ru = max(
        {"Sillas": kpis["util_chairs"], "Enfermería": kpis["util_nurses"], "Farmacia": kpis["util_pharm"]}.items(),
        key=lambda x: x[1]
    )
    insights.append(f"📊 Recurso más utilizado: **{ru[0]}** ({ru[1]:.1f}%).")
    if kpis.get("most_loaded_day") is not None:
        insights.append(f"📅 Día más cargado: **Día {int(kpis['most_loaded_day'])}**.")
    for ins in insights:
        st.markdown(f"- {ins}")

    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown('<div class="section-header">🔴 Top 5 Días Críticos</div>', unsafe_allow_html=True)
    crit_stats = treat_only.groupby("day").agg(
        Sesiones=("patient_id", "count"), Mód_Trat=("treatment_modules", "sum"),
        Mód_Extra=("extra_chair_modules", "sum"), Espera_Max=("wait_after_pharmacy", "max"),
    ).reset_index()
    if not df_ocup.empty:
        oc2 = df_ocup.copy()
        oc2["n_comp"] = _nurse_col(df_ocup)
        crit_ocup = oc2.groupby("day").agg(
            Peak_Sillas=("chairs_used", "max"),
            Peak_Enferm=("n_comp", "max"),
            Peak_Farm=("pharmacy_used", "max"),
        ).reset_index()
        crit_df = crit_stats.merge(crit_ocup, on="day", how="left")
    else:
        crit_df = crit_stats.copy()
    crit_df = crit_df.sort_values(["Mód_Extra", "Mód_Trat", "Espera_Max"], ascending=False).head(5).reset_index(drop=True)
    crit_df.insert(0, "Día Cal.", crit_df["day"] + 1)
    st.dataframe(crit_df, width="stretch", hide_index=True)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 2 — KPIs DETALLADOS
# ─────────────────────────────────────────────────────────────────────────────
with tab_kpi:
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### Indicadores de Desempeño Operacional")
    st.caption("Cumplimiento y espera excluyen tareas `pharmacy_only` (sin tratamiento en silla).")
    st.markdown("<br>", unsafe_allow_html=True)

    modo = "Solo Modelo Real"
    if kpis_h is not None:
        lbl_h = f"Heurística (días {start_d}–{end_h})"
        modo  = st.radio("Modo de visualización",
                         ["Solo Modelo Real", f"Solo {lbl_h}", f"Comparación vs {lbl_h}"],
                         horizontal=True)
        st.markdown("<br>", unsafe_allow_html=True)

    def _metric(col, label, key, fmt="{}", inverse=False):
        vr = kpis.get(key, 0)
        vh = kpis_h.get(key, 0) if kpis_h else 0
        vr_s = fmt.format(vr) if vr is not None else "N/A"
        vh_s = fmt.format(vh) if vh is not None else "N/A"
        if kpis_h and "Heurística" in modo and "Solo" in modo:
            col.metric(label, vh_s)
        elif kpis_h and "Comparación" in modo:
            if isinstance(vr, (int, float)) and isinstance(vh, (int, float)):
                delta = vr - vh
                col.metric(label, vr_s, delta=f"{delta:+.1f}", delta_color="inverse" if inverse else "normal")
            else:
                col.metric(label, vr_s)
        else:
            col.metric(label, vr_s)

    st.markdown('<div class="section-header">1. Demanda y Flujo</div>', unsafe_allow_html=True)
    c1, c2, c3, c4 = st.columns(4)
    _metric_card(c1, "Sesiones (Total)", kpis.get("sessions", 0), kpis.get("s_day", pd.Series()), "{:,.0f}", "{:.0f}")
    _metric_card(c2, "Pacientes (Total)", kpis.get("unique_patients", 0), kpis.get("u_day", pd.Series()), "{:,.0f}", "{:.0f}")
    _metric_card(c3, "Cumpl. Jornada", kpis.get("cumplimiento", 0), kpis.get("cumpl_day", pd.Series()), "{:.1f}%", "{:.0f}%")
    _metric(c4, "Día Más Cargado", "most_loaded_day", "Día {:.0f}", inverse=True)

    st.markdown('<div class="section-header">2. Espera Intradía (Farmacia → Tratamiento)</div>', unsafe_allow_html=True)
    st.caption("Módulos entre pharmacy_end y treatment_start, clippeados a 0.")
    c5, c6, c7 = st.columns(3)
    _metric_time(c5, "Espera Máxima", kpis.get("avg_wait_pharm", 0), 0, kpis.get("max_wait_pharm", 0))
    _metric_time(c6, "Inicio (Desde Llegada)", kpis.get("avg_start_time", 0), 0, kpis.get("max_start_time", 0))
    _metric_card(c7, "Módulos Extra (Total)", kpis.get("total_extra", 0), kpis.get("extra_day", pd.Series()), "{:,.0f}", "{:.0f}")

    st.markdown('<div class="section-header">3. Utilización de Recursos</div>', unsafe_allow_html=True)
    c8, c9, c10, c11 = st.columns(4)
    _metric_card(c8,  "Util. Sillas (Total)", kpis.get("util_chairs", 0), kpis.get("ch_day", pd.Series()), "{:.1f}%", "{:.0f}%")
    _metric_card(c9,  "Util. Sillas (Regular)", kpis.get("util_chairs_reg", 0), kpis.get("ch_reg_day", pd.Series()), "{:.1f}%", "{:.0f}%")
    _metric_card(c10, "Ocup. Enfermería", kpis.get("util_nurses", 0), kpis.get("nu_day", pd.Series()), "{:.1f}%", "{:.0f}%")
    _metric_card(c11, "Ocup. Farmacia (mód≤20)", kpis.get("util_pharm", 0), kpis.get("ph_day", pd.Series()), "{:.1f}%", "{:.0f}%")

    st.markdown('<div class="section-header">4. Estrategia de Farmacia</div>', unsafe_allow_html=True)
    st.caption("Porcentaje de remedios preparados de forma anticipada (el día anterior).")
    c12, _, _ = st.columns(3)
    _metric_card(c12, "Farmacia Anticipada (%)", kpis.get("perc_ant_tot", 0), kpis.get("perc_ant_day", pd.Series()), "{:.1f}%", "{:.0f}%")

    st.markdown('<div class="section-header">5. Saturación Extraordinaria</div>', unsafe_allow_html=True)


    td = df_prog[df_prog["task_type"] != "pharmacy_only"].copy()
    td["espera_real"] = (td["treatment_start"] - td["pharmacy_end"]).clip(lower=0)
    fig_box = px.box(td, x="patient_type", y="espera_real", color="patient_type",
                     color_discrete_sequence=px.colors.qualitative.Bold,
                     labels={"patient_type": "Tipo de Paciente", "espera_real": "Espera (módulos)"})
    fig_box.update_layout(showlegend=False, plot_bgcolor=COLORS["bg"], height=300)
    st.plotly_chart(fig_box, width="stretch")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 3 — DÍA ESPECÍFICO
# ─────────────────────────────────────────────────────────────────────────────
with tab_dia:
    treat_today = df_prog[(df_prog["day"] == selected_day) & (df_prog["task_type"] != "pharmacy_only")]
    if "pharmacy_day" in df_prog_raw.columns:
        pharm_today = df_prog_raw[(df_prog_raw["pharmacy_day"] == selected_day) & (df_prog_raw["task_type"] == "pharmacy_only")]
    else:
        pharm_today = df_prog[(df_prog["day"] == selected_day) & (df_prog["task_type"] == "pharmacy_only")]
    day_prog = pd.concat([treat_today, pharm_today])
    day_ocup = df_ocup[df_ocup["day"] == selected_day].copy() if not df_ocup.empty else pd.DataFrame()

    if day_prog.empty:
        st.info(f"Sin datos para el Día {selected_day}.")
    else:
        st.markdown("<br>", unsafe_allow_html=True)
        if not day_ocup.empty:
            day_ocup = day_ocup.copy()
            day_ocup["n_comp"] = _nurse_col(day_ocup)

        treat_day = day_prog[day_prog["task_type"] != "pharmacy_only"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Sesiones (tratamiento)", len(treat_day))
        c2.metric("Pacientes Únicos", day_prog["patient_id"].nunique())
        c3.metric("Módulos Tratamiento", int(treat_day["treatment_modules"].sum()))
        c4.metric("Módulos Extra", int(day_prog["extra_chair_modules"].sum()))

        espera_day = (treat_day["treatment_start"] - treat_day["pharmacy_end"]).clip(lower=0)
        c5, c6, c7, c8 = st.columns(4)
        c5.metric("Espera Máxima",  f"{espera_day.max():.0f} mód" if not espera_day.empty else "–")
        c6.metric("Peak Sillas",    int(day_ocup["chairs_used"].max())    if not day_ocup.empty else "–")
        c7.metric("Peak Enfermería",int(day_ocup["n_comp"].max())         if not day_ocup.empty and "n_comp" in day_ocup.columns else "–")
        c8.metric("Peak Farmacia",  int(day_ocup["pharmacy_used"].max())  if not day_ocup.empty else "–")

        fa_pct = (day_prog["task_type"] == "treatment_only_prepared").sum() / len(day_prog) * 100
        if fa_pct > 0:
            st.info(f"ℹ️ **{fa_pct:.0f}%** de las sesiones usan farmacia preparada el día anterior.")

        st.markdown("<br>", unsafe_allow_html=True)
        t_sillas, t_pacs, t_recs = st.tabs(["🪑 Gantt Sillas", "👥 Línea de Tiempo Pacientes", "⚙️ Ocupación Recursos"])

        with t_sillas:
            fig_g = go.Figure()
            colors_pat = px.colors.qualitative.Alphabet + px.colors.qualitative.Dark24 + px.colors.qualitative.Light24
            for _, r in treat_day.iterrows():
                hover = (f"Paciente: {r['patient_id']} | Tipo: {r['patient_type']}<br>"
                         f"Tarea: {r['task_type']}<br>"
                         f"Farmacia: {r['pharmacy_start']} – {r['pharmacy_end']}<br>"
                         f"Tratamiento: {r['treatment_start']} – {r['treatment_end']}<br>"
                         f"Espera: {max(0, (r['treatment_start'] or 0) - (r['pharmacy_end'] or 0)):.0f} mód | Extra: {r['extra_chair_modules']}")
                bc  = colors_pat[int(r["patient_id"]) % len(colors_pat)]
                chl = f"Silla {int(r['chair_id'])}" if not pd.isna(r.get("chair_id")) else "—"
                fig_g.add_trace(go.Bar(
                    x=[r["treatment_modules"]], y=[chl], base=[r["treatment_start"]],
                    orientation="h", marker_color=bc, marker_line=dict(color="white", width=1),
                    name=r["task_type"], hoverinfo="text", hovertext=hover,
                    text=f"P{r['patient_id']}", textposition="inside", showlegend=False,
                ))
            for tt, tc in TASK_COLORS.items():
                fig_g.add_trace(go.Bar(x=[0], y=["Silla 1"], base=[0], orientation="h",
                                       marker_color=tc, name=tt, showlegend=True, visible="legendonly"))
            fig_g.add_vline(x=48, line_width=2, line_dash="dash", line_color=COLORS["danger"],
                            annotation_text="Jornada Extra", annotation_position="top right")
            fig_g.update_layout(
                barmode="stack", showlegend=True,
                xaxis=dict(title="Módulo", range=[0, 56], dtick=4, gridcolor="#f4f4f5"),
                yaxis=dict(type="category", categoryorder="array",
                           categoryarray=[f"Silla {i}" for i in range(15, 0, -1)]),
                plot_bgcolor=COLORS["bg"], height=420,
                legend=dict(orientation="h", y=-0.2),
            )
            st.plotly_chart(fig_g, width="stretch")

        with t_pacs:
            fig_p = go.Figure()
            dps = day_prog.sort_values("treatment_start", ascending=False)
            ph_x, ph_y, ph_b, ph_h = [], [], [], []
            ph_ant_x, ph_ant_y, ph_ant_b, ph_ant_h = [], [], [], []
            wt_x, wt_y, wt_b, wt_h = [], [], [], []
            tr_x, tr_y, tr_b, tr_h = [], [], [], []
            tr_ant_x, tr_ant_y, tr_ant_b, tr_ant_h = [], [], [], []

            for _, r in dps.iterrows():
                pid = f"P{r['patient_id']}"
                hov = f"Pac:{r['patient_id']}|Tipo:{r['patient_type']}<br>Tarea:{r['task_type']}"
                pm  = r.get("pharmacy_modules") or 0
                if pm > 0:
                    if r["task_type"] == "pharmacy_only":
                        ph_ant_x.append(pm); ph_ant_y.append(pid); ph_ant_b.append(r["pharmacy_start"]); ph_ant_h.append(hov)
                    else:
                        ph_x.append(pm); ph_y.append(pid); ph_b.append(r["pharmacy_start"]); ph_h.append(hov)
                
                # Wait time
                if r["task_type"] != "pharmacy_only" and pd.notna(r["pharmacy_end"]):
                    w = max(0, (r["treatment_start"] or 0) - (r["pharmacy_end"] or 0))
                    if w > 0:
                        wt_x.append(w); wt_y.append(pid); wt_b.append(r["pharmacy_end"]); wt_h.append(hov)
                
                tm = r.get("treatment_modules") or 0
                if tm > 0:
                    if r["task_type"] == "treatment_only_prepared":
                        tr_ant_x.append(tm); tr_ant_y.append(pid); tr_ant_b.append(r["treatment_start"]); tr_ant_h.append(hov)
                    else:
                        tr_x.append(tm); tr_y.append(pid); tr_b.append(r["treatment_start"]); tr_h.append(hov)

            if ph_x: fig_p.add_trace(go.Bar(x=ph_x, y=ph_y, base=ph_b, orientation="h", name="Farmacia (Hoy)",
                                             marker_color="#0ea5e9", hovertext=ph_h, hoverinfo="text"))
            if ph_ant_x: fig_p.add_trace(go.Bar(x=ph_ant_x, y=ph_ant_y, base=ph_ant_b, orientation="h", name="Farmacia (Anticipada)",
                                             marker_color="#f59e0b", hovertext=ph_ant_h, hoverinfo="text"))
            if wt_x: fig_p.add_trace(go.Bar(x=wt_x, y=wt_y, base=wt_b, orientation="h", name="Espera",
                                             marker_color="#ef4444", hovertext=wt_h, hoverinfo="text"))
            if tr_x: fig_p.add_trace(go.Bar(x=tr_x, y=tr_y, base=tr_b, orientation="h", name="Tratamiento",
                                             marker_color="#10b981", hovertext=tr_h, hoverinfo="text"))
            if tr_ant_x: fig_p.add_trace(go.Bar(x=tr_ant_x, y=tr_ant_y, base=tr_ant_b, orientation="h", name="Tratamiento (Droga Lista)",
                                             marker_color="#14b8a6", hovertext=tr_ant_h, hoverinfo="text"))
            
            fig_p.add_vline(x=48, line_width=2, line_dash="dash", line_color=COLORS["danger"])
            fig_p.update_layout(
                barmode="stack",
                xaxis=dict(title="Módulo", range=[0, 56], dtick=4, gridcolor="#f4f4f5"),
                yaxis=dict(type="category"),
                plot_bgcolor=COLORS["bg"], height=max(300, len(day_prog) * 14),
                legend=dict(orientation="h", y=-0.15),
            )
            st.plotly_chart(fig_p, width="stretch")

        with t_recs:
            if day_ocup.empty:
                st.info("Sin datos de ocupación para este día.")
            else:
                fig_r3 = go.Figure()
                fig_r3.add_trace(go.Bar(x=day_ocup["module"], y=day_ocup["chairs_used"],
                                        name="Sillas", marker_color=COLORS["primary"]))
                fig_r3.add_trace(go.Scatter(x=day_ocup["module"], y=day_ocup["chair_capacity"],
                                            name="Cap Sillas", mode="lines",
                                            line=dict(dash="dash", color=COLORS["primary"], width=1.5)))
                if "n_comp" in day_ocup.columns:
                    fig_r3.add_trace(go.Bar(x=day_ocup["module"], y=day_ocup["n_comp"],
                                            name="Enfermería", marker_color=COLORS["purple"]))
                    fig_r3.add_trace(go.Scatter(x=day_ocup["module"], y=day_ocup["nurse_capacity"],
                                                name="Cap Enfermería", mode="lines",
                                                line=dict(dash="dash", color=COLORS["purple"], width=1.5)))
                fig_r3.add_trace(go.Bar(x=day_ocup["module"], y=day_ocup["pharmacy_used"],
                                        name="Farmacia", marker_color=COLORS["info"]))
                fig_r3.add_trace(go.Scatter(x=day_ocup["module"], y=day_ocup["pharmacy_capacity"],
                                            name="Cap Farmacia", mode="lines",
                                            line=dict(dash="dash", color=COLORS["info"], width=1.5)))
                fig_r3.add_vline(x=48, line_width=2, line_dash="dash", line_color=COLORS["danger"])
                fig_r3.update_layout(
                    barmode="group", plot_bgcolor=COLORS["bg"], height=340,
                    xaxis=dict(title="Módulo", gridcolor="#f4f4f5"),
                    yaxis=dict(title="Unidades", gridcolor="#f4f4f5"),
                )
                st.plotly_chart(fig_r3, width="stretch")

                # --- NUEVA GRÁFICA: Farmacia Detallada ---
                if "pharmacy_day" in df_prog_raw.columns:
                    df_prog_ph = df_prog_raw[df_prog_raw["pharmacy_day"] == selected_day].copy()
                else:
                    df_prog_ph = df_prog[df_prog['day'] == selected_day].copy()
                pharm_hoy = [0] * len(day_ocup)
                pharm_ant = [0] * len(day_ocup)
                for _, row in df_prog_ph.iterrows():
                    if row["pharmacy_modules"] > 0 and pd.notna(row["pharmacy_start"]):
                        s_m = int(row["pharmacy_start"])
                        e_m = int(row["pharmacy_end"])
                        for m in range(s_m, e_m + 1):
                            if m < len(day_ocup):
                                if row.get("task_type") == "pharmacy_only":
                                    pharm_ant[m] += 1
                                else:
                                    pharm_hoy[m] += 1

                st.markdown('<br><div class="section-header">Ocupación Detallada de Farmacia</div>', unsafe_allow_html=True)
                fig_ph = go.Figure()
                fig_ph.add_trace(go.Bar(x=day_ocup["module"], y=pharm_hoy, name="Preparaciones del Día", marker_color="#0ea5e9")) # info
                fig_ph.add_trace(go.Bar(x=day_ocup["module"], y=pharm_ant, name="Preparaciones Anticipadas", marker_color="#f59e0b")) # warning/orange
                fig_ph.add_trace(go.Scatter(x=day_ocup["module"], y=day_ocup["pharmacy_capacity"],
                                            name="Capacidad Farmacia", mode="lines",
                                            line=dict(dash="dash", color="#ef4444", width=2))) # danger
                fig_ph.update_layout(
                    barmode="stack", plot_bgcolor=COLORS["bg"], height=280,
                    xaxis=dict(title="Módulo", range=[0, 25], dtick=5, gridcolor="#f4f4f5"),
                    yaxis=dict(title="Drogas Preparando", gridcolor="#f4f4f5"),
                    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
                )
                st.plotly_chart(fig_ph, width="stretch")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 4 — IC 95%
# ─────────────────────────────────────────────────────────────────────────────
with tab_ic:
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### Intervalos de Confianza al 95% — 30 Réplicas")

    replicas_folder = None
    for rp in REPLICAS_PATHS:
        if Path(rp).exists():
            replicas_folder = Path(rp)
            break

    summary_csv  = replicas_folder / "kpis_intradia_ic95.csv"       if replicas_folder else None
    replicas_csv = replicas_folder / "kpis_intradia_replicas.csv"   if replicas_folder else None
    daily_csv    = replicas_folder / "kpis_intradia_daily_ic95.csv" if replicas_folder else None

    if replicas_folder and summary_csv and summary_csv.exists() and replicas_csv and replicas_csv.exists():
        df_ic_data  = pd.read_csv(summary_csv)
        df_rep_data = pd.read_csv(replicas_csv)
        df_daily_ic = pd.read_csv(daily_csv) if daily_csv and daily_csv.exists() else pd.DataFrame()
        if "day" in df_daily_ic.columns and not df_daily_ic.empty:
            df_daily_ic = df_daily_ic[(df_daily_ic["day"] >= start_d) & (df_daily_ic["day"] <= end_d)]
        n_rep = df_rep_data["replica"].nunique() if "replica" in df_rep_data.columns else len(df_rep_data)
        st.success(f"✅ CSVs encontrados | {n_rep} réplicas")
        c1, c2, c3 = st.columns(3)
        c1.metric("Réplicas válidas", n_rep)
        c2.metric("KPIs resumidos", len(df_ic_data))
        c3.metric("Días con IC diario", df_daily_ic["day"].nunique() if not df_daily_ic.empty else 0)
        cols_show = [c for c in ["label", "n", "mean", "ci95_low", "ci95_high", "min", "max"] if c in df_ic_data.columns]
        st.dataframe(df_ic_data[cols_show], width="stretch", hide_index=True)
        if not df_daily_ic.empty and "label" in df_daily_ic.columns:
            st.markdown('<div class="section-header">Evolución diaria con banda IC 95%</div>', unsafe_allow_html=True)
            sel_kpi_ic = st.selectbox("KPI diario", sorted(df_daily_ic["label"].dropna().unique()))
            dv = df_daily_ic[df_daily_ic["label"] == sel_kpi_ic].copy()
            if "day" in dv.columns:
                fig_ic = go.Figure()
                fig_ic.add_trace(go.Scatter(x=dv["day"], y=dv.get("ci95_high"), mode="lines",
                                            name="IC 95% sup", line=dict(color=COLORS["slate"], dash="dot")))
                fig_ic.add_trace(go.Scatter(x=dv["day"], y=dv.get("ci95_low"), mode="lines",
                                            name="IC 95% inf", fill="tonexty",
                                            fillcolor="rgba(148,163,184,0.2)",
                                            line=dict(color=COLORS["slate"], dash="dot")))
                fig_ic.add_trace(go.Scatter(x=dv["day"], y=dv.get("mean"), mode="lines+markers",
                                            name="Media", line=dict(color=COLORS["primary"], width=2),
                                            marker=dict(size=3)))
                fig_ic.update_layout(plot_bgcolor=COLORS["bg"], height=320,
                                     xaxis_title="Día", yaxis_title=sel_kpi_ic)
                st.plotly_chart(fig_ic, width="stretch")
    else:
        rep_files = sorted(replicas_folder.glob("solution_intradia-*.xlsx")) if replicas_folder else []
        if len(rep_files) > 1:
            st.info(f"📂 {len(rep_files)} réplicas encontradas. Calculando KPIs en tiempo real...")
            rows = []; prog_bar = st.progress(0)
            for i, rf in enumerate(rep_files):
                _, rp, ro, _ = load_data(str(rf))
                if rp is not None:
                    rp_f = rp[(rp["day"] >= start_d) & (rp["day"] <= end_d)]
                    ro_f = ro[(ro["day"] >= start_d) & (ro["day"] <= end_d)] if ro is not None else pd.DataFrame()
                    k = compute_kpis(rp_f, ro_f); k["replica"] = i + 1; rows.append(k)
                prog_bar.progress((i + 1) / len(rep_files))
            if rows:
                df_rep = pd.DataFrame(rows)
                num_cols = [c for c in df_rep.columns if c != "replica" and df_rep[c].dtype in [float, int]]
                summary  = df_rep[num_cols].agg(["mean", "std", "min", "max"]).T
                n = len(df_rep); t = 2.045 if n == 30 else 1.96
                summary["se"]       = summary["std"] / np.sqrt(n)
                summary["ci95_low"] = summary["mean"] - t * summary["se"]
                summary["ci95_high"]= summary["mean"] + t * summary["se"]
                st.success(f"✅ {n} réplicas calculadas.")
                st.dataframe(summary.round(3), width="stretch")
        else:
            st.warning(
                "⏳ **Las 30 réplicas están en proceso.**\n\n"
                "Cuando estén disponibles, colócalas en:\n"
                "`Analisis Sensibilidad/resultados_intradia/S0_base/solution_intradia-N.xlsx`\n\n"
                "El dashboard las detectará automáticamente."
            )
            kpi_prev = {
                "Sesiones": kpis.get("sessions"),
                "Pacientes Únicos": kpis.get("unique_patients"),
                "Cumpl. Horario (%)": round(kpis.get("cumplimiento", 0), 2),
                "Espera Máxima (mód)": kpis.get("max_wait_pharm"),
                "Espera Promedio (mód)": round(kpis.get("avg_wait_pharm", 0), 2),
                "Util. Sillas Total (%)": round(kpis.get("util_chairs", 0), 2),
                "Util. Sillas Regular (%)": round(kpis.get("util_chairs_reg", 0), 2),
                "Ocup. Enfermería (%)": round(kpis.get("util_nurses", 0), 2),
                "Ocup. Farmacia (%)": round(kpis.get("util_pharm", 0), 2),
                "Módulos Extra Totales": kpis.get("total_extra"),
                "Días con Extra": kpis.get("days_extra"),
            }
            st.markdown('<div class="section-header">KPIs del caso base S0 como referencia</div>', unsafe_allow_html=True)
            st.dataframe(pd.DataFrame(list(kpi_prev.items()), columns=["KPI", "Valor (S0_base)"]),
                         width="stretch", hide_index=True)

# ─────────────────────────────────────────────────────────────────────────────
# TAB 5 — ANÁLISIS DE SENSIBILIDAD
# ─────────────────────────────────────────────────────────────────────────────
with tab_sens:
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### 🔬 Análisis de Sensibilidad — Comparación de Escenarios")

    SCENARIO_LABELS = {
        "S0_base":           "S0 – Base",
        "S1_demanda_110":    "S1 – Demanda +10%",
        "S2_demanda_120":    "S2 – Demanda +20%",
        "S3_sillas_14":      "S3 – 14 Sillas (−1)",
        "S4_sillas_16":      "S4 – 16 Sillas (+1)",
        "S5_enfermeras_5":   "S5 – 5 Enfermeras (+1)",
        "S6_earlycap_200":   "S6 – Farmacia cap 200",
        "S7_duracion_110":   "S7 – Duración +10%",
        "S8_eventos_expost": "S8 – Eventos ex post",
    }

    available_scen = {}
    for sid, slabel in SCENARIO_LABELS.items():
        fp = BASE_DIR / sid / "solution_intradia-1.xlsx"
        if fp.exists():
            available_scen[sid] = {"label": slabel, "path": str(fp)}

    scen_rows = []
    for sid, sinfo in available_scen.items():
        _, sp, so, _ = load_data(sinfo["path"])
        if sp is None:
            continue
        sp_f = sp[(sp["day"] >= start_d) & (sp["day"] <= end_d)]
        so_f = so[(so["day"] >= start_d) & (so["day"] <= end_d)] if so is not None else pd.DataFrame()
        sk = compute_kpis(sp_f, so_f)
        sk["escenario"] = sinfo["label"]
        sk["id"]        = sid
        scen_rows.append(sk)

    KPI_COLS = {
        "sessions":        ("Sesiones",              "{:,.0f}", False),
        "unique_patients": ("Pacientes",              "{:,.0f}", False),
        "cumplimiento":    ("Cumpl. (%)",             "{:.1f}",  False),
        "max_wait_pharm":  ("Esp. Máx Farm->Sillón",  "{:.1f}",  True),
        "max_start_time":  ("Inicio Máx Desde Llegada", "{:.1f}", True),
        "avg_wait_pharm":  ("Esp. Prom Farm->Sillón", "{:.2f}",  True),
        "avg_start_time":  ("Inicio Prom Desde Llegada", "{:.2f}", True),
        "total_extra":     ("Mód. Extra",             "{:,.0f}", True),
        "days_extra":      ("Días Extra",             "{:.0f}",  True),
        "util_chairs":     ("Util. Sillas (%)",       "{:.1f}",  False),
        "util_nurses":     ("Util. Enferm. (%)",      "{:.1f}",  False),
        "util_pharm":      ("Util. Farm. (%)",        "{:.1f}",  False),
    }

    if not scen_rows:
        st.info(
            "⏳ Aún no hay resultados de sensibilidad.\n\n"
            "Se detectarán automáticamente cuando estén en:\n"
            "`Analisis Sensibilidad/resultados_intradia/Sn_*/solution_intradia-1.xlsx`"
        )
        df_def = pd.DataFrame([
            {"ID": k, "Descripción": v, "Disponible": "✅" if k in available_scen else "⏳"}
            for k, v in SCENARIO_LABELS.items()
        ])
        st.dataframe(df_def, width="stretch", hide_index=True)
    else:
        df_sens = pd.DataFrame(scen_rows)
        st.markdown(f"**{len(df_sens)} escenarios cargados de {len(SCENARIO_LABELS)} definidos.**")

        st.markdown('<div class="section-header">Tabla comparativa de KPIs</div>', unsafe_allow_html=True)
        disp = []
        for _, row in df_sens.iterrows():
            d = {"Escenario": row["escenario"]}
            for k, (lbl, fmt, _) in KPI_COLS.items():
                val = row.get(k, np.nan)
                d[lbl] = fmt.format(val) if not pd.isna(val) else "N/A"
            disp.append(d)
        st.dataframe(pd.DataFrame(disp), width="stretch", hide_index=True)

        base_row_s = df_sens[df_sens["id"] == "S0_base"].iloc[0] if "S0_base" in df_sens["id"].values else None
        if base_row_s is not None and len(df_sens) > 1:
            st.markdown('<div class="section-header">Delta vs Base (S0)</div>', unsafe_allow_html=True)
            delta_rows = []
            for _, row in df_sens[df_sens["id"] != "S0_base"].iterrows():
                d = {"Escenario": row["escenario"]}
                for k, (lbl, _, _wh) in KPI_COLS.items():
                    val  = row.get(k, np.nan)
                    base = base_row_s.get(k, np.nan)
                    if pd.isna(val) or pd.isna(base) or base == 0:
                        d[f"Δ {lbl}"] = "–"
                    else:
                        dp = (val - base) / abs(base) * 100
                        d[f"Δ {lbl}"] = f"{'▲' if dp > 0 else '▼'} {abs(dp):.1f}%"
                delta_rows.append(d)
            st.dataframe(pd.DataFrame(delta_rows), width="stretch", hide_index=True)

            st.markdown('<div class="section-header">Radar de KPIs (utilización de recursos)</div>', unsafe_allow_html=True)
            r_kpis = ["cumplimiento", "util_chairs", "util_nurses", "util_pharm"]
            r_lbls = ["Cumplimiento", "Util.Sillas", "Util.Enfermería", "Util.Farmacia"]
            fig_rad = go.Figure()
            pal = px.colors.qualitative.Bold
            for i, (_, row) in enumerate(df_sens.iterrows()):
                vals = [row.get(k, 0) for k in r_kpis]
                fig_rad.add_trace(go.Scatterpolar(
                    r=vals + [vals[0]], theta=r_lbls + [r_lbls[0]],
                    name=row["escenario"], line_color=pal[i % len(pal)],
                ))
            fig_rad.update_layout(polar=dict(radialaxis=dict(range=[0, 100])), showlegend=True, height=400)
            st.plotly_chart(fig_rad, width="stretch")

        st.markdown('<div class="section-header">Comparación por KPI individual</div>', unsafe_allow_html=True)
        sel_ks = st.selectbox("KPI a comparar",
                              [(k, lbl) for k, (lbl, _, _) in KPI_COLS.items()],
                              format_func=lambda x: x[1])

        k_sel, lbl_sel = sel_ks
        fig_cmp = px.bar(
            df_sens.sort_values(k_sel),
            x="escenario",
            y=k_sel,
            color="escenario",
            labels={"escenario": "Escenario", k_sel: lbl_sel},
            color_discrete_sequence=px.colors.qualitative.Bold,
        )
        fig_cmp.update_layout(showlegend=False, plot_bgcolor=COLORS["bg"], height=320)
        st.plotly_chart(fig_cmp, width="stretch")

# ─────────────────────────────────────────────────────────────────────────────
# TAB 6 — MODELO / CG
# ─────────────────────────────────────────────────────────────────────────────
with tab_cg:
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("### Diagnóstico del Modelo y Column Generation")

    df_res_f = df_res_raw[(df_res_raw["day"] >= start_d) & (df_res_raw["day"] <= end_d)].copy() \
        if df_res_raw is not None and not df_res_raw.empty and "day" in df_res_raw.columns else pd.DataFrame()
    df_cg_f = df_cg_raw[(df_cg_raw["day"] >= start_d) & (df_cg_raw["day"] <= end_d)].copy() \
        if df_cg_raw is not None and not df_cg_raw.empty and "day" in df_cg_raw.columns else pd.DataFrame()
    max_iters_s = df_cg_f.groupby("day")["iteration"].max() if not df_cg_f.empty and "iteration" in df_cg_f.columns else pd.Series(dtype=float)

    if df_res_f.empty and df_cg_f.empty:
        st.info("No hay hojas `Resumen_Dias` o `CG_Historial` disponibles para el archivo cargado.")
    else:
        if not df_res_f.empty and "total_patterns" in df_res_f.columns:
            st.markdown('<div class="section-header">Patrones Generados por Día</div>', unsafe_allow_html=True)
            fig_pt = go.Figure()
            fig_pt.add_trace(go.Scatter(x=df_res_f["day"], y=df_res_f["total_patterns"],
                                        mode="lines+markers", fill="tozeroy",
                                        marker_color=COLORS["primary"],
                                        fillcolor="rgba(99,102,241,0.15)", name="Patrones"))
            fig_pt.update_layout(plot_bgcolor=COLORS["bg"], height=240,
                                 xaxis_title="Día", yaxis_title="# Patrones",
                                 xaxis=dict(gridcolor="#f4f4f5"), yaxis=dict(gridcolor="#f4f4f5"))
            st.plotly_chart(fig_pt, width="stretch")

        if not df_res_f.empty and "obj_value" in df_res_f.columns:
            st.markdown('<div class="section-header">Valor Objetivo del Master LP por Día</div>', unsafe_allow_html=True)
            fig_ob = go.Figure()
            fig_ob.add_trace(go.Scatter(x=df_res_f["day"], y=df_res_f["obj_value"],
                                        mode="lines+markers",
                                        line=dict(color=COLORS["success"], width=2),
                                        marker=dict(size=3), name="Obj Value"))
            fig_ob.update_layout(plot_bgcolor=COLORS["bg"], height=240,
                                 xaxis_title="Día", yaxis_title="Obj. Value",
                                 xaxis=dict(gridcolor="#f4f4f5"), yaxis=dict(gridcolor="#f4f4f5"))
            st.plotly_chart(fig_ob, width="stretch")

        st.markdown('<div class="section-header">Convergencia CG — Día Seleccionado</div>', unsafe_allow_html=True)
        if not df_cg_f.empty and "iteration" in df_cg_f.columns:
            days_cg_multi = sorted(df_cg_f[df_cg_f["iteration"] > 1]["day"].unique())
            if days_cg_multi:
                sel_cg_day = st.selectbox(
                    "Día con CG iterativo", days_cg_multi,
                    format_func=lambda d: f"Día {d} ({int(max_iters_s.get(d, 1))} iters)",
                )
                cg_day = df_cg_f[df_cg_f["day"] == sel_cg_day].sort_values("iteration")
                fig_cv = go.Figure()
                fig_cv.add_trace(go.Scatter(x=cg_day["iteration"], y=cg_day["master_lp_obj"],
                                            mode="lines+markers", name="Master LP Obj",
                                            line=dict(color=COLORS["primary"], width=2)))
                fig_cv.add_trace(go.Bar(x=cg_day["iteration"], y=cg_day["added_patterns"],
                                        name="Patrones Añadidos", marker_color=COLORS["info"],
                                        opacity=0.6, yaxis="y2"))
                fig_cv.update_layout(
                    plot_bgcolor=COLORS["bg"], height=310,
                    xaxis_title="Iteración", yaxis_title="Master LP Obj",
                    yaxis2=dict(title="Patrones añadidos", overlaying="y", side="right", showgrid=False),
                    legend=dict(orientation="h", y=-0.25),
                )
                st.plotly_chart(fig_cv, width="stretch")
            else:
                st.info("Todos los días se resolvieron en 1 iteración en el período seleccionado.")
        else:
            st.info("No hay historial de Column Generation para el período seleccionado.")

        with st.expander("📋 Ver tabla CG_Historial"):
            st.dataframe(df_cg_f, width="stretch", hide_index=True)
        with st.expander("📋 Ver tabla Resumen_Dias"):
            if not df_res_f.empty:
                st.dataframe(df_res_f, width="stretch", hide_index=True)
