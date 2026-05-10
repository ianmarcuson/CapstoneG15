new_code = r'''import pandas as pd
import json
import os

def load_data(excel_path="solution_deldia_v2.xlsx"):
    print(f"Cargando datos desde {excel_path}...")
    df_prog = pd.read_excel(excel_path, sheet_name="Programacion")
    df_ocup = pd.read_excel(excel_path, sheet_name="Ocupacion_Modulos")
    
    # Asegurarnos de que están ordenados
    df_prog = df_prog.sort_values(["day", "treatment_start"])
    df_ocup = df_ocup.sort_values(["day", "module"])
    
    dashboard_data = {}
    
    days = df_prog["day"].unique()
    for d in days:
        day_prog = df_prog[df_prog["day"] == d]
        day_ocup = df_ocup[df_ocup["day"] == d]
        
        patients = []
        for _, row in day_prog.iterrows():
            pharm_start = int(row["pharmacy_start"])
            pharm_len = int(row["pharmacy_modules"])
            treat_start = int(row["treatment_start"])
            treat_len = int(row["treatment_modules"])
            
            wait_start = pharm_start + pharm_len
            wait_len = treat_start - wait_start
            
            patients.append({
                "id": int(row["row_idx"]),
                "pid": int(row["patient_id"]),
                "type": int(row["patient_type"]),
                "pharm_start": pharm_start,
                "pharm_len": pharm_len,
                "wait_start": wait_start,
                "wait_len": wait_len,
                "treat_start": treat_start,
                "treat_len": treat_len
            })
            
        # Greedy chair assignment
        chair_free_at = [0] * 15
        patients_sorted = sorted(patients, key=lambda p: p['treat_start'])
        for p in patients_sorted:
            assigned = False
            for c in range(15):
                if chair_free_at[c] <= p['treat_start']:
                    p['chair_id'] = c + 1
                    chair_free_at[c] = p['treat_start'] + p['treat_len']
                    assigned = True
                    break
            if not assigned:
                p['chair_id'] = 16
        
        occupancy = {
            "chairs": day_ocup["chairs_used"].tolist(),
            "nurses": day_ocup["nurse_events"].tolist() if "nurse_events" in day_ocup.columns else day_ocup["nurse_starts"].tolist(),
            "pharmacy": day_ocup["pharmacy_used"].tolist(),
            "cap_chairs": int(day_ocup["chair_capacity"].iloc[0]),
            "cap_nurses": int(day_ocup["nurse_capacity"].iloc[0]),
            "cap_pharmacy": int(day_ocup["pharmacy_capacity"].iloc[0])
        }
        
        week = (d // 7) + 1
        
        dashboard_data[str(d)] = {
            "day": int(d),
            "week": int(week),
            "patients": patients,
            "occupancy": occupancy
        }
        
    return dashboard_data

def generate_html(dashboard_data, output_path="dashboard_intradia.html"):
    print("Generando HTML...")
    
    json_data = json.dumps(dashboard_data)
    
    html_content = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dashboard Intradía</title>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
        
        :root {
            --bg-color: #f8fafc;
            --card-bg: #ffffff;
            --text-main: #0f172a;
            --text-muted: #64748b;
            --primary: #2563eb;
            --border: #e2e8f0;
            --pharm-color: #38bdf8;
            --wait-color: #f43f5e;
            --treat-color: #10b981;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            padding: 2rem;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
        }

        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 2rem;
            padding-bottom: 1rem;
            border-bottom: 1px solid var(--border);
        }

        h1 { font-weight: 700; font-size: 1.5rem; letter-spacing: -0.025em; }

        .controls {
            display: flex;
            gap: 1rem;
            align-items: center;
        }

        .controls input {
            padding: 0.5rem;
            border-radius: 8px;
            border: 1px solid var(--border);
            font-family: 'Inter', sans-serif;
            font-size: 0.95rem;
            width: 80px;
            text-align: center;
            background: var(--card-bg);
            outline: none;
            transition: border-color 0.2s;
        }
        
        .controls input:focus { border-color: var(--primary); }
        
        .controls button {
            padding: 0.5rem 1rem;
            border-radius: 8px;
            border: none;
            background: var(--primary);
            color: white;
            font-family: 'Inter', sans-serif;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        .controls button:hover {
            background: #1d4ed8;
        }
        
        .toggle-group {
            display: flex;
            background: var(--border);
            border-radius: 8px;
            padding: 0.25rem;
        }
        
        .toggle-btn {
            padding: 0.4rem 1rem;
            border: none;
            background: transparent;
            color: var(--text-muted);
            border-radius: 6px;
            cursor: pointer;
            font-weight: 500;
            transition: all 0.2s;
        }
        
        .toggle-btn.active {
            background: white;
            color: var(--text-main);
            box-shadow: 0 1px 2px rgba(0,0,0,0.1);
        }

        .card {
            background: var(--card-bg);
            border-radius: 12px;
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            box-shadow: 0 1px 3px rgba(0,0,0,0.05), 0 1px 2px rgba(0,0,0,0.03);
            border: 1px solid var(--border);
        }

        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
        }

        h2 {
            font-size: 1.1rem;
            font-weight: 600;
            color: var(--text-main);
        }

        .grid-3 {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 1.5rem;
        }
        
        .plot-container { width: 100%; height: 300px; }
        .plot-container.gantt { height: 600px; }

        .legend {
            display: flex;
            gap: 1.5rem;
            font-size: 0.85rem;
            color: var(--text-muted);
        }
        .legend-item { display: flex; align-items: center; gap: 0.4rem; }
        .dot { width: 10px; height: 10px; border-radius: 50%; }
        .dot.pharm { background: var(--pharm-color); }
        .dot.wait { background: var(--wait-color); }
        .dot.treat { background: var(--treat-color); }
    </style>
</head>
<body>

<div class="container">
    <header>
        <h1>Agendamiento Intradía</h1>
        <div class="controls">
            <label for="startDay" style="font-size: 0.9rem; color: var(--text-muted);">Día Inicio:</label>
            <input type="number" id="startDay" value="0" min="0" max="475">
            <label for="endDay" style="font-size: 0.9rem; color: var(--text-muted);">Día Fin:</label>
            <input type="number" id="endDay" value="0" min="0" max="475">
            <button id="btnFilter">Actualizar</button>
        </div>
    </header>

    <div class="card">
        <div class="card-header">
            <h2 id="ganttTitle">Programación (Vista por Sillas)</h2>
            <div class="toggle-group">
                <button id="btnViewChair" class="toggle-btn active">Vista Sillas</button>
                <button id="btnViewPat" class="toggle-btn">Vista Pacientes</button>
            </div>
        </div>
        <div class="legend" id="ganttLegend">
            <!-- Dynamic Legend -->
        </div>
        <div id="ganttChart" class="plot-container gantt" style="display: none;"></div>
        <div id="chairChart" class="plot-container gantt"></div>
    </div>

    <div class="grid-3">
        <div class="card">
            <h2>Ocupación de Sillas</h2>
            <div id="chairsChart" class="plot-container"></div>
        </div>
        <div class="card">
            <h2>Carga de Enfermería</h2>
            <div id="nursesChart" class="plot-container"></div>
        </div>
        <div class="card">
            <h2>Carga de Farmacia</h2>
            <div id="pharmacyChart" class="plot-container"></div>
        </div>
    </div>
</div>

<script>
    const data = JSON_DATA_PLACEHOLDER;
    
    const startInput = document.getElementById('startDay');
    const endInput = document.getElementById('endDay');
    const btnFilter = document.getElementById('btnFilter');
    const btnViewChair = document.getElementById('btnViewChair');
    const btnViewPat = document.getElementById('btnViewPat');
    const ganttChart = document.getElementById('ganttChart');
    const chairChart = document.getElementById('chairChart');
    const ganttTitle = document.getElementById('ganttTitle');
    const ganttLegend = document.getElementById('ganttLegend');
    
    let currentView = 'chair'; // 'chair' or 'patient'
    
    // Configurar límites basados en los datos
    const availableDays = Object.keys(data).map(Number).sort((a,b)=>a-b);
    if(availableDays.length > 0) {
        startInput.value = availableDays[0];
        endInput.value = availableDays[availableDays.length - 1];
    }
    
    const commonLayout = {
        font: { family: 'Inter, sans-serif', color: '#64748b' },
        margin: { t: 10, r: 10, b: 40, l: 40 },
        paper_bgcolor: 'rgba(0,0,0,0)',
        plot_bgcolor: 'rgba(0,0,0,0)',
        hovermode: 'closest'
    };

    function updateLegend() {
        if(currentView === 'chair') {
            ganttTitle.textContent = "Programación (Vista por Sillas)";
            ganttLegend.innerHTML = '<div class="legend-item"><div class="dot treat"></div>Tratamiento</div>';
        } else {
            ganttTitle.textContent = "Programación (Vista por Pacientes)";
            ganttLegend.innerHTML = '<div class="legend-item"><div class="dot pharm"></div>Farmacia</div><div class="legend-item"><div class="dot wait"></div>Espera</div><div class="legend-item"><div class="dot treat"></div>Tratamiento en Silla</div>';
        }
    }

    function drawCharts() {
        updateLegend();
        
        const startDay = parseInt(startInput.value);
        const endDay = parseInt(endInput.value);
        
        let allPatients = [];
        let allChairs = [], allNurses = [], allPharmacy = [], xResource = [];
        let capChairs = 0, capNurses = 0, capPharmacy = 0;
        let dayShapesH = []; // Horizontal dividers (for Chair View)
        let dayShapesV = []; // Vertical dividers (for Patient View & Resources)
        
        for(let d = startDay; d <= endDay; d++) {
            const dayData = data[d];
            if(!dayData) continue;
            
            capChairs = dayData.occupancy.cap_chairs;
            capNurses = dayData.occupancy.cap_nurses;
            capPharmacy = dayData.occupancy.cap_pharmacy;
            
            allChairs.push(...dayData.occupancy.chairs);
            allNurses.push(...dayData.occupancy.nurses);
            allPharmacy.push(...dayData.occupancy.pharmacy);
            
            for(let m=0; m<56; m++) {
                xResource.push(d * 56 + m);
            }
            
            dayShapesV.push({
                type: 'line', x0: d * 56, x1: d * 56, y0: 0, y1: 1, yref: 'paper',
                line: { color: '#cbd5e1', width: 1, dash: 'dot' }
            });
            
            dayShapesH.push({
                type: 'line', y0: d * 56, y1: d * 56, x0: 0, x1: 1, xref: 'paper',
                line: { color: '#cbd5e1', width: 2, dash: 'solid' }
            });
            
            dayData.patients.forEach(p => {
                allPatients.push({
                    ...p,
                    abs_pharm_start: d * 56 + p.pharm_start,
                    abs_wait_start: d * 56 + p.wait_start,
                    abs_treat_start: d * 56 + p.treat_start,
                    day: d
                });
            });
        }
        
        if(allPatients.length === 0) return;
        
        // --- CHAIR CHART (X=Chairs, Y=Modules reversed) ---
        const chairX = [], chairY = [], chairBase = [], chairTexts = [], chairHovers = [];
        // Max 15 chairs
        const chairCategories = Array.from({length: 15}, (_, i) => `Silla ${i+1}`);
        
        allPatients.forEach(p => {
            chairX.push(`Silla ${p.chair_id}`);
            chairY.push(p.treat_len);
            chairBase.push(p.abs_treat_start);
            chairTexts.push(`${p.id}`); // Solo el ID dentro de la barra
            chairHovers.push(`Día: ${p.day} | Paciente: ${p.id}<br>Módulos: ${p.treat_start} - ${p.treat_start+p.treat_len}`);
        });
        
        const chairPlotData = [{
            x: chairX, y: chairY, base: chairBase, type: 'bar', orientation: 'v',
            marker: { color: '#10b981', opacity: 0.9, line: {color: 'white', width: 1} }, 
            name: 'Tratamiento', text: chairTexts, hoverinfo: 'text', textposition: 'inside', hovertext: chairHovers, insidetextanchor: 'middle'
        }];
        
        const chairLayout = { ...commonLayout,
            margin: { t: 10, r: 10, b: 40, l: 60 },
            barmode: 'stack', showlegend: false,
            xaxis: { type: 'category', categoryarray: chairCategories, gridcolor: '#f1f5f9' },
            yaxis: { title: 'Módulos Absolutos (Día × 56 + Módulo)', gridcolor: '#f1f5f9', autorange: 'reversed' },
            shapes: dayShapesH
        };
        Plotly.newPlot('chairChart', chairPlotData, chairLayout, {displayModeBar: false});


        // --- PATIENT CHART (X=Modules, Y=Patients) ---
        const ganttData = [];
        const sortedPatients = [...allPatients].sort((a,b) => a.abs_treat_start - b.abs_treat_start).reverse();
        
        const pharmX = [], pharmY = [], pharmBase = [];
        const waitX = [], waitY = [], waitBase = [];
        const treatX = [], treatY = [], treatBase = [];
        const hoverTexts = [];
        
        sortedPatients.forEach(p => {
            const yLabel = `D${p.day}-P${p.id}`;
            if(p.pharm_len > 0) {
                pharmX.push(p.pharm_len); pharmY.push(yLabel); pharmBase.push(p.abs_pharm_start);
            }
            if(p.wait_len > 0) {
                waitX.push(p.wait_len); waitY.push(yLabel); waitBase.push(p.abs_wait_start);
            }
            if(p.treat_len > 0) {
                treatX.push(p.treat_len); treatY.push(yLabel); treatBase.push(p.abs_treat_start);
            }
            hoverTexts.push(`Día: ${p.day} | Paciente: ${p.id}<br>Farmacia: M${p.pharm_start}-M${p.pharm_start+p.pharm_len}<br>Tratamiento: M${p.treat_start}-M${p.treat_start+p.treat_len}`);
        });

        if(pharmX.length > 0) ganttData.push({ x: pharmX, y: pharmY, base: pharmBase, type: 'bar', orientation: 'h', marker: { color: '#38bdf8', opacity: 0.9 }, name: 'Farmacia', hoverinfo: 'none' });
        if(waitX.length > 0) ganttData.push({ x: waitX, y: waitY, base: waitBase, type: 'bar', orientation: 'h', marker: { color: '#f43f5e', opacity: 0.9 }, name: 'Espera', hoverinfo: 'none' });
        if(treatX.length > 0) ganttData.push({ x: treatX, y: treatY, base: treatBase, type: 'bar', orientation: 'h', marker: { color: '#10b981', opacity: 0.9 }, name: 'Tratamiento', text: hoverTexts, hoverinfo: 'text' });

        const ganttLayout = { ...commonLayout, 
            margin: { t: 10, r: 10, b: 40, l: 80 }, 
            barmode: 'stack', showlegend: false,
            xaxis: { gridcolor: '#f1f5f9', title: 'Módulos Absolutos' },
            yaxis: { type: 'category', gridcolor: '#f1f5f9' },
            shapes: dayShapesV
        };
        Plotly.newPlot('ganttChart', ganttData, ganttLayout, {displayModeBar: false});
        
        
        // --- RESOURCE CHARTS ---
        function drawResource(elementId, usage, capacity, color, name) {
            const trace = { x: xResource, y: usage, type: 'bar', marker: { color: color }, name: name };
            const capLine = {
                x: [xResource[0], xResource[xResource.length-1]+1], y: [capacity, capacity], type: 'scatter', mode: 'lines',
                line: { color: '#ef4444', width: 2, dash: 'dash' }, name: 'Capacidad'
            };
            const layout = { ...commonLayout, showlegend: false, 
                xaxis: { gridcolor: '#f1f5f9', title: 'Módulos Absolutos' },
                yaxis: { gridcolor: '#f1f5f9', range: [0, capacity + Math.max(2, capacity*0.2)] },
                shapes: dayShapesV
            };
            Plotly.newPlot(elementId, [trace, capLine], layout, {displayModeBar: false});
        }
        
        drawResource('chairsChart', allChairs, capChairs, '#6366f1', 'Sillas');
        drawResource('nursesChart', allNurses, capNurses, '#8b5cf6', 'Enfermeras');
        drawResource('pharmacyChart', allPharmacy, capPharmacy, '#ec4899', 'Farmacia');
    }

    // Handlers
    btnFilter.addEventListener('click', drawCharts);
    
    btnViewChair.addEventListener('click', () => {
        currentView = 'chair';
        btnViewChair.classList.add('active');
        btnViewPat.classList.remove('active');
        ganttChart.style.display = 'none';
        chairChart.style.display = 'block';
        updateLegend();
    });
    
    btnViewPat.addEventListener('click', () => {
        currentView = 'patient';
        btnViewPat.classList.add('active');
        btnViewChair.classList.remove('active');
        chairChart.style.display = 'none';
        ganttChart.style.display = 'block';
        updateLegend();
    });

    drawCharts();

</script>
</body>
</html>
"""
    html_content = html_content.replace("JSON_DATA_PLACEHOLDER", json_data)
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    print(f"HTML guardado exitosamente en: {output_path}")

if __name__ == "__main__":
    data = load_data("1-100solution_deldia_v2.xlsx")
    generate_html(data, "dashboard_intradia.html")
'''

with open('rewrite_dashboard.py', 'w', encoding='utf-8') as f:
    f.write(new_code)
