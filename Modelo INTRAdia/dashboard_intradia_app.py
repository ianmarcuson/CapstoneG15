import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os

# Fintual style config
st.set_page_config(page_title="Dashboard Intradía", layout="wide")

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
    
    total_chairs_cap = f_ocup["chair_capacity"].sum() if not f_ocup.empty else 0
    util_chairs = (f_ocup["chairs_used"].sum() / total_chairs_cap * 100) if total_chairs_cap > 0 else 0
    
    n_col = "nurse_events" if "nurse_events" in f_ocup.columns else "nurse_starts"
    if n_col == "nurse_starts" and "nurse_ends" in f_ocup.columns:
        nurse_used = f_ocup["nurse_starts"].sum() + f_ocup["nurse_ends"].sum()
    else:
        nurse_used = f_ocup[n_col].sum() if not f_ocup.empty else 0
    util_nurses = (nurse_used / f_ocup["nurse_capacity"].sum() * 100) if not f_ocup.empty and f_ocup["nurse_capacity"].sum() > 0 else 0
    
    util_pharm = (f_ocup["pharmacy_used"].sum() / f_ocup["pharmacy_capacity"].sum() * 100) if not f_ocup.empty and f_ocup["pharmacy_capacity"].sum() > 0 else 0
    most_loaded_day = f_prog.groupby("day")["treatment_modules"].sum().idxmax() if total_sessions > 0 else None
    
    return {
        "sessions": total_sessions, "unique_patients": unique_patients, "cumplimiento": cumplimiento,
        "total_extra": total_extra, "days_extra": days_extra, "max_wait": max_wait,
        "util_chairs": util_chairs, "util_nurses": util_nurses, "util_pharm": util_pharm,
        "most_loaded_day": most_loaded_day
    }

def get_critical_days(df_prog, df_ocup):
    if df_prog.empty: return []
    extra_days = df_prog[df_prog["extra_chair_modules"] > 0]["day"].unique()
    wait_days = df_prog[df_prog["wait_after_pharmacy"] > 6]["day"].unique()
    if df_ocup.empty: return list(set(extra_days) | set(wait_days))
    chairs_crit = df_ocup[df_ocup["chairs_used"] == df_ocup["chair_capacity"]]["day"].unique()
    n_col = "nurse_events" if "nurse_events" in df_ocup.columns else "nurse_starts"
    if n_col == "nurse_starts" and "nurse_ends" in df_ocup.columns: n_used = df_ocup["nurse_starts"] + df_ocup["nurse_ends"]
    else: n_used = df_ocup[n_col]
    nurses_crit = df_ocup[n_used == df_ocup["nurse_capacity"]]["day"].unique()
    pharm_crit = df_ocup[df_ocup["pharmacy_used"] == df_ocup["pharmacy_capacity"]]["day"].unique()
    return list(set(extra_days) | set(wait_days) | set(chairs_crit) | set(nurses_crit) | set(pharm_crit))

# ---------------------------------------------------------
# 2. INITIALIZATION
# ---------------------------------------------------------
possible_paths = [
    "Modelo INTRAdia/Modelo INTRAdia/475_solution_deldia_v2.xlsx",
    "Modelo INTRAdia/475_solution_deldia_v2.xlsx",
    "475_solution_deldia_v2.xlsx",
    "Modelo INTRAdia/solution_deldia_v2.xlsx",
    "solution_deldia_v2.xlsx"
]

st.sidebar.markdown("### Configuración")
uploaded_file = st.sidebar.file_uploader("Cargar Archivo Excel", type=["xlsx"])
file_to_load = None
if uploaded_file:
    file_to_load = uploaded_file
else:
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
# 3. SIDEBAR FILTERS
# ---------------------------------------------------------
min_d, max_d = int(df_prog_raw["day"].min()), int(df_prog_raw["day"].max())

c1, c2 = st.sidebar.columns(2)
start_d = c1.number_input("Día Inicio", min_value=0, max_value=10000, value=min_d)
end_d = c2.number_input("Día Término", min_value=0, max_value=10000, value=max_d)

if start_d > end_d:
    st.sidebar.error("Inicio > Término")
    st.stop()

df_prog = df_prog_raw[(df_prog_raw["day"] >= start_d) & (df_prog_raw["day"] <= end_d)].copy()
df_ocup = df_ocup_raw[(df_ocup_raw["day"] >= start_d) & (df_ocup_raw["day"] <= end_d)].copy()

valid_days_raw = df_prog["day"].unique()
day_options = [f"Día {int(d)} | Cal {int(d)+1}" for d in sorted(valid_days_raw)]
if not day_options:
    st.warning("No hay datos en el rango seleccionado.")
    st.stop()
    
