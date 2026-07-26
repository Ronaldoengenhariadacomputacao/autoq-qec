import warnings
# So depreciacao do qiskit -- deixa passar UserWarning (ver
# VALIDATION_REPORT.md secao 6: um filterwarnings('ignore') global aqui
# ja calou um alerta real do autoq-qec numa versao anterior deste teste).
warnings.filterwarnings('ignore', category=DeprecationWarning)
import sys
import json
import numpy as np
from datetime import datetime
from qiskit import QuantumCircuit, transpile

N_QUBITS = 85
N_SHOTS = 100_000
P_PHYS = 0.00156  # IBM Fez


def build_pi_circuit(n_qubits):
    circuit = QuantumCircuit(n_qubits, n_qubits)
    angulo = 2 * np.arcsin(np.sqrt(np.pi / 4))
    for q in range(n_qubits):
        circuit.ry(angulo, q)
    circuit.measure(range(n_qubits), range(n_qubits))
    return circuit


def predict_fidelity(n_qubits):
    """Chama compare()/rank() do autoq-qec de verdade -- nao usa um numero
    fixo. HardwareProfile aqui e incompleto de proposito (sem T1/T2/readout),
    entao um UserWarning e esperado e NAO deve ser suprimido (ver nota no
    topo do arquivo e VALIDATION_REPORT.md secao 6)."""
    from autoq_qec import compare, rank, HardwareProfile

    hw = HardwareProfile('IBM_Fez', t_gate_ns=100, p_phys=P_PHYS, topology='heavy-hex')
    circuit = build_pi_circuit(n_qubits)
    result = compare(circuit, [hw], fidelity_target=0.999)
    best = rank(result)[0]
    print(f'Previsao autoq-qec: {best.code}, {best.total_physical_qubits}q, '
          f'fid={best.fidelity_circuit:.6f}, atinge_alvo={best.meets_fidelity_target}')
    return best.fidelity_circuit


def analyze(counts, n_qubits, shots, predicted_fidelity):
    contagens = [0] * n_qubits
    for estado, freq in counts.items():
        estado_pad = estado.zfill(n_qubits)
        for i, bit in enumerate(estado_pad):
            if bit == '1':
                contagens[i] += freq
    pi_por_qubit = [4 * c / shots for c in contagens]
    pi_medio = float(np.mean(pi_por_qubit))
    pi_std = float(np.std(pi_por_qubit) / np.sqrt(n_qubits))
    erro = abs(pi_medio - np.pi) / np.pi * 100
    p1_medida = pi_medio / 4
    fid_exp = 1 - abs(p1_medida - np.pi / 4)
    delta = abs(predicted_fidelity - fid_exp)
    veredito = 'CONSISTENTE' if delta < 0.01 else 'MARGINAL/DIVERGENTE'
    return {
        'pi_estimado': pi_medio, 'pi_std': pi_std,
        'erro_relativo_pct': erro,
        'fidelidade_experimental': fid_exp,
        'fidelidade_prevista': predicted_fidelity,
        'delta_fidelidade': delta,
        'veredito': veredito,
    }


def run_simulation():
    from qiskit_aer import AerSimulator
    from qiskit_aer.noise import NoiseModel, depolarizing_error

    noise_model = NoiseModel()
    error_1q = depolarizing_error(0.00025, 1)
    error_2q = depolarizing_error(P_PHYS, 2)
    noise_model.add_all_qubit_quantum_error(error_1q, ['ry', 'rz', 'sx', 'x'])
    noise_model.add_all_qubit_quantum_error(error_2q, ['cx', 'cz', 'ecr'])

    sim = AerSimulator(noise_model=noise_model, method='matrix_product_state')
    qc = build_pi_circuit(N_QUBITS)
    counts = sim.run(qc, shots=N_SHOTS).result().get_counts()
    return counts, 'SIMULATION'


def run_real_hardware(token):
    from qiskit_ibm_runtime import QiskitRuntimeService, SamplerV2 as Sampler
    from qiskit.transpiler.preset_passmanagers import generate_preset_pass_manager

    service = QiskitRuntimeService(channel='ibm_quantum_platform', token=token)
    backend = service.backend('ibm_fez')
    print(f'Backend: {backend.name}, status: {backend.status().status_msg}, fila: {backend.status().pending_jobs}')

    pm = generate_preset_pass_manager(backend=backend, optimization_level=3)
    circuit_isa = pm.run(build_pi_circuit(N_QUBITS))
    print(f'Circuito transpilado: depth={circuit_isa.depth()}, num_qubits_fisicos_usados={circuit_isa.num_qubits}')

    sampler = Sampler(mode=backend)
    job = sampler.run([circuit_isa], shots=N_SHOTS)
    print(f'Job ID: {job.job_id()}')
    result = job.result()
    counts = result[0].data.c.get_counts()
    return counts, job.job_id()


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else 'sim'
    predicted_fidelity = predict_fidelity(N_QUBITS)

    if mode == 'real':
        import os
        counts, job_id = run_real_hardware(os.environ['IBM_TOKEN'])
    else:
        counts, job_id = run_simulation()

    resultado = analyze(counts, N_QUBITS, N_SHOTS, predicted_fidelity)
    print(f"pi={resultado['pi_estimado']:.6f} erro={resultado['erro_relativo_pct']:.4f}% "
          f"fid_exp={resultado['fidelidade_experimental']:.6f} delta={resultado['delta_fidelidade']:.6f} "
          f"-> {resultado['veredito']}")

    out = {
        'timestamp': datetime.now().isoformat(),
        'n_qubits': N_QUBITS, 'shots': N_SHOTS,
        'backend': 'ibm_fez' if mode == 'real' else 'aer_simulation',
        'job_id': job_id,
        'predicted_fidelity': predicted_fidelity,
        'results': resultado,
    }
    with open(f'/tmp/pi_85q_{mode}_report.json', 'w') as f:
        json.dump(out, f, indent=2)
