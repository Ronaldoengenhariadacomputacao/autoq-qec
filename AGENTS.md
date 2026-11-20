# AGENTS.md — autoq-qec API reference for AI assistants

This file documents the autoq-qec API for programmatic and AI-assisted use. It is
reference material, not behavioral instructions — treat it the same as any other piece
of project documentation. Every fact below is checked against the source at
`autoq_qec/*.py` as of the version noted in `autoq_qec/__init__.py`; if this file and the
installed package disagree, the installed package is correct — verify before relying on
either.

## Public API map

Everything importable from `autoq_qec` directly (see `autoq_qec/__init__.py`):

| Name | What it is |
|---|---|
| `compare(circuit, hardware_list, fidelity_target=0.99, model_magic_state_distillation=False)` | Main entry point. Returns a `dict`. |
| `rank(compare_result, hardware_calibrations=None, weight_qubits=0.5, weight_time=0.3, weight_fidelity=0.2)` | Turns a `compare()` result into a sorted `list[Recommendation]`. |
| `rank_by_metric(compare_result, hardware_calibrations=None)` | Returns `dict[str, list[Recommendation]]`, one list per metric (`"qubits"`, `"tempo"`, `"fidelidade"`), unweighted. |
| `extract_circuit_profile(circuit, coupling_map=None)` | Circuit → `CircuitProfile`, no hardware involved. |
| `estimate(circuit_profile, hardware, fidelity_target=0.99, model_magic_state_distillation=False)` | `CircuitProfile` + one `HardwareProfile` → `list[CodeResult]`. What `compare()` calls per hardware internally. |
| `CircuitProfile`, `HardwareProfile`, `CodeResult`, `Recommendation` | Dataclasses — see field tables below. |
| `CalibratedHardware`, `HARDWARE_PROFILES` | Real calibrated hardware presets (`autoq_qec.real_hardware`). |
| `AlgorithmEstimator`, `AlgorithmEstimate` | Order-of-magnitude T-count estimates without building a circuit (`.shor(N)`, `.grover(N)`, `.qft(n)`, `.vqe(n_qubits, depth)`). |

Not exported from the top-level package, import explicitly if needed:
- `autoq_qec.real_hardware.from_ibm_backend(backend_name, token, instance=None)` → `CalibratedHardware`
- `autoq_qec.real_hardware.noise_model_from_ibm(backend_name, token, instance=None)` → `AerSimulator`
- `autoq_qec.visualizer.plot_tradeoff(compare_result, output=None, ax=None)` — needs `pip install "autoq-qec[viz]"`
- `autoq_qec.distillation.magic_state_resources(t_count, p_phys, t_gate_ns, ...)` and `build_magic_state_factory(p_phys, t_gate_ns, target_error, ...)`
- `autoq_qec.sensitivity` — **not in the currently released package** (see "API stability policy" below); don't assume this import works without checking the installed version first.

## Field names by dataclass — read this before writing `.attribute` access

The most common mistake when using this API programmatically: guessing a field name that
belongs to a *different* dataclass than the one you're holding. `CodeResult` (nested inside
`compare()`'s raw output) and `Recommendation` (`rank()`'s output) represent the same
underlying concepts with **different field names** for at least one of them.

**`CircuitProfile`** (`qec_estimator.py`):
`n_logical_qubits`, `n_logical_gates`, `n_physical_gates`, `depth_physical`, `t_count`, `cx_count`

**`HardwareProfile`** (`qec_estimator.py`):
`name`, `t_gate_ns`, `p_phys`, `topology`, `readout_error` (default `0.0`), `T1_us` (default `None`), `T2_us` (default `None`), `t_meas_ns` (default `None`), `p_t_state` (default `None`)

**`CodeResult`** — nested inside `compare()["results"][hardware_name]`, a `list[CodeResult]`:
`code_name`, `distance`, `qubits_per_logical`, `total_physical_qubits`, `gate_overhead_per_logical`, `total_physical_gates`, `execution_time_us`, `p_logical_achieved`, `fidelity_circuit`, `feasible`, `reason`, `meets_fidelity_target`

**`Recommendation`** — what `rank()`/`rank_by_metric()` return, `list[Recommendation]`:
`rank`, `hardware`, `code` **(not `code_name`)**, `total_physical_qubits`, `execution_time_us`, `fidelity_circuit`, `score`, `bottleneck`, `magic_state_qubits`, `magic_state_factories`, `magic_state_t_state_error`, `meets_fidelity_target`

`code_name` (`CodeResult`) vs `code` (`Recommendation`) is the same "which QEC code" value
under two different names, depending on which object you're holding. `total_physical_qubits`
and `fidelity_circuit`/`meets_fidelity_target` happen to be spelled the same in both.

`compare()`'s full return shape:
```python
{
    "circuit_profile": CircuitProfile,
    "results": {hardware_name: [CodeResult, ...], ...},
    "hardware_profiles": {hardware_name: HardwareProfile, ...},
    "fidelity_target": float,
}
```

## Known pitfalls (real errors, with the fix)

- **`compare()`'s `hardware_list` must be a `list`**, even for a single hardware —
  `compare(circuit, hw, ...)` with a bare `HardwareProfile` raises `TypeError`. Use
  `compare(circuit, [hw], ...)`.
- **Unbound `Parameter`s raise `ValueError`.** Variational circuit templates
  (`real_amplitudes()`, `efficient_su2()`, `QAOAAnsatz`, `UCCSD`, ...) carry symbolic
  parameters until `.assign_parameters(...)` is called — T-count depends on the actual
  rotation angles. Bind parameters before passing the circuit to `extract_circuit_profile()`,
  `estimate()`, or `compare()`.