selected_day_str = st.sidebar.selectbox("Día Específico", options=day_options)
selected_day = int(selected_day_str.split(" ")[1])

with st.sidebar.expander("⚙️ Filtros Avanzados", expanded=False):
    patient_types = sorted(df_prog["patient_type"].unique())
    sel_ptypes = st.multiselect("Tipos de Paciente", options=patient_types, default=patient_types)
    
    patient_ids = sorted(df_prog["patient_id"].unique())
    sel_pids = st.multiselect("ID Paciente", options=patient_ids, default=[])
    
    show_extra = st.checkbox("Solo sesiones con módulos extra", value=False)
    show_critical = st.checkbox("Solo días críticos", value=False)

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
# 4. MAIN HEADER
# ---------------------------------------------------------
st.title("Planificación Intradiaria")
st.markdown(f"**Período seleccionado:** día interno {start_d}–{end_d} | día calendario {start_d+1}–{end_d+1}")
st.markdown(f"*{len(valid_days)} días con datos | {len(df_prog)} sesiones | {df_prog['patient_id'].nunique()} pacientes únicos*")
st.markdown("---")

if (df_prog["chair_id"] == 16).any():
    st.error("⚠️ Hay sesiones que no pudieron asignarse a las 15 sillas en la visualización. Revisar consistencia.")
if (df_prog["treatment_end"] > 55).any():
    st.error("⚠️ Existen sesiones con treatment_end > 55.")
    
# ---------------------------------------------------------
# 5. RENDERERS
# ---------------------------------------------------------
kpis = compute_kpis(df_prog, df_ocup)

def render_resumen():
    c1, c2, c3 = st.columns(3)
    c1.metric("Sesiones Realizadas", f"{kpis['sessions']:,}")
    c2.metric("Pacientes Únicos", f"{kpis['unique_patients']:,}")
    c3.metric("Cumpl. Horario Reg.", f"{kpis['cumplimiento']:.1f}%")
    
    c4, c5, c6 = st.columns(3)
    c4.metric("Módulos Extra Usados", f"{kpis['total_extra']:,}")
    c5.metric("Espera Máxima", f"{kpis['max_wait']} mod")
    c6.metric("Día Más Cargado", f"Día {kpis['most_loaded_day']}")
    
    st.markdown("#### 💡 Lectura rápida del período")
    insights = []
    if kpis["total_extra"] == 0: insights.append("- No se usaron módulos extraordinarios en el período.")
    else: insights.append(f"- Se usaron {kpis['total_extra']} módulos extra en {kpis['days_extra']} días.")
    if kpis["cumplimiento"] < 95: insights.append(f"- Hay sesiones que terminan fuera del horario regular (Cumplimiento: {kpis['cumplimiento']:.1f}%).")
    else: insights.append(f"- Excelente cumplimiento del horario regular ({kpis['cumplimiento']:.1f}%).")
    if kpis["max_wait"] > 6: insights.append(f"- Se detectan esperas intradía altas (Máxima: {kpis['max_wait']} mod).")
    insights.append(f"- El día más cargado de tratamiento es el Día {kpis['most_loaded_day']}.")
    
    ru = max({"Sillas": kpis["util_chairs"], "Enfermería": kpis["util_nurses"], "Farmacia": kpis["util_pharm"]}.items(), key=lambda x: x[1])
    insights.append(f"- El recurso más utilizado promedio fue {ru[0]} ({ru[1]:.1f}%).")
    
    for ins in insights: st.markdown(ins)
        
    st.markdown("<br>", unsafe_allow_html=True)
    st.markdown("#### Carga diaria del período")
    daily = df_prog.groupby("day").agg(Tratamiento=("treatment_modules", "sum"), Sesiones=("session", "count"), Extra=("extra_chair_modules", "sum")).reset_index()
    fig = px.bar(daily, x="day", y=["Tratamiento", "Extra"], color_discrete_sequence=["#10b981", "#f59e0b"], barmode="stack")
    fig.add_trace(go.Scatter(x=daily["day"], y=daily["Sesiones"], name="Sesiones", mode="lines+markers", yaxis="y2", line=dict(color="#3b82f6")))
    fig.update_layout(plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(title="Módulos"), yaxis2=dict(title="Sesiones", overlaying="y", side="right"))
    st.plotly_chart(fig, use_container_width=True)

    st.markdown("#### Top 5 Días Críticos")
    crit_stats = df_prog.groupby("day").agg(sesiones=("session", "count"), modulos_trat=("treatment_modules", "sum"), modulos_extra=("extra_chair_modules", "sum"), espera_max=("wait_after_pharmacy", "max")).reset_index()
    df_ocup_copy = df_ocup.copy()
    if "nurse_events" in df_ocup_copy.columns: n_col = df_ocup_copy["nurse_events"]
    elif "nurse_starts" in df_ocup_copy.columns: n_col = df_ocup_copy["nurse_starts"] + df_ocup_copy.get("nurse_ends", 0)
    else: n_col = 0
    df_ocup_copy["n_comp"] = n_col
    crit_ocup = df_ocup_copy.groupby("day").agg(max_chairs=("chairs_used", "max"), max_nurses=("n_comp", "max"), max_pharmacy=("pharmacy_used", "max")).reset_index()
    crit_df = pd.merge(crit_stats, crit_ocup, on="day", how="left")
    crit_df["dia_calendario"] = crit_df["day"] + 1
    crit_df = crit_df.sort_values(by=["modulos_extra", "modulos_trat", "espera_max", "max_nurses", "max_pharmacy"], ascending=[False, False, False, False, False]).head(5)
    st.dataframe(crit_df[["day", "dia_calendario", "sesiones", "modulos_trat", "modulos_extra", "espera_max", "max_chairs", "max_nurses", "max_pharmacy"]], use_container_width=True)

