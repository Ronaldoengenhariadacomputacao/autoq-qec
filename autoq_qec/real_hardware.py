"""
AutoQ Real Hardware Integration
Três modos de operação:
  1. IBM real   — puxa backend.properties() com token
  2. IBM noise  — AerSimulator com noise model do backend real
  3. Publicado  — dados de papers/specs para fabricantes sem API aberta
"""
import math
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class CalibratedHardware:
    """Perfil de hardware com dados reais de calibração."""
    name: str
    n_qubits: int
    p_1q_mean: float        # erro médio porta 1q
    p_2q_mean: float        # erro médio porta 2q (CX/CZ/ZZ)
    p_2q_worst: float       # erro máximo — par de qubits mais ruidoso
    t_1q_ns: float          # duração porta 1q em ns
    t_2q_ns: float          # duração porta 2q em ns
    T1_us: float            # tempo de relaxação médio
    T2_us: float            # tempo de decoerência médio
    readout_error: float    # erro de leitura médio
    topology: str
    source: str             # referência dos dados
    # Erro de injeção do T-state físico, se diferente de p_2q_mean (opcional
    # -- ver HardwareProfile.p_t_state em qec_estimator.py). Relevante para
    # qubits onde a operação Clifford (aqui, p_2q_mean) tem proteção
    # diferente da porta T física (ex.: Majorana, proteção topológica só
    # em Clifford).
    p_t_state: Optional[float] = None
    # p_phys efetivo para QEC: geralmente dominado por 2q gates
    @property
    def p_phys(self) -> float:
        return self.p_2q_mean

    def t1_constraint(self, n_physical_gates: int, gate_overhead: float,
                       execution_time_us: float = None) -> dict:
        """
        Verifica se o circuito QEC cabe dentro do T1.
        Por padrão recalcula o tempo a partir de n_physical_gates×gate_overhead
        (comportamento antigo). Se `execution_time_us` for fornecido, usa esse
        valor diretamente — necessário quando o tempo real inclui overhead
        que gate_overhead não captura (ex.: destilação de estado mágico,
        que pode alongar execution_time_us além do que N×gate_overhead prevê).
        """
        t_circuit_us = (
            execution_time_us if execution_time_us is not None
            else n_physical_gates * gate_overhead * self.t_2q_ns / 1000
        )
        t1_us = self.T1_us
        ratio = t_circuit_us / t1_us
        return {
            "t_circuit_us": t_circuit_us,
            "T1_us": t1_us,
            "ratio": ratio,
            "feasible": ratio < 0.5,  # conservador: <50% de T1
            "warning": ratio > 0.1,
        }


# ── Dados publicados por fabricante ───────────────────────────────────────────

