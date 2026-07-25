# Multi-Level Validation of autoq-qec: Analytical Prediction, Noise-Calibrated Simulation, and Real Hardware Execution on IBM Fez

**Author:** Ronaldo Rodrigues
**Date:** July 25, 2026
**Dataset DOI:** https://doi.org/10.5281/zenodo.21571464
**Related software:** autoq-qec v3.4.3 — https://doi.org/10.5281/zenodo.21560570
**Repository:** https://github.com/Ronaldoengenhariadacomputacao/autoq-qec

---

## Abstract

This report presents a three-level validation of the **autoq-qec** quantum error
correction resource estimator: (1) analytical prediction, (2) five
noise-calibrated simulation runs, and (3) five independent executions on real
quantum hardware (IBM Fez, Heron r2, 156 qubits). A quantum Pi estimator
circuit served as benchmark. Across five real-hardware trials, the autoq-qec
fidelity prediction (0.999796) agreed with the measured fidelity (mean
0.991584 ± 0.001307) within 0.821 ± 0.131 percentage points — consistently
inside the 1% threshold used here in all five trials, though with limited
margin in the worst case. Across five simulation runs (depolarizing noise
model), the error was an order of magnitude smaller (mean 0.0472% ± 0.0313% in
π, vs. 1.0716% ± 0.1664% on real hardware) — real hardware showed roughly 23×
more error in π and 40× more deviation in fidelity than the simulation,
quantifying the contribution of noise sources beyond simple depolarizing
models (readout error, crosstalk, calibration drift).

---

## 1. Benchmark Circuit: Quantum Pi Estimator

The circuit encodes π/4 as a quantum amplitude:

```
RY(θ) with θ = 2·arcsin(√(π/4)) ≈ 2.178272 rad
→ P(|1⟩) = sin²(θ/2) = π/4
→ π = 4·P(|1⟩)
```

Four parallel estimators (4 logical qubits) reduce statistical error by √4 = 2.

| Parameter | Value |
|---|---|
| Logical qubits | 4 |
| Gates per qubit | 1 RY + 1 measurement |
| Shots (per trial) | 100,000 |
| Theoretical shot-noise limit (mean of 4 qubits) | ±0.0026 |

---

## 2. Level 1 — Analytical Prediction (autoq-qec)

| Metric | Predicted Value |
|---|---|
| Optimal QEC code | Steane [[7,1,3]] |
| Physical qubits | 52 (13 per logical) |
| Circuit fidelity | 0.999796 |
| Execution time | 2.4 µs |
| Best hardware | IBM Fez |

Full hardware ranking:

| Rank | Hardware | QEC Code | Phys. Qubits | Fidelity | Time (µs) |
|---|---|---|---|---|---|
| 1 | IBM Fez | Steane [[7,1,3]] | 52 | 0.999796 | 2.4 |
| 2 | Quantinuum H2 | Steane [[7,1,3]] | 52 | 0.999993 | 2400.0 |
| 3 | IBM Fez | Bacon-Shor | 144 | 0.999780 | 24.0 |
| 4 | Quantinuum H2 | Floquet Code | 208 | 0.999765 | 400.0 |
| 5 | IBM Heron | Steane [[7,1,3]] | 52 | 0.999244 | 2.4 |

This ranking was identical and deterministic across all ten runs in this
report (analytical prediction does not depend on shot outcomes).

---

## 3. Level 2 — Noise-Calibrated Simulation (Qiskit Aer), 5 runs

Depolarizing noise model with IBM Fez published error rates
(1Q = 2.5×10⁻⁴, 2Q = 1.56×10⁻³), 100,000 shots per run, no fixed random seed:

