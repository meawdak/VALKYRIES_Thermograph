# AGENTS.md — Rules for the coding agent (Antigravity)

Read this file, `PRD.md` and `TECH_SPEC.md` before every task.

## Working rules

1. **Do one task from `TASKS.md` at a time.** Do not start the next task until the user says so.
2. **At the end of each task**, run `python processing/check_outputs.py` (once it exists) and report: files changed, commands run, PASS/FAIL results, and any problems.
3. **If an acceptance criterion fails, stop and report.** Do not change parameters, thresholds or data to make it pass.
4. If `PRD.md` and `TECH_SPEC.md` disagree, or something is unclear, **ask the user** — do not guess.

## Data rules

5. **Never modify, move, rename or delete anything in `data/`.** Read only.
6. **Never modify or delete `output/thermal_sites.csv`.** It is the legacy result for comparison.
7. Generated files go only in `output/` (and `docs/` for reports).
8. The pipeline must not make internet requests.

## Scientific rules

9. **No machine-learning models.** DBSCAN from scikit-learn is the only scikit-learn use allowed.
10. **Never invent numbers.** Every number shown in the UI or API must come from the database. No hard-coded counts, scores, percentages or example results in front-end code.
11. **Never show accuracy, precision, recall, or "confidence %"** for THERMOGRAPH results.
12. Simulated data must always have `is_simulated = 1`, be hidden by default, and be labelled `[SIMULATED]` in text and with a banner in the UI.
13. Call site classes "rule-based classes" and parameters "prototype settings". Never call them AI predictions or validated values.

## Code rules

14. **No new dependencies** beyond TECH_SPEC §2 without the user's approval.
15. All paths and parameters come from `processing/config.py`. Use `pathlib` for paths.
16. Keep code simple: plain functions, short files, plain-English comments explaining each step. No classes unless necessary.
17. No React, Node, npm, Docker, PostGIS, or build steps.
18. Front-end libraries are loaded from `app/static/vendor/`, not from a CDN.
19. The whole project must run with two commands:
    - `python processing/run_pipeline.py`
    - `python app/app.py`
20. Print clear progress and error messages a beginner can understand (e.g. "Expected 21,513 detections, found 21,400. Stopping.").
