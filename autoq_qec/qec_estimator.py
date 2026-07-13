"""
AutoQ QEC Estimator — módulo de estimativa multi-código fault-tolerant
Referências:
  Surface Code:  Fowler et al., PRA 86, 032324 (2012)
  Bacon-Shor:    Bacon, PRA 73, 012340 (2006); Aliferis & Cross (2007)
  Steane [[7,1,3]]: Steane, PRL 77, 793 (1996)
"""
import math
from dataclasses import dataclass
from typing import Optional

# ── Tipos ────────────────────────────────────────────────────────────────────

@dataclass
class CircuitProfile:
    """Métricas extraídas de um circuito Qiskit."""
    n_logical_qubits: int
    n_logical_gates: int       # portas lógicas (nível Qiskit)
    n_physical_gates: int      # portas físicas após transpile CX+U
    depth_physical: int        # profundidade na base física
    t_count: int               # número de portas T (dominam custo FT)
    cx_count: int

@dataclass
class HardwareProfile:
    name: str
    t_gate_ns: float           # tempo de porta em nanossegundos
    p_phys: float              # taxa de erro físico por porta
    topology: str              # "heavy-hex", "all-to-all", "linear", "grid"
    readout_error: float = 0.0  # erro de leitura médio por qubit (opcional)

@dataclass
class CodeResult:
    code_name: str
    distance: Optional[int]
    qubits_per_logical: Optional[int]
    total_physical_qubits: Optional[int]
    gate_overhead_per_logical: Optional[float]
    total_physical_gates: Optional[float]
    execution_time_us: Optional[float]
    p_logical_achieved: Optional[float]
    fidelity_circuit: Optional[float]
    feasible: bool
    reason: str                # motivo de inviabilidade ou sumário

# ── Modelos QEC ──────────────────────────────────────────────────────────────

def _surface_code_model(p_phys: float, p_L_target: float,
                        p_th: float = 0.01, A: float = 0.1):
    """
    Fowler et al. 2012: p_L ≈ A*(p/p_th)^((d+1)/2)
    Retorna (d, qubits_per_logical, cycles_per_gate, p_L_achieved) ou raises
    """
    if p_phys >= p_th:
        raise ValueError(f"p_phys={p_phys:.4f} ≥ threshold={p_th}: não converge")
    # Resolver d mínimo
    ratio = math.log(p_L_target / A) / math.log(p_phys / p_th)
    d = max(3, math.ceil(2 * ratio - 1 + 1e-9))
    # Safeguard contra erro de ponto flutuante na fronteira
    p_L_check = A * (p_phys / p_th) ** ((d + 1) / 2)
    if p_L_check > p_L_target * (1 + 1e-12):
        d += 2  # próximo ímpar
    if d % 2 == 0:
        d += 1  # d deve ser ímpar no Surface Code rotacionado
    p_L = A * (p_phys / p_th) ** ((d + 1) / 2)
    q_per_logical = 2 * d**2 - 1
    # Ciclos de síndrome por porta lógica fault-tolerant: d (conservative)
    cycles_per_gate = d
    return d, q_per_logical, cycles_per_gate, p_L


def _bacon_shor_model(p_phys: float, p_L_target: float,
                      p_th: float = 0.008):
    """
    Aliferis & Cross 2007: p_L ≈ (p/p_th)^d para [[d²,1,d]]
    threshold ~0.7-1.1% dependendo do modelo; usamos 0.8% (conservador)
    """
    if p_phys >= p_th:
        raise ValueError(f"p_phys={p_phys:.4f} ≥ threshold_BS={p_th}: não converge")
    d = max(2, math.ceil(math.log(p_L_target) / math.log(p_phys / p_th)))
    p_L = (p_phys / p_th) ** d
    q_per_logical = d**2
    cycles_per_gate = 2 * (d - 1)  # medições de gauge por ciclo
    return d, q_per_logical, cycles_per_gate, p_L


