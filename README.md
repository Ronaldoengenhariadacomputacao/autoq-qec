# AutoQ QEC Estimator

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21398841.svg)](https://doi.org/10.5281/zenodo.21398841)

**Multi-code fault-tolerant quantum error correction estimator for arbitrary Qiskit circuits.**

Given any Qiskit circuit and a set of hardware profiles, AutoQ QEC returns a ranked comparison of QEC codes (Surface Code, Floquet Code, Bacon-Shor, Steane [[7,1,3]]) with physically grounded resource estimates: physical qubit count, execution time, and circuit fidelity.

## What this does that nothing else does

| Tool | Multi-code | Arbitrary circuit | Analytic model | Qiskit-native |
|---|---|---|---|---|
| Azure Resource Estimator | ✅ Surface + Floquet + custom | ✅ | ✅ | ⚠️ accepts Qiskit input, compiles via QIR |
| stim | ✅ | ❌ needs rewrite | ❌ simulation | ❌ |
| qiskit-qec | ✅ | ❌ no estimator | ❌ | ✅ |
| **AutoQ QEC** | ✅ | ✅ | ✅ | ✅ |

## Install

```bash
pip install autoq-qec
# With IBM Quantum integration:
pip install "autoq-qec[ibm,sim]"
```

## Quickstart

```python
from qiskit import QuantumCircuit
from autoq_qec import compare, rank
from autoq_qec import HARDWARE_PROFILES, CalibratedHardware, HardwareProfile

# Any Qiskit circuit
circuit = QuantumCircuit(4)
circuit.h(0); circuit.cx(0,1); circuit.cx(1,2); circuit.cx(2,3)

# Hardware profiles (built-in or custom). readout_error is optional
# (defaults to 0.0) but recommended — omitting it overestimates fidelity,
# since it ignores measurement error entirely (see "Physical models" below).
hardwares = [
    HardwareProfile("IBM_Eagle",     t_gate_ns=391,   p_phys=0.0062, topology="heavy-hex", readout_error=0.014),
    HardwareProfile("IBM_Heron",     t_gate_ns=100,   p_phys=0.003,  topology="heavy-hex", readout_error=0.009),
    HardwareProfile("Quantinuum_H2", t_gate_ns=100e3, p_phys=0.0015, topology="all-to-all", readout_error=0.0015),
]

# One call — returns all codes × all hardwares
result = compare(circuit, hardwares, fidelity_target=0.99)

# Pass hardware_calibrations to exclude combinations that violate T1
# (t_circuit >= 0.5×T1) — matches by name or by (t_gate_ns, p_phys)
recommendations = rank(result, hardware_calibrations=HARDWARE_PROFILES)

for r in recommendations[:3]:
    print(f"#{r.rank} {r.hardware} + {r.code}: "
          f"{r.total_physical_qubits}q, {r.execution_time_us:.1f}µs, "
          f"fidelity={r.fidelity_circuit:.4f}")
```

**Variational circuits (VQE, QAOA, etc.) must have parameters bound first.** `RealAmplitudes`, `EfficientSU2`, `QAOAAnsatz`, and similar templates carry symbolic parameters until you call `assign_parameters()` — T-count depends on the actual rotation angles, which don't exist in a symbolic circuit. Passing an unbound circuit raises a clear `ValueError` (as of 3.2.2):

```python
from qiskit.circuit.library import RealAmplitudes
import numpy as np

template = RealAmplitudes(4, reps=2).decompose()
rng = np.random.default_rng(42)
circuit = template.assign_parameters(rng.uniform(0, 2*np.pi, template.num_parameters))

result = compare(circuit, hardwares, fidelity_target=0.99)  # now works
```

## With real IBM calibration data

```python
from autoq_qec.real_hardware import from_ibm_backend, noise_model_from_ibm

# Pulls today's calibration — T1, T2, CX error per qubit pair
hw = from_ibm_backend("ibm_brisbane", token="YOUR_IBM_TOKEN")

# Simulate locally with real noise model (no queue, no cost)
sim = noise_model_from_ibm("ibm_brisbane", token="YOUR_IBM_TOKEN")
```

## Physical models

| Code | Model | Reference |
|---|---|---|
| Surface Code | $p_L \approx A(p/p_{th})^{(d+1)/2}$, $q=2d^2-1$, overhead $=d^3$ | Fowler et al., PRA 86, 032324 (2012) |
| Floquet Code | $p_L \approx 0.07(p/p_{th})^{(d+1)/2}$, $q=4d^2+8(d-1)$, overhead $=\lfloor d/2\rfloor$ | Gidney & Fowler, arXiv:2202.11829 |
| Bacon-Shor | $p_L \approx (p/p_{th})^d$, $q=d^2$, overhead $=d\cdot2(d-1)$ | Aliferis & Cross, PRL 98, 220502 (2007); overhead: Li, Miller & Brown, arXiv:1804.01127 (2018) + Aliferis PhD thesis, quant-ph/0703230, p.93 |
| Steane [[7,1,3]] | $p_L \approx 21p^2$, $q=13$, overhead $=6$ (fixo) | Steane, PRL 77, 793 (1996) |

Thresholds are enforced: `p ≥ p_th` raises `ValueError` — no silent wrong results.

**Magic state distillation (opt-in).** By default, `total_physical_qubits`/`execution_time_us` scale with `n_physical_gates` only and ignore T-gate count — physically inaccurate, since magic state distillation (needed for T-gates, not Clifford gates) is normally the dominant resource cost in real fault-tolerant quantum computing. Pass `model_magic_state_distillation=True` to `compare()`/`estimate()` to include it: each `CodeResult` gets `magic_state_qubits`, `magic_state_factories`, and `magic_state_t_state_error` populated, and both totals grow accordingly.

```python
result = compare(circuit, hardwares, fidelity_target=0.99, model_magic_state_distillation=True)
```

The T-factory cost model (`autoq_qec/distillation.py`) implements the multi-round 15-to-1 distillation formulas from Beverland, Kliuchnikov, Schoute et al., "Assessing requirements to scale to practical quantum advantage", arXiv:2211.07629 (Appendix C, Table VI; Appendix E, Eqs. C1–C4, E4–E6) — validated against the paper's own worked examples (Table VII) as regression tests (`tests/test_distillation.py`), reproducing their exact numbers (qubits, time, output error) for both a 1-round and a 2-round factory. Two simplifications versus the paper, documented in the module docstring: the per-round factory search is greedy (cheapest distance meeting the round's error target) rather than a global optimum over a full factory catalog, and the physical T-state input error is assumed equal to the hardware's Clifford error rate `p_phys` (the paper allows a separate value for Majorana qubits, which this package doesn't model). Default is `False` — existing code is unaffected.