HARDWARE_PROFILES = {

    "IBM_Eagle_r3": CalibratedHardware(
        name="IBM Eagle r3 (ibm_brisbane)",
        n_qubits=127,
        p_1q_mean=2.8e-4,
        p_2q_mean=6.2e-3,
        p_2q_worst=2.1e-2,
        t_1q_ns=56.0,
        t_2q_ns=391.0,
        T1_us=198.4,
        T2_us=143.2,
        readout_error=0.0142,
        topology="heavy-hex",
        source="IBM Quantum Network calibration data, Eagle r3, 2024",
    ),

    "IBM_Heron_r2": CalibratedHardware(
        name="IBM Heron r2 (ibm_fez)",
        n_qubits=156,
        p_1q_mean=4.2e-4,
        p_2q_mean=6.7e-3,   # CZ gate no Heron
        p_2q_worst=2.0e-1,
        t_1q_ns=24.0,
        t_2q_ns=68.6,
        T1_us=139.3,
        T2_us=101.0,
        readout_error=0.0149,
        topology="heavy-hex",
        source="Calibração ao vivo real de ibm_fez via QiskitRuntimeService, 16 Jul 2026 "
               "(corrigido nesta sessão: a entrada anterior tinha n_qubits=133 — que é a "
               "contagem do Heron r1, não do r2, que tem 156 — associada a ibm_torino, que "
               "é na verdade Heron r1, não r2 (o r2 real é acessível via ibm_fez); a citação "
               "'arXiv:2404.07471' também estava errada — esse paper é sobre modelos de "
               "linguagem para código-fonte, não hardware quântico).",
    ),

    "Quantinuum_H2": CalibratedHardware(
        name="Quantinuum H2-1",
        n_qubits=56,
        p_1q_mean=3.0e-5,    # infidelidade típica de porta 1 qubit
        p_2q_mean=1.5e-3,    # ZZ gate — infidelidade típica (Table 1)
        p_2q_worst=3.0e-3,   # infidelidade máxima (Table 1)
        t_1q_ns=10e3,        # 10 µs
        t_2q_ns=100e3,       # 100 µs (íon aprisionado)
        T1_us=1e7,           # horas — sem limite prático de T1
        T2_us=1e5,           # ~0.1 s
        readout_error=0.0015,  # SPAM típico 1.5e-3 (Table 1) — já batia
        topology="all-to-all",
        source="Quantinuum System Model H2 Product Data Sheet, v1.4, 4 Jun 2024, Table 1 "
               "(https://docs.quantinuum.com/systems/data_sheets/) — corrigido nesta sessão: "
               "p_2q_mean/p_2q_worst antigos (2.9e-4/5.0e-4) vinham subestimados ~5x vs. o "
               "valor oficial típico/máximo (1.5e-3/3.0e-3); readout_error já batia.",
    ),

    "IonQ_Aria": CalibratedHardware(
        name="IonQ Aria-1",
        n_qubits=25,
        p_1q_mean=6.0e-4,    # 0.06% RB, ionq.com/quantum-systems/aria
        p_2q_mean=6.0e-3,    # 0.6% MS gate (Mølmer-Sørensen), ionq.com/quantum-systems/aria
        p_2q_worst=8.0e-3,
        t_1q_ns=135e3,       # 135 µs
        t_2q_ns=600e3,       # 600 µs
        T1_us=1e7,           # >10 s
        T2_us=1e6,           # ~1 s (era 1e5/~0.1s — 10x subestimado)
        readout_error=0.0039,  # 0.39% SPAM, ionq.com/quantum-systems/aria
        topology="all-to-all",
        source="IonQ Aria — especificação oficial publicada em "
               "https://www.ionq.com/quantum-systems/aria (corrigido nesta sessão: a "
               "citação anterior, 'arXiv:2307.01765', é um paper de matemática pura sobre "
               "medianas de Wasserstein, sem nenhuma relação com IonQ; p_1q_mean, T2_us e "
               "readout_error também foram ajustados para os valores oficiais reais).",
    ),

    "Google_Sycamore": CalibratedHardware(
        name="Google Sycamore (53q)",
        n_qubits=53,
        p_1q_mean=1.6e-3,
        p_2q_mean=6.2e-3,    # fSim gate
        p_2q_worst=1.1e-2,
        t_1q_ns=25.0,
        t_2q_ns=12.0,        # fSim muito rápido
        T1_us=15.0,
        T2_us=20.0,
        readout_error=0.037,
        topology="grid-2d",
        source="Arute et al., Nature 574, 505 (2019)",
    ),

    "Google_Willow": CalibratedHardware(
        name="Google Willow (105q)",
        n_qubits=105,
        p_1q_mean=5.0e-4,
        p_2q_mean=3.0e-3,
        p_2q_worst=8.0e-3,
        t_1q_ns=25.0,
        t_2q_ns=25.0,
        T1_us=68.0,          # era 100.0 — paper reporta T1 medio de 68us
        T2_us=89.0,          # era 150.0 — paper reporta T2,CPMG de 89us
        readout_error=0.007,
        topology="grid-2d",
        source="Acharya et al. (Google), Nature 638 (2025). doi:10.1038/s41586-024-08449-y "
               "(corrigido nesta sessão: T1/T2 estavam superestimados — 100/150us no lugar "
               "dos 68/89us reportados no paper; p_1q_mean/p_2q_mean não puderam ser "
               "confirmados como numeros isolados no texto do paper, mantidos como estavam).",
    ),

    "IBM_Heron_r3": CalibratedHardware(
        name="IBM Heron r3 (ibm_pittsburgh)",
        n_qubits=156,        # r3 mantém o desenho de 156 qubits introduzido no r2, não 133 (isso é r1)
        p_1q_mean=1.5e-4,
        p_2q_mean=1.7e-3,    # "latest calibration" — não o valor recorde isolado (~5e-4) de um tweet de lançamento
        p_2q_worst=5.0e-3,
        t_1q_ns=56.0,
        t_2q_ns=88.0,
        T1_us=300.0,
        T2_us=370.0,
        readout_error=0.007,
        topology="heavy-hex",
        source="Jay Gambetta (IBM), anúncio de lançamento ibm_pittsburgh, jul 2025 "
               "(x.com/jaygambetta/status/1925017189959991338) + postquantum.com cobertura "
               "do lançamento — corrigido nesta sessão: n_qubits estava em 133 (contagem do "
               "Heron r1), mas r3 mantém os 156 qubits do r2; T1/T2 também corrigidos "
               "(180/140 → 300/370, valores reais reportados no lançamento).",
    ),

    # ── Ilustrativo, NÃO medido — ver README "Majorana / qubits topológicos" ──
    "Majorana_MS_ResourceEstimator_illustrative": CalibratedHardware(
        name="Majorana (MS Resource Estimator default — not measured hardware)",
        n_qubits=4,          # "four-tetron" unit cell prototipado (Majorana 2, jul/2026);
                              # resultados publicados são de UM nanofio/tetron isolado, não
                              # de um array de 4 operando junto — não é uma contagem de
                              # capacidade, é o tamanho da célula unitária fabricada.
        p_1q_mean=1e-5,      # = error_rate default da classe qdk.qre.models.qubits.Majorana
        p_2q_mean=1e-5,      # (regime "realista" dos 3 citados: 1e-4/1e-5/1e-6). O modelo da
        p_2q_worst=1e-5,     # MS não distingue erro de 1q/2q -- um error_rate só, coberto por
                              # proteção topológica (medição/Clifford).
        t_1q_ns=1000.0,      # 1µs fixo p/ toda operação -- doc: "measurements and the physical
        t_2q_ns=1000.0,      # T gate each take 1 µs".
        T1_us=20_000_000.0,  # "mean qubit lifetime" ~20s (Forbes, lançamento Majorana 2,
                              # jul/2026) -- ATENÇÃO: é o tempo de vida reportado p/ MZM
                              # (relacionado a poisoning de quasipartícula), não
                              # necessariamente T1 no sentido de relaxação de energia usado
                              # nas outras entradas deste dict. Usado aqui como o análogo
                              # público mais próximo disponível p/ o filtro de viabilidade T1.
        T2_us=None,          # sem análogo público claro reportado -- não inventado.
        readout_error=1e-5,  # mesmo error_rate (medição É a operação Clifford neste modelo).
        topology="all-to-all",  # não modelado -- sem dado público de conectividade de lattice
                                 # surgery/braiding; tratado como sem penalidade de SWAP em vez
                                 # de inventar uma topologia sem fonte (ver README).
        p_t_state=0.015,     # porta T física (não-Clifford, SEM proteção topológica) no mesmo
                              # regime "realista" -- doc: "5%, 1.5%, and 1% error rate for
                              # non-Clifford physical T gates" p/ os 3 regimes.
        source="Modelo de erro/tempo: Microsoft Learn, qdk.qre.models.qubits.Majorana "
               "(learn.microsoft.com/python/qdk/qdk.qre.models.qubits.majorana, "
               "error_rate default=1e-5, regime 'realista'; cita Karzig et al. "
               "arXiv:1610.05289, Kitaev cond-mat/0010440, Das Sarma et al. "
               "arXiv:1501.02813) -- valor-ALVO de planejamento da própria Microsoft, "
               "não medição de hardware. T1: Forbes, cobertura do lançamento do chip "
               "'Majorana 2' (jul/2026), 'mean qubit lifetime of 20 seconds'. "
               "IMPORTANTE: dois-qubit/braiding ainda não haviam sido demonstrados "
               "publicamente no momento dessa cobertura ('two-qubit entangling gates... "
               "have yet to be demonstrated') -- ou seja, p_phys/p_t_state aqui são "
               "metas de projeto do Resource Estimator, não números medidos no chip "
               "real. Cobertura crítica independente: Nature "
               "(nature.com/articles/d41586-026-01788-y, 'researchers are still "
               "sceptical') e ScienceNews levantam ceticismo da comunidade sobre as "
               "alegações do anúncio -- usar esta entrada só para explorar a forma do "
               "modelo, não como previsão de desempenho real.",
    ),
}

