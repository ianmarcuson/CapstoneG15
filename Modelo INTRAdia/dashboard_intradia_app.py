"""
Instrucciones de uso:
1. Instalar dependencias:
   pip install streamlit pandas plotly openpyxl
2. Ejecutar la aplicación:
   streamlit run dashboard_intradia_app.py
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import os

st.set_page_config(page_title="Dashboard Intradía", layout="wide")

st.title("Dashboard de Planificación Intradiaria")
st.subheader("Centro Oncológico | Análisis local")

# Sidebar
st.sidebar.header("Configuración")
uploaded_file = st.sidebar.file_uploader("Cargar archivo Excel (opcional)", type=["xlsx"])

@st.cache_data
def load_data(file):
    try:
        xls = pd.ExcelFile(file)
        df_res = xls.parse("Resumen_Dias") if "Resumen_Dias" in xls.sheet_names else pd.DataFrame()
        df_prog = xls.parse("Programacion")
        df_ocup = xls.parse("Ocupacion_Modulos")
        df_cg = xls.parse("CG_Historial") if "CG_Historial" in xls.sheet_names else pd.DataFrame()
        return df_res, df_prog, df_ocup, df_cg
    except Exception as e:
        return None, None, None, None

file_to_load = None
if uploaded_file is not None:
    file_to_load = uploaded_file
else:
    # Look in local dir
    if os.path.exists("solution_deldia_v2.xlsx"):
        file_to_load = "solution_deldia_v2.xlsx"
    elif os.path.exists("475_solution_deldia_v2.xlsx"):
        file_to_load = "475_solution_deldia_v2.xlsx"

if file_to_load is None:
    st.error("No se encontró 'solution_deldia_v2.xlsx' ni '475_solution_deldia_v2.xlsx' en el directorio. Por favor carga un archivo en la barra lateral.")
    st.stop()

df_res, df_prog, df_ocup, df_cg = load_data(file_to_load)

if df_prog is None or df_prog.empty:
    st.error("Error al leer el archivo. Asegúrate de que contiene la hoja 'Programacion'.")
    st.stop()
if df_ocup is None or df_ocup.empty:
    st.error("Error al leer el archivo. Asegúrate de que contiene la hoja 'Ocupacion_Modulos'.")
    st.stop()

# --- FILTROS ---
min_day = int(df_prog["day"].min())
max_day = int(df_prog["day"].max())

if min_day == max_day:
    range_days = (min_day, max_day)
else:
    range_days = st.sidebar.slider("Rango de Días", min_value=min_day, max_value=max_day, value=(min_day, max_day))

start_d, end_d = range_days

st.sidebar.markdown("---")
specific_day = st.sidebar.number_input("Seleccionar Día para Detalle", min_value=start_d, max_value=end_d, value=start_d)

# Filtrar data
mask_prog = (df_prog["day"] >= start_d) & (df_prog["day"] <= end_d)
f_prog = df_prog[mask_prog]

mask_ocup = (df_ocup["day"] >= start_d) & (df_ocup["day"] <= end_d)
f_ocup = df_ocup[mask_ocup]

if f_prog.empty or f_ocup.empty:
    st.warning("No hay datos para el rango seleccionado.")
    st.stop()

# --- KPIs ---
total_sessions = len(f_prog)
unique_patients = f_prog["patient_id"].nunique()

cumplimiento_horario = (f_prog["treatment_end"] <= 47).sum() / total_sessions * 100 if total_sessions > 0 else 0

total_extra_modules = f_prog["extra_chair_modules"].sum()
days_with_extra = f_prog[f_prog["extra_chair_modules"] > 0]["day"].nunique()

max_wait = f_prog["wait_after_pharmacy"].max()
avg_wait = f_prog["wait_after_pharmacy"].mean()

total_chairs_used = f_ocup["chairs_used"].sum()
total_chairs_cap = f_ocup["chair_capacity"].sum()
util_chairs = (total_chairs_used / total_chairs_cap * 100) if total_chairs_cap > 0 else 0

reg_ocup = f_ocup[f_ocup["is_extra"] == 0]
reg_chairs_used = reg_ocup["chairs_used"].sum()
reg_chairs_cap = reg_ocup["chair_capacity"].sum()
util_chairs_reg = (reg_chairs_used / reg_chairs_cap * 100) if reg_chairs_cap > 0 else 0

if "nurse_events" in f_ocup.columns:
    nurse_used = f_ocup["nurse_events"].sum()
else:
    nurse_used = f_ocup["nurse_starts"].sum() + f_ocup["nurse_ends"].sum()
nurse_cap = f_ocup["nurse_capacity"].sum()
util_nurses = (nurse_used / nurse_cap * 100) if nurse_cap > 0 else 0

pharm_used = f_ocup["pharmacy_used"].sum()
pharm_cap = f_ocup["pharmacy_capacity"].sum()
util_pharm = (pharm_used / pharm_cap * 100) if pharm_cap > 0 else 0

daily_load = f_prog.groupby("day")["treatment_modules"].sum()
most_loaded_day = daily_load.idxmax() if not daily_load.empty else "N/A"

# --- INSIGHTS AUTOMÁTICOS ---
st.markdown("### 💡 Insights Automáticos")
insights = []
if total_extra_modules == 0:
    insights.append("✅ No se usaron módulos extraordinarios en el período.")
else:
    insights.append(f"⚠️ Se usaron {total_extra_modules} módulos extra distribuidos en {days_with_extra} días.")

if cumplimiento_horario < 95:
    insights.append(f"⚠️ Hay sesiones que terminan fuera del horario regular (Cumplimiento: {cumplimiento_horario:.1f}%).")
else:
    insights.append(f"✅ Excelente cumplimiento del horario regular ({cumplimiento_horario:.1f}%).")

if max_wait > 6:
    insights.append(f"⚠️ Se detectan esperas intradía altas (Máxima: {max_wait} módulos = {max_wait*15} min).")

insights.append(f"📅 El día más cargado fue el Día {most_loaded_day} con {daily_load.max() if not daily_load.empty else 0} módulos de tratamiento.")

recursos = {"Sillas": util_chairs, "Enfermería": util_nurses, "Farmacia": util_pharm}
max_recurso = max(recursos, key=recursos.get)
insights.append(f"📊 El recurso más utilizado promedio fue **{max_recurso}** ({recursos[max_recurso]:.1f}%).")

for ins in insights:
    st.markdown(f"- {ins}")

st.markdown("---")

# --- MAIN TABS ---
tab1, tab2, tab3, tab4 = st.tabs(["📊 Resumen", "⚙️ Recursos", "📅 Día Específico", "🗄️ Datos"])

with tab1:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Sesiones", total_sessions)
    col2.metric("Pacientes Únicos", unique_patients)
    col3.metric("Cumpl. Horario Reg.", f"{cumplimiento_horario:.1f}%")
    col4.metric("Día Más Cargado", f"Día {most_loaded_day}")
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Módulos Extra", total_extra_modules)
    col2.metric("Días con Extra", days_with_extra)
    col3.metric("Espera Máx", f"{max_wait} mod ({max_wait*15} min)")
    col4.metric("Espera Promedio", f"{avg_wait:.1f} mod ({int(avg_wait*15)} min)")
    
    st.markdown("### Carga Diaria")
    daily_stats = f_prog.groupby("day").agg(
        Tratamiento=("treatment_modules", "sum"),
        Sesiones=("session", "count"),
        Extra=("extra_chair_modules", "sum")
    ).reset_index()
    
    fig1 = px.bar(daily_stats, x="day", y=["Tratamiento", "Extra"], 
                  title="Módulos de Tratamiento y Extra por Día",
                  labels={"value": "Módulos", "variable": "Tipo", "day": "Día"},
                  barmode="stack", color_discrete_sequence=["#10b981", "#f43f5e"])
    st.plotly_chart(fig1, use_container_width=True)
    
    fig2 = px.line(daily_stats, x="day", y="Sesiones", title="Sesiones por Día", markers=True)
    st.plotly_chart(fig2, use_container_width=True)

with tab2:
    st.markdown("### Utilización de Recursos (Promedio)")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Sillas (Total)", f"{util_chairs:.1f}%")
    col2.metric("Sillas (Regular)", f"{util_chairs_reg:.1f}%")
    col3.metric("Enfermería", f"{util_nurses:.1f}%")
    col4.metric("Farmacia", f"{util_pharm:.1f}%")
    
    if "nurse_events" in f_ocup.columns:
        n_col = f_ocup["nurse_events"]
    else:
        n_col = f_ocup["nurse_starts"] + f_ocup["nurse_ends"]
        
    f_ocup_copy = f_ocup.copy()
    f_ocup_copy["nurse_computed"] = n_col
    
    ocup_avg = f_ocup_copy.groupby("module").agg(
        Sillas=("chairs_used", "mean"),
        Enfermería=("nurse_computed", "mean"),
        Farmacia=("pharmacy_used", "mean"),
        Cap_Sillas=("chair_capacity", "max"),
        Cap_Enfermería=("nurse_capacity", "max"),
        Cap_Farmacia=("pharmacy_capacity", "max")
    ).reset_index()
    
    fig_res = go.Figure()
    fig_res.add_trace(go.Bar(x=ocup_avg["module"], y=ocup_avg["Sillas"], name="Sillas Promedio", marker_color="#6366f1"))
    fig_res.add_trace(go.Scatter(x=ocup_avg["module"], y=ocup_avg["Cap_Sillas"], name="Cap Sillas", mode="lines", line=dict(dash="dash", color="#6366f1")))
    
    fig_res.add_trace(go.Bar(x=ocup_avg["module"], y=ocup_avg["Enfermería"], name="Enfermeras Promedio", marker_color="#8b5cf6"))
    fig_res.add_trace(go.Scatter(x=ocup_avg["module"], y=ocup_avg["Cap_Enfermería"], name="Cap Enfermería", mode="lines", line=dict(dash="dash", color="#8b5cf6")))
    
    fig_res.add_trace(go.Bar(x=ocup_avg["module"], y=ocup_avg["Farmacia"], name="Farmacia Promedio", marker_color="#ec4899"))
    fig_res.add_trace(go.Scatter(x=ocup_avg["module"], y=ocup_avg["Cap_Farmacia"], name="Cap Farmacia", mode="lines", line=dict(dash="dash", color="#ec4899")))
    
    fig_res.update_layout(title="Perfil Promedio de Ocupación (Módulo 0-55)", xaxis_title="Módulo", yaxis_title="Uso Promedio", barmode="group")
    st.plotly_chart(fig_res, use_container_width=True)
    
    st.markdown("### Top Días Críticos")
    crit_stats = f_prog.groupby("day").agg(
        sesiones=("session", "count"),
        modulos_trat=("treatment_modules", "sum"),
        modulos_extra=("extra_chair_modules", "sum"),
        espera_max=("wait_after_pharmacy", "max")
    ).reset_index()
    
    crit_ocup = f_ocup_copy.groupby("day").agg(
        max_chairs=("chairs_used", "max"),
        max_nurses=("nurse_computed", "max"),
        max_pharmacy=("pharmacy_used", "max")
    ).reset_index()
    
    crit_df = pd.merge(crit_stats, crit_ocup, on="day")
    crit_df["dia_calendario"] = crit_df["day"] + 1
    crit_df = crit_df.sort_values(by="modulos_trat", ascending=False).head(10)
    
    st.dataframe(crit_df[["day", "dia_calendario", "sesiones", "modulos_trat", "modulos_extra", "espera_max", "max_chairs", "max_nurses", "max_pharmacy"]], use_container_width=True)

with tab3:
    st.markdown(f"### Detalle Día {specific_day}")
    day_prog = f_prog[f_prog["day"] == specific_day].copy()
    day_ocup = f_ocup[f_ocup["day"] == specific_day].copy()
    
    if day_prog.empty:
        st.info("No hay sesiones programadas para este día.")
    else:
        st.markdown("#### Tabla de Sesiones")
        st.dataframe(day_prog[["patient_id", "patient_type", "pharmacy_start", "pharmacy_modules", "wait_after_pharmacy", "treatment_start", "treatment_modules", "extra_chair_modules"]], use_container_width=True)
        
        st.markdown("#### Ocupación Intradía por Módulo")
        fig_d_res = go.Figure()
        fig_d_res.add_trace(go.Bar(x=day_ocup["module"], y=day_ocup["chairs_used"], name="Sillas", marker_color="#6366f1"))
        fig_d_res.add_trace(go.Scatter(x=day_ocup["module"], y=day_ocup["chair_capacity"], name="Cap Sillas", mode="lines", line=dict(dash="dash", color="#ef4444")))
        
        if "nurse_events" in day_ocup.columns:
            day_n_events = day_ocup["nurse_events"]
        else:
            day_n_events = day_ocup["nurse_starts"] + day_ocup["nurse_ends"]
            
        fig_d_res.add_trace(go.Bar(x=day_ocup["module"], y=day_n_events, name="Enfermeras", marker_color="#8b5cf6"))
        fig_d_res.add_trace(go.Bar(x=day_ocup["module"], y=day_ocup["pharmacy_used"], name="Farmacia", marker_color="#ec4899"))
        
        fig_d_res.update_layout(barmode="group", xaxis_title="Módulo", yaxis_title="Uso")
        st.plotly_chart(fig_d_res, use_container_width=True)
        
        st.markdown("#### Gantt de Pacientes")
        gantt_data = []
        day_prog = day_prog.sort_values(by="treatment_start", ascending=False)
        
        pharm_x, pharm_y, pharm_base = [], [], []
        wait_x, wait_y, wait_base = [], [], []
        treat_x, treat_y, treat_base = [], [], []
        
        for _, row in day_prog.iterrows():
            pid = f"Pat {int(row['patient_id'])}"
            if row["pharmacy_modules"] > 0:
                pharm_x.append(row["pharmacy_modules"])
                pharm_y.append(pid)
                pharm_base.append(row["pharmacy_start"])
            
            if row["wait_after_pharmacy"] > 0:
                wait_x.append(row["wait_after_pharmacy"])
                wait_y.append(pid)
                wait_base.append(row["pharmacy_start"] + row["pharmacy_modules"])
                
            if row["treatment_modules"] > 0:
                treat_x.append(row["treatment_modules"])
                treat_y.append(pid)
                treat_base.append(row["treatment_start"])
                
        fig_gantt = go.Figure()
        if pharm_x:
            fig_gantt.add_trace(go.Bar(x=pharm_x, y=pharm_y, base=pharm_base, orientation='h', name='Farmacia', marker_color='#38bdf8'))
        if wait_x:
            fig_gantt.add_trace(go.Bar(x=wait_x, y=wait_y, base=wait_base, orientation='h', name='Espera', marker_color='#f43f5e'))
        if treat_x:
            fig_gantt.add_trace(go.Bar(x=treat_x, y=treat_y, base=treat_base, orientation='h', name='Tratamiento', marker_color='#10b981'))
            
        fig_gantt.update_layout(barmode='stack', xaxis=dict(title='Módulo', range=[0, 56], tick0=0, dtick=4), yaxis=dict(type='category'))
        st.plotly_chart(fig_gantt, use_container_width=True)

with tab4:
    st.markdown("### Datos Crudos")
    if not df_res.empty:
        st.markdown("#### Resumen")
        st.dataframe(df_res, use_container_width=True)
    st.markdown("#### Programación")
    st.dataframe(f_prog, use_container_width=True)
    st.markdown("#### Ocupación")
    st.dataframe(f_ocup, use_container_width=True)