**Fidelity formula**: `fidelity_circuit = (1 - p_L)^n_gates × (1 - readout_error)^n_logical_qubits × exp(-execution_time_us / T2_us)`. `readout_error` and `T2_us` are optional fields on `HardwareProfile` (default `0.0` / `None`, preserving the old formula if omitted).

This is an order-of-magnitude estimator, not a calibrated simulator. The readout term was added after comparing a hand-rolled `(1-p_phys)^n_gates` baseline against noisy Aer simulations of a GHZ-4 circuit, across 4 hardware noise models — 3 real (IBM `ibm_fez`, `ibm_marrakesh`, `ibm_kingston`, pulled live via Open Plan) and 1 synthetic (Google Willow, built from the published Nature 638 specs, since Google has no public self-service hardware access):

| Hardware | Prediction error, gate-error only | Prediction error, with readout term |
|---|---|---|
| ibm_fez (real) | 5.3% | 2.4% |
| ibm_marrakesh (real) | 10.3% | 2.7% |
| ibm_kingston (real) | 0.8% | 5.3% (worse) |
| Google Willow (synthetic) | 2.4% | 0.4% |

Adding readout error improved the prediction in 3 of 4 cases; it made `ibm_kingston` worse, most likely single-run shot noise (4000 shots, one run) rather than a systematic flaw — `ibm_kingston`'s gate-error-only baseline was already unusually accurate (0.8% off) before the correction. This was a structural sanity check on the *shape* of the formula, not a calibration of `fidelity_circuit` itself (which uses `p_L`, the post-QEC logical error rate — several orders of magnitude smaller than raw `p_phys`, so the two aren't numerically comparable). Treat `fidelity_circuit` as directionally correct, not a precise prediction.

**Independent re-check (2026-07-16)**, using the actual circuits shown in this README (Quickstart) and in `example.py` (not a separate GHZ-4), against live calibration for the same 3 IBM backends: no-readout error stayed low (0.3%–3.3%, measured via density-matrix state fidelity — a stricter check than the shot-based method above), but the readout-term error was larger and less consistent (1.4%–29.1%, measured via classical shot fidelity). Two identified causes, neither indicating the formula is wrong: (1) hardware calibration drifts daily, so no single run's percentages are stable ground truth; (2) shot-based fidelity is insensitive to phase errors on circuits whose ideal measurement distribution is already close to uniform (e.g. QFT), which can make the readout term look like it hurts accuracy for reasons unrelated to its correctness. Bottom line unchanged, reinforced: this is a directional sanity check, not a reproducible-to-the-decimal benchmark — expect the exact percentages to vary run to run.

## Algorithm Estimator

Order-of-magnitude T-count estimates for known algorithms, without building the full circuit:

```python
from autoq_qec import AlgorithmEstimator

est = AlgorithmEstimator.shor(2048)
print(est.t_count_estimate, est.t_count_uncertainty)  # ±5x — build the real circuit for precise numbers
```

Covers `shor`, `grover`, `qft`, `vqe`. These are rough estimates (±2×–±10× depending on the algorithm) — use `extract_circuit_profile()` on a real circuit whenever possible.

## Hardware profiles

Includes `Google_Willow` (105q, Acharya et al., Nature 638, 964-971, 2025) and `IBM_Heron_r3` (`ibm_pittsburgh`, Q4 2025), alongside `IBM_Eagle_r3`, `IBM_Heron_r2`, `Quantinuum_H2`, `IonQ_Aria`, `Google_Sycamore`.

## Visualization

```bash
pip install "autoq-qec[viz]"
```

```python
from autoq_qec.visualizer import plot_tradeoff

result = compare(circuit, hardwares, fidelity_target=0.99)
plot_tradeoff(result, output="tradeoff.png")  # log-log qubits × time, color = fidelity
```

## Test

```bash
pytest tests/ -v   # 81 tests, all verify physics not arithmetic
```

## What the tests check (unlike most QEC tools)

- `p ≥ threshold` raises `ValueError`, not wrong overhead
- `d` is always odd for Surface Code (rotated lattice requirement)
- `p_L ≤ p_L_target` guaranteed after distance selection
- Noisier hardware requires larger `d` (monotonicity)
- `estimate()` raises `ValueError` on a zero-gate `CircuitProfile` (e.g. destroyed by transpiler) — not `extract_circuit_profile()` itself, which returns a valid zero-gate profile for an actually empty circuit
- `extract_circuit_profile()` raises `ValueError` on circuits with unbound parameters — see "Variational circuits" above
- Fidelity scales correctly with `t_gate`

## Author

Ronaldo Rodrigues — ORCID: [0009-0006-7449-1190](https://orcid.org/0009-0006-7449-1190)
