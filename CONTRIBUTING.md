# Contributing to AutoQ QEC

## Setup

```bash
git clone https://github.com/Ronaldoengenhariadacomputacao/autoq-qec
cd autoq-qec
pip install -e ".[dev]"
```

## Running tests

```bash
pytest tests/ -v
```

All 22 tests must pass before any PR is merged.

## Adding a new QEC code

1. Add the analytic model function in `autoq_qec/qec_estimator.py`
   following the pattern of `_surface_code_model()`
2. Add at least 3 tests in `tests/test_qec_estimator.py`:
   - threshold rejection
   - p_L ≤ p_L_target guarantee  
   - qubit count formula
3. Add to the `estimate()` function
4. Add hardware data (if applicable) to `real_hardware.py`

## What we do NOT accept

- Tests that verify `f(x) == f(x)` (circular)
- Overhead values without a literature reference
- Silent acceptance of `p > threshold`
