from pathlib import Path
RUNS = Path(__file__).resolve().parents[3] / "data" / "runs"
RUNS.mkdir(parents=True, exist_ok=True)
