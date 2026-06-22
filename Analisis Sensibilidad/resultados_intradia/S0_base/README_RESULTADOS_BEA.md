# Resultados base intradia recibidos de Bea

Este directorio contiene los resultados base del intradia con farmacia tardia y restriccion de 24h.

Archivos recibidos:

- 30 archivos `solution_intradia-*.xlsx`.
- 30 archivos `log_intradia-*.txt`.
- `resumen_intradia_replicas.csv` con 30 replicas en estado `OK`.

Archivos generados localmente para el dashboard:

- `kpis_intradia_replicas.csv`.
- `kpis_intradia_ic95.csv`.
- `kpis_intradia_daily_replicas.csv`.
- `kpis_intradia_daily_ic95.csv`.
- `kpis_intradia_most_loaded_day_freq.csv`.

Para publicar el dashboard no es necesario versionar los 30 Excel ni los 30 logs. Basta con `solution_intradia-1.xlsx` para la vista base y los CSV `kpis_intradia_*.csv` para la pestana de IC 95%.
