import gurobipy as gp
from gurobipy import GRB
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import warnings
import time
warnings.filterwarnings('ignore')


class ExecutionTimer:
    """Timer simple para medir etapas de ejecucion."""

    def __init__(self, name="Ejecucion"):
        self.name = name
        self.start = time.perf_counter()
        self.last = self.start
        print(f"[TIMER] Inicio {self.name}")

    def lap(self, label):
        now = time.perf_counter()
        print(f"[TIMER] {label}: +{now - self.last:.2f}s | total {now - self.start:.2f}s")
        self.last = now

    def finish(self, label=None):
        now = time.perf_counter()
        final_label = label or self.name
        print(f"[TIMER] Fin {final_label}: total {now - self.start:.2f}s")



class DataGenerator:
    """Genera datos sintéticos para el modelo con tasas de llegada reales por tipo de paciente."""
    
    def __init__(self, base_data_path="Data G15.xlsx"):
        """
        Inicializa el generador de datos.
        
        Args:
            base_data_path: Path al archivo Excel con datos base (por defecto busca Data G15.xlsx)
        """
        print(f"[INFO] Cargando datos base desde: {base_data_path}")
        timer = ExecutionTimer("carga de datos base")
        self.base_data = self._load_base_data(base_data_path)
        timer.finish("carga de datos base")
        
    def _load_base_data(self, path):
        """Carga y procesa los datos reales del Excel (Sheet1 y Sheet2)."""
        try:
            # === Sheet1: Parámetros generales ===
            timer = ExecutionTimer("lectura Excel")
            df_params = pd.read_excel(path, sheet_name='Sheet1', header=None)
            timer.lap("Sheet1 leida")
            capacity = {
                'chairs': int(df_params.iloc[2, 1]),           # n_sillas
                'modules_ordinary': int(df_params.iloc[4, 1]),
                'modules_extraordinary': int(df_params.iloc[5, 1]),
                'total_modules': int(df_params.iloc[4, 1] * df_params.iloc[0, 1] if False else 720),  # puedes ajustar
                'modulos_farmacia': int(df_params.iloc[6, 1]),
                'n_farmaceuticos': int(df_params.iloc[7, 1]),
            }

            # === Sheet2: Tipos de pacientes (14 tipos) ===
            df_types = pd.read_excel(path, sheet_name='Sheet2')
            timer.lap("Sheet2 leida")
            
            patient_types = {}
            for _, row in df_types.iterrows():
                pid = int(row['Id'])
                var = row['variable']
                val = row['valor']
                
                if pid not in patient_types:
                    patient_types[pid] = {}
                
                if var == 'Ciclos':
                    patient_types[pid]['ciclos'] = int(val)
                elif var == 'Sesiones':
                    patient_types[pid]['sesiones'] = int(val)
                elif var == 'Módulos':
                    patient_types[pid]['modulos'] = int(val)
                elif var == 'TBS':
                    patient_types[pid]['tbs'] = int(val)
                elif var == 'TBC':
                    patient_types[pid]['tbc'] = int(val)
                elif var == 'Tasa de Llegada':
                    patient_types[pid]['tasa_llegada'] = float(val)
                elif var == 'Módulos Lab.':
                    patient_types[pid]['modulos_lab'] = int(val)  # guardamos por si lo usas después

            print(f"[INFO] Tipos de pacientes cargados: {len(patient_types)}")
            timer.finish("lectura Excel")
            return {
                'capacity': capacity,
                'patient_types': patient_types
            }
            
        except Exception as e:
            print(f"⚠️ Error al leer Excel: {e}. Usando datos por defecto.")
            return self._get_default_base_data()

    def _get_default_base_data(self):
        """Datos por defecto (idénticos al Excel) por si falla la lectura."""
        return {
            'capacity': {
                'chairs': 15,
                'modules_ordinary': 48,
                'modules_extraordinary': 8,
                'total_modules': 720,
            },
            'patient_types': {
                1: {'ciclos': 1, 'sesiones': 24, 'modulos': 16, 'tbs': 14, 'tbc': 1, 'tasa_llegada': 0.0},
                2: {'ciclos': 1, 'sesiones': 12, 'modulos': 8,  'tbs': 21, 'tbc': 1, 'tasa_llegada': 0.06},
                3: {'ciclos': 1, 'sesiones': 24, 'modulos': 16, 'tbs': 14, 'tbc': 1, 'tasa_llegada': 0.58},
                4: {'ciclos': 1, 'sesiones': 6,  'modulos': 25, 'tbs': 21, 'tbc': 1, 'tasa_llegada': 0.3},
                5: {'ciclos': 1, 'sesiones': 24, 'modulos': 16, 'tbs': 14, 'tbc': 1, 'tasa_llegada': 0.44},
                6: {'ciclos': 1, 'sesiones': 15, 'modulos': 20, 'tbs': 21, 'tbc': 1, 'tasa_llegada': 0.19},
                7: {'ciclos': 1, 'sesiones': 4,  'modulos': 14, 'tbs': 21, 'tbc': 1, 'tasa_llegada': 0.72},
                8: {'ciclos': 1, 'sesiones': 5,  'modulos': 15, 'tbs': 21, 'tbc': 1, 'tasa_llegada': 0.27},
                9: {'ciclos': 9, 'sesiones': 5,  'modulos': 15, 'tbs': 1,  'tbc': 21, 'tasa_llegada': 0.1},
                10:{'ciclos': 1, 'sesiones': 24, 'modulos': 16, 'tbs': 14, 'tbc': 1, 'tasa_llegada': 1.01},
                11:{'ciclos': 1, 'sesiones': 5,  'modulos': 8,  'tbs': 21, 'tbc': 1, 'tasa_llegada': 0.16},
                12:{'ciclos': 1, 'sesiones': 4,  'modulos': 16, 'tbs': 14, 'tbc': 1, 'tasa_llegada': 0.08},
                13:{'ciclos': 1, 'sesiones': 8,  'modulos': 10, 'tbs': 14, 'tbc': 1, 'tasa_llegada': 0.04},
                14:{'ciclos': 1, 'sesiones': 12, 'modulos': 10, 'tbs': 14, 'tbc': 1, 'tasa_llegada': 0.1},
            }
        }

    def generate_patients(self, num_patients, time_horizon, arrival_horizon=None):
        """
        Genera pacientes usando la tasa de llegada REAL de cada tipo (Poisson).
        """
        timer = ExecutionTimer("generacion de pacientes")
        if arrival_horizon is None:
            arrival_horizon = 90
        
        patients = []
        patient_id = 1
        patient_types = self.base_data['patient_types']
        max_day = min(time_horizon, arrival_horizon + 1)
        print(f"[INFO] Generando hasta {num_patients} pacientes en {max_day} dias de llegada")
        
        for day in range(max_day):
            # Para cada tipo de paciente generamos llegadas según su tasa
            for ptype, info in patient_types.items():
                tasa = info.get('tasa_llegada', 0.0)
                if tasa <= 0:
                    continue
                    
                # Número de pacientes de este tipo que llegan hoy (distribución Poisson)
                arrivals_today = np.random.poisson(tasa)
                
                for _ in range(arrivals_today):
                    if patient_id > num_patients:
                        break
                    
                    patients.append({
                        'patient_id': patient_id,
                        'patient_type': ptype,
                        'arrival_day': day,
                        'cycles': info['ciclos'],
                        'sessions': info['sesiones'],
                        'modules_per_session': info['modulos'],
                        'days_between_sessions': info['tbs'],
                        'days_between_cycles': info['tbc'],
                    })
                    patient_id += 1
                    
            if patient_id > num_patients:
                break
            if (day + 1) % 10 == 0 or day == max_day - 1:
                print(f"[PROGRESO] Dia {day + 1}/{max_day}: {len(patients)} pacientes acumulados")
        
        df = pd.DataFrame(patients)
        print(f"✓ Generados {len(df)} pacientes (usando tasas reales del Excel)")
        timer.finish("generacion de pacientes")
        return df

    def generate_scenario(self, num_patients=150, arrival_horizon=90, time_horizon=1000):
        """Genera un escenario completo."""
        timer = ExecutionTimer("generacion de escenario")
        patients = self.generate_patients(num_patients, time_horizon, arrival_horizon)
        timer.lap("pacientes generados")
        
        scenario = {
            'patients': patients,
            'capacity': self.base_data['capacity'],
            'time_horizon': time_horizon,
            'arrival_horizon': arrival_horizon,
            'total_patients': len(patients),
        }
        timer.finish("generacion de escenario")
        return scenario


