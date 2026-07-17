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
# from_calibrated() carrega T2_us/T1_us/readout_error reais automaticamente
# -- sem isso, montar HardwareProfile só com t_gate_ns/p_phys/topology (como
# este exemplo fazia antes) ignora decoerência por completo, ver "Two-tier
# ranking" no README.
hardwares = [HardwareProfile.from_calibrated(hw) for hw in [
    HARDWARE_PROFILES["IBM_Eagle_r3"],
    HARDWARE_PROFILES["IBM_Heron_r2"],
    HARDWARE_PROFILES["Quantinuum_H2"],
    HARDWARE_PROFILES["IonQ_Aria"],
]]

# ── Estimar recursos QEC — uma chamada ───────────────────────────────
result = compare(qc, hardwares, fidelity_target=0.99)
recommendations = rank(result, weight_qubits=0.4, weight_time=0.4, weight_fidelity=0.2)

# ── Imprimir resultado ────────────────────────────────────────────────
prof = result["circuit_profile"]
print(f"Circuito: {prof.n_logical_qubits}q lógicos | "
      f"{prof.n_physical_gates} portas físicas | profundidade {prof.depth_physical}")
print()
print(f"{'#':>3} {'Hardware':<25} {'Código':<22} {'Qubits':>7} {'Tempo(µs)':>11} {'Fidelidade':>11} {'Atinge alvo?':>13}")
print("-" * 100)
for r in recommendations:
    mark = " ← MELHOR" if r.rank == 1 else ""
    print(f"{r.rank:>3} {r.hardware:<25} {r.code:<22} "
          f"{r.total_physical_qubits:>7} {r.execution_time_us:>11.1f} "
          f"{r.fidelity_circuit:>11.4f} {str(r.meets_fidelity_target):>13}{mark}")

if not recommendations[0].meets_fidelity_target:
    print("\n(Nenhuma combinação testada atinge fidelity_target=0.99 de verdade —"
          " '← MELHOR' aqui é só a mais próxima, não uma resposta que cumpre o pedido.)")

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
