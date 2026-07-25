"""
=============================================================================
VALIDACAO EXPERIMENTAL: autoq-qec vs IBM Fez Real
=============================================================================
Objetivo:
    Validar as previsoes do autoq-qec executando o estimador quantico de Pi
    no hardware real IBM Fez e comparando fidelidade prevista vs medida.

Fluxo:
    1. autoq-qec preve: codigo QEC, qubits fisicos, fidelidade, tempo
    2. Circuito executa no IBM Fez real
    3. Comparacao: previsao vs resultado experimental

Requisitos:
    pip install qiskit qiskit-ibm-runtime qiskit-aer autoq-qec

Uso:
    1. Configure IBM_TOKEN com seu token de https://quantum.cloud.ibm.com
    2. python pi_ibm_fez_validation.py
=============================================================================
"""

import json
import numpy as np
from datetime import datetime

# ============================================================
# CONFIGURACAO
# ============================================================
import os
IBM_TOKEN    = os.environ.get("IBM_TOKEN", "SEU_TOKEN_AQUI")
BACKEND_NAME = "ibm_fez"      # 156 qubits, erro 2Q = 1.56E-3, online
N_QUBITS     = 4              # estimadores paralelos de Pi
N_SHOTS      = 100_000        # shots para precisao estatistica


# ============================================================
# PARTE 1: PREVISAO COM autoq-qec
# ============================================================

def build_pi_circuit(n_qubits: int):
    """
    Circuito estimador de Pi (versao corrigida).

    Fisica: RY(theta) com theta = 2*arcsin(sqrt(pi/4))
    prepara P(|1>) = sin^2(theta/2) = pi/4.
    Logo pi = 4 * P(|1>).

    n_qubits estimadores paralelos reduzem o erro estatistico
    por fator sqrt(n).
    """
    from qiskit import QuantumCircuit

    circuit = QuantumCircuit(n_qubits, n_qubits)
    angulo = 2 * np.arcsin(np.sqrt(np.pi / 4))
    for q in range(n_qubits):
        circuit.ry(angulo, q)
    circuit.measure(range(n_qubits), range(n_qubits))
    return circuit


def predict_with_autoq_qec(circuit):
    """
    Previsao de recursos QEC com autoq-qec.
    Retorna o melhor resultado para IBM Fez.
    """
    import warnings
    warnings.filterwarnings('ignore')
    from autoq_qec import compare, rank, HardwareProfile

    hardwares = [
        HardwareProfile('IBM_Fez',       t_gate_ns=100,
                        p_phys=0.00156,  topology='heavy-hex'),
        HardwareProfile('IBM_Heron',     t_gate_ns=100,
                        p_phys=0.003,    topology='heavy-hex'),
        HardwareProfile('Quantinuum_H2', t_gate_ns=100e3,
                        p_phys=0.00029,  topology='all-to-all'),
    ]

    result = compare(circuit, hardwares, fidelity_target=0.999)
    rankings = rank(result)

    print("=" * 65)
    print("PARTE 1: PREVISAO autoq-qec")
    print("=" * 65)
    print()
    print(f"{'Rank':>4} | {'Hardware':>16} | {'Codigo':>20} | "
          f"{'Qubits':>7} | {'Fidelidade':>10} | {'Tempo us':>9}")
    print("-" * 80)
    for r in rankings[:5]:
        print(f"{r.rank:>4} | {r.hardware:>16} | {r.code:>20} | "
              f"{r.total_physical_qubits:>7} | {r.fidelity_circuit:>10.6f} | "
              f"{r.execution_time_us:>9.1f}")

    best_fez = next((r for r in rankings if 'Fez' in r.hardware), rankings[0])

    print()
    print("PREVISAO PARA IBM FEZ:")
    print(f"  Codigo QEC:      {best_fez.code}")
    print(f"  Qubits fisicos:  {best_fez.total_physical_qubits}")
    print(f"  Fidelidade:      {best_fez.fidelity_circuit:.6f}")
    print(f"  Tempo:           {best_fez.execution_time_us:.1f} us")

    return {
        'code': best_fez.code,
        'physical_qubits': best_fez.total_physical_qubits,
        'fidelity_predicted': float(best_fez.fidelity_circuit),
        'execution_time_us': float(best_fez.execution_time_us),
    }


# ============================================================
# PARTE 2: EXECUCAO NO IBM FEZ REAL
# ============================================================

def run_on_ibm_fez(circuit, token, backend_name, shots):
    """Executa o circuito no IBM Fez real via SamplerV2."""
    from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2 as Sampler
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

    print()
    print("=" * 65)
    print("PARTE 2: EXECUCAO NO IBM FEZ REAL")
    print("=" * 65)

    service = QiskitRuntimeService(channel="ibm_quantum_platform", token=token)
    backend = service.backend(backend_name)

    print(f"\nBackend: {backend.name}")
    print(f"Status:  {backend.status().status_msg}")
    print(f"Fila:    {backend.status().pending_jobs} jobs pendentes")

    pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
    circuit_isa = pm.run(circuit)

    print(f"\nCircuito transpilado: depth={circuit_isa.depth()}, "
          f"gates={circuit_isa.count_ops()}")

    sampler = Sampler(mode=backend)
    job = sampler.run([circuit_isa], shots=shots)
    print(f"\nJob ID: {job.job_id()}")
    print("Aguardando execucao no hardware real...")

    result = job.result()
    counts = result[0].data.c.get_counts()

    return counts, job.job_id()


