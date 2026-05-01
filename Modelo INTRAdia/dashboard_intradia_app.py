import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os

# Fintual style config
st.set_page_config(page_title="Dashboard Intradía", layout="wide")

# Inject custom CSS to make tabs look like a top menu
st.markdown("""
<style>
    .block-container {
        padding-top: 1rem;
        padding-bottom: 2rem;
        font-family: 'Inter', sans-serif;
    }
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Enhance Tabs to act as a Top Menu */
    .stTabs [data-baseweb="tab-list"] {
        gap: 15px;
        padding-bottom: 5px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: transparent;
        border-radius: 4px;
        padding: 10px 16px;
        font-weight: 600;
        font-size: 16px;
    }
    .stTabs [aria-selected="true"] {
        background-color: #f3f4f6;
        color: #10b981;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------
# 1. CORE FUNCTIONS
# ---------------------------------------------------------

@st.cache_data
def load_data(file_path):
    try:
        xls = pd.ExcelFile(file_path)
        df_res = xls.parse("Resumen_Dias") if "Resumen_Dias" in xls.sheet_names else pd.DataFrame()
        df_prog = xls.parse("Programacion")
        df_ocup = xls.parse("Ocupacion_Modulos")
        return df_res, df_prog, df_ocup
    except Exception as e:
        return None, None, None

def assign_chairs_for_visualization(df_prog, n_chairs=15):
    assigned_rows = []
    for day, day_df in df_prog.groupby("day"):
        day_df = day_df.sort_values(by="treatment_start")
        chair_free_at = {c: 0 for c in range(1, n_chairs + 1)}
        for _, row in day_df.iterrows():
            r_dict = row.to_dict()
            assigned = False
            for c in range(1, n_chairs + 1):
                if chair_free_at[c] <= row["treatment_start"]:
                    r_dict["chair_id"] = c
                    chair_free_at[c] = row["treatment_start"] + row["treatment_modules"]
                    assigned = True
                    break
            if not assigned:
                r_dict["chair_id"] = 16
            assigned_rows.append(r_dict)
    return pd.DataFrame(assigned_rows)

def compute_kpis(f_prog, f_ocup):
    total_sessions = len(f_prog)
    unique_patients = f_prog["patient_id"].nunique() if total_sessions > 0 else 0
    cumplimiento = (f_prog["treatment_end"] <= 47).sum() / total_sessions * 100 if total_sessions > 0 else 0
    total_extra = f_prog["extra_chair_modules"].sum() if total_sessions > 0 else 0
    days_extra = f_prog[f_prog["extra_chair_modules"] > 0]["day"].nunique() if total_sessions > 0 else 0
    max_wait = f_prog["wait_after_pharmacy"].max() if total_sessions > 0 else 0
    avg_wait = f_prog["wait_after_pharmacy"].mean() if total_sessions > 0 else 0
    total_chairs_used = f_ocup["chairs_used"].sum() if not f_ocup.empty else 0
    total_chairs_cap = f_ocup["chair_capacity"].sum() if not f_ocup.empty else 0
    util_chairs = (total_chairs_used / total_chairs_cap * 100) if total_chairs_cap > 0 else 0
    reg_ocup = f_ocup[f_ocup["is_extra"] == 0]
    util_chairs_reg = (reg_ocup["chairs_used"].sum() / reg_ocup["chair_capacity"].sum() * 100) if not reg_ocup.empty and reg_ocup["chair_capacity"].sum() > 0 else 0
    n_col = "nurse_events" if "nurse_events" in f_ocup.columns else "nurse_starts"
    if n_col == "nurse_starts" and "nurse_ends" in f_ocup.columns:
        nurse_used = f_ocup["nurse_starts"].sum() + f_ocup["nurse_ends"].sum()
    else:
        nurse_used = f_ocup[n_col].sum() if not f_ocup.empty else 0
    nurse_cap = f_ocup["nurse_capacity"].sum() if not f_ocup.empty else 0
    util_nurses = (nurse_used / nurse_cap * 100) if nurse_cap > 0 else 0
    pharm_used = f_ocup["pharmacy_used"].sum() if not f_ocup.empty else 0
    pharm_cap = f_ocup["pharmacy_capacity"].sum() if not f_ocup.empty else 0
    util_pharm = (pharm_used / pharm_cap * 100) if pharm_cap > 0 else 0
    most_loaded_day = f_prog.groupby("day")["treatment_modules"].sum().idxmax() if total_sessions > 0 else None
    return {
        "sessions": total_sessions, "unique_patients": unique_patients, "cumplimiento": cumplimiento,
        "total_extra": total_extra, "days_extra": days_extra, "max_wait": max_wait, "avg_wait": avg_wait,
        "util_chairs": util_chairs, "util_chairs_reg": util_chairs_reg, "util_nurses": util_nurses,
        "util_pharm": util_pharm, "most_loaded_day": most_loaded_day
    }

def get_critical_days(df_prog, df_ocup):
    if df_prog.empty: return []
    extra_days = df_prog[df_prog["extra_chair_modules"] > 0]["day"].unique()
    wait_days = df_prog[df_prog["wait_after_pharmacy"] > 6]["day"].unique()
    if df_ocup.empty: return list(set(extra_days) | set(wait_days))
    chairs_crit = df_ocup[df_ocup["chairs_used"] == df_ocup["chair_capacity"]]["day"].unique()
    n_col = "nurse_events" if "nurse_events" in df_ocup.columns else "nurse_starts"
    if n_col == "nurse_starts" and "nurse_ends" in df_ocup.columns:
        n_used = df_ocup["nurse_starts"] + df_ocup["nurse_ends"]
    else:
        n_used = df_ocup[n_col]
    nurses_crit = df_ocup[n_used == df_ocup["nurse_capacity"]]["day"].unique()
    pharm_crit = df_ocup[df_ocup["pharmacy_used"] == df_ocup["pharmacy_capacity"]]["day"].unique()
    criticals = set(extra_days) | set(wait_days) | set(chairs_crit) | set(nurses_crit) | set(pharm_crit)
    return list(criticals)

# ---------------------------------------------------------
# 2. INITIALIZATION
# ---------------------------------------------------------
st.title("Planificación Intradiaria")

possible_paths = [
    "Modelo INTRAdia/Modelo INTRAdia/475_solution_deldia_v2.xlsx",
    "Modelo INTRAdia/475_solution_deldia_v2.xlsx",
    "475_solution_deldia_v2.xlsx",
    "Modelo INTRAdia/solution_deldia_v2.xlsx",
    "solution_deldia_v2.xlsx"
]

file_to_load = None
for p in possible_paths:
    if os.path.exists(p):
        file_to_load = p
        break

if file_to_load is None:
    st.error("No se encontró el archivo de datos.")
    st.stop()

df_res, df_prog_raw, df_ocup_raw = load_data(file_to_load)

if df_prog_raw is None or df_prog_raw.empty:
    st.error("Error leyendo 'Programacion'.")
    st.stop()

if "chair_id" not in df_prog_raw.columns:
    df_prog_raw = assign_chairs_for_visualization(df_prog_raw)

# ---------------------------------------------------------
# 3. FILTERS (TOP LEVEL)
# ---------------------------------------------------------
st.markdown("---")
c1, c2, c3 = st.columns(3)

min_d, max_d = int(df_prog_raw["day"].min()), int(df_prog_raw["day"].max())

start_d = c1.number_input("📅 Día Inicio", min_value=0, max_value=10000, value=min_d)
end_d = c2.number_input("📅 Día Término", min_value=0, max_value=10000, value=max_d)

if start_d > end_d:
    st.error("El Día Inicio no puede ser mayor al Día Término.")
    st.stop()

df_prog = df_prog_raw[(df_prog_raw["day"] >= start_d) & (df_prog_raw["day"] <= end_d)].copy()
df_ocup = df_ocup_raw[(df_ocup_raw["day"] >= start_d) & (df_ocup_raw["day"] <= end_d)].copy()

valid_days_raw = df_prog["day"].unique()
day_options = [f"Día {int(d)} | Cal {int(d)+1}" for d in sorted(valid_days_raw)]

if not day_options:
    st.warning("No hay datos en el rango seleccionado.")
    st.stop()

selected_day_str = c3.selectbox("🔍 Día Específico (Detalle)", options=day_options)
selected_day = int(selected_day_str.split(" ")[1])

with st.expander("⚙️ Filtros Avanzados", expanded=False):
    f_c1, f_c2 = st.columns(2)
    patient_types = sorted(df_prog["patient_type"].unique())
    sel_ptypes = f_c1.multiselect("Tipos de Paciente", options=patient_types, default=patient_types)
    
    patient_ids = sorted(df_prog["patient_id"].unique())
    sel_pids = f_c2.multiselect("ID Paciente (Opcional)", options=patient_ids, default=[])
    
    f_c3, f_c4 = st.columns(2)
    show_extra = f_c3.checkbox("Mostrar solo sesiones con módulos extra", value=False)
    show_critical = f_c4.checkbox("Mostrar solo días críticos", value=False)

if sel_ptypes: df_prog = df_prog[df_prog["patient_type"].isin(sel_ptypes)]
if sel_pids: df_prog = df_prog[df_prog["patient_id"].isin(sel_pids)]
if show_extra: df_prog = df_prog[df_prog["extra_chair_modules"] > 0]

valid_days = df_prog["day"].unique()
if show_critical:
    crit_days = get_critical_days(df_prog_raw, df_ocup_raw)
    valid_days = [d for d in valid_days if d in crit_days]
    df_prog = df_prog[df_prog["day"].isin(valid_days)]

df_ocup = df_ocup[df_ocup["day"].isin(valid_days)]

if df_prog.empty:
    st.warning("No hay datos que coincidan con los filtros avanzados.")
    st.stop()

# ---------------------------------------------------------
# 4. RENDERERS
# ---------------------------------------------------------
kpis = compute_kpis(df_prog, df_ocup)

if (df_prog["chair_id"] == 16).any():
    st.error("⚠️ Hay sesiones que no pudieron asignarse a las 15 sillas en la visualización. Revisar consistencia.")
if (df_prog["treatment_end"] > 55).any():
    st.error("⚠️ Existen sesiones con treatment_end > 55.")
if (df_prog["pharmacy_start"] < 0).any() or (df_prog["treatment_start"] < 0).any():
    st.error("⚠️ Existen inicios de módulo negativos.")

# Minimalist color palette
C_PHARM = "#38bdf8"
C_WAIT = "#f43f5e"
C_TREAT = "#10b981"
C_EXTRA = "#f59e0b"
C_CAP = "#a0aec0"

def render_executive_view():
    st.markdown("<br>", unsafe_allow_html=True)
    if kpis["total_extra"] == 0:
        st.success("💡 No se usaron módulos extraordinarios en el período.")
    else:
        st.warning(f"💡 Se usaron {kpis['total_extra']} módulos extra en {kpis['days_extra']} días.")
        
    if kpis["cumplimiento"] < 95:
        st.warning(f"💡 Hay sesiones que terminan fuera del horario regular. (Cumplimiento: {kpis['cumplimiento']:.1f}%)")
    else:
        st.success(f"💡 Excelente cumplimiento del horario regular ({kpis['cumplimiento']:.1f}%).")
        
    if kpis["max_wait"] > 6:
        st.error(f"💡 Se detectan esperas intradía altas (Máxima: {kpis['max_wait']} mod / {kpis['max_wait']*15} min).")
        
    st.markdown("---")
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sesiones Realizadas", f"{kpis['sessions']:,}")
    c2.metric("Pacientes Únicos", f"{kpis['unique_patients']:,}")
    c3.metric("Cumpl. Horario", f"{kpis['cumplimiento']:.1f}%")
    c4.metric("Día Más Cargado", f"Día {kpis['most_loaded_day']}")
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Módulos Extra", f"{kpis['total_extra']:,}")
    c2.metric("Días con Extra", f"{kpis['days_extra']}")
    c3.metric("Espera Máxima", f"{kpis['max_wait']} mod")
    c4.metric("Espera Promedio", f"{kpis['avg_wait']:.1f} mod")
    
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Util. Sillas (Total)", f"{kpis['util_chairs']:.1f}%")
    c2.metric("Util. Sillas (Reg)", f"{kpis['util_chairs_reg']:.1f}%")
    c3.metric("Ocup. Enfermería", f"{kpis['util_nurses']:.1f}%")
    c4.metric("Ocup. Farmacia", f"{kpis['util_pharm']:.1f}%")

    daily = df_prog.groupby("day").agg(
        Tratamiento=("treatment_modules", "sum"),
        Sesiones=("session", "count"),
        Extra=("extra_chair_modules", "sum")
    ).reset_index()
    
    fig = px.bar(daily, x="day", y=["Tratamiento", "Extra"], title="Módulos Tratamiento y Extra por Día",
                 color_discrete_sequence=[C_TREAT, C_EXTRA], barmode="stack")
    fig.update_layout(plot_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, use_container_width=True)

def render_sillas_view(day):
    st.markdown("<br>", unsafe_allow_html=True)
    day_df = df_prog[df_prog["day"] == day]
    if day_df.empty:
        st.info("No hay pacientes para este día.")
        return
        
    fig = go.Figure()
    ptypes = day_df["patient_type"].unique()
    colors = px.colors.qualitative.Pastel
    color_map = {pt: colors[i % len(colors)] for i, pt in enumerate(ptypes)}
    
    for _, r in day_df.iterrows():
        hover = (f"Paciente: {r['patient_id']} | Tipo: {r['patient_type']}<br>"
                 f"Ciclo/Ses: {r['cycle']}/{r['session']}<br>"
                 f"Silla: {r['chair_id']}<br>"
                 f"Farmacia: {r['pharmacy_start']} - {r['pharmacy_end']}<br>"
                 f"Espera: {r['wait_after_pharmacy']} mod<br>"
                 f"Tratamiento: {r['treatment_start']} - {r['treatment_end']}<br>"
                 f"Extra: {r['extra_chair_modules']}")
                 
        fig.add_trace(go.Bar(
            x=[r["treatment_modules"]],
            y=[f"Silla {int(r['chair_id'])}"],
            base=[r["treatment_start"]],
            orientation="h",
            marker_color=color_map[r["patient_type"]],
            name=f"Tipo {r['patient_type']}",
            hoverinfo="text",
            hovertext=hover,
            text=f"Pat {r['patient_id']}",
            textposition="inside"
        ))
        
    fig.add_vline(x=48, line_width=2, line_dash="dash", line_color=C_WAIT, annotation_text="Inicio jornada extra")
    
    fig.update_layout(
        title=f"Asignación Fija a Sillas - Día {day}",
        barmode="stack", showlegend=False, 
        xaxis=dict(title="Módulos (0 a 55)", range=[0, 56], tick0=0, dtick=4, gridcolor="#f0f0f0"),
        yaxis=dict(type="category", categoryorder="array", categoryarray=[f"Silla {i}" for i in range(15, 0, -1)]),
        plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=80, r=20, t=40, b=40)
    )
    
    st.plotly_chart(fig, use_container_width=True)

def render_pacientes_view(day):
    st.markdown("<br>", unsafe_allow_html=True)
    day_df = df_prog[df_prog["day"] == day]
    if day_df.empty:
        st.info("No hay pacientes.")
        return
        
    fig = go.Figure()
    day_df = day_df.sort_values("treatment_start", ascending=False)
    
    pharm_x, pharm_y, pharm_base, pharm_h = [], [], [], []
    wait_x, wait_y, wait_base, wait_h = [], [], [], []
    treat_x, treat_y, treat_base, treat_h = [], [], [], []
    
    for _, r in day_df.iterrows():
        pid = f"Pat {r['patient_id']}"
        h_str = (f"Pat: {r['patient_id']} | Tipo: {r['patient_type']}<br>"
                 f"Silla {r['chair_id']} | Extra {r['extra_chair_modules']}<br>"
                 f"Farmacia: {r['pharmacy_start']} - {r['pharmacy_end']}<br>"
                 f"Tratamiento: {r['treatment_start']} - {r['treatment_end']}")
                 
        if r["pharmacy_modules"] > 0:
            pharm_x.append(r["pharmacy_modules"]); pharm_y.append(pid); pharm_base.append(r["pharmacy_start"]); pharm_h.append(h_str)
        if r["wait_after_pharmacy"] > 0:
            wait_x.append(r["wait_after_pharmacy"]); wait_y.append(pid); wait_base.append(r["pharmacy_end"]); wait_h.append(h_str)
        if r["treatment_modules"] > 0:
            treat_x.append(r["treatment_modules"]); treat_y.append(pid); treat_base.append(r["treatment_start"]); treat_h.append(h_str)
            
    if pharm_x:
        fig.add_trace(go.Bar(x=pharm_x, y=pharm_y, base=pharm_base, orientation='h', name='Farmacia', marker_color=C_PHARM, hovertext=pharm_h, hoverinfo='text'))
    if wait_x:
        fig.add_trace(go.Bar(x=wait_x, y=wait_y, base=wait_base, orientation='h', name='Espera', marker_color=C_WAIT, hovertext=wait_h, hoverinfo='text'))
    if treat_x:
        fig.add_trace(go.Bar(x=treat_x, y=treat_y, base=treat_base, orientation='h', name='Tratamiento', marker_color=C_TREAT, hovertext=treat_h, hoverinfo='text'))
        
    fig.add_vline(x=48, line_width=2, line_dash="dash", line_color=C_WAIT, annotation_text="Inicio jornada extra")
    fig.update_layout(
        title=f"Gantt de Actividades por Paciente - Día {day}",
        barmode="stack",
        xaxis=dict(title="Módulos (0 a 55)", range=[0, 56], tick0=0, dtick=4, gridcolor="#f0f0f0"),
        yaxis=dict(type="category"),
        plot_bgcolor="rgba(0,0,0,0)"
    )
    st.plotly_chart(fig, use_container_width=True)

def render_recursos_view():
    st.markdown("<br>", unsafe_allow_html=True)
    tab_day, tab_avg = st.tabs(["📊 Día Específico", "📈 Promedio del Período"])
    
    def get_nurse(df):
        if "nurse_events" in df.columns: return df["nurse_events"]
        if "nurse_starts" in df.columns and "nurse_ends" in df.columns: return df["nurse_starts"] + df["nurse_ends"]
        return df["nurse_starts"] if "nurse_starts" in df.columns else 0

    with tab_day:
        day_ocup = df_ocup[df_ocup["day"] == selected_day].copy()
        if day_ocup.empty:
            st.info("No hay datos de ocupación.")
        else:
            day_ocup["nurse_computed"] = get_nurse(day_ocup)
            fig = go.Figure()
            fig.add_trace(go.Bar(x=day_ocup["module"], y=day_ocup["chairs_used"], name="Sillas", marker_color="#6366f1"))
            fig.add_trace(go.Scatter(x=day_ocup["module"], y=day_ocup["chair_capacity"], name="Cap Sillas", mode="lines", line=dict(dash="dash", color=C_CAP)))
            
            fig.add_trace(go.Bar(x=day_ocup["module"], y=day_ocup["nurse_computed"], name="Enfermería", marker_color="#8b5cf6"))
            fig.add_trace(go.Scatter(x=day_ocup["module"], y=day_ocup["nurse_capacity"], name="Cap Enfermería", mode="lines", line=dict(dash="dash", color=C_CAP)))
            
            fig.add_trace(go.Bar(x=day_ocup["module"], y=day_ocup["pharmacy_used"], name="Farmacia", marker_color=C_PHARM))
            fig.add_trace(go.Scatter(x=day_ocup["module"], y=day_ocup["pharmacy_capacity"], name="Cap Farmacia", mode="lines", line=dict(dash="dash", color=C_CAP)))
            
            fig.add_vline(x=48, line_width=2, line_dash="dash", line_color=C_WAIT)
            fig.update_layout(title=f"Perfil de Recursos - Día {selected_day}", barmode="group", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(gridcolor="#f0f0f0"))
            st.plotly_chart(fig, use_container_width=True)
            
    with tab_avg:
        df_ocup_copy = df_ocup.copy()
        df_ocup_copy["nurse_computed"] = get_nurse(df_ocup_copy)
        avg = df_ocup_copy.groupby("module").agg(
            Sillas=("chairs_used", "mean"), Enf=("nurse_computed", "mean"), Pharm=("pharmacy_used", "mean"),
            cS=("chair_capacity", "max"), cE=("nurse_capacity", "max"), cP=("pharmacy_capacity", "max")
        ).reset_index()
        
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(x=avg["module"], y=avg["Sillas"], name="Sillas Prom", marker_color="#6366f1"))
        fig2.add_trace(go.Scatter(x=avg["module"], y=avg["cS"], mode="lines", line=dict(dash="dash", color=C_CAP)))
        fig2.add_trace(go.Bar(x=avg["module"], y=avg["Enf"], name="Enf Prom", marker_color="#8b5cf6"))
        fig2.add_trace(go.Scatter(x=avg["module"], y=avg["cE"], mode="lines", line=dict(dash="dash", color=C_CAP)))
        fig2.add_trace(go.Bar(x=avg["module"], y=avg["Pharm"], name="Farm Prom", marker_color=C_PHARM))
        fig2.add_trace(go.Scatter(x=avg["module"], y=avg["cP"], mode="lines", line=dict(dash="dash", color=C_CAP)))
        fig2.add_vline(x=48, line_width=2, line_dash="dash", line_color=C_WAIT)
        fig2.update_layout(title="Ocupación Promedio del Período", barmode="group", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(gridcolor="#f0f0f0"))
        st.plotly_chart(fig2, use_container_width=True)

def render_critical_days_view():
    st.markdown("<br>", unsafe_allow_html=True)
    crit_stats = df_prog.groupby("day").agg(
        sesiones=("session", "count"),
        modulos_trat=("treatment_modules", "sum"),
        modulos_extra=("extra_chair_modules", "sum"),
        espera_max=("wait_after_pharmacy", "max")
    ).reset_index()
    
    df_ocup_copy = df_ocup.copy()
    if "nurse_events" in df_ocup_copy.columns: n_col = df_ocup_copy["nurse_events"]
    elif "nurse_starts" in df_ocup_copy.columns: n_col = df_ocup_copy["nurse_starts"] + df_ocup_copy.get("nurse_ends", 0)
    else: n_col = 0
    df_ocup_copy["n_comp"] = n_col
    
    crit_ocup = df_ocup_copy.groupby("day").agg(
        max_chairs=("chairs_used", "max"),
        max_nurses=("n_comp", "max"),
        max_pharmacy=("pharmacy_used", "max")
    ).reset_index()
    
    crit_df = pd.merge(crit_stats, crit_ocup, on="day", how="left")
    crit_df["dia_calendario"] = crit_df["day"] + 1
    
    crit_df = crit_df.sort_values(
        by=["modulos_extra", "modulos_trat", "espera_max", "max_nurses", "max_pharmacy"], 
        ascending=[False, False, False, False, False]
    )
    
    st.dataframe(crit_df[["day", "dia_calendario", "sesiones", "modulos_trat", "modulos_extra", "espera_max", "max_chairs", "max_nurses", "max_pharmacy"]], use_container_width=True)

def render_datos_view():
    st.markdown("<br>", unsafe_allow_html=True)
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("📥 Descargar Programación (CSV)", df_prog.to_csv(index=False), "programacion_filtrada.csv", "text/csv")
    with col2:
        st.download_button("📥 Descargar Ocupación (CSV)", df_ocup.to_csv(index=False), "ocupacion_filtrada.csv", "text/csv")
        
    st.markdown("##### Programación")
    df_prog_show = df_prog.copy()
    df_prog_show["dia_calendario"] = df_prog_show["day"] + 1
    df_prog_show["en_horario"] = df_prog_show["treatment_end"] <= 47
    
    st.dataframe(df_prog_show[[
        "day", "dia_calendario", "patient_id", "patient_type", "cycle", "session", 
        "pharmacy_start", "pharmacy_end", "pharmacy_modules", "wait_after_pharmacy", 
        "treatment_start", "treatment_end", "treatment_modules", "extra_chair_modules", 
        "chair_id", "en_horario"
    ]], use_container_width=True)

# ---------------------------------------------------------
# 5. EXECUTE VIEW ROUTER (Top Menu with Tabs)
# ---------------------------------------------------------

tab_ejec, tab_sillas, tab_pacs, tab_rec, tab_crit, tab_dat = st.tabs([
    "📊 Ejecutiva", "🪑 Sillas Intradía", "👥 Pacientes Intradía", "⚙️ Recursos", "🚨 Día Crítico", "🗄️ Datos"
])

with tab_ejec:
    render_executive_view()

with tab_sillas:
    day_df = df_prog[df_prog["day"] == selected_day]
    if not day_df.empty:
        st.markdown("<br>", unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Sesiones", len(day_df))
        c2.metric("Pacientes Únicos", day_df["patient_id"].nunique())
        c3.metric("Módulos de Tratamiento", day_df["treatment_modules"].sum())
        c4.metric("Módulos Extra", day_df["extra_chair_modules"].sum())
    render_sillas_view(selected_day)

with tab_pacs:
    render_pacientes_view(selected_day)

with tab_rec:
    render_recursos_view()

with tab_crit:
    render_critical_days_view()

with tab_dat:
    render_datos_view()
