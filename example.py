"""
AutoQ QEC — exemplo de uso completo
Roda sem token IBM, usando dados publicados de hardware.
"""
import math
from qiskit import QuantumCircuit
from autoq_qec import compare, rank, HardwareProfile
from autoq_qec.real_hardware import HARDWARE_PROFILES

# ── Construir um circuito real: QFT em 4 qubits ──────────────────────
qc = QuantumCircuit(4)
for i in range(4):
    qc.h(i)
    for j in range(i + 1, 4):
        qc.cp(math.pi / 2**(j - i), j, i)
for i in range(2):
    qc.swap(i, 3 - i)

# ── Definir hardwares para comparar ──────────────────────────────────
hardwares = [
    HardwareProfile("IBM_Eagle",     t_gate_ns=391,   p_phys=0.0062,  topology="heavy-hex"),
    HardwareProfile("IBM_Heron",     t_gate_ns=100,   p_phys=0.003,   topology="heavy-hex"),
    HardwareProfile("Quantinuum_H2", t_gate_ns=100e3, p_phys=0.00029, topology="all-to-all"),
    HardwareProfile("IonQ_Aria",     t_gate_ns=600e3, p_phys=0.0055,  topology="all-to-all"),
]

# ── Estimar recursos QEC — uma chamada ───────────────────────────────
result = compare(qc, hardwares, fidelity_target=0.99)
recommendations = rank(result, weight_qubits=0.4, weight_time=0.4, weight_fidelity=0.2)

# ── Imprimir resultado ────────────────────────────────────────────────
prof = result["circuit_profile"]
print(f"Circuito: {prof.n_logical_qubits}q lógicos | "
      f"{prof.n_physical_gates} portas físicas | profundidade {prof.depth_physical}")
print()
print(f"{'#':>3} {'Hardware':<18} {'Código':<22} {'Qubits':>7} {'Tempo(µs)':>11} {'Fidelidade':>11}")
print("-" * 75)
for r in recommendations:
    mark = " ← MELHOR" if r.rank == 1 else ""
    print(f"{r.rank:>3} {r.hardware:<18} {r.code:<22} "
          f"{r.total_physical_qubits:>7} {r.execution_time_us:>11.1f} "
          f"{r.fidelity_circuit:>11.4f}{mark}")

# ── Circuitos variacionais (VQE/QAOA) precisam de parâmetros vinculados ──
# Exemplo 1: o erro esperado se você esquecer de vincular.
print("\n--- Exemplo: ansatz não vinculado (erro esperado) ---")
from qiskit.circuit.library import RealAmplitudes

ansatz_template = RealAmplitudes(4, reps=2).decompose()
try:
    compare(ansatz_template, hardwares, fidelity_target=0.99)
except ValueError as e:
    print(f"ValueError (esperado): {e}")

# Exemplo 2: forma correta — vincular valores numéricos antes de estimar.
print("\n--- Exemplo: mesmo ansatz, agora vinculado ---")
import numpy as np

rng = np.random.default_rng(42)
ansatz_vinculado = ansatz_template.assign_parameters(
    rng.uniform(0, 2 * np.pi, ansatz_template.num_parameters)
)
result_vqe = compare(ansatz_vinculado, hardwares, fidelity_target=0.99)
prof_vqe = result_vqe["circuit_profile"]
print(f"VQE vinculado: {prof_vqe.n_logical_qubits}q lógicos | "
      f"T-count={prof_vqe.t_count} | {prof_vqe.n_physical_gates} portas físicas")