def _steane_model(p_phys: float, p_L_target: float,
                  p_th: float = 0.007):
    """
    Steane [[7,1,3]]: código CSS fixo, d=3, p_L ≈ 21*p²
    Só é viável se p < p_th E p_L_target > 21*p²
    """
    if p_phys >= p_th:
        raise ValueError(f"p_phys={p_phys:.4f} ≥ threshold_Steane={p_th}")
    p_L = 21 * p_phys**2
    if p_L > p_L_target:
        raise ValueError(
            f"Steane d=3 insuficiente: p_L={p_L:.2e} > alvo={p_L_target:.2e}. "
            f"Necessário concatenação ou código de distância maior."
        )
    return 3, 13, 6, p_L  # 7 data + 6 ancilla, 6 síndrome por ciclo


def _floquet_code_model(p_phys: float, p_L_target: float,
                        p_th: float = 0.01, A: float = 0.07):
    """
    Floquet Code planar (4.8.8) — Gidney & Fowler, arXiv:2202.11829
    Vantagem vs Surface Code: overhead de tempo menor (d//2 vs d³ rodadas).
    Custo: ~2× mais qubits por lógico (4d²+8(d-1) vs 2d²-1).
    """
    if p_phys >= p_th:
        raise ValueError(f"p_phys={p_phys:.4f} ≥ threshold_Floquet={p_th}: não converge")
    ratio = math.log(p_L_target / A) / math.log(p_phys / p_th)
    d = max(3, math.ceil(2 * ratio - 1 + 1e-9))
    if d % 2 == 0:
        d += 1
    p_L = A * (p_phys / p_th) ** ((d + 1) / 2)
    if p_L > p_L_target * (1 + 1e-9):
        d += 2
        p_L = A * (p_phys / p_th) ** ((d + 1) / 2)
    q_per_logical = 4 * d**2 + 8 * (d - 1)
    gate_overhead = d // 2
    return d, q_per_logical, gate_overhead, p_L

# ── Extrator de perfil de circuito ───────────────────────────────────────────

def _count_t_gates(circuit) -> int:
    """
    Conta T e T† gates após decomposição na base Clifford+T.
    Portas Clifford (H, S, CX) têm custo zero em QEC fault-tolerant.
    optimization_level=2 simplifica ângulos redundantes antes da contagem
    (ex.: T·T·T otimiza para S·T — 1 T-gate real, não 3).
    """
    from qiskit import transpile
    t_basis = transpile(
        circuit,
        basis_gates=['t', 'tdg', 's', 'sdg', 'h', 'x', 'y', 'z', 'cx'],
        optimization_level=2,
        seed_transpiler=42
    )
    ops = t_basis.count_ops()
    return ops.get('t', 0) + ops.get('tdg', 0)


def extract_circuit_profile(circuit) -> CircuitProfile:
    """
    Extrai métricas reais de um QuantumCircuit Qiskit.
    Transpila para base {CX, U} para obter contagem física real.
    """
    from qiskit import transpile

    # Perfil lógico
    n_q = circuit.num_qubits
    ops_logical = {k: v for k, v in circuit.count_ops().items()
                   if k not in ('measure', 'barrier', 'reset')}
    n_logical = sum(ops_logical.values())

    # Perfil físico — transpile para base universal sem backend específico
    phys = transpile(circuit, basis_gates=['cx', 'u'],
                     optimization_level=3, seed_transpiler=42)
    ops_phys = {k: v for k, v in phys.count_ops().items()
                if k not in ('measure', 'barrier', 'reset')}
    n_physical = sum(ops_phys.values())
    depth_phys = phys.depth()

    # T-gates: contagem exata via decomposição Clifford+T (ver _count_t_gates).
    # Portas Clifford (H, S, CX) têm custo zero em QEC fault-tolerant.
    t_count = _count_t_gates(circuit)
    cx_count = ops_phys.get('cx', 0)

    return CircuitProfile(
        n_logical_qubits=n_q,
        n_logical_gates=n_logical,
        n_physical_gates=n_physical,
        depth_physical=depth_phys,
        t_count=t_count,
        cx_count=cx_count,
    )

