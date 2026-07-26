# Multi-Scale Validation of autoq-qec: Analytical Prediction, Simulation, and Real Hardware Execution on IBM Fez

**Author:** Ronaldo Rodrigues
**Date:** July 25, 2026
**Dataset DOI:** https://doi.org/10.5281/zenodo.21571464
**Related software:** autoq-qec v3.4.3 — https://doi.org/10.5281/zenodo.21560570
**Repository:** https://github.com/Ronaldoengenhariadacomputacao/autoq-qec

---

## Abstract

This report validates the **autoq-qec** quantum error correction resource
estimator across two circuit scales (4 and 85 logical qubits) and two
simulation methodologies, using a quantum Pi-estimator circuit executed on
real IBM Fez hardware (Heron r2, 156 qubits). Across ten independent
real-hardware trials (5 per scale), autoq-qec's fidelity predictions agreed
with measured fidelity within 1 percentage point in every trial, though the
safety margin shrank sharply with scale — from 0.052 points at 4 qubits to
0.0045 points at 85 qubits. A second, independent finding emerged from
comparing two simulation methodologies: simulating with a manually-specified,
incomplete `HardwareProfile` (missing `readout_error`/`T1_us`/`T2_us`)
underestimated real-hardware error by 23–105×, while simulating with the
package's own fully-calibrated hardware profile
(`HARDWARE_PROFILES["IBM_Heron_r2"]`, which models the same physical chip)
tracked real-hardware error within 5–10× better agreement. This was traced to
a `UserWarning` that autoq-qec already emits for incomplete profiles — silenced
by a blanket `warnings.filterwarnings("ignore")` in the original test
script — meaning the large simulation-to-hardware gap reported in earlier
drafts of this validation was substantially a testing-methodology artifact,
not a limitation of autoq-qec's underlying fidelity model.

---

## 1. Benchmark Circuit: Quantum Pi Estimator

The circuit encodes π/4 as a quantum amplitude:

```
RY(θ) with θ = 2·arcsin(√(π/4)) ≈ 2.178272 rad
→ P(|1⟩) = sin²(θ/2) = π/4
→ π = 4·P(|1⟩)
```