class InterdayModel:
    """Modelo de asignación de días en Gurobi."""
    
    def __init__(self, scenario_data):
        """
        Inicializa el modelo.
        
        Args:
            scenario_data: Diccionario con datos del escenario
        """
        self.scenario = scenario_data
        self.patients = scenario_data['patients']
        self.capacity = scenario_data['capacity']['total_modules']
        self.time_horizon = scenario_data['time_horizon']
        self.model = None
        self.variables = {}
        self.solution = None
        
        # Parámetros de peso en función objetivo
        self.alpha = 1.0    # Peso para ocupación máxima
        self.beta = 0.5     # Peso para holgura
        self.gamma = 0.1    # Peso para tiempo de espera
    
    def _build_model(self):
        """Construye el modelo de Gurobi."""
        timer = ExecutionTimer("construccion del modelo")
        self.model = gp.Model("Interday_Assignment")
        self.model.setParam('OutputFlag', 0)  # Suprimir output por defecto
        
        # Conjuntos
        P = range(len(self.patients))  # Pacientes
        T = range(self.time_horizon)   # Días
        
        # Crear diccionarios con información de pacientes
        patient_info = {}
        for idx, row in self.patients.iterrows():
            patient_info[idx] = {
                'cycles': int(row['cycles']),
                'sessions': int(row['sessions']),
                'modules': int(row['modules_per_session']),
                'tbs': int(row['days_between_sessions']),
                'tbc': int(row['days_between_cycles']),
                'arrival': int(row['arrival_day']),
            }
        print(f"[INFO] Pacientes: {len(patient_info)} | Horizonte: {self.time_horizon} dias")
        timer.lap("diccionario patient_info construido")
        
        # Variables de decisión
        # x[p,t,c,s] = 1 si paciente p se asigna al día t, ciclo c, sesión s
        x = {}
        print("[PROGRESO] Creando variables x[p,t,c,s]...")
        for p in P:
            info = patient_info[p]
            for t in T:
                if t >= info['arrival']:  # No puede ser antes de llegada
                    for c in range(info['cycles']):
                        for s in range(info['sessions']):
                            x[p, t, c, s] = self.model.addVar(
                                vtype=GRB.BINARY,
                                name=f"x_{p}_{t}_{c}_{s}"
                            )
            if (p + 1) % 25 == 0 or (p + 1) == len(patient_info):
                print(f"[PROGRESO] Variables x: paciente {p + 1}/{len(patient_info)} | total parcial {len(x)}")
        timer.lap(f"variables x creadas ({len(x)})")
        
        # Variable de holgura y[t] para capacidad
        y = {}
        for t in T:
            y[t] = self.model.addVar(vtype=GRB.CONTINUOUS, lb=0, name=f"y_{t}")
        timer.lap(f"variables y creadas ({len(y)})")
        
        # Variable de ocupación máxima W
        W = self.model.addVar(vtype=GRB.CONTINUOUS, lb=0, name="W")
        timer.lap("variable W creada")
        
        self.variables = {
            'x': x,
            'y': y,
            'W': W,
            'patient_info': patient_info,
            'P': P,
            'T': T,
        }
        
        # Restricciones
        self._add_constraints()
        timer.lap(f"restricciones agregadas ({self.model.NumConstrs} antes de update)")
        
        # Función objetivo
        self._set_objective()
        timer.lap("objetivo definido")
        
        self.model.update()
        timer.lap(f"model.update terminado | vars={self.model.NumVars}, constrs={self.model.NumConstrs}")
        timer.finish("construccion del modelo")
    
    def _add_constraints(self):
        """Agrega restricciones al modelo."""
        timer = ExecutionTimer("restricciones")
        x = self.variables['x']
        y = self.variables['y']
        W = self.variables['W']
        patient_info = self.variables['patient_info']
        P = self.variables['P']
        T = self.variables['T']
        print("[PROGRESO] Agregando R1: cada sesion una vez")
        constr_count = 0
        
        # Restricción 1: Cada sesión se programa en un solo día
        for p in P:
            info = patient_info[p]
            for c in range(info['cycles']):
                for s in range(info['sessions']):
                    # Sumar solo sobre días válidos (>= arrival)
                    session_vars = [x[p, t, c, s] for t in T 
                                   if t >= info['arrival'] and (p, t, c, s) in x]
                    if session_vars:
                        self.model.addConstr(
                            gp.quicksum(session_vars) == 1,
                            name=f"session_once_{p}_{c}_{s}"
                        )
                        constr_count += 1
            if (p + 1) % 25 == 0 or (p + 1) == len(patient_info):
                print(f"[PROGRESO] R1 paciente {p + 1}/{len(patient_info)} | restricciones {constr_count}")
        timer.lap(f"R1 terminada ({constr_count} restricciones)")
        print("[PROGRESO] Agregando R2: capacidad diaria")
        constr_count = 0
        
        # Restricción 2: Respeta capacidad máxima
        for t in T:
            capacity_expr = gp.quicksum(
                patient_info[p]['modules'] * x[p, t, c, s]
                for p in P
                for c in range(patient_info[p]['cycles'])
                for s in range(patient_info[p]['sessions'])
                if (p, t, c, s) in x
            )
            self.model.addConstr(
                capacity_expr <= self.capacity + y[t],
                name=f"capacity_{t}"
            )
            constr_count += 1
            if (t + 1) % 50 == 0 or (t + 1) == self.time_horizon:
                print(f"[PROGRESO] R2 dia {t + 1}/{self.time_horizon}")
        timer.lap(f"R2 terminada ({constr_count} restricciones)")
        print("[PROGRESO] Agregando R3: tiempos entre ciclos")
        constr_count = 0
        
        # Restricción 3: Tiempos entre ciclos
        for p in P:
            info = patient_info[p]
            for c in range(info['cycles'] - 1):
                for s in range(info['sessions']):
                    # Días de la sesión actual (ciclo c)
                    days_current = gp.quicksum(
                        t * x[p, t, c, s]
                        for t in T
                        if (p, t, c, s) in x
                    )
                    # Días de la siguiente sesión (ciclo c+1)
                    days_next = gp.quicksum(
                        t * x[p, t, c+1, s]
                        for t in T
                        if (p, t, c+1, s) in x
                    )
                    # Diferencia debe ser TBC
                    self.model.addConstr(
                        days_next - days_current == info['tbc'],
                        name=f"between_cycles_{p}_{c}_{s}"
                    )
                    constr_count += 1
            if (p + 1) % 25 == 0 or (p + 1) == len(patient_info):
                print(f"[PROGRESO] R3 paciente {p + 1}/{len(patient_info)} | restricciones {constr_count}")
        timer.lap(f"R3 terminada ({constr_count} restricciones)")
        print("[PROGRESO] Agregando R4: tiempos entre sesiones")
        constr_count = 0
        
        # Restricción 4: Tiempos entre sesiones
        for p in P:
            info = patient_info[p]
            for c in range(info['cycles']):
                for s in range(info['sessions'] - 1):
                    # Días de la sesión actual (sesión s)
                    days_current = gp.quicksum(
                        t * x[p, t, c, s]
                        for t in T
                        if (p, t, c, s) in x
                    )
                    # Días de la siguiente sesión (sesión s+1)
                    days_next = gp.quicksum(
                        t * x[p, t, c, s+1]
                        for t in T
                        if (p, t, c, s+1) in x
                    )
                    # Diferencia debe ser TBS
                    self.model.addConstr(
                        days_next - days_current == info['tbs'],
                        name=f"between_sessions_{p}_{c}_{s}"
                    )
                    constr_count += 1
            if (p + 1) % 25 == 0 or (p + 1) == len(patient_info):
                print(f"[PROGRESO] R4 paciente {p + 1}/{len(patient_info)} | restricciones {constr_count}")
        timer.lap(f"R4 terminada ({constr_count} restricciones)")
        print("[PROGRESO] Agregando R5: ocupacion maxima W")
        constr_count = 0
        
        # Restricción 5: Definición de W (ocupación máxima)
        for t in T:
            capacity_expr = gp.quicksum(
                patient_info[p]['modules'] * x[p, t, c, s]
                for p in P
                for c in range(patient_info[p]['cycles'])
                for s in range(patient_info[p]['sessions'])
                if (p, t, c, s) in x
            )
            self.model.addConstr(
                capacity_expr <= W,
                name=f"max_occupation_{t}"
            )
            constr_count += 1
            if (t + 1) % 50 == 0 or (t + 1) == self.time_horizon:
                print(f"[PROGRESO] R5 dia {t + 1}/{self.time_horizon}")
        timer.lap(f"R5 terminada ({constr_count} restricciones)")
        timer.finish("restricciones")
    
    def _set_objective(self):
        """Establece la función objetivo."""
        timer = ExecutionTimer("objetivo")
        x = self.variables['x']
        y = self.variables['y']
        W = self.variables['W']
        patient_info = self.variables['patient_info']
        P = self.variables['P']
        T = self.variables['T']
        
        # Minimizar: α*W + β*Σy[t] + γ*Σ(t - R_p)*x[p,t,1,1]
        
        # Primer término: ocupación máxima
        obj_W = self.alpha * W
        
        # Segundo término: suma de holguras
        obj_y = self.beta * gp.quicksum(y[t] for t in T)
        
        # Tercer término: tiempo de espera (para la primera sesión del primer ciclo)
        obj_wait = self.gamma * gp.quicksum(
            (t - patient_info[p]['arrival']) * x[p, t, 0, 0]
            for p in P
            for t in T
            if (p, t, 0, 0) in x and t >= patient_info[p]['arrival']
        )
        
        self.model.setObjective(obj_W + obj_y + obj_wait, GRB.MINIMIZE)
        timer.finish("objetivo")
    
    def optimize(self, time_limit=300, print_output=True):
        """
        Resuelve el modelo.
        
        Args:
            time_limit: Límite de tiempo en segundos
            print_output: Si mostrar output de Gurobi
        """
        timer = ExecutionTimer("optimize completo")
        if self.model is None:
            self._build_model()
            timer.lap("modelo construido")
        
        # Configurar parámetros
        self.model.setParam('TimeLimit', time_limit)
        if print_output:
            self.model.setParam('OutputFlag', 1)
        
        # Resolver
        print(f"[INFO] Iniciando Gurobi con TimeLimit={time_limit}s | vars={self.model.NumVars} | constrs={self.model.NumConstrs}")
        gurobi_start = time.perf_counter()
        self.model.optimize()
        gurobi_elapsed = time.perf_counter() - gurobi_start
        print(f"[TIMER] Gurobi optimize(): {gurobi_elapsed:.2f}s | Runtime reportado {self.model.Runtime:.2f}s | status {self.model.status}")
        timer.lap("optimizacion Gurobi terminada")
        
        # Guardar solución
        if self.model.status == GRB.OPTIMAL or self.model.status == GRB.TIME_LIMIT:
            self._extract_solution()
            timer.finish("optimize completo")
            return True
        else:
            print(f"Modelo no resuelto. Status: {self.model.status}")
            timer.finish("optimize completo")
            return False
    
    def _extract_solution(self):
        """Extrae la solución del modelo."""
        timer = ExecutionTimer("extraccion de solucion")
        x = self.variables['x']
        y = self.variables['y']
        W = self.variables['W']
        patient_info = self.variables['patient_info']
        
        solution = {
            'status': self.model.status,
            'obj_value': self.model.objVal,
            'W_value': W.X,
            'slack_sum': sum(y[t].X for t in self.variables['T']),
            'assignments': [],
            'daily_occupancy': {},
            'patient_schedule': {}
        }
        
        # Extraer asignaciones
        for (p, t, c, s), var in x.items():
            if var.X > 0.5:
                solution['assignments'].append({
                    'patient_id': p,
                    'patient_type': int(self.patients.iloc[p]['patient_type']),
                    'day': t,
                    'cycle': c,
                    'session': s,
                    'modules': patient_info[p]['modules']
                })
        
        # Calcular ocupación diaria
        for t in self.variables['T']:
            daily_load = sum(
                patient_info[p]['modules']
                for (p, t_var, c, s), var in x.items()
                if t_var == t and var.X > 0.5
            )
            solution['daily_occupancy'][t] = daily_load
        
        # Agrupar por paciente
        for p in self.variables['P']:
            patient_assignments = [a for a in solution['assignments'] if a['patient_id'] == p]
            if patient_assignments:
                solution['patient_schedule'][p] = sorted(patient_assignments, key=lambda x: (x['cycle'], x['session']))
        
        self.solution = solution
        return solution
    
    def print_summary(self):
        """Imprime resumen de la solución."""
        if not self.solution:
            print("No hay solución disponible.")
            return
        
        print("\n" + "="*70)
        
        print("RESUMEN DE LA SOLUCIÓN")
        print("="*70)
        print(f"Status: {self.solution['status']}")
        print(f"Función Objetivo: {self.solution['obj_value']:.2f}")
        print(f"Ocupación Máxima (W): {self.solution['W_value']:.0f} módulos")
        print(f"Suma de Holguras: {self.solution['slack_sum']:.2f}")
        print(f"Total de Asignaciones: {len(self.solution['assignments'])}")
        print(f"Pacientes Programados: {len(self.solution['patient_schedule'])}")
        
        print("\n" + "-"*70)
        print("OCUPACIÓN POR DÍA (Primeros 20 días)")
        print("-"*70)
        for t in range(min(20, len(self.solution['daily_occupancy']))):
            occ = self.solution['daily_occupancy'].get(t, 0)
            pct = (occ / self.capacity) * 100
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            print(f"Día {t:3d}: {occ:4.0f}/{self.capacity} [{bar}] {pct:5.1f}%")
        
        print("\n" + "-"*70)
        print("PRIMEROS 5 PACIENTES PROGRAMADOS")
        print("-"*70)
        for p in list(self.solution['patient_schedule'].keys())[:5]:
            schedules = self.solution['patient_schedule'][p]
            arrival = self.patients.iloc[p]['arrival_day']
            p_type = self.patients.iloc[p]['patient_type']
            print(f"\nPaciente {p} → Tipo {p_type} (Llegada: día {arrival}):")
            for sched in schedules:
                print(f"  Ciclo {sched['cycle']+1}, Sesión {sched['session']+1}: Día {sched['day']+1}")
    
    def get_solution_dataframe(self):
        """Retorna la solución como DataFrame."""
        if not self.solution:
            return None
        
        df = pd.DataFrame(self.solution['assignments'])
        df = df.merge(
            self.patients[['arrival_day', 'patient_type']],
            left_on='patient_id',
            right_index=True
        )
        return df.sort_values(['patient_id', 'cycle', 'session'])


