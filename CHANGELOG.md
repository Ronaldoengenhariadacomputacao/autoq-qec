# Changelog

All notable changes to this project are documented here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/).

## [3.3.4] - 2026-07-16

Found by an end-to-end user-simulation test (fresh venv, `pip install autoq-qec`
from PyPI, walking through every code snippet in the README).

### Fixed
- `rank()`/`rank_by_metric()` silently dropped `magic_state_qubits`,
  `magic_state_factories`, and `magic_state_t_state_error` when building
  `Recommendation` from `CodeResult`. These fields exist and are correctly
  populated in `compare()`'s raw output when
  `model_magic_state_distillation=True`, but `Recommendation` (the object
  `rank()` returns — the primary documented workflow) didn't carry them at
  all, so accessing `r.magic_state_qubits` on a ranked result raised
  `AttributeError`. `total_physical_qubits` was already correct (it included
  distillation overhead); only the breakdown was inaccessible without
  bypassing `rank()` and reading the raw `compare()` dict. Fixed by adding
  the three fields to `Recommendation` (default `None`, backward-compatible)
  and propagating them from `CodeResult` in `rank()`.
- `CONTRIBUTING.md`/`README.md` referenced a stale, hardcoded test count
  ("22 tests" / "81 tests"); the suite has grown to 97 tests across recent
  releases. `CONTRIBUTING.md` no longer hardcodes a number; `README.md`
  updated to 97.

### Added
- `.github/ISSUE_TEMPLATE/bug_report.md` — structured bug report template
  (version, hardware/backend, reproducing circuit, expected vs. actual).

## [3.3.3] - 2026-07-16

Version jumps from 3.2.3 to 3.3.3 (skipping 3.3.0–3.3.2) to mark this release
distinctly — it closes a full bias-audit round covering hardware profile data,
model behavior invariants, and API transparency, not just a routine patch.
No code exists at 3.3.0–3.3.2; this is intentional, not a numbering error.

This release also warrants a minor bump on its own merits: it adds a new
public function (`rank_by_metric()`), which is new backward-compatible
functionality, not just a bug fix.

### Fixed — decorative/ignored `HardwareProfile` fields
- `HardwareProfile.topology` was declared but never read anywhere in the
  codebase — every circuit was transpiled assuming all-to-all connectivity,
  regardless of the hardware's real topology (`heavy-hex`, `linear`, `grid`).
  `compare()` now builds a real `qiskit.transpiler.CouplingMap` per hardware
  from `topology` (using Qiskit's `CouplingMap.from_line`/`from_grid`/
  `from_heavy_hex`) and transpiles per-hardware, so connectivity-limited
  hardware now pays real SWAP-routing overhead. Unknown/unrecognized
  topology strings fall back to the old unconstrained behavior rather than
  raising. `output["circuit_profile"]` remains the topology-agnostic
  baseline for backward compatibility/display.
- `HardwareProfile.T1_us` (set directly by the user, as opposed to via a
  matched `CalibratedHardware`) was never read by `rank()`'s T1 feasibility
  filter — a user-supplied T1 was silently ignored unless it happened to
  numerically match a built-in `HARDWARE_PROFILES` entry. `rank()` now
  checks `HardwareProfile.T1_us` directly whenever `hardware_calibrations`
  doesn't yield a match, excluding combinations whose execution time
  exceeds 50% of that T1.

### Fixed — hardware profile data errors (verified against primary sources)
- `IBM_Heron_r2`: `n_qubits` was `133` (that's Heron r1's count) instead of
  the real `156`; the cited source (`arXiv:2404.07471`) is a paper about
  code pre-trained language models, unrelated to quantum hardware. Replaced
  with a live calibration snapshot of `ibm_fez` (the real Heron r2 backend —
  `ibm_torino`, previously cited, is actually Heron r1) pulled via
  `QiskitRuntimeService` this session.
- `IBM_Heron_r3`: `n_qubits` was also `133` instead of `156` (r3 keeps r2's
  qubit count). `T1_us`/`T2_us` updated from `180`/`140` to the real
  `300`/`370` reported at launch (Jay Gambetta/IBM, ibm_pittsburgh).
- `IonQ_Aria`: cited source `arXiv:2307.01765` is a pure-mathematics paper
  ("Wasserstein medians"), unrelated to IonQ. Replaced with IonQ's official
  published specs (ionq.com/quantum-systems/aria): `p_1q_mean` `4.0e-4` →
  `6.0e-4`, `T2_us` `1e5` (~0.1s) → `1e6` (~1s, was 10x underestimated),
  `readout_error` `0.005` → `0.0039`.
- `Google_Willow`: `T1_us`/`T2_us` were `100`/`150`, overestimated versus
  the `68`/`89` µs reported in the source paper (Acharya et al., Nature 638,
  2025). Gate error rates (`p_1q_mean`/`p_2q_mean`) could not be confirmed
  as standalone figures in the paper text and were left unchanged.
- `IBM_Eagle_r3` was checked against public benchmarks and found reasonably
  accurate (`n_qubits=127` confirmed; gate error within normal calibration
  variance of published figures) — no change needed.
- A second, related bug: `Google_Willow`'s `topology="grid-2d"` wasn't
  recognized by the new coupling-map logic above (which only matched
  `"grid"`), silently falling back to unconstrained connectivity. Fixed by
  treating `"grid-2d"` as an alias for `"grid"`.

### Added
- `rank_by_metric(compare_result, hardware_calibrations=None)`: ranks
  qubits, execution time, and fidelity independently, with no weighting.
  Complements `rank()` — when one hardware+code combination Pareto-dominates
  every other candidate (better or equal on every metric at once), no
  weight combination in `rank()` can ever select anything else as `#1`,
  which can hide real trade-offs among the non-dominant options.
  `rank_by_metric()` reveals those trade-offs directly. Verified on a real
  example (QFT-6, `fidelity_target=0.999`): `rank()` converges to the same
  `#1` under 5 different weight presets, yet `rank_by_metric()` shows a
  ~78x execution-time spread and ~20x qubit-count spread between the
  per-metric winners.

### Verified (no change needed)
- Magic-state-distillation invariant: enabling
  `model_magic_state_distillation=True` never decreases `total_physical_qubits`
  or `execution_time_us` relative to the same circuit without it — checked
  across 12 circuit×fidelity×hardware combinations, 0 violations.
- T-count synthesis for controlled-phase gates with unusual angle
  denominators (`cp(pi/3)` through `cp(pi/13)`) — consistently large T-counts
  in the same order of magnitude, no anomalies.

### Docs
- README: full parameter manual for `HardwareProfile` fields, `compare()`,
  and `rank()`, including a table of what each field/parameter controls and
  what happens if it's omitted.
- README: `rank()` weights section with 5 named presets (default, speed,
  fidelity margin, balanced, operational cost), each with a real example
  and guidance on when to use it.
- README: new "Known limitation" note — mid-circuit measurement error is
  not modeled separately from end-of-circuit `readout_error`.

## [3.2.3] - 2026-07-16

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