# ── Integração IBM real (requer token) ────────────────────────────────────────

def from_ibm_backend(backend_name: str, token: str, instance: str = None) -> CalibratedHardware:
    """
    Puxa calibração real do IBM Quantum via qiskit-ibm-runtime.
    Requer: pip install qiskit-ibm-runtime
    Token gratuito em: https://quantum.cloud.ibm.com (plataforma IBM Cloud —
    substituiu o antigo quantum.ibm.com/channel 'ibm_quantum', descontinuado).
    `instance`: CRN da instância IBM Cloud, se sua conta exigir (opcional no
    Open Plan para a maioria dos casos).
    """
    try:
        from qiskit_ibm_runtime import QiskitRuntimeService
    except ImportError:
        raise ImportError("pip install qiskit-ibm-runtime")

    kwargs = {"token": token}
    if instance:
        kwargs["instance"] = instance
    service = QiskitRuntimeService(**kwargs)
    backend = service.backend(backend_name)
    props = backend.properties()
    config = backend.configuration()

    def _duration_ns(param) -> float:
        # A API da IBM já retorna gate_length na unidade indicada em
        # param.unit — hoje é 'ns'. Não assumir segundos silenciosamente.
        unit = getattr(param, "unit", "") or "ns"
        if unit == "ns":
            return param.value
        if unit == "us":
            return param.value * 1e3
        if unit in ("s", ""):
            return param.value * 1e9
        raise ValueError(f"Unidade de duração desconhecida da IBM: {unit!r}")

    # Erros/durações de porta — a porta nativa de 2 qubits varia por backend
    # (cx, cz, ecr...); identificar pelo número de qubits, não pelo nome.
    # Acopladores desativados/quebrados reportam gate_error==1.0 — excluí-los
    # das estatísticas: nenhum circuito real é roteado por eles (o transpiler
    # evita), então incluí-los infla p_2q_mean/p_2q_worst de forma enganosa.
    DEAD_COUPLER_THRESHOLD = 0.99
    two_q_errors, two_q_durations = [], []
    one_q_errors, one_q_durations = [], []
    n_dead_couplers = 0
    n_dead_qubits = 0
    for gate in props.gates:
        gate_errs = [p.value for p in gate.parameters if p.name == 'gate_error']
        is_dead = bool(gate_errs) and gate_errs[0] >= DEAD_COUPLER_THRESHOLD
        if len(gate.qubits) == 2:
            if is_dead:
                n_dead_couplers += 1
                continue
            for param in gate.parameters:
                if param.name == 'gate_error': two_q_errors.append(param.value)
                if param.name == 'gate_length': two_q_durations.append(_duration_ns(param))
        elif len(gate.qubits) == 1 and gate.gate in ('sx', 'x'):
            if is_dead:
                n_dead_qubits += 1
                continue
            for param in gate.parameters:
                if param.name == 'gate_error': one_q_errors.append(param.value)
                if param.name == 'gate_length': one_q_durations.append(_duration_ns(param))

    if not two_q_errors:
        raise ValueError(
            f"Nenhuma porta de 2 qubits com dados de calibração encontrada "
            f"em {backend_name} — não é possível estimar p_2q_mean."
        )

    T1_vals, T2_vals, ro_errs = [], [], []
    for q in range(config.n_qubits):
        try:
            t1, t2, ro = props.t1(q), props.t2(q), props.readout_error(q)
        except Exception:
            continue  # qubit sem calibração (ex.: desativado) — pula, não quebra
        if t1: T1_vals.append(t1 * 1e6)
        if t2: T2_vals.append(t2 * 1e6)
        ro_errs.append(ro)

    return CalibratedHardware(
        name=f"IBM {backend_name} (calibração ao vivo)",
        n_qubits=config.n_qubits,
        p_1q_mean=sum(one_q_errors)/len(one_q_errors) if one_q_errors else 3e-4,
        p_2q_mean=sum(two_q_errors)/len(two_q_errors),
        p_2q_worst=max(two_q_errors),
        t_1q_ns=sum(one_q_durations)/len(one_q_durations) if one_q_durations else 56,
        t_2q_ns=sum(two_q_durations)/len(two_q_durations),
        T1_us=sum(T1_vals)/len(T1_vals) if T1_vals else 200,
        T2_us=sum(T2_vals)/len(T2_vals) if T2_vals else 150,
        readout_error=sum(ro_errs)/len(ro_errs) if ro_errs else 0.015,
        topology="heavy-hex",
        source=(
            f"IBM Quantum live calibration — {backend_name} "
            f"({n_dead_couplers} acoplador(es) e {n_dead_qubits} qubit(s) com "
            f"erro>={DEAD_COUPLER_THRESHOLD} excluído(s) da média)"
        ),
    )