def render_dia_especifico(day):
    day_df = df_prog[df_prog["day"] == day]
    day_ocup = df_ocup[df_ocup["day"] == day].copy()
    if day_df.empty:
        st.info("No hay datos para el día seleccionado.")
        return
        
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Sesiones", len(day_df))
    c2.metric("Pacientes Únicos", day_df["patient_id"].nunique())
    c3.metric("Módulos de Tratamiento", day_df["treatment_modules"].sum())
    c4.metric("Módulos Extra", day_df["extra_chair_modules"].sum())
    
    if "nurse_events" in day_ocup.columns: n_col = day_ocup["nurse_events"]
    elif "nurse_starts" in day_ocup.columns: n_col = day_ocup["nurse_starts"] + day_ocup.get("nurse_ends", 0)
    else: n_col = 0
    day_ocup["n_comp"] = n_col
    
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("Espera Máxima", f"{day_df['wait_after_pharmacy'].max()} mod")
    c6.metric("Peak Sillas", day_ocup["chairs_used"].max() if not day_ocup.empty else 0)
    c7.metric("Peak Enfermería", day_ocup["n_comp"].max() if not day_ocup.empty else 0)
    c8.metric("Peak Farmacia", day_ocup["pharmacy_used"].max() if not day_ocup.empty else 0)
    
    st.markdown("<br>", unsafe_allow_html=True)
    t_sillas, t_pacs, t_recs = st.tabs(["🪑 Sillas", "👥 Pacientes", "⚙️ Recursos"])
    
    with t_sillas:
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
            fig.add_trace(go.Bar(x=[r["treatment_modules"]], y=[f"Silla {int(r['chair_id'])}"], base=[r["treatment_start"]], orientation="h", marker_color=color_map[r["patient_type"]], name=f"Tipo {r['patient_type']}", hoverinfo="text", hovertext=hover, text=f"Pat {r['patient_id']}", textposition="inside"))
        fig.add_vline(x=48, line_width=2, line_dash="dash", line_color="#f43f5e", annotation_text="Jornada Extra")
        fig.update_layout(barmode="stack", showlegend=False, xaxis=dict(title="Módulos", range=[0, 56], tick0=0, dtick=4, gridcolor="#f0f0f0"), yaxis=dict(type="category", categoryorder="array", categoryarray=[f"Silla {i}" for i in range(15, 0, -1)]), plot_bgcolor="rgba(0,0,0,0)", margin=dict(l=80, r=20, t=40, b=40))
        st.plotly_chart(fig, use_container_width=True)
        
    with t_pacs:
        fig2 = go.Figure()
        day_df_s = day_df.sort_values("treatment_start", ascending=False)
        pharm_x, pharm_y, pharm_base, pharm_h = [], [], [], []
        wait_x, wait_y, wait_base, wait_h = [], [], [], []
        treat_x, treat_y, treat_base, treat_h = [], [], [], []
        for _, r in day_df_s.iterrows():
            pid = f"Pat {r['patient_id']}"
            h_str = (f"Pat: {r['patient_id']} | Tipo: {r['patient_type']}<br>"
                     f"Silla {r['chair_id']} | Extra {r['extra_chair_modules']}<br>"
                     f"Farmacia: {r['pharmacy_start']} - {r['pharmacy_end']}<br>"
                     f"Tratamiento: {r['treatment_start']} - {r['treatment_end']}")
            if r["pharmacy_modules"] > 0: pharm_x.append(r["pharmacy_modules"]); pharm_y.append(pid); pharm_base.append(r["pharmacy_start"]); pharm_h.append(h_str)
            if r["wait_after_pharmacy"] > 0: wait_x.append(r["wait_after_pharmacy"]); wait_y.append(pid); wait_base.append(r["pharmacy_end"]); wait_h.append(h_str)
            if r["treatment_modules"] > 0: treat_x.append(r["treatment_modules"]); treat_y.append(pid); treat_base.append(r["treatment_start"]); treat_h.append(h_str)
        if pharm_x: fig2.add_trace(go.Bar(x=pharm_x, y=pharm_y, base=pharm_base, orientation='h', name='Farmacia', marker_color="#38bdf8", hovertext=pharm_h, hoverinfo='text'))
        if wait_x: fig2.add_trace(go.Bar(x=wait_x, y=wait_y, base=wait_base, orientation='h', name='Espera', marker_color="#f43f5e", hovertext=wait_h, hoverinfo='text'))
        if treat_x: fig2.add_trace(go.Bar(x=treat_x, y=treat_y, base=treat_base, orientation='h', name='Tratamiento', marker_color="#10b981", hovertext=treat_h, hoverinfo='text'))
        fig2.add_vline(x=48, line_width=2, line_dash="dash", line_color="#f43f5e")
        fig2.update_layout(barmode="stack", xaxis=dict(title="Módulos", range=[0, 56], tick0=0, dtick=4, gridcolor="#f0f0f0"), yaxis=dict(type="category"), plot_bgcolor="rgba(0,0,0,0)")
        st.plotly_chart(fig2, use_container_width=True)
        
    with t_recs:
        if day_ocup.empty: st.info("No hay datos de ocupación.")
        else:
            fig3 = go.Figure()
            fig3.add_trace(go.Bar(x=day_ocup["module"], y=day_ocup["chairs_used"], name="Sillas", marker_color="#6366f1"))
            fig3.add_trace(go.Scatter(x=day_ocup["module"], y=day_ocup["chair_capacity"], name="Cap Sillas", mode="lines", line=dict(dash="dash", color="#a0aec0")))
            fig3.add_trace(go.Bar(x=day_ocup["module"], y=day_ocup["n_comp"], name="Enfermería", marker_color="#8b5cf6"))
            fig3.add_trace(go.Scatter(x=day_ocup["module"], y=day_ocup["nurse_capacity"], name="Cap Enfermería", mode="lines", line=dict(dash="dash", color="#a0aec0")))
            fig3.add_trace(go.Bar(x=day_ocup["module"], y=day_ocup["pharmacy_used"], name="Farmacia", marker_color="#38bdf8"))
            fig3.add_trace(go.Scatter(x=day_ocup["module"], y=day_ocup["pharmacy_capacity"], name="Cap Farmacia", mode="lines", line=dict(dash="dash", color="#a0aec0")))
            fig3.add_vline(x=48, line_width=2, line_dash="dash", line_color="#f43f5e")
            fig3.update_layout(barmode="group", plot_bgcolor="rgba(0,0,0,0)", xaxis=dict(gridcolor="#f0f0f0"))
            st.plotly_chart(fig3, use_container_width=True)