| Run | π estimate | Error (%) | Measured fidelity | Δ fidelity |
|---|---|---|---|---|
| 1 | 3.143730 ± 0.000823 | 0.0680 | 0.999466 | 0.000330 |
| 2 | 3.141150 ± 0.001568 | 0.0141 | 0.999889 | 0.000094 |
| 3 | 3.144440 ± 0.002249 | 0.0906 | 0.999288 | 0.000507 |
| 4 | 3.140480 ± 0.001363 | 0.0354 | 0.999722 | 0.000074 |
| 5 | 3.142470 ± 0.001077 | 0.0279 | 0.999781 | 0.000015 |
| **Mean ± std** | — | **0.0472 ± 0.0313** | **0.999629 ± 0.000246** | **0.000204 ± 0.000208** |

*(Run 1 was regenerated 2026-07-25 after the original run's raw JSON was
accidentally overwritten before being archived — only its printed console
output survived, so it was re-run to have a verifiable raw file backing every
row in this table, consistent with the real-hardware trials below.)*

All five runs land comfortably inside the consistency threshold, with large
margin — as expected, since the depolarizing model is a simplified noise
channel that does not capture every real hardware error mechanism.

---

## 4. Level 3 — Real Hardware Execution (IBM Fez), 5 independent trials

**Backend:** ibm_fez (Heron r2, 156 qubits)
**Shots:** 100,000 per trial
**Date:** July 25, 2026 (all five trials within roughly 2.5 hours of each other)

| Trial | Job ID | π estimate | Error (%) | Measured fidelity | Δ fidelity | Verdict |
|---|---|---|---|---|---|---|
| 1 | `d9if92shonhs73aedc7g` | 3.102860 ± 0.020486 | 1.2329 | 0.990317 | 0.009479 | CONSISTENT |
| 2 | `d9ifus50k0jc738jip7g` | 3.104670 ± 0.019346 | 1.1753 | 0.990769 | 0.009026 | CONSISTENT |
| 3 | `d9ig2d8gk0ls73f4cplg` | 3.112870 ± 0.020184 | 0.9143 | 0.992819 | 0.006976 | CONSISTENT |
| 4 | `d9ig4p3sbqfc73erfaog` | 3.114250 ± 0.016492 | 0.8703 | 0.993164 | 0.006631 | CONSISTENT |
| 5 | `d9ignkrhdfks73ch0ms0` | 3.104990 ± 0.004649 | 1.1651 | 0.990849 | 0.008946 | CONSISTENT |
| **Mean ± std** | — | — | **1.0716 ± 0.1664** | **0.991584 ± 0.001307** | **0.008212 ± 0.001307** | **5/5 CONSISTENT** |

Job IDs are publicly verifiable by IBM Quantum account holders with access to
the `RonaldoIBM` instance's job history.

---

## 5. Analysis

### 5.1 Statistical significance of the hardware deviation

Across all five trials, the observed π estimate deviates from the true value
by 0.027–0.039 — roughly **10–15σ above the theoretical shot-noise limit**
(±0.0026 for the 4-qubit averaged estimator). This rules out shot noise as the
explanation and confirms the deviation reflects real, repeatable hardware
noise (readout error, crosstalk, and/or calibration drift), not statistical
fluctuation. This report does not decompose the deviation into those
individual noise sources — that would require a separate, targeted experiment
(e.g. readout-error-only or crosstalk-only circuits).

### 5.2 Trial-to-trial consistency

The five real-hardware trials cluster tightly (error range 0.87%–1.23%, a
spread of ~0.36 percentage points, std 0.1664%) and all five independently
fall inside the 1% fidelity-consistency threshold. The tightest trial
(Trial 1) has only 0.052 percentage points of margin before crossing into
"MARGINAL" — so the *worst case* is close to the threshold, but the fact that
five independently-queued, independently-transpiled, independently-executed
jobs (not re-runs of a cached result) all land in a narrow band well above
zero and below the threshold is what gives the "CONSISTENT" verdict real
weight, rather than resting on a single lucky trial.

The five simulation runs are similarly tight relative to their own much
smaller scale (error range 0.014%–0.091%, std 0.0313%), confirming the
depolarizing-noise baseline itself is stable and reproducible — the
order-of-magnitude gap to real hardware is not simulation noise, it's a real
physical gap.

### 5.3 Simulation-to-hardware gap

