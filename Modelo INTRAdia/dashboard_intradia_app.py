from pathlib import Path
import runpy


ROOT_DIR = Path(__file__).resolve().parents[1]
DASHBOARD_APP = ROOT_DIR / "Dashboard" / "dashboard_intradia_app.py"

runpy.run_path(str(DASHBOARD_APP), run_name="__main__")