def main():
    """Función principal para demostración."""
    print("Generando datos del escenario...")
    
    # Generar datos
    generator = DataGenerator(base_data_path="Data G15.xlsx")   # ← pon el path correcto
    scenario = generator.generate_scenario(
        num_patients=150, 
        arrival_horizon=90, 
        time_horizon=365
    )
    
    print(f"✓ Datos generados:")
    print(f"  - Pacientes: {scenario['total_patients']}")
    print(f"  - Llegadas hasta día: {scenario.get('arrival_horizon', 90)}")
    print(f"  - Horizonte de planificación: {scenario['time_horizon']} días")
    print(f"  - Capacidad: {scenario['capacity']['total_modules']} módulos/día")
    
    # Crear y resolver modelo
    print("\nConstruyendo modelo de optimización...")
    model = InterdayModel(scenario)
    
    print("Resolviendo... (esto puede tomar algunos minutos)")
    success = model.optimize(time_limit=300, print_output=False)
    
    if success:
        model.print_summary()
        print(f"⏱️ Tiempo de optimización Gurobi: {model.model.Runtime:.2f} segundos")
        # Guardar solución en Excel (en la misma carpeta que el script)
        print("\n" + "="*70)
        print("Guardando resultados...")
        
        sol_df = model.get_solution_dataframe()
        
        output_path = 'solution_interday.xlsx'   # ← se guarda en la carpeta actual
        
        with pd.ExcelWriter(output_path, engine='openpyxl') as writer:
            sol_df.to_excel(writer, sheet_name='Asignaciones', index=False)
            
            # Hoja con ocupación diaria
            occ_df = pd.DataFrame([
                {'Día': t, 'Ocupación': model.solution['daily_occupancy'].get(t, 0)}
                for t in range(scenario['time_horizon'])
            ])
            occ_df.to_excel(writer, sheet_name='Ocupación Diaria', index=False)
            
            # Hoja con resumen
            summary_data = {
                'Métrica': [
                    'Total Pacientes',
                    'Pacientes Programados',
                    'Horizonte (días)',
                    'Capacidad (módulos/día)',
                    'Ocupación Máxima',
                    'Suma de Holguras',
                    'Valor Función Objetivo'
                ],
                'Valor': [
                    scenario['total_patients'],
                    len(model.solution['patient_schedule']),
                    scenario['time_horizon'],
                    model.capacity,
                    f"{model.solution['W_value']:.0f}",
                    f"{model.solution['slack_sum']:.2f}",
                    f"{model.solution['obj_value']:.2f}"
                ]
            }
            summary_df = pd.DataFrame(summary_data)
            summary_df.to_excel(writer, sheet_name='Resumen', index=False)
        
        print(f"✓ Resultados guardados en: {output_path}")
    else:
        print("No se pudo resolver el modelo.")


if __name__ == "__main__":
    main()