def run_simulation_fallback(circuit, shots):
    """Simulacao local com ruido do IBM Fez (fallback sem token)."""
    from qiskit_aer import AerSimulator
    from qiskit_aer.noise import NoiseModel, depolarizing_error
    from qiskit import transpile

    print()
    print("=" * 65)
    print("PARTE 2: SIMULACAO LOCAL (sem token -- usando ruido IBM Fez)")
    print("=" * 65)

    # Modelo de ruido baseado no erro real do IBM Fez
    noise_model = NoiseModel()
    error_1q = depolarizing_error(0.00025, 1)   # erro 1Q tipico Fez
    error_2q = depolarizing_error(0.00156, 2)   # erro 2Q medido Fez
    noise_model.add_all_qubit_quantum_error(error_1q, ['ry', 'rz', 'sx', 'x'])
    noise_model.add_all_qubit_quantum_error(error_2q, ['cx', 'cz', 'ecr'])

    sim = AerSimulator(noise_model=noise_model)
    qc = transpile(circuit, sim)
    counts = sim.run(qc, shots=shots).result().get_counts()

    return counts, "SIMULATION"


# ============================================================
# PARTE 3: ANALISE E COMPARACAO
# ============================================================

def analyze_results(counts, n_qubits, shots, prediction):
    """Extrai Pi dos resultados e compara com a previsao do autoq-qec."""

    print()
    print("=" * 65)
    print("PARTE 3: ANALISE -- PREVISAO vs REALIDADE")
    print("=" * 65)

    # Cada qubit e um estimador independente de Pi
    contagens_1_por_qubit = [0] * n_qubits
    for estado, freq in counts.items():
        estado_pad = estado.zfill(n_qubits)
        for i, bit in enumerate(estado_pad):
            if bit == '1':
                contagens_1_por_qubit[i] += freq

    pi_por_qubit = [4 * c / shots for c in contagens_1_por_qubit]
    pi_medio = float(np.mean(pi_por_qubit))
    pi_std = float(np.std(pi_por_qubit) / np.sqrt(n_qubits))
    erro_relativo = abs(pi_medio - np.pi) / np.pi * 100

    print()
    print("--- Estimativa de Pi ---")
    for i, p in enumerate(pi_por_qubit):
        print(f"  Qubit {i}: pi = {p:.6f}")
    print(f"\n  Pi medio:    {pi_medio:.6f} +/- {pi_std:.6f}")
    print(f"  Pi real:     {np.pi:.6f}")
    print(f"  Erro:        {erro_relativo:.4f}%")

    # Fidelidade experimental estimada:
    # razao entre P(|1>) medida e P(|1>) ideal
    p1_ideal = np.pi / 4
    p1_medida = pi_medio / 4
    fidelidade_exp = 1 - abs(p1_medida - p1_ideal)

    print()
    print("--- Comparacao com previsao autoq-qec ---")
    print(f"  Fidelidade prevista (autoq-qec): {prediction['fidelity_predicted']:.6f}")
    print(f"  Fidelidade experimental (proxy): {fidelidade_exp:.6f}")
    delta = abs(prediction['fidelity_predicted'] - fidelidade_exp)
    print(f"  Diferenca:                       {delta:.6f}")

    if delta < 0.01:
        print("  CONSISTENTE -- previsao dentro de 1% do medido")
        veredito = "CONSISTENTE"
    elif delta < 0.05:
        print("  MARGINAL -- diferenca entre 1-5%")
        veredito = "MARGINAL"
    else:
        print("  DIVERGENTE -- investigar fontes de erro adicionais")
        veredito = "DIVERGENTE"

    return {
        'pi_estimado': pi_medio,
        'pi_std': pi_std,
        'erro_relativo_pct': float(erro_relativo),
        'fidelidade_experimental': float(fidelidade_exp),
        'fidelidade_prevista': prediction['fidelity_predicted'],
        'delta_fidelidade': float(delta),
        'veredito': veredito,
    }


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 65)
    print("VALIDACAO EXPERIMENTAL: autoq-qec x IBM Fez")
    print(f"Data: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print("=" * 65)
    print()

    # Circuito
    circuit = build_pi_circuit(N_QUBITS)
    print(f"Circuito: {N_QUBITS} estimadores paralelos de Pi")
    print(f"Angulo RY: {2*np.arcsin(np.sqrt(np.pi/4)):.6f} rad")
    print(f"Shots: {N_SHOTS}")
    print()

    # Parte 1 -- Previsao
    prediction = predict_with_autoq_qec(circuit)

    # Parte 2 -- Execucao
    if IBM_TOKEN != "SEU_TOKEN_AQUI":
        counts, job_id = run_on_ibm_fez(circuit, IBM_TOKEN, BACKEND_NAME, N_SHOTS)
    else:
        counts, job_id = run_simulation_fallback(circuit, N_SHOTS)

    # Parte 3 -- Analise
    resultado = analyze_results(counts, N_QUBITS, N_SHOTS, prediction)

    # Salvar relatorio JSON
    relatorio = {
        'timestamp': datetime.now().isoformat(),
        'backend': BACKEND_NAME if job_id != "SIMULATION" else "aer_simulation",
        'job_id': job_id,
        'n_qubits': N_QUBITS,
        'shots': N_SHOTS,
        'prediction_autoq_qec': prediction,
        'results': resultado,
    }
    with open('pi_fez_validation_report.json', 'w') as f:
        json.dump(relatorio, f, indent=2)

    print()
    print("Relatorio salvo: pi_fez_validation_report.json")
    return relatorio


if __name__ == "__main__":
    main()