def render_datos():
    col1, col2 = st.columns(2)
    with col1: st.download_button("📥 Descargar Programación (CSV)", df_prog.to_csv(index=False), "programacion_filtrada.csv", "text/csv")
    with col2: st.download_button("📥 Descargar Ocupación (CSV)", df_ocup.to_csv(index=False), "ocupacion_filtrada.csv", "text/csv")
        
    st.markdown("---")
    show_prog = st.checkbox("Mostrar programación filtrada")
    show_ocup = st.checkbox("Mostrar ocupación filtrada")
    show_res = st.checkbox("Mostrar resumen si existe")
    
    if show_prog:
        df_prog_show = df_prog.copy()
        df_prog_show["dia_calendario"] = df_prog_show["day"] + 1
        df_prog_show["en_horario"] = df_prog_show["treatment_end"] <= 47
        st.dataframe(df_prog_show, use_container_width=True)
    if show_ocup: st.dataframe(df_ocup, use_container_width=True)
    if show_res and not df_res.empty: st.dataframe(df_res, use_container_width=True)

# ---------------------------------------------------------
# 6. ROUTER
# ---------------------------------------------------------
tab1, tab2, tab3 = st.tabs(["📊 Resumen", "📅 Día Específico", "🗄️ Datos"])

with tab1: render_resumen()
with tab2: render_dia_especifico(selected_day)
with tab3: render_datos()