def noise_model_from_ibm(backend_name: str, token: str, instance: str = None):
    """
    Constrói AerSimulator com noise model real do backend IBM.
    Permite simular localmente com ruído realista sem usar shots pagos.
    Requer: pip install qiskit-ibm-runtime qiskit-aer
    """
    try:
        from qiskit_ibm_runtime import QiskitRuntimeService
        from qiskit_aer.noise import NoiseModel
        from qiskit_aer import AerSimulator
    except ImportError:
        raise ImportError("pip install qiskit-ibm-runtime qiskit-aer")

    kwargs = {"token": token}
    if instance:
        kwargs["instance"] = instance
    service = QiskitRuntimeService(**kwargs)
    backend = service.backend(backend_name)
    noise_model = NoiseModel.from_backend(backend)
    sim = AerSimulator(noise_model=noise_model,
                       coupling_map=backend.configuration().coupling_map,
                       basis_gates=noise_model.basis_gates)
    return sim


# ── Análise de viabilidade T1 ────────────────────────────────────────────────

def t1_feasibility_report(hw: CalibratedHardware,
                           n_physical_gates: int,
                           gate_overhead: float) -> None:
    """Imprime relatório de viabilidade baseado em T1/T2."""
    check = hw.t1_constraint(n_physical_gates, gate_overhead)
    status = "✓ VIÁVEL" if check["feasible"] else "✗ INVIÁVEL (excede T1)"
    warn   = "⚠ ATENÇÃO" if check["warning"] and check["feasible"] else ""
    print(f"  T1 check [{hw.name}]: {status} {warn}")
    print(f"    t_circuit = {check['t_circuit_us']:.1f} µs")
    print(f"    T1 médio  = {check['T1_us']:.1f} µs")
    print(f"    ratio     = {check['ratio']:.3f} ({check['ratio']*100:.1f}% de T1)")