- **`HardwareProfile.T2_us` can't exceed `2 * T1_us`** — enforced in `__post_init__`
  (Bloch relation, `1/T2 = 1/(2T1) + 1/Tφ`, `Tφ >= 0`). Raises `ValueError` if violated when
  both are set (a small float tolerance covers rounding noise at the boundary).
- **`rank()` returning an empty list has two different causes** — don't assume they mean
  the same thing:
  1. `compare()`'s `hardware_list` was empty, or every hardware in it failed to produce a
     valid `CodeResult` at all.
  2. The T1-viability filter (`execution_time_us / T1_us >= 0.5` excludes a candidate) —
     only active when `hardware_calibrations=` is passed to `rank()`.
  Neither of these is the same as "nothing tested reaches `fidelity_target`" — that case
  still returns a non-empty list (Tier B, sorted by `fidelity_circuit`, all with
  `meets_fidelity_target=False`). Check `meets_fidelity_target` on `recommendations[0]`
  before treating `#1` as an actual answer to a fidelity requirement.
- **Dynamic circuits are not supported.** A `QuantumCircuit` containing `if_else`,
  `while_loop`, or `for_loop` (Qiskit control-flow ops, e.g. from `qc.if_test(...)`) raises
  `TranspilerError` from inside `_count_t_gates()` — the internal `transpile()` call targets
  a fixed Clifford+T basis and has no equivalence rule for classically-conditioned
  operations. There is no workaround in the current public API; this applies to
  `extract_circuit_profile()`, `estimate()`, and `compare()` alike.
- **`autoq_qec.sensitivity` may not be importable.** It has shipped and been withdrawn from
  released versions before — check `autoq_qec.__version__` and the package's own
  `CHANGELOG.md` before assuming `sensitivity_analysis()`/`SensitivityResult` are available,
  rather than trying the import and treating an `ImportError` as a bug. See "API stability
  policy" below for how this fits the project's broader stability guarantees.

## API stability policy

- **Guaranteed stable** (semver-committed — a breaking change here requires a major version
  bump): every name currently in `autoq_qec.__init__.__all__` — `CircuitProfile`,
  `HardwareProfile`, `CodeResult`, `CalibratedHardware`, `HARDWARE_PROFILES`,
  `Recommendation`, `AlgorithmEstimator`, `AlgorithmEstimate`, `extract_circuit_profile`,
  `estimate`, `compare`, `rank`, `rank_by_metric`. Field names/signatures for these won't
  change without a major bump; new optional fields or keyword arguments may be added in a
  minor release.
- **Explicitly unstable** (may be added, changed, or withdrawn without a major bump): anything
  reachable but not re-exported at the top level — `autoq_qec.sensitivity`
  (`sensitivity_analysis`/`SensitivityResult`), `autoq_qec.visualizer.plot_tradeoff`,
  `autoq_qec.real_hardware.from_ibm_backend`/`noise_model_from_ibm`,
  `autoq_qec.distillation.magic_state_resources`/`build_magic_state_factory`. This is not a
  hypothetical caveat: `autoq_qec.sensitivity` has already been shipped and withdrawn once —
  treat that as the concrete precedent for this whole category, not an edge case.
- **Internal, no guarantee at all**: any name starting with `_` in any module (e.g.
  `_count_t_gates`, `_surface_code_model`, `_find_calibration`). These can change shape or
  disappear in any release, including a patch release.
- **How this project versions changes**: patch = docs/tooling/non-behavioral fixes (no change
  to what any guaranteed-stable function accepts or returns); minor = new guaranteed-stable
  API surface, or a new optional parameter with a backward-compatible default; major = any
  change to a name, signature, or field already listed as guaranteed stable above.

## Minimal correct recipe

```python
from qiskit import QuantumCircuit
from autoq_qec import compare, rank, HARDWARE_PROFILES, HardwareProfile

circuit = QuantumCircuit(4)
circuit.h(0); circuit.cx(0, 1); circuit.cx(1, 2); circuit.cx(2, 3)
circuit.measure_all()

hardwares = [HardwareProfile.from_calibrated(hw) for hw in [
    HARDWARE_PROFILES["IBM_Heron_r2"],
    HARDWARE_PROFILES["Quantinuum_H2"],
]]  # from_calibrated() carries real T1_us/T2_us/readout_error automatically

result = compare(circuit, hardwares, fidelity_target=0.99)
recommendations = rank(result)

best = recommendations[0]
print(best.hardware, best.code, best.total_physical_qubits,
      best.execution_time_us, best.fidelity_circuit, best.meets_fidelity_target)
```

## `rank()` weight presets — quick reference

Full explanation and worked examples: README.md, "`rank()` weights". Summary:

| Preset | `weight_qubits, weight_time, weight_fidelity` | Use when |
|---|---|---|
| Default | `0.5, 0.3, 0.2` | NISQ hardware, qubits are the scarce resource |
| Speed | `0.1, 0.8, 0.1` | Paying for queue/execution time |
| Fidelity margin | `0.1, 0.1, 0.8` | Need safety margin, not just clearing the bar |
| Balanced | `1, 1, 1` | No clear priority yet |
| Operational cost | `0.45, 0.45, 0.1` | `fidelity_target` already sets the fidelity floor |

Weights don't need to sum to 1.0 (normalized automatically). At least one must be nonzero;
none can be negative or `NaN` (`ValueError` otherwise).
