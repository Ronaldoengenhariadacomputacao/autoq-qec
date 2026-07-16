# Changelog

All notable changes to this project are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [3.2.2] - Unreleased

### Fixed
- `extract_circuit_profile()` now raises a clear `ValueError` when given a circuit
  with unbound symbolic parameters (e.g. `RealAmplitudes`, `EfficientSU2`,
  `QAOAAnsatz` templates before `assign_parameters()`), instead of letting a deep
  `qiskit.transpiler.exceptions.TranspilerError` leak from inside `_count_t_gates()`.
  T-count depends on the actual rotation angles, which don't exist in a symbolic
  circuit — this is a usage error, not something the estimator can compute around.

### Tests
- Added `TestParametrosNaoVinculados` (4 tests) covering: `RealAmplitudes` and
  `QAOAAnsatz` unbound → `ValueError`; `RealAmplitudes` bound → works normally
  with a nonzero T-count; a manually-built circuit with a single `Parameter`
  → `ValueError` unbound, works once `assign_parameters()` is called (confirms
  the check is generic, not specific to library ansatz classes).

### Docs
- README: added an explicit example showing parameter binding is required before
  passing variational circuits (VQE, QAOA, etc.) to `compare()`/`extract_circuit_profile()`.
- `example.py`: added two runnable examples — the expected `ValueError` on an
  unbound ansatz, and the correct pattern with `assign_parameters()`.

## [3.2.1] - 2026-07-14

### Fixed
- Corrected Bacon-Shor overhead formula — was missing the factor of `d` measurement
  rounds per logical operation.

## [3.2.0] - 2026-07-12

### Added
- Magic state distillation modeling (T-factories), opt-in via
  `model_magic_state_distillation=True`.

### Fixed
- Two inconsistencies between the new distillation modeling and prior features.

## [3.1.0] and earlier

- Readout error and T1/T2 decoherence terms added to the fidelity formula.
- Real IBM Cloud calibration integration (`from_ibm_backend`), with several bugs
  found and fixed against live hardware data.

See `git log` for full history prior to this changelog's introduction.