| Level | π error (mean ± std) | Fidelity (mean ± std) |
|---|---|---|
| Ideal (analytical) | 0% | 0.999796 |
| Simulation (depolarizing, 5 runs) | 0.0472% ± 0.0313% | 0.999629 ± 0.000246 |
| Real hardware (IBM Fez, 5 runs) | 1.0716% ± 0.1664% | 0.991584 ± 0.001307 |

Real hardware shows **~22.7× more error in π** and **~40.3× more deviation in
fidelity** than the simulation, now backed by five runs on each side rather
than a single stochastic sample of each. This is a meaningful, reproducible
gap — not measurement noise on either side — and quantifies exactly how much
a simple depolarizing model underestimates real-world error for this circuit
class on this hardware. This gap is itself a useful calibration target for
future autoq-qec versions that might incorporate readout-error and crosstalk
terms directly into the noise model.

### 5.4 Validation verdict

Across five independent real-hardware trials, the autoq-qec analytical
fidelity prediction (0.999796) agreed with the measured fidelity
(0.991584 ± 0.001307) within **0.821 ± 0.131 percentage points** — inside the
1% consistency threshold in all five trials, though with limited margin in
the worst case (Trial 1, 0.052 points of margin). The Steane [[7,1,3]]
recommendation (13:1 physical-to-logical overhead) held up consistently as
the top-ranked choice for this circuit class on Heron-architecture hardware
across every trial. Five trials is a modest but meaningfully stronger sample
than one or three — the tight clustering (std 0.13 points on the fidelity
delta) gives confidence this is a real, reproducible effect rather than
chance. More trials across different days (to capture day-to-day calibration
drift, which this dataset — collected within one afternoon — does not
capture) would further strengthen the result.

---

## 6. Reproducibility

```bash
pip install autoq-qec qiskit-ibm-runtime
export IBM_TOKEN='your_token_here'
python pi_ibm_fez_validation.py
```

The script performs all three levels automatically: prediction → simulation
fallback or real execution → comparison report (JSON). Note: as of
`qiskit-ibm-runtime` 0.48+, the IBM Quantum Platform requires
`channel="ibm_quantum_platform"` (the older `"ibm_quantum"` channel value used
in earlier script versions was rejected with a `ValueError` during this
validation and had to be updated).

Job IDs `d9if92shonhs73aedc7g`, `d9ifus50k0jc738jip7g`, `d9ig2d8gk0ls73f4cplg`,
`d9ig4p3sbqfc73erfaog`, `d9ignkrhdfks73ch0ms0` can be independently verified
by IBM Quantum account holders.

---

## 7. Methodology Notes

- **Fidelity proxy:** `1 − |P(|1⟩)_measured − π/4|`. This is an
  amplitude-domain proxy appropriate for this benchmark, not full process
  fidelity. Process tomography would be required for gate-level fidelity claims.
- **Error scaling:** statistical error scales as `1/√(n·shots)`; QEC overhead
  scales linearly with n logical qubits.
- **Sample size:** 5 real-hardware trials and 5 simulation runs give enough
  data to compute a meaningful mean and standard deviation and distinguish a
  reproducible effect from a one-off fluke, but this is still a modest sample
  collected within a single afternoon — readers should not treat the reported
  statistics as a definitive, long-term characterization of IBM Fez's noise
  behavior for this circuit class (see calibration-drift note below).
- **Hardware error rates** (IBM Fez, July 2026): 2Q best = 7.92×10⁻⁴ to
  1.56×10⁻³ (layered); values from IBM Quantum Platform calibration data at
  the time of the analytical prediction (calibration drifts daily; all five
  real-hardware trials above were run within roughly 2.5 hours of each other
  on the same day, so day-to-day drift is not captured here).

---

## License

MIT — consistent with autoq-qec.

## Citation

If you use this validation dataset, please cite both this record
(DOI: 10.5281/zenodo.21571464) and the autoq-qec software
(DOI: 10.5281/zenodo.21560570).
