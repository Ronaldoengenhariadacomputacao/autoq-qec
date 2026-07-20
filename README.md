# AutoQ QEC Estimator

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21433371.svg)](https://doi.org/10.5281/zenodo.21433371)
[![Qiskit Ecosystem](https://qisk.it/e-5c47e416)](https://qisk.it/e)

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

# Hardware profiles: built-in (recommended — carries real readout_error/T1_us/
# T2_us automatically) or custom, built by hand for hardware not in the list.
hardwares = [HardwareProfile.from_calibrated(hw) for hw in [
    HARDWARE_PROFILES["IBM_Eagle_r3"],
    HARDWARE_PROFILES["IBM_Heron_r2"],
    HARDWARE_PROFILES["Quantinuum_H2"],
]]

# Custom hardware (not in HARDWARE_PROFILES): build HardwareProfile by hand.
# readout_error/T1_us/T2_us are all optional (default 0.0/None) but
# recommended — omitting readout_error overestimates fidelity (see "Physical
# models" below); omitting T2_us skips the decoherence penalty entirely
# (see "Two-tier ranking" below for why that matters for rank()).
# hardwares = [HardwareProfile("MyChip", t_gate_ns=200, p_phys=0.004,
#                               topology="heavy-hex", readout_error=0.01, T2_us=150)]

# One call — returns all codes × all hardwares
result = compare(circuit, hardwares, fidelity_target=0.99)

# Pass hardware_calibrations to exclude combinations that violate T1
# (t_circuit >= 0.5×T1) — matches by name or by (t_gate_ns, p_phys)
recommendations = rank(result, hardware_calibrations=HARDWARE_PROFILES)

for r in recommendations[:3]:
    print(f"#{r.rank} {r.hardware} + {r.code}: "
          f"{r.total_physical_qubits}q, {r.execution_time_us:.1f}µs, "
          f"fidelity={r.fidelity_circuit:.4f}, meets_target={r.meets_fidelity_target}")
```

Using real calibrated `T2_us` (via `from_calibrated()` above), this particular circuit/hardware combination doesn't actually clear `fidelity_target=0.99` on any of the 3 built-in profiles — `meets_target` prints `False` for all of them. That's the point of `meets_fidelity_target`: it tells you honestly when nothing tested delivers what you asked for, instead of silently ranking the least-bad option as if it were a real answer. Try `fidelity_target=0.9` or a deeper/wider circuit to see `meets_target=True` results.

## `rank()` weights

`rank()` combines three different metrics into a single score, using weights you choose. Each weight controls how much that metric counts against the other two:

| Parameter | Default | Controls | Increasing it favors... |
|---|---|---|---|
| `weight_qubits` | `0.5` | Total physical qubits the hardware+code combination needs | Combinations that save qubits, even if slower or with less fidelity margin |
| `weight_time` | `0.3` | Execution time (µs) the combination takes | Fast combinations, even if they need more qubits |
| `weight_fidelity` | `0.2` | Fidelity margin *among combinations that already meet `fidelity_target`* (see "Two-tier ranking" below — this weight never lets a combination below your target outrank one that meets it) | Combinations with more fidelity safety margin, even if costlier in qubits/time |

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

### Two-tier ranking: `meets_fidelity_target`

A QEC code being "feasible" (a valid distance `d` exists for your `p_phys`) only guarantees the *gate-error* contribution to `p_L` stays under budget. It does **not** guarantee the final `fidelity_circuit` — which also multiplies in `readout_error` and, if you set `T2_us`, a decoherence penalty (`exp(-execution_time_us / T2_us)`) — actually reaches your `fidelity_target`. A slow combination (e.g. deep QEC syndrome-extraction overhead on a long-`t_gate_ns` hardware) can be "feasible" by the gate-error criterion alone while its real fidelity, once decoherence is accounted for, has collapsed to near zero.

Each `Recommendation` (and the underlying `CodeResult`) has a `meets_fidelity_target: bool` field for exactly this: `True` only when `fidelity_circuit >= fidelity_target`. `rank()` uses it to build two tiers, **without excluding anything**:

- **Tier A** (`meets_fidelity_target=True`): ranked normally, by the weighted score above (the 5 presets, weights table). `#1` only ever comes from this tier.
- **Tier B** (`meets_fidelity_target=False`): never outranks Tier A, regardless of weights — qubits/time trade-offs are meaningless for a combination that doesn't deliver the fidelity you asked for. Sorted purely by `fidelity_circuit` descending (closest to the target first), with `bottleneck` explaining the shortfall (e.g. `"NÃO atinge fidelity_target=0.9900 (fidelidade real: 0.0000) — ..."`).

If Tier A is empty (nothing tested actually reaches your target), `rank()` still returns Tier B — check `meets_fidelity_target` before trusting `#1` as an actual answer to your request, not just "the best of what was tried."

```python
recommendations = rank(result)
if not recommendations[0].meets_fidelity_target:
    print("Nenhuma combinação testada atinge o fidelity_target pedido.")
```

### Getting real decoherence data: `HardwareProfile.from_calibrated()`

`T2_us` defaults to `None` (no decoherence penalty applied) — and it's easy to lose accidentally: hand-building a `HardwareProfile` (as the Quickstart above does) by copying only `t_gate_ns`/`p_phys`/`topology`/`readout_error` silently drops `T2_us`/`T1_us` even when real values exist. The built-in `HARDWARE_PROFILES` (`CalibratedHardware` objects) already have real `T2_us` for every entry — use `from_calibrated()` to carry all of it over at once instead of copying fields by hand:

```python
from autoq_qec import HardwareProfile
from autoq_qec.real_hardware import HARDWARE_PROFILES

hw = HardwareProfile.from_calibrated(HARDWARE_PROFILES["IBM_Heron_r2"])
# hw.T2_us, hw.T1_us, hw.readout_error are all populated — nothing to remember
```

If you build a `HardwareProfile` by hand and leave `readout_error`/`T1_us`/`T2_us` at their defaults, `compare()`/`estimate()` emit a `UserWarning` naming exactly which of the three are still missing (with a short description of what each one does) — set one and it drops out of the message; set (or load via `from_calibrated()`) all three and the warning stops. Zero or negative values for `t_gate_ns`, `p_phys`, `T1_us`, `T2_us`, or `t_meas_ns` (and `readout_error` outside `[0, 1)`) raise `ValueError` immediately — they have no physical meaning, and previously produced silently wrong results (`t_gate_ns=0` gave `execution_time_us=0.0`; `readout_error=5.0` gave `fidelity_circuit` above `1.0`).

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

`rank_by_metric()` inherits the same two-tier logic as `rank()`: within Tier A (`meets_fidelity_target=True`), each list is genuinely sorted by its own metric — `["qubits"]` by qubit count, `["tempo"]` by time. But if *nothing* tested reaches `fidelity_target`, all three lists fall entirely into Tier B and get sorted by `fidelity_circuit` instead, regardless of the list's name — check `meets_fidelity_target` on the entries before assuming `["qubits"][0]` is actually the qubit-cheapest option.

### Comparing across vendors — weights don't guarantee a "neutral" answer

`rank()`'s weights let *you* pick what matters, but that's configurability, not neutrality — the ranking still reflects each hardware's real physical numbers (`p_phys`, `T1_us`, `T2_us`, gate times), and different circuits genuinely favor different vendors depending on which weight you emphasize. There's no fixed pattern where one vendor "usually wins" a given preset — verified empirically: ranking a 4-qubit GHZ circuit across `IBM_Heron_r2`, `Quantinuum_H2`, and `IonQ_Aria` (all via `HardwareProfile.from_calibrated()`) puts `Quantinuum_H2` at `#1` under the default preset, the fidelity-focused preset (`weight_fidelity=0.8`), *and* the speed-focused preset (`weight_time=0.8`) — not the "IBM wins by default, ion-trap wins on fidelity" pattern you might expect. A different circuit can flip this entirely.

```python
hardwares = [HardwareProfile.from_calibrated(hw) for hw in [
    HARDWARE_PROFILES["IBM_Heron_r2"],
    HARDWARE_PROFILES["Quantinuum_H2"],
    HARDWARE_PROFILES["IonQ_Aria"],
]]
result = compare(circuit, hardwares, fidelity_target=0.9)

for r in rank(result, weight_qubits=0.1, weight_time=0.1, weight_fidelity=0.8)[:3]:
    print(f"#{r.rank} {r.hardware} + {r.code}: {r.total_physical_qubits}q, fid={r.fidelity_circuit:.4f}")
```

The practical takeaway: always compare against **your actual circuit** with **multiple real hardware profiles** (`HARDWARE_PROFILES`, not just one vendor) before trusting a `#1` — and pick weights that match your real constraints (see the presets table above), not weights chosen to make a particular hardware win.

**Variational circuits (VQE, QAOA, etc.) must have parameters bound first.** `real_amplitudes()`, `efficient_su2()`, `QAOAAnsatz`, and similar templates carry symbolic parameters until you call `assign_parameters()` — T-count depends on the actual rotation angles, which don't exist in a symbolic circuit. Passing an unbound circuit raises a clear `ValueError` (as of 3.2.2):

```python
from qiskit.circuit.library import real_amplitudes
import numpy as np

template = real_amplitudes(4, reps=2)
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
| Floquet Code | $p_L \approx 0.07(p/p_{th})^{(d+1)/2}$, $q=4d^2+8(d-1)$, overhead $=\lfloor d/2\rfloor$ | Paetznick, Knapp, Delfosse, Bauer, Haah, Hastings & da Silva, arXiv:2202.11829 |
| Bacon-Shor | $p_L \approx (p/p_{th})^d$, $q=d^2$, overhead $=d\cdot2(d-1)$ | Aliferis & Cross, PRL 98, 220502 (2007); overhead: Li, Miller & Brown, arXiv:1804.01127 (2018) + Aliferis PhD thesis, quant-ph/0703230, p.93 |
| Steane [[7,1,3]] | $p_L \approx 21p^2$, $q=13$, overhead $=6$ (fixo) | Steane, PRL 77, 793 (1996) |

Thresholds are enforced: `p ≥ p_th` raises `ValueError` — no silent wrong results.

### Majorana / topological qubits

The Floquet Code model above is already Majorana-native, even though nothing in its implementation says so: the cited paper (Paetznick, Knapp, Delfosse, Bauer, Haah, Hastings & da Silva, arXiv:2202.11829, Microsoft authors) defines its physical error rate `p` as *"each two-qubit measurement fails independently with probability p"* — the native operation for measurement-only Majorana zero mode (MZM) qubits, not a gate. `p_th=0.01`/`A=0.07` were checked number-for-number against the paper's own formula. No change to `extract_circuit_profile()`'s gate-count-based pipeline was needed for this to hold — a counted 2-qubit operation already serves as the right proxy for a 2-qubit measurement, whichever physical mechanism actually implements it.

What Majorana qubits need that gate-based hardware doesn't: topological protection covers Clifford operations (measurement) but not the physical T-gate, which has a separate, much higher error rate. `HardwareProfile.p_t_state` (and `CalibratedHardware.p_t_state`) exists for exactly this — an optional field, distinct from `p_phys`, used only by magic state distillation (`model_magic_state_distillation=True`) as the T-state injection error `Q_0`. `p_t_state=None` (default) preserves the old behavior (`Q_0 = p_phys`) for every hardware that doesn't need the distinction.

```python
from autoq_qec import HardwareProfile
from autoq_qec.real_hardware import HARDWARE_PROFILES

hw = HardwareProfile.from_calibrated(
    HARDWARE_PROFILES["Majorana_MS_ResourceEstimator_illustrative"]
)
print(hw.p_phys, hw.p_t_state)  # 1e-05 0.015 -- distinct values
```

**This built-in entry is illustrative, not measured hardware — the name says so on purpose.** It's built from Microsoft's own public planning targets for the Azure Quantum Resource Estimator's `qdk.qre.models.qubits.Majorana` class (`error_rate` default `1e-5`, 1µs fixed time for every measurement/T-gate, "realistic"-regime non-Clifford T-gate error of 1.5% — [Microsoft Learn](https://learn.microsoft.com/en-us/python/qdk/qdk.qre.models.qubits.majorana), citing Karzig et al. arXiv:1610.05289, Kitaev cond-mat/0010440, Das Sarma et al. arXiv:1501.02813), plus the ~20-second mean qubit lifetime Microsoft reported for its "Majorana 2" chip launch ([Forbes, Jul 2026](https://www.forbes.com/sites/moorinsights/2026/07/16/microsoft-doubles-down-on-topological-qubits-with-majorana-2-chip/)) used as the closest public analogue for the `T1_us` viability filter. As of that same coverage, **two-qubit entangling/braiding operations had not yet been publicly demonstrated on real Majorana hardware** — "two-qubit entangling gates, which are essential for quantum computing, have yet to be demonstrated" — and independent physicists remain skeptical of the platform's core claims ([Nature, "Microsoft upgrades controversial quantum chip — researchers are still sceptical"](https://www.nature.com/articles/d41586-026-01788-y)). `p_phys`/`p_t_state` on this entry are Microsoft's own design targets, not measurements of a working chip — use it to explore the shape of the cost model, not as a performance prediction. This caveat is in the hardware's `name` field itself (`"... — not measured hardware"`), so it surfaces directly in any printed ranking table, not just here.

Microsoft has also published an older, distinct Majorana parameter pair in the Azure Quantum Resource Estimator itself (`qubit_maj_ns_e4`/`qubit_maj_ns_e6`, from Beverland, Kliuchnikov, Schoute et al., arXiv:2211.07629, Table 2 — 100ns operations, 5%/1% T-gate error at the `1e-4`/`1e-6` Clifford-error tiers, vs. this package's 1µs/1.5% from the newer `qdk.qre` Python API). Both are real, citable, Microsoft-published planning targets for the same underlying hardware concept — this package uses the newer API's numbers; if you need the older preset's numbers specifically, build a `HardwareProfile` by hand from Table 2 rather than assuming they match this entry.

**Surface Code, Bacon-Shor, and Steane [[7,1,3]] are not validated for this physical error mechanism.** Their thresholds come from gate-error literature (Fowler et al. PRA 86 032324 for Surface Code; Aliferis & Cross PRL 98 220502 for Bacon-Shor; Steane PRL 77 793) — a different physical error mechanism than the 2-qubit-measurement error Majorana qubits actually have. This is a documented gap, not a correction — there's no published data to recalibrate those three models against measurement-based error for topological qubits, so running them against a Majorana `HardwareProfile` extrapolates outside what their source literature covers.

**Magic state distillation (opt-in).** By default, `total_physical_qubits`/`execution_time_us` scale with `n_physical_gates` only and ignore T-gate count — physically inaccurate, since magic state distillation (needed for T-gates, not Clifford gates) is normally the dominant resource cost in real fault-tolerant quantum computing. Pass `model_magic_state_distillation=True` to `compare()`/`estimate()` to include it: each `CodeResult` gets `magic_state_qubits`, `magic_state_factories`, and `magic_state_t_state_error` populated, and both totals grow accordingly.

```python
result = compare(circuit, hardwares, fidelity_target=0.99, model_magic_state_distillation=True)
```

The T-factory cost model (`autoq_qec/distillation.py`) implements the multi-round 15-to-1 distillation formulas from Beverland, Kliuchnikov, Schoute et al., "Assessing requirements to scale to practical quantum advantage", arXiv:2211.07629 (Appendix C, Table VI; Appendix E, Eqs. C1–C4, E4–E6) — validated against the paper's own worked examples (Table VII) as regression tests (`tests/test_distillation.py`), reproducing their exact numbers (qubits, time, output error) for both a 1-round and a 2-round factory. Two simplifications versus the paper, documented in the module docstring: the per-round factory search is greedy (cheapest distance meeting the round's error target) rather than a global optimum over a full factory catalog, and the physical T-state input error defaults to the hardware's Clifford error rate `p_phys` unless you pass `HardwareProfile.p_t_state` — a separate value for the physical T-gate error, relevant when it differs from the Clifford/measurement error rate (the paper's own motivating case is Majorana qubits — see "Majorana / topological qubits" below). Default is `False` — existing code is unaffected.

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

Includes `Google_Willow` (105q, Acharya et al., Nature 638, 964-971, 2025) and `IBM_Heron_r3` (`ibm_pittsburgh`, Q4 2025), alongside `IBM_Eagle_r3`, `IBM_Heron_r2`, `Quantinuum_H2`, `IonQ_Aria`, `Google_Sycamore` — all with real `T1_us`/`T2_us`/`readout_error`. Use `HardwareProfile.from_calibrated(HARDWARE_PROFILES["..."])` to turn any of them into a `HardwareProfile` for `compare()` (see "Getting real decoherence data" above).

`Majorana_MS_ResourceEstimator_illustrative` is also included, but it's a different kind of entry — a topological-qubit design target, not measured hardware. See "Majorana / topological qubits" above before using it.

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
pytest tests/ -v   # 142 tests, all verify physics not arithmetic
```

## What the tests check (unlike most QEC tools)

- `p ≥ threshold` raises `ValueError`, not wrong overhead
- `d` is always odd for Surface Code (rotated lattice requirement)
- `p_L ≤ p_L_target` guaranteed after distance selection (gate-error contribution only — see "Two-tier ranking" above for what this does *not* guarantee about the final `fidelity_circuit`)
- Noisier hardware requires larger `d` (monotonicity)
- `estimate()` raises `ValueError` on a zero-gate `CircuitProfile` (e.g. destroyed by transpiler) — not `extract_circuit_profile()` itself, which returns a valid zero-gate profile for an actually empty circuit
- `extract_circuit_profile()` raises `ValueError` on circuits with unbound parameters — see "Variational circuits" above
- Fidelity scales correctly with `t_gate`
- `meets_fidelity_target=False` when decoherence (`T2_us`) collapses `fidelity_circuit` below `fidelity_target`, even though the code is still `feasible` by the gate-error criterion alone
- `rank()` never lets a combination below `fidelity_target` outrank one that meets it, regardless of weights

## Author

Ronaldo Rodrigues — ORCID: [0009-0006-7449-1190](https://orcid.org/0009-0006-7449-1190)
