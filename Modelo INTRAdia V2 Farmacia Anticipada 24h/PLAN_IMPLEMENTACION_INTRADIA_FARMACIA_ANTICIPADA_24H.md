# Plan Intradia Farmacia Anticipada 24h

Objetivo: restringir que los remedios preparados el dia anterior se administren dentro de 24 horas reales, usando el `pharmacy_end` elegido por el intradia del dia anterior.

## Diagnostico

- El Interdia H450 funciona bien y entrega `pharmacy_day`, `pharmacy_offset` y `pharmacy_modules`.
- El Intradia FA separa las sesiones anticipadas en `pharmacy_only` y `treatment_only_prepared`.
- La restriccion no puede ser local a un solo dia si no se conoce el modulo real en que termino farmacia el dia anterior.
- Con modulos de 15 min, 24 horas son 96 modulos calendario.
- Para una farmacia que termino en modulo `pf` del dia `t-1`, el tratamiento del dia `t` debe iniciar en modulo `<= pf`.

## Checklist

- [x] Mantener intacto el modelo Interdia H450.
- [x] Usar una carpeta experimental 24h separada.
- [x] Agregar trazabilidad de `prepared_pharmacy_end`, `latest_treatment_start` y `prepared_elapsed_modules`.
- [x] Forzar ejecucion secuencial en el Intradia 24h.
- [x] Guardar `pharmacy_end` real de tareas `pharmacy_only`.
- [x] Inyectar `latest_treatment_start = pharmacy_end` en tareas `treatment_only_prepared`.
- [x] Filtrar patrones de tratamiento preparado para cumplir `treatment_start <= latest_treatment_start`.
- [x] Validar globalmente `prepared_elapsed_modules <= 96`.
- [x] Compilar el modelo.
- [x] Ejecutar prueba de 2 dias con output H450.
- [x] Validar capacidades y regla 24h en el Excel de prueba.
- [ ] Ejecutar corrida completa H450.

## Comando De Prueba

```powershell
cd "C:\Users\ianma\OneDrive\Escritorio\Codigo Capstone\CapstoneG15\Modelo INTRAdia V2 Farmacia Anticipada 24h"

python modelo_intradia_farmacia_anticipada_24h.py `
  --solution "..\Modelo Interdia Farmacia Anticipada H450\solution_interday_farmacia_anticipada_h450.xlsx" `
  --base-data "..\Data Inicial\Data G15.xlsx" `
  --output "test_intradia_farmacia_anticipada_h450_24h_max2.xlsx" `
  --workers 1 `
  --max-days 2 `
  --max-iterations 30
```

## Comando Corrida Completa

```powershell
cd "C:\Users\ianma\OneDrive\Escritorio\Codigo Capstone\CapstoneG15\Modelo INTRAdia V2 Farmacia Anticipada 24h"

python modelo_intradia_farmacia_anticipada_24h.py `
  --solution "..\Modelo Interdia Farmacia Anticipada H450\solution_interday_farmacia_anticipada_h450.xlsx" `
  --base-data "..\Data Inicial\Data G15.xlsx" `
  --output "solution_intradia_farmacia_anticipada_h450_24h.xlsx" `
  --workers 1 `
  --all-days
```