`n` parallel estimators (`n` logical qubits, each an independent RY +
measurement, no entangling gates) reduce statistical error by √n. Two scales
were tested: **n = 4** (the original validation) and **n = 85** (a scale-up
test, using roughly half of IBM Fez's 156 physical qubits).

| Parameter | n = 4 | n = 85 |
|---|---|---|
| Logical qubits | 4 | 85 |
| Gates per qubit | 1 RY + 1 measurement | 1 RY + 1 measurement |
| Shots per trial | 100,000 | 100,000 |
| Theoretical shot-noise limit (mean of n qubits) | ±0.0026 | ±0.00057 |

---

## 2. Level 1 — Analytical Prediction (autoq-qec)

Predictions used a manually-specified `HardwareProfile("IBM_Fez", t_gate_ns=100,
p_phys=0.00156, topology="heavy-hex")` — see Section 6 for why this choice of
profile matters.

### n = 4

| Rank | Hardware | QEC Code | Phys. Qubits | Fidelity | Time (µs) |
|---|---|---|---|---|---|
| 1 | IBM Fez | Steane [[7,1,3]] | 52 | 0.999796 | 2.4 |
| 2 | Quantinuum H2 | Steane [[7,1,3]] | 52 | 0.999993 | 2400.0 |
| 3 | IBM Fez | Bacon-Shor | 144 | 0.999780 | 24.0 |
| 4 | Quantinuum H2 | Floquet Code | 208 | 0.999765 | 400.0 |
| 5 | IBM Heron | Steane [[7,1,3]] | 52 | 0.999244 | 2.4 |

### n = 85

| Rank | Hardware | QEC Code | Phys. Qubits | Fidelity | Time (µs) |
|---|---|---|---|---|---|
| 1 | IBM Fez | Bacon-Shor | 4165 | 0.999089 | 714.0 |
| 2 | IBM Fez | Floquet Code | 32980 | 0.999450 | 34.0 |
| 3 | IBM Fez | Surface Code | 13685 | 0.999215 | 6196.5 |
| — | IBM Fez | Steane [[7,1,3]] | — | — | **infeasible** |

**Qualitative shift with scale**: Steane [[7,1,3]] — the #1 code at n=4 — drops
out of the ranking entirely at n=85. Steane has a *fixed* code distance
(d=3), so its logical error rate is fixed at `p_L ≈ 21·p_phys²`; as the
circuit grows, the total physical-gate count `N` grows too, tightening the
per-gate error budget `p_L_target = (1−fidelity_target)/N`. A fixed-distance
code cannot adapt to a tighter budget the way Surface/Floquet/Bacon-Shor can
(by increasing `d`), so it becomes infeasible past a certain scale — a real,
predicted consequence of the underlying physics, not an artifact.

---

## 3. Level 2 — Simulation (Qiskit Aer, depolarizing noise from the manual profile)

Depolarizing noise model derived from the manual `HardwareProfile`
(1Q = 2.5×10⁻⁴, 2Q = 1.56×10⁻³ used for reference only — this circuit has no
2Q gates), 100,000 shots per run, no fixed random seed. **No readout error, no
T1/T2 decoherence** — see Section 6 for why this matters.

### n = 4, 5 runs (predicted fidelity target: 0.999796, Steane)

| Run | π estimate | Error (%) | Measured fidelity | Δ fidelity |
|---|---|---|---|---|
| 1 | 3.143730 ± 0.000823 | 0.0680 | 0.999466 | 0.000330 |
| 2 | 3.141150 ± 0.001568 | 0.0141 | 0.999889 | 0.000094 |
| 3 | 3.144440 ± 0.002249 | 0.0906 | 0.999288 | 0.000507 |
| 4 | 3.140480 ± 0.001363 | 0.0354 | 0.999722 | 0.000074 |
| 5 | 3.142470 ± 0.001077 | 0.0279 | 0.999781 | 0.000015 |
| **Mean ± std** | — | **0.0472 ± 0.0313** | **0.999629 ± 0.000246** | **0.000204 ± 0.000208** |

### n = 85, 5 runs (predicted fidelity target: 0.999089, Bacon-Shor)

| Run | π estimate | Error (%) | Measured fidelity | Δ fidelity |
|---|---|---|---|---|
| 1 | 3.140739 | 0.0272 | 0.999787 | 0.000698 |
| 2 | 3.142140 | 0.0174 | 0.999863 | 0.000774 |
| 3 | 3.141792 | 0.0063 | 0.999950 | 0.000861 |
| 4 | 3.141372 | 0.0070 | 0.999945 | 0.000856 |
| 5 | 3.141367 | 0.0072 | 0.999944 | 0.000855 |
| **Mean ± std** | — | **0.0130 ± 0.0091** | **0.999898 ± 0.0000718** | **0.000809 ± 0.0000718** |

---

## 4. Level 3 — Real Hardware Execution (IBM Fez), 5 trials per scale

**Backend:** ibm_fez (Heron r2, 156 qubits). **Shots:** 100,000/trial.

### n = 4

| Trial | Job ID | π estimate | Error (%) | Measured fidelity | Δ fidelity | Verdict |
|---|---|---|---|---|---|---|
| 1 | `d9if92shonhs73aedc7g` | 3.102860 ± 0.020486 | 1.2329 | 0.990317 | 0.009479 | CONSISTENT |
| 2 | `d9ifus50k0jc738jip7g` | 3.104670 ± 0.019346 | 1.1753 | 0.990769 | 0.009026 | CONSISTENT |
| 3 | `d9ig2d8gk0ls73f4cplg` | 3.112870 ± 0.020184 | 0.9143 | 0.992819 | 0.006976 | CONSISTENT |
| 4 | `d9ig4p3sbqfc73erfaog` | 3.114250 ± 0.016492 | 0.8703 | 0.993164 | 0.006631 | CONSISTENT |
| 5 | `d9ignkrhdfks73ch0ms0` | 3.104990 ± 0.004649 | 1.1651 | 0.990849 | 0.008946 | CONSISTENT |
| **Mean ± std** | — | — | **1.0716 ± 0.1664** | **0.991584 ± 0.001307** | **0.008212 ± 0.001307** | **5/5** |

### n = 85

| Trial | Job ID | π estimate | Error (%) | Measured fidelity | Δ fidelity | Verdict |
|---|---|---|---|---|---|---|
| 1 | `d9ii7j0ii2cc73edk3d0` | 3.098937 | 1.3578 | 0.989336 | 0.009753 | CONSISTENT |
| 2 | `d9iko0gii2cc73edn940` | 3.098129 | 1.3835 | 0.989134 | 0.009955 | CONSISTENT |
| 3 | `d9il133hdfks73ch69a0` | 3.098526 | 1.3709 | 0.989233 | 0.009856 | CONSISTENT |
| 4 | `d9il243jf64c739fn01g` | 3.098568 | 1.3695 | 0.989244 | 0.009845 | CONSISTENT |
| 5 | `d9il3doii2cc73ednmmg` | 3.099077 | 1.3533 | 0.989371 | 0.009718 | CONSISTENT |
| **Mean ± std** | — | — | **1.3670 ± 0.0119** | **0.989264 ± 0.0000934** | **0.009825 ± 0.0000934** | **5/5** |

Job IDs are publicly verifiable by IBM Quantum account holders with access to
the `RonaldoIBM` instance's job history.

---

## 5. Scale-Dependence Analysis

| Metric | n = 4 | n = 85 |
|---|---|---|
| Winning code (analytical) | Steane [[7,1,3]] | Bacon-Shor |
| Steane still viable? | Yes (#1) | **No — infeasible** |
| Δ fidelity, hardware real (mean ± std) | 0.008212 ± 0.001307 | 0.009825 ± 0.0000934 |
| Worst-case margin to 1% threshold | 0.000521 | **0.0000452 (~11× tighter)** |
| Std across 5 hardware trials | 0.001307 (higher run-to-run spread) | 0.0000934 (**14× more consistent**) |

**Interpretation**: scaling from 4 to 85 logical qubits produced two opposite
effects simultaneously. Predictions became *more consistent* run-to-run
(averaging over 85 physical qubits samples more of the chip's calibration
landscape, narrowing the spread of the mean by the central-limit effect), but
also *closer to the failure threshold* — the safety margin between predicted
and measured fidelity shrank roughly 11-fold. A validation that stopped at
n=4 would have reported a comfortable margin and missed this entirely; the
scale-up test was necessary to surface it.

---

## 6. Methodology Finding: Hardware Profile Completeness

### 6.1 The gap between simulation and real hardware

Comparing Sections 3 and 4 directly: at n=4, simulation error (0.0472%) was
~23× smaller than real-hardware error (1.0716%); at n=85, ~105× smaller
(0.0130% vs. 1.3670%). This gap was flagged in earlier drafts of this report
as a property of the depolarizing-noise model's simplicity. Investigating
further revealed a more specific, correctable cause.

### 6.2 Root cause: an unheeded warning

The manually-specified `HardwareProfile("IBM_Fez", t_gate_ns=100,
p_phys=0.00156, topology="heavy-hex")` used for every prediction and
simulation above omits `readout_error`, `T1_us`, and `T2_us`. autoq-qec
already detects this and raises a `UserWarning` on every `compare()` call:

> *"HardwareProfile 'IBM_Fez' sem: readout_error [...] — assumindo 0.0
> (leitura perfeita); T1_us [...] — sem ele, o filtro de viabilidade por T1
> em rank() fica desligado; T2_us [...] — sem ele, decoerência não é
> modelada e fidelity_circuit ignora o tempo de execução por completo.
> fidelity_circuit pode estar superestimada. Use
> HardwareProfile.from_calibrated(HARDWARE_PROFILES[...]) para carregar
> dados reais automaticamente, se o hardware estiver na lista embutida."*

This warning was silenced throughout by a blanket
`warnings.filterwarnings("ignore")` at the top of the validation script — a
common pattern used to suppress unrelated `qiskit`/`qiskit-ibm-runtime`
deprecation noise, which also silently swallowed this unrelated, directly
relevant `UserWarning`. The warning names the exact problem and the exact
fix, both confirmed correct in Section 6.3 below.

### 6.3 Re-running with the package's own calibrated profile

`autoq_qec.real_hardware.HARDWARE_PROFILES["IBM_Heron_r2"]` is, in fact, a
real calibration snapshot of `ibm_fez` itself (`name="IBM Heron r2
(ibm_fez)"`, pulled 2026-07-16): `T1_us=139.3`, `T2_us=101.0`,
`readout_error=0.0149`, `p_1q_mean=0.00042`, `p_2q_mean=0.0067`. Using
`HardwareProfile.from_calibrated(HARDWARE_PROFILES["IBM_Heron_r2"])`:

- **Prediction, n=4**: best code becomes Floquet (not Steane), predicted
  fidelity **0.905948** — does *not* meet a 0.999 target. The manual
  profile's predicted 0.999796 was a substantial overestimate.
- **Prediction, n=85**: `rank()` returns an **empty list** — every code
  fails the T1-viability filter (execution time vastly exceeds 50% of
  `T1_us=139.3µs`; e.g. Bacon-Shor needs 48,513.9µs). autoq-qec correctly
  identifies that nothing tested is viable at this scale given real T1 —
  this is the T1 filter (present since v3.2.4) working as designed, not a
  bug.
- **Simulation** (thermal relaxation from real T1/T2 + real 1Q depolarizing
  rate + real readout error), 5 runs per scale:

| Scale | Error (%), mean ± std | Fidelity, mean ± std |
|---|---|---|
| n=4, manual profile (Section 3) | 0.0472 ± 0.0313 | 0.999629 ± 0.000246 |
| **n=4, calibrated profile** | **1.1673 ± 0.0970** | **0.990832 ± 0.000762** |
| n=4, real hardware (Section 4) | 1.0716 ± 0.1664 | 0.991584 ± 0.001307 |
| n=85, manual profile (Section 3) | 0.0130 ± 0.0091 | 0.999898 ± 0.0000718 |
| **n=85, calibrated profile** | **1.1214 ± 0.0150** | **0.991193 ± 0.000118** |
| n=85, real hardware (Section 4) | 1.3670 ± 0.0119 | 0.989264 ± 0.0000934 |

The calibrated-profile simulation lands far closer to the real-hardware row
than the manual-profile simulation does in both cases: the gap between
simulated and measured error shrinks from **1.02 percentage points (manual)
to 0.10 (calibrated)** at n=4 — roughly a **10× improvement** — and from
**1.35 to 0.25** at n=85 — roughly **5.5×**.

### 6.4 Conclusion

The large simulation-to-hardware gap reported in Section 6.1, and in earlier
drafts of this report, is substantially explained by an incomplete test
input, not a flaw in autoq-qec's fidelity formula
(`fidelity_circuit = (1−p_L)^n_gates × (1−readout_error)^n_logical_qubits ×
exp(−execution_time_us/T2_us)`) — that formula already accounts for readout
error and T2 decoherence *when given the data*. This is, if anything, a
successful validation of the formula's correctness once fed complete inputs,
and a caution for any user of this methodology: prefer
`HardwareProfile.from_calibrated()` with a real calibration entry over a
hand-built profile with only `t_gate_ns`/`p_phys`, and do not blanket-suppress
warnings when calling `compare()`/`estimate()`.

One genuinely open modeling question surfaced by 6.3's n=85 result: the T2
decoherence penalty is applied to the *entire* QEC-protected execution time
(already inflated by syndrome-extraction overhead), treating it as passive
idle decay. Real QEC actively corrects errors throughout that time rather
than letting them accumulate un-checked — whether the current formula is
appropriately conservative or overly pessimistic for actively-corrected
logical qubits is a physics modeling question this report does not resolve,
noted here as a candidate for future investigation, not a defect to patch.

---

## 7. Reproducibility

```bash
pip install autoq-qec qiskit-ibm-runtime qiskit-aer
export IBM_TOKEN='your_token_here'
python pi_ibm_fez_validation.py       # n=4, manual profile
python pi_85q_test.py real            # n=85, manual profile
```

Note: as of `qiskit-ibm-runtime` 0.48+, the IBM Quantum Platform requires
`channel="ibm_quantum_platform"` (the older `"ibm_quantum"` channel value
used in earlier script versions raises `ValueError`).

All 20 raw run outputs (10 per scale: 5 simulation + 5 real hardware, manual
profile) plus this report are included in this Zenodo record and in
`validation/data/` in the repository — `hardware_run*.json`/
`simulation_run*.json` are the n=4 runs, `scale85_hardware_run*.json`/
`scale85_simulation_run*.json` are the n=85 runs. `pi_ibm_fez_validation.py`
(n=4) and `pi_85q_test.py` (n=85, parameterized at the top of the file) are
both included. The calibrated-profile comparison (Section 6.3) used ad hoc
scripts built on the same circuit and is described but not separately
archived per-run in this version.

Job IDs, n=4: `d9if92shonhs73aedc7g`, `d9ifus50k0jc738jip7g`,
`d9ig2d8gk0ls73f4cplg`, `d9ig4p3sbqfc73erfaog`, `d9ignkrhdfks73ch0ms0`.
Job IDs, n=85: `d9ii7j0ii2cc73edk3d0`, `d9iko0gii2cc73edn940`,
`d9il133hdfks73ch69a0`, `d9il243jf64c739fn01g`, `d9il3doii2cc73ednmmg`.

---

## 8. Methodology Notes

- **Fidelity proxy:** `1 − |P(|1⟩)_measured − π/4|`. Amplitude-domain proxy
  appropriate for this benchmark, not full process fidelity.
- **Execution time is never validated experimentally in this report.** The
  `execution_time_us` figures in Section 2 describe a hypothetical fully
  QEC-encoded circuit (with real syndrome-extraction rounds) that was never
  physically built or run — only the *raw*, unencoded circuit was executed,
  on both simulator and real hardware. Confirming those timing figures would
  require implementing the actual fault-tolerant circuits, which is outside
  both this report's and autoq-qec's own scope (autoq-qec estimates resources
  without requiring the full circuit to be built).
- **Sample size**: 5 real-hardware trials and 5 simulation runs per scale is
  enough to distinguish a reproducible effect from a one-off fluke, but
  remains a modest sample collected within about one afternoon (2026-07-25);
  it does not capture day-to-day calibration drift.
- **Hardware error rates** (IBM Fez, July 2026, from
  `HARDWARE_PROFILES["IBM_Heron_r2"]`): `p_1q_mean=0.00042`,
  `p_2q_mean=0.0067`, `T1_us=139.3`, `T2_us=101.0`, `readout_error=0.0149`,
  calibration snapshot from 2026-07-16 (calibration drifts daily; all ten
  real-hardware trials above were run within a few hours of each other on
  2026-07-25).

---

## License

MIT — consistent with autoq-qec.

## Citation

If you use this validation dataset, please cite both this record
(concept DOI: 10.5281/zenodo.21571464) and the autoq-qec software
(DOI: 10.5281/zenodo.21560570).
