# Backend Tests

## Quick Run
- All tests: `python -m pytest`
- Regression-only: `python scripts/run_regression.py`
- Regression-only (direct): `python -m pytest -m regression`

## Scope
- `regression` marker is for stable behavior already implemented in the project.
- These tests are meant to catch unintended regressions without manual checking.
