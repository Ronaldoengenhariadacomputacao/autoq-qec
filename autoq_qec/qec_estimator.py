"""
AutoQ QEC Estimator — módulo de estimativa multi-código fault-tolerant
Referências:
  Surface Code:  Fowler et al., PRA 86, 032324 (2012)
  Bacon-Shor:    Bacon, PRA 73, 012340 (2006); Aliferis & Cross (2007)
  Steane [[7,1,3]]: Steane, PRL 77, 793 (1996)
"""
import math
import warnings
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
    T1_us: Optional[float] = None  # tempo de relaxação (opcional)
    T2_us: Optional[float] = None  # tempo de decoerência (opcional)
    t_meas_ns: Optional[float] = None  # tempo de medição (opcional, default=t_gate_ns)
    # Erro de injeção do T-state físico, quando diferente de p_phys (opcional).
    # p_phys aqui é o erro da operação de 2 qubits "protegida" (porta física em
    # qubits baseados em porta; medição conjunta em qubits topológicos/Majorana).
    # Operações não-Clifford (T-gate físico) podem não ter a mesma proteção --
    # em Majorana, por exemplo, a proteção topológica cobre operações Clifford,
    # mas não o T físico, que fica com erro bem maior (ver HARDWARE_PROFILES
    # "Majorana_MS_ResourceEstimator_illustrative" e distillation.py). None
    # (padrão) preserva o comportamento antigo: destilação usa p_phys como Q_0.
    p_t_state: Optional[float] = None

    def __post_init__(self):
        """
        Zero ou negativo não tem significado físico para nenhum destes
        campos (uma porta não roda em tempo zero/negativo; T1/T2 zero
        seria decoerência instantânea, não "não modelada" -- isso já é
        representado por None). Rejeita cedo, com ValueError claro, em vez
        de deixar passar silenciosamente e produzir resultados absurdos
        mais adiante (achado: t_gate_ns=0 gerava execution_time_us=0.0 sem
        nenhum erro; readout_error fora de [0,1] gerava fidelity_circuit
        > 1.0).
        """
        if self.t_gate_ns <= 0:
            raise ValueError(f"t_gate_ns deve ser > 0, recebido {self.t_gate_ns}")
        if not (0 < self.p_phys < 1):
            raise ValueError(f"p_phys deve estar em (0, 1), recebido {self.p_phys}")
        if not (0 <= self.readout_error < 1):
            raise ValueError(f"readout_error deve estar em [0, 1), recebido {self.readout_error}")
        if self.T1_us is not None and self.T1_us <= 0:
            raise ValueError(f"T1_us deve ser > 0 ou None, recebido {self.T1_us}")
        if self.T2_us is not None and self.T2_us <= 0:
            raise ValueError(f"T2_us deve ser > 0 ou None, recebido {self.T2_us}")
        if self.t_meas_ns is not None and self.t_meas_ns <= 0:
            raise ValueError(f"t_meas_ns deve ser > 0 ou None, recebido {self.t_meas_ns}")
        if self.p_t_state is not None and self.p_t_state <= 0:
            raise ValueError(f"p_t_state deve ser > 0 ou None, recebido {self.p_t_state}")

    @classmethod
    def from_calibrated(cls, cal) -> "HardwareProfile":
        """
        Constrói um HardwareProfile a partir de um CalibratedHardware
        (ex.: HARDWARE_PROFILES["IBM_Heron_r2"]), carregando T1_us/T2_us/
        readout_error automaticamente.

        Existe porque HardwareProfile precisa ser construído manualmente
        pra usar em compare()/rank(), e os exemplos documentados (README,
        example.py) historicamente copiavam só t_gate_ns/p_phys/topology
        à mão, esquecendo T2_us/readout_error — o que faz a fidelidade
        prevista ignorar decoerência por completo (ver "Known limitation:
        HardwareProfile sem T2_us" no README). Usar este construtor evita
        esse esquecimento: carrega todos os campos calibrados de uma vez.
        """
        return cls(
            name=cal.name,
            t_gate_ns=cal.t_2q_ns,
            p_phys=cal.p_phys,
            topology=cal.topology,
            readout_error=cal.readout_error,
            T1_us=cal.T1_us,
            T2_us=cal.T2_us,
            p_t_state=getattr(cal, "p_t_state", None),
        )

