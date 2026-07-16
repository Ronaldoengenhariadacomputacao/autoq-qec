# Changelog

All notable changes to this project are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [3.2.3] - Unreleased

### Fixed
- `HARDWARE_PROFILES["Quantinuum_H2"]` two-qubit gate error was underestimated ~5x:
  `p_2q_mean`/`p_2q_worst` were `2.9e-4`/`5.0e-4`, vs. the official typical/max values
  of `1.5e-3`/`3.0e-3` per Quantinuum's own System Model H2 Product Data Sheet
  (v1.4, 4 Jun 2024, Table 1 — the 56-qubit generation, matching `n_qubits=56`
  already in the profile). `readout_error` (`0.0015`) already matched the
  datasheet's typical SPAM error exactly and was not changed. The same incorrect
  `p_phys=0.00029` value was duplicated (not read from `HARDWARE_PROFILES`) in the
  README Quickstart snippet, `example.py`, and two tests in `test_v2_features.py` —
  all corrected to `0.0015`. This affected every `compare()`/`rank()` result
  involving Quantinuum H2 in this package's own examples and documentation,
  making it look more favorable than the hardware's own published specs support.

## [3.2.2] - 2026-07-16

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
