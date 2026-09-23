"""
THERMOGRAPH — Full Pipeline Runner
Executes the complete processing pipeline from raw data loading through simulation
and output verification in a single deterministic command.

Stages executed:
  1. Load FIRMS detections (load_firms.py)
  2. Spatial clustering into thermal sites (cluster_sites.py)
  3. Load OSM industrial facilities (load_facilities.py)
  4. Spatial facility matching (match_facilities.py)
  5. 52-week site history aggregation (site_history.py)
  6. 39-week historical baseline & classification (baselines.py)
  7. Rule-based anomaly detection & priority scoring (anomalies.py)
  8. Simulated demo event generation (simulate_event.py)
  9. Comprehensive output verification checks C1–C15 (check_outputs.py)

Specification: TASKS.md T9; AGENTS.md Rule 19 ("python processing/run_pipeline.py").
"""

import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from processing.load_firms import main as run_stage_1
from processing.cluster_sites import run_clustering as run_stage_2
from processing.load_facilities import run_load_facilities as run_stage_3
from processing.match_facilities import run_facility_matching as run_stage_4
from processing.site_history import run_site_history as run_stage_5
from processing.baselines import run_baselines as run_stage_6
from processing.anomalies import run_anomalies as run_stage_7
from processing.simulate_event import run_simulation as run_stage_8
from processing.check_outputs import main as run_validation


def main() -> None:
    print("=" * 70)
    print("THERMOGRAPH — End-to-End Pipeline Execution")
    print("=" * 70)
    total_start_time = time.time()

    stages = [
        ("Stage 1: Load FIRMS Detections", run_stage_1),
        ("Stage 2: Cluster Thermal Sites", run_stage_2),
        ("Stage 3: Load OSM Facilities", run_stage_3),
        ("Stage 4: Match Sites to Facilities", run_stage_4),
        ("Stage 5: Generate Site Weekly History", run_stage_5),
        ("Stage 6: Historical Baselines & Site Classes", run_stage_6),
        ("Stage 7: Anomaly Detection & Priority Scoring", run_stage_7),
        ("Stage 8: Simulated Demo Event", run_stage_8),
        ("Stage 9: Output Verification (Checks C1–C15)", run_validation),
    ]

    for idx, (stage_name, stage_fn) in enumerate(stages, 1):
        print(f"\n>>> Running [{idx}/{len(stages)}] {stage_name}...")
        stage_start = time.time()
        try:
            stage_fn()
        except SystemExit as e:
            if e.code != 0:
                print(f"\n[FAIL] Pipeline stopped: {stage_name} exited with status {e.code}.")
                sys.exit(e.code)
        except Exception as e:
            print(f"\n[FAIL] Pipeline stopped due to unexpected exception in {stage_name}: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

        stage_elapsed = time.time() - stage_start
        print(f">>> Completed {stage_name} in {stage_elapsed:.2f}s.")

    total_elapsed = time.time() - total_start_time
    print("\n" + "=" * 70)
    print(f"ALL PIPELINE STAGES COMPLETED SUCCESSFULLY in {total_elapsed:.2f}s.")
    print("=" * 70)


if __name__ == "__main__":
    main()
