import pandas as pd
import numpy as np
from dashboard_intradia_app import load_data, compute_kpis

df_res, df_prog, df_ocup, df_pend = load_data("solution_heuristica_240.xlsx")
if 'wait_after_pharmacy' not in df_prog.columns:
    df_prog['wait_after_pharmacy'] = np.where(df_prog['pharmacy_modules'] > 0, df_prog['treatment_start'] - df_prog['pharmacy_end'] - 1, 0)

kpis = compute_kpis(df_prog, df_ocup, df_res, df_pend)

print("KPIs Heurística:")
for k, v in kpis.items():
    print(f"{k}: {v}")