# ── Estimador principal ───────────────────────────────────────────────────────

def estimate(circuit_profile: CircuitProfile,
             hardware: HardwareProfile,
             fidelity_target: float = 0.99) -> list[CodeResult]:
    """
    Para um dado CircuitProfile + HardwareProfile + alvo de fidelidade,
    retorna lista de CodeResult para cada código QEC analisado.

    p_L_per_gate = (1 - fidelity_target) / n_physical_gates
    """
    if not (0 < fidelity_target < 1):
        raise ValueError("fidelity_target deve estar em (0, 1)")

    N = circuit_profile.n_physical_gates
    if N == 0:
        raise ValueError("Circuito tem 0 portas físicas — foi destruído pelo transpile?")

    p_L_target = (1 - fidelity_target) / N
    t_ns = hardware.t_gate_ns
    n_L = circuit_profile.n_logical_qubits
    p = hardware.p_phys

    results = []

    # ── Surface Code ──────────────────────────────────────────────────────────
    try:
        d, q_per_L, cycles, p_L = _surface_code_model(p, p_L_target)
        total_q = q_per_L * n_L
        # cycles = d rodadas de síndrome por porta lógica (Fowler et al. PRA 86,
        # 032324, Sec. IV). Cada rodada tem d² medições de estabilizador (CX por
        # ciclo). Overhead total por porta lógica: d rodadas × d² medições = d³.
        gate_overhead = cycles * d**2  # = d³
        total_phys_gates = N * gate_overhead
        time_us = total_phys_gates * t_ns / 1000
        # Fidelidade do circuito × fidelidade de leitura (medição de cada
        # qubit lógico ao final). readout_error=0.0 (padrão) preserva o
        # comportamento anterior — sem esse termo, superestimava-se a
        # fidelidade em cenários reais (achado testando com IBM real).
        fid = (1 - p_L) ** N * (1 - hardware.readout_error) ** n_L
        results.append(CodeResult(
            code_name="Surface Code",
            distance=d,
            qubits_per_logical=q_per_L,
            total_physical_qubits=total_q,
            gate_overhead_per_logical=gate_overhead,
            total_physical_gates=total_phys_gates,
            execution_time_us=time_us,
            p_logical_achieved=p_L,
            fidelity_circuit=fid,
            feasible=True,
            reason=f"d={d}, p_L={p_L:.2e}",
        ))
    except ValueError as e:
        results.append(CodeResult(
            code_name="Surface Code", distance=None, qubits_per_logical=None,
            total_physical_qubits=None, gate_overhead_per_logical=None,
            total_physical_gates=None, execution_time_us=None,
            p_logical_achieved=None, fidelity_circuit=None,
            feasible=False, reason=str(e),
        ))

    # ── Bacon-Shor ────────────────────────────────────────────────────────────
    try:
        d, q_per_L, cycles, p_L = _bacon_shor_model(p, p_L_target)
        total_q = q_per_L * n_L
        total_phys_gates = N * cycles
        time_us = total_phys_gates * t_ns / 1000
        # Fidelidade do circuito × fidelidade de leitura (medição de cada
        # qubit lógico ao final). readout_error=0.0 (padrão) preserva o
        # comportamento anterior — sem esse termo, superestimava-se a
        # fidelidade em cenários reais (achado testando com IBM real).
        fid = (1 - p_L) ** N * (1 - hardware.readout_error) ** n_L
        results.append(CodeResult(
            code_name="Bacon-Shor",
            distance=d,
            qubits_per_logical=q_per_L,
            total_physical_qubits=total_q,
            gate_overhead_per_logical=cycles,
            total_physical_gates=total_phys_gates,
            execution_time_us=time_us,
            p_logical_achieved=p_L,
            fidelity_circuit=fid,
            feasible=True,
            reason=f"d={d}, [[{d**2},1,{d}]], p_L={p_L:.2e}",
        ))
    except ValueError as e:
        results.append(CodeResult(
            code_name="Bacon-Shor", distance=None, qubits_per_logical=None,
            total_physical_qubits=None, gate_overhead_per_logical=None,
            total_physical_gates=None, execution_time_us=None,
            p_logical_achieved=None, fidelity_circuit=None,
            feasible=False, reason=str(e),
        ))

    # ── Steane [[7,1,3]] ──────────────────────────────────────────────────────
    try:
        d, q_per_L, cycles, p_L = _steane_model(p, p_L_target)
        total_q = q_per_L * n_L
        total_phys_gates = N * cycles
        time_us = total_phys_gates * t_ns / 1000
        # Fidelidade do circuito × fidelidade de leitura (medição de cada
        # qubit lógico ao final). readout_error=0.0 (padrão) preserva o
        # comportamento anterior — sem esse termo, superestimava-se a
        # fidelidade em cenários reais (achado testando com IBM real).
        fid = (1 - p_L) ** N * (1 - hardware.readout_error) ** n_L
        results.append(CodeResult(
            code_name="Steane [[7,1,3]]",
            distance=3,
            qubits_per_logical=q_per_L,
            total_physical_qubits=total_q,
            gate_overhead_per_logical=cycles,
            total_physical_gates=total_phys_gates,
            execution_time_us=time_us,
            p_logical_achieved=p_L,
            fidelity_circuit=fid,
            feasible=True,
            reason=f"d=3 fixo, p_L={p_L:.2e}",
        ))
    except ValueError as e:
        results.append(CodeResult(
            code_name="Steane [[7,1,3]]", distance=None, qubits_per_logical=None,
            total_physical_qubits=None, gate_overhead_per_logical=None,
            total_physical_gates=None, execution_time_us=None,
            p_logical_achieved=None, fidelity_circuit=None,
            feasible=False, reason=str(e),
        ))

    # ── Floquet Code ──────────────────────────────────────────────────────────
    try:
        d, q_per_L, cycles, p_L = _floquet_code_model(p, p_L_target)
        total_q = q_per_L * n_L
        total_phys_gates = N * cycles
        time_us = total_phys_gates * t_ns / 1000
        # Fidelidade do circuito × fidelidade de leitura (medição de cada
        # qubit lógico ao final). readout_error=0.0 (padrão) preserva o
        # comportamento anterior — sem esse termo, superestimava-se a
        # fidelidade em cenários reais (achado testando com IBM real).
        fid = (1 - p_L) ** N * (1 - hardware.readout_error) ** n_L
        results.append(CodeResult(
            code_name="Floquet Code",
            distance=d,
            qubits_per_logical=q_per_L,
            total_physical_qubits=total_q,
            gate_overhead_per_logical=cycles,
            total_physical_gates=total_phys_gates,
            execution_time_us=time_us,
            p_logical_achieved=p_L,
            fidelity_circuit=fid,
            feasible=True,
            reason=f"d={d} (4.8.8 planar), p_L={p_L:.2e}",
        ))
    except ValueError as e:
        results.append(CodeResult(
            code_name="Floquet Code", distance=None, qubits_per_logical=None,
            total_physical_qubits=None, gate_overhead_per_logical=None,
            total_physical_gates=None, execution_time_us=None,
            p_logical_achieved=None, fidelity_circuit=None,
            feasible=False, reason=str(e),
        ))

    return results


def compare(circuit, hardware_list: list[HardwareProfile],
            fidelity_target: float = 0.99):
    """
    API principal: recebe circuito Qiskit + lista de hardwares,
    devolve dicionário hardware_name → [CodeResult].
    """
    profile = extract_circuit_profile(circuit)
    output = {"circuit_profile": profile, "results": {}, "hardware_profiles": {}}
    for hw in hardware_list:
        output["results"][hw.name] = estimate(profile, hw, fidelity_target)
        output["hardware_profiles"][hw.name] = hw
    return output
