# AutoQ QEC Estimator

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21402245.svg)](https://doi.org/10.5281/zenodo.21402245)

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

## `rank()` weights

`rank()` combines three different metrics into a single score, using weights you choose. Each weight controls how much that metric counts against the other two:

| Parameter | Default | Controls | Increasing it favors... |
|---|---|---|---|
| `weight_qubits` | `0.5` | Total physical qubits the hardware+code combination needs | Combinations that save qubits, even if slower or with less fidelity margin |
| `weight_time` | `0.3` | Execution time (µs) the combination takes | Fast combinations, even if they need more qubits |
| `weight_fidelity` | `0.2` | How far predicted fidelity sits above your `fidelity_target` | Combinations with more fidelity safety margin, even if costlier in qubits/time |

Weights don't need to sum to 1.0 — they're normalized automatically (the ratio between them is what matters, not the absolute values). **The default weights genuinely change the outcome — verified empirically**: the same circuit/hardware list ranked with `weight_time=0.9` instead of the default reordered the ranking substantially (a combination that ranked #3 by default dropped out of the top 5 entirely, replaced by a faster-but-more-qubit-hungry option). Qubits, time, and fidelity are different units with no natural common scale — the weights *are* the exchange rate between them, and the right rate depends on your actual constraints (e.g., queue-time-billed access cares more about time; qubit-scarce hardware cares more about qubit count). There is no single "objective" ranking — pass weights that reflect your real situation.

```python
# 1. Default: prioritize qubit savings
recommendations = rank(result)  # weight_qubits=0.5, weight_time=0.3, weight_fidelity=0.2

# 2. Prioritize execution speed
recommendations = rank(result, weight_qubits=0.1, weight_time=0.8, weight_fidelity=0.1)

# 3. Prioritize fidelity margin
recommendations = rank(result, weight_qubits=0.1, weight_time=0.1, weight_fidelity=0.8)

# 4. Balanced: all three metrics count equally
recommendations = rank(result, weight_qubits=1, weight_time=1, weight_fidelity=1)

# 5. Operational cost (qubits + time); fidelity only needs to clear the target
recommendations = rank(result, weight_qubits=0.45, weight_time=0.45, weight_fidelity=0.1)
```

| # | Preset | When to use |
|---|---|---|
| 1 | Default (qubit savings) | NISQ hardware with few physical qubits available — the most common constraint today |
| 2 | Speed | You pay for queue/execution time, or decoherence over time is the bigger concern |
| 3 | Fidelity margin | Your use case can't tolerate being right at the edge — you want extra safety margin, not just barely clearing the bar |
| 4 | Balanced | You don't yet know which constraint matters most and want a neutral starting point |
| 5 | Operational cost | Fidelity is already guaranteed by `fidelity_target` (a minimum requirement, not something to maximize) — what's left to decide is qubits vs. time |

### `rank_by_metric()` — when weights can't show you the trade-off

When one hardware+code combination beats every other candidate on *every* metric at once (qubits, time, *and* fidelity — a "Pareto-dominant" option), no weight combination in `rank()` can ever pick anything else as `#1`: a weighted sum can't rank a dominated option above a dominant one. That's mathematically correct, but it can hide real trade-offs among the *non-dominant* options. `rank_by_metric()` sidesteps this by ranking each metric independently, with no weighting at all:

```python
from autoq_qec import rank_by_metric

por_metrica = rank_by_metric(result)
for metrica, lista in por_metrica.items():
    top = lista[0]
    print(f"Best by {metrica}: {top.hardware}/{top.code} — "
          f"{top.total_physical_qubits}q, {top.execution_time_us}µs, fid={top.fidelity_circuit:.5f}")
```

Real example from this package's own test suite (QFT on 6 qubits, `fidelity_target=0.999`, comparing IBM Eagle/Heron and Quantinuum H2) — `rank()` converges to the same `#1` under all 5 presets above, yet the per-metric breakdown reveals a real trade-off hidden behind that single "winner":

| Metric | Winner | Qubits | Time | Fidelity |
|---|---|---|---|---|
| Qubits | `Quantinuum_H2`/Bacon-Shor | **294** | 680,400 µs | 0.99934 |
| Time | `IBM_Heron`/Floquet Code | 6,072 | **77.7 µs** | 0.99949 |
| Fidelity | `Quantinuum_H2`/Floquet Code | 2,328 | 32,400 µs | **0.99957** |

A ~78× time spread and a ~20× qubit spread between the extremes — none of that is visible if you only look at `rank()`'s combined `#1`. Use `rank_by_metric()` first to see the actual shape of your trade-off space, then use `rank()` with weights once you know which end of that space you actually care about.

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

**Known limitation: mid-circuit measurement error is not modeled separately.** `readout_error` represents end-of-circuit measurement error only. Real hardware (including Quantinuum's own datasheet, cited above) reports a distinct, usually different "mid-circuit measurement and reset cross-talk error" for measurements that happen mid-circuit — common in real fault-tolerant protocols using dynamic circuits (measurement + conditional reset). This package does not currently distinguish between the two — any measurement in your circuit, wherever it occurs, is treated as if it happens at the end. If your circuit relies heavily on mid-circuit measurement, treat `readout_error`'s contribution to `fidelity_circuit` as an approximation, not a precise model of that specific error source.

This is an order-of-magnitude estimator, not a calibrated simulator. The table below validates the formula's *shape* — not a precise calibration — against the actual Quickstart circuit above, on real live calibration for 3 IBM backends (`ibm_fez`, `ibm_marrakesh`, `ibm_kingston`, pulled via `QiskitRuntimeService`, Open Plan) and 1 synthetic profile (Google Willow, `HARDWARE_PROFILES["Google_Willow"]`, built from the published Nature 638 specs — Google has no public self-service hardware access). Two different, methodology-matched ground truths are used per column: the no-readout prediction is checked against **state fidelity** (density-matrix comparison, no measurement — readout error structurally can't appear here, so this is the right ground truth for that column); the with-readout prediction is checked against **classical shot fidelity** (real measurement, 8192 shots — the only way readout error actually manifests):

| Hardware | Empirical (state fidelity) | Predicted, no readout | Error | Empirical (shots) | Predicted, with readout | Error |
|---|---|---|---|---|---|---|
| ibm_fez (real) | 98.24% | 99.62% | 1.4% | 93.46% | 92.31% | 1.2% |
| ibm_marrakesh (real) | 98.99% | 99.62% | 0.6% | 97.04% | 88.43% | 8.9% |
| ibm_kingston (real) | 99.35% | 99.74% | 0.4% | 96.90% | 92.41% | 4.6% |
| Google Willow (synthetic) | 99.04% | 99.92% | 0.9% | 99.22% | 96.77% | 2.5% |

*(Last measured 2026-07-16. `Google_Willow`'s figures use a simplified synthetic noise model — depolarizing errors sized from `p_1q_mean`/`p_2q_mean`, no full thermal-relaxation channel — since there's no live backend to query; treat it as a rougher check than the 3 real rows.)*

The no-readout column is consistently accurate (0.4%–1.4% error). The with-readout column is less precise (1.2%–8.9%) but still directionally correct — treat `fidelity_circuit` as an order-of-magnitude estimate, not a calibrated prediction. **These exact percentages will not reproduce on a future run**: IBM's live calibration drifts daily (this table is a snapshot, not a fixed benchmark), and no fixed random seed underlies the noisy simulation. If you need this validated against *today's* calibration, the methodology above is straightforward to rerun — pull `CalibratedHardware` via `from_ibm_backend()`, build a noisy `AerSimulator` via `NoiseModel.from_backend()`, and compare `state_fidelity`/shot-based classical fidelity against `estimate()`'s `fidelity_circuit`.

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
pytest tests/ -v   # 97 tests, all verify physics not arithmetic
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
