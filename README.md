# AutoQ QEC Estimator

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.21327566.svg)](https://doi.org/10.5281/zenodo.21327566)

**Multi-code fault-tolerant quantum error correction estimator for arbitrary Qiskit circuits.**

Given any Qiskit circuit and a set of hardware profiles, AutoQ QEC returns a ranked comparison of QEC codes (Surface Code, Floquet Code, Bacon-Shor, Steane [[7,1,3]]) with physically grounded resource estimates: physical qubit count, execution time, and circuit fidelity.

## What this does that nothing else does

| Tool | Multi-code | Arbitrary circuit | Analytic model | Hardware-agnostic |
|---|---|---|---|---|
| Azure Resource Estimator | ❌ Surface Code only | ✅ | ✅ | ❌ Azure only |
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

# Hardware profiles (built-in or custom)
hardwares = [
    HardwareProfile("IBM_Eagle",     t_gate_ns=391,   p_phys=0.0062, topology="heavy-hex"),
    HardwareProfile("IBM_Heron",     t_gate_ns=100,   p_phys=0.003,  topology="heavy-hex"),
    HardwareProfile("Quantinuum_H2", t_gate_ns=100e3, p_phys=0.00029,topology="all-to-all"),
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
| Bacon-Shor | $p_L \approx (p/p_{th})^d$, $q=d^2$ | Aliferis & Cross (2007) |
| Steane [[7,1,3]] | $p_L \approx 21p^2$, $q=13$ | Steane, PRL 77, 793 (1996) |

Thresholds are enforced: `p ≥ p_th` raises `ValueError` — no silent wrong results.

## Algorithm Estimator

Order-of-magnitude T-count estimates for known algorithms, without building the full circuit:

```python
from autoq_qec import AlgorithmEstimator

est = AlgorithmEstimator.shor(2048)
print(est.t_count_estimate, est.t_count_uncertainty)  # ±5x — build the real circuit for precise numbers
```

Covers `shor`, `grover`, `qft`, `vqe`. These are rough estimates (±2×–±10× depending on the algorithm) — use `extract_circuit_profile()` on a real circuit whenever possible.

## Test

```bash
pytest tests/ -v   # 49 tests, all verify physics not arithmetic
```

## What the tests check (unlike most QEC tools)

- `p ≥ threshold` raises `ValueError`, not wrong overhead
- `d` is always odd for Surface Code (rotated lattice requirement)
- `p_L ≤ p_L_target` guaranteed after distance selection
- Noisier hardware requires larger `d` (monotonicity)
- Circuit with 0 gates raises `ValueError` (destroyed by transpiler)
- Fidelity scales correctly with `t_gate`

## Author

Ronaldo Rodrigues — ORCID: [0009-0006-7449-1190](https://orcid.org/0009-0006-7449-1190)