@dataclass
class CodeResult:
    code_name: str
    distance: Optional[int]
    qubits_per_logical: Optional[int]
    total_physical_qubits: Optional[int]
    gate_overhead_per_logical: Optional[float]
    total_physical_gates: Optional[float]  # portas do circuito de dados QEC apenas —
                                            # NÃO inclui as portas internas das rodadas
                                            # de destilação (magic_state_qubits/factories
                                            # contam qubits e tempo da fábrica, não portas)
    execution_time_us: Optional[float]
    p_logical_achieved: Optional[float]
    fidelity_circuit: Optional[float]
    feasible: bool
    reason: str                # motivo de inviabilidade ou sumário
    # True se fidelity_circuit >= fidelity_target (só definido quando
    # feasible=True). feasible sozinho só garante p_L <= p_L_target (erro
    # de porta) -- fidelity_circuit inclui também readout_error e a
    # penalidade de decoerência T2_us, que podem derrubar a fidelidade
    # real bem abaixo do alvo mesmo com feasible=True (achado auditando
    # rank() com T2_us ativado: combinações com fidelidade ~0% apareciam
    # como "viáveis"). Ver rank(), que usa este campo para não deixar uma
    # opção que não entrega o alvo pedido competir por #1.
    meets_fidelity_target: Optional[bool] = None
    # Custo de destilação de estado mágico — só preenchido quando
    # model_magic_state_distillation=True em estimate() (ver distillation.py)
    magic_state_qubits: Optional[int] = None
    magic_state_factories: Optional[int] = None
    magic_state_t_state_error: Optional[float] = None

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

    Li, Miller & Brown 2018 (arXiv:1804.01127) mostram que uma única rodada
    de extração de síndrome com ancilla nua mede os 2(d-1) estabilizadores
    de forma tolerante a falhas (sem redundância extra dentro da rodada).
    Mas, como no Surface Code, uma operação lógica precisa repetir a
    extração de síndrome ~d vezes para preservar a proteção da distância
    do código durante o gate (mesma convenção-padrão de arquitetura FT;
    confirmado também na tese do Aliferis, quant-ph/0703230, p.93: as
    medições "não podem, em geral, ser confiáveis a menos que algumas
    sejam repetidas um número de vezes dependendo da distância do código").
    Custo total por porta lógica = d rodadas × 2(d-1) medições/rodada.
    """
    if p_phys >= p_th:
        raise ValueError(f"p_phys={p_phys:.4f} ≥ threshold_BS={p_th}: não converge")
    d = max(2, math.ceil(math.log(p_L_target) / math.log(p_phys / p_th)))
    p_L = (p_phys / p_th) ** d
    q_per_logical = d**2
    cycles_per_gate = d * 2 * (d - 1)  # d rodadas × 2(d-1) medições de gauge por rodada
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
    Floquet Code planar (4.8.8) — Paetznick, Knapp, Delfosse, Bauer, Haah,
    Hastings & da Silva, "Performance of planar Floquet codes with
    Majorana-based qubits", arXiv:2202.11829 (autoria corrigida nesta
    sessão -- estava atribuído a "Gidney & Fowler", citação fabricada/errada).
    p_th=0.01, A=0.07 conferidos número-por-número contra o texto do paper
    (fórmula "4.8.8": p_L ≈ 0.07(p/0.01)^((d+1)/2)).

    Importante: este paper modela especificamente qubits MZM (Majorana
    zero modes) topológicos, e define p como o erro de CADA MEDIÇÃO DE 2
    QUBITS (não erro de porta) -- ou seja, p_phys aqui já representa a
    operação física nativa de qubits Majorana. Ver
    HARDWARE_PROFILES["Majorana_MS_ResourceEstimator_illustrative"] em
    real_hardware.py e "Majorana / qubits topológicos" no README. Para
    qubits baseados em porta, a mesma fórmula é reaproveitada tratando p
    como o erro da porta física de 2 qubits (aproximação -- ver
    extract_circuit_profile()/n_physical_gates, que conta portas físicas
    via transpile, usado como proxy do número de operações de 2 qubits
    independente do mecanismo físico real).

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


def extract_circuit_profile(circuit, coupling_map=None) -> CircuitProfile:
    """
    Extrai métricas reais de um QuantumCircuit Qiskit.
    Transpila para base {CX, U} para obter contagem física real.

    coupling_map (opcional): restrição de conectividade real do hardware
    (qiskit.transpiler.CouplingMap). Se omitido (padrão), assume
    conectividade total (all-to-all) — sem custo de SWAP para rotear
    qubits não-vizinhos. Ver compare(), que passa isso automaticamente
    por hardware com base em HardwareProfile.topology (v3.2.4).
    """
    from qiskit import transpile

    if circuit.num_parameters > 0:
        raise ValueError(
            f"Circuito tem {circuit.num_parameters} parâmetro(s) não vinculado(s) "
            f"({[str(p) for p in list(circuit.parameters)[:3]]}"
            f"{', ...' if circuit.num_parameters > 3 else ''}). "
            "Ansätze variacionais (RealAmplitudes, EfficientSU2, QAOAAnsatz, etc.) "
            "precisam ter os parâmetros vinculados a valores numéricos antes da "
            "estimativa de recursos — o T-count depende dos ângulos de rotação reais, "
            "que não existem enquanto o circuito for simbólico. "
            "Use circuit.assign_parameters(valores) antes de chamar compare()/extract_circuit_profile()."
        )

    # Perfil lógico
    n_q = circuit.num_qubits
    ops_logical = {k: v for k, v in circuit.count_ops().items()
                   if k not in ('measure', 'barrier', 'reset')}
    n_logical = sum(ops_logical.values())

    # Perfil físico — transpile para base universal, com coupling_map real
    # do hardware se informado (insere SWAPs reais para qubits não-vizinhos).
    phys = transpile(circuit, basis_gates=['cx', 'u'], coupling_map=coupling_map,
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

def _decoherence_factor(time_us: float, T2_us: Optional[float]) -> float:
    """
    Fator de sobrevivência à decoerência T2 ao longo da execução do circuito
    (aproximação exp(-t/T2), padrão em estimativas de coerência). Captura
    perda de fidelidade que o erro por-porta não pega: qubits ociosos
    decaindo enquanto outras portas do circuito ainda rodam — relevante
    porque o overhead de sindrome do QEC (d³ para Surface Code) alonga
    bastante o tempo total de execução.
    T2_us=None (padrão) preserva o comportamento anterior — sem esse termo.
    """
    if T2_us is None or T2_us <= 0:
        return 1.0
    return math.exp(-time_us / T2_us)


# ── Estimador principal ───────────────────────────────────────────────────────

def _warn_incomplete_hardware_profile(hardware: HardwareProfile) -> None:
    """
    Avisa quando HardwareProfile está com campos no default silencioso
    (readout_error=0.0, T1_us=None, T2_us=None) — cada um faz fidelity_circuit
    parecer melhor do que seria com dados reais, sem nenhum sinal de que
    algo foi omitido. Lista só os campos que faltam de fato: se o usuário
    já informou um deles, ele some da mensagem; o aviso para de aparecer
    de vez quando os três estiverem preenchidos (ou explicitamente ligados
    a partir de HardwareProfile.from_calibrated(), que já traz os três).
    """
    faltando = []
    if hardware.readout_error == 0.0:
        faltando.append(
            "readout_error [erro médio de leitura por qubit ao final do "
            "circuito, fração 0-1] — assumindo 0.0 (leitura perfeita)"
        )
    if hardware.T1_us is None:
        faltando.append(
            "T1_us [tempo de relaxação T1 do hardware, em µs] — sem ele, "
            "o filtro de viabilidade por T1 em rank() fica desligado"
        )
    if hardware.T2_us is None:
        faltando.append(
            "T2_us [tempo de decoerência T2 do hardware, em µs] — sem ele, "
            "decoerência não é modelada e fidelity_circuit ignora o tempo "
            "de execução por completo"
        )
    if faltando:
        warnings.warn(
            f"HardwareProfile '{hardware.name}' sem: {'; '.join(faltando)}. "
            "fidelity_circuit pode estar superestimada. Use "
            "HardwareProfile.from_calibrated(HARDWARE_PROFILES[...]) para "
            "carregar dados reais automaticamente, se o hardware estiver "
            "na lista embutida.",
            UserWarning, stacklevel=3,
        )


def estimate(circuit_profile: CircuitProfile,
             hardware: HardwareProfile,
             fidelity_target: float = 0.99,
             model_magic_state_distillation: bool = False) -> list[CodeResult]:
    """
    Para um dado CircuitProfile + HardwareProfile + alvo de fidelidade,
    retorna lista de CodeResult para cada código QEC analisado.

    p_L_per_gate = (1 - fidelity_target) / n_physical_gates

    CodeResult.feasible=True garante só que esse p_L_target foi atingido
    (erro de porta); CodeResult.meets_fidelity_target=True garante que
    fidelity_circuit (que também inclui readout_error e a penalidade de
    T2_us, se informado) realmente é >= fidelity_target -- os dois podem
    divergir (ver "Two-tier ranking" no README).

    Emite UserWarning se HardwareProfile estiver sem readout_error/T1_us/
    T2_us (ver _warn_incomplete_hardware_profile) -- não bloqueia a
    execução, só avisa que fidelity_circuit pode estar superestimada.

    model_magic_state_distillation=False (padrão) preserva o comportamento
    anterior: total_physical_qubits/execution_time_us não incluem o custo
    de destilação de estado mágico (T-factories) — ver "Known limitation"
    no README. Quando True, cada CodeResult viável ganha o custo de
    fábrica de destilação (Beverland et al., arXiv:2211.07629) somado aos
    totais, e os campos magic_state_* são preenchidos.
    """
    if not (0 < fidelity_target < 1):
        raise ValueError("fidelity_target deve estar em (0, 1)")

    _warn_incomplete_hardware_profile(hardware)

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
        fid = ((1 - p_L) ** N * (1 - hardware.readout_error) ** n_L
               * _decoherence_factor(time_us, hardware.T2_us))
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
            meets_fidelity_target=fid >= fidelity_target,
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
        fid = ((1 - p_L) ** N * (1 - hardware.readout_error) ** n_L
               * _decoherence_factor(time_us, hardware.T2_us))
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
            meets_fidelity_target=fid >= fidelity_target,
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
        fid = ((1 - p_L) ** N * (1 - hardware.readout_error) ** n_L
               * _decoherence_factor(time_us, hardware.T2_us))
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
            meets_fidelity_target=fid >= fidelity_target,
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
        fid = ((1 - p_L) ** N * (1 - hardware.readout_error) ** n_L
               * _decoherence_factor(time_us, hardware.T2_us))
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
            meets_fidelity_target=fid >= fidelity_target,
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

    if model_magic_state_distillation:
        _apply_magic_state_distillation(results, circuit_profile, hardware,
                                         p_L_target, fidelity_target)

    return results


def _apply_magic_state_distillation(results: list, circuit_profile: CircuitProfile,
                                     hardware: HardwareProfile, p_L_target: float,
                                     fidelity_target: float) -> None:
    """
    Adiciona o custo de destilação de estado mágico (T-factories) aos
    CodeResult viáveis, mutando a lista in-place. Reaproveita o mesmo
    orçamento de erro por operação lógica (p_L_target) já usado pelo
    resto do circuito como alvo de erro do T-state — ver distillation.py.
    """
    from .distillation import magic_state_resources

    t_count = circuit_profile.t_count
    if t_count == 0:
        return  # circuito sem T-gates: nada a destilar

    for r in results:
        if not r.feasible:
            continue
        try:
            extra_qubits, n_factories, factory = magic_state_resources(
                t_count=t_count,
                p_phys=hardware.p_phys,
                t_gate_ns=hardware.t_gate_ns,
                target_t_state_error=p_L_target,
                data_circuit_time_us=r.execution_time_us,
                t_meas_ns=hardware.t_meas_ns,
                p_t_state=hardware.p_t_state,
            )
        except ValueError as e:
            r.feasible = False
            r.reason = f"destilação de estado mágico inviável: {e}"
            continue

        r.magic_state_qubits = extra_qubits
        r.magic_state_factories = n_factories
        r.magic_state_t_state_error = factory.output_error if factory else None
        r.total_physical_qubits += extra_qubits

        if factory:
            old_time_us = r.execution_time_us
            new_time_us = max(old_time_us, factory.time_us)
            if new_time_us != old_time_us and r.fidelity_circuit is not None:
                # fidelity_circuit já foi calculada com o decoherence_factor
                # do tempo ANTIGO (antes de somar o tempo da fábrica) — sem
                # isso, o tempo total cresceria mas a penalidade de T2 ficaria
                # desatualizada, reabrindo o mesmo problema que o termo de
                # decoerência foi criado pra resolver.
                old_decoherence = _decoherence_factor(old_time_us, hardware.T2_us)
                new_decoherence = _decoherence_factor(new_time_us, hardware.T2_us)
                if old_decoherence > 0:
                    r.fidelity_circuit = r.fidelity_circuit / old_decoherence * new_decoherence
                r.meets_fidelity_target = r.fidelity_circuit >= fidelity_target
            r.execution_time_us = new_time_us


def _coupling_map_for_topology(topology: str, n_qubits: int):
    """
    Constrói um CouplingMap real do Qiskit a partir do campo topology de um
    HardwareProfile, para modelar custo de roteamento (SWAP) em hardware de
    conectividade limitada (v3.2.4 — antes, topology era lido em nenhum
    lugar e todo circuito era transpilado como se o hardware fosse
    all-to-all, mesmo quando heavy-hex/linear/grid era informado).

    Retorna None para "all-to-all" (sem restrição) ou topologias
    desconhecidas — nesse caso o comportamento antigo (sem custo de SWAP)
    é preservado, por segurança, em vez de falhar.
    """
    if topology == "all-to-all" or n_qubits <= 1:
        return None

    from qiskit.transpiler import CouplingMap

    if topology == "linear":
        return CouplingMap.from_line(n_qubits)
    if topology in ("grid", "grid-2d"):  # "grid-2d" usado em Google_Willow
        cols = math.ceil(math.sqrt(n_qubits))
        rows = math.ceil(n_qubits / cols)
        return CouplingMap.from_grid(rows, cols)
    if topology == "heavy-hex":
        d = 3  # distância mínima válida (ímpar) do heavy-hex
        while (5 * d**2 - 2 * d - 1) // 2 < n_qubits:
            d += 2
        return CouplingMap.from_heavy_hex(d)
    return None


def compare(circuit, hardware_list: list[HardwareProfile],
            fidelity_target: float = 0.99,
            model_magic_state_distillation: bool = False):
    """
    API principal: recebe circuito Qiskit + lista de hardwares, devolve
    {"circuit_profile": CircuitProfile, "results": {hw_name: [CodeResult]},
    "hardware_profiles": {hw_name: HardwareProfile}, "fidelity_target": float}.

    Cada hardware é transpilado com o coupling_map real da sua topology
    (v3.2.4) — hardware de conectividade limitada (heavy-hex, linear, grid)
    paga o custo real de SWAPs para rotear qubits não-vizinhos, em vez de
    assumir all-to-all para todo mundo. output["circuit_profile"] continua
    sendo o perfil topology-agnostic (all-to-all), mantido por compatibilidade
    e para uso exibicional; as estimativas em output["results"] usam o
    perfil específico de cada hardware internamente.

    output["fidelity_target"] (v3.4.0) carrega o fidelity_target usado nesta
    chamada -- rank() lê esse valor pra montar a mensagem de "não atinge o
    alvo" em Recommendation.bottleneck (ver meets_fidelity_target em
    CodeResult/Recommendation, e "Two-tier ranking" no README).
    """
    profile = extract_circuit_profile(circuit)
    output = {"circuit_profile": profile, "results": {}, "hardware_profiles": {},
              "fidelity_target": fidelity_target}
    for hw in hardware_list:
        hw_profile = profile
        coupling_map = _coupling_map_for_topology(hw.topology, circuit.num_qubits)
        if coupling_map is not None:
            hw_profile = extract_circuit_profile(circuit, coupling_map=coupling_map)
        output["results"][hw.name] = estimate(
            hw_profile, hw, fidelity_target, model_magic_state_distillation
        )
        output["hardware_profiles"][hw.name] = hw
    return output
