"""
AutoQ QEC — custo de destilação de estado mágico (T-factories).

Fórmulas de: Beverland, Kliuchnikov, Schoute et al., "Assessing requirements
to scale to practical quantum advantage", arXiv:2211.07629 (2022):
  - Tabela V (erro lógico / qubits / tempo por patch de Surface Code)
  - Tabela VI (unidades de destilação 15-para-1, lógicas)
  - Apêndice C, Eqs. C1-C4 (agregação de fábrica multi-rodada)
  - Apêndice E, Eqs. E4-E6 (número de fábricas e qubits totais)

Validado contra os 3 exemplos numéricos da Tabela VII do paper — ver
tests/test_distillation.py, que reproduz esses números exatos.

Simplificações assumidas (documentadas, não escondidas):
  - Q_0 (erro de entrada do T-state físico) = p_phys do hardware por padrão
    (p_t_state=None) — o paper permite um p_T físico separado, relevante em
    particular para qubits Majorana, onde a proteção topológica cobre
    operações Clifford (medição conjunta) mas não a porta T física, que
    fica com erro bem maior (ver HardwareProfile.p_t_state e
    HARDWARE_PROFILES["Majorana_MS_ResourceEstimator_illustrative"] em
    real_hardware.py). Passe p_t_state explicitamente para usar um valor
    diferente de p_phys nesse cálculo.
  - A busca de configuração de fábrica (Eq. E4 escolhe o argmin sobre um
    catálogo de fábricas candidatas) é aproximada por uma busca gulosa:
    a cada rodada, escolhe a menor distância que reduz o erro, minimizando
    qubits×tempo dessa rodada. Não é garantidamente o ótimo global entre
    todas as configurações possíveis, mas usa as mesmas fórmulas físicas
    por rodada do paper.
  - M(D) (T-states entregues em >=99% das execuções) é simplificado para 1
    por invocação completa da fábrica — não modela a distribuição de
    falha por pós-seleção em detalhe.
"""
import math
from dataclasses import dataclass, field
from typing import Optional

# Tabela VI — unidades de destilação 15-para-1 lógicas (Beverland et al. 2022)
_UNIT_QUBIT_MULTIPLIER = {
    "space-eff": 20,
    "rm-prep": 31,
}
_UNIT_TIME_MULTIPLIER = 13  # ambas as unidades: tempo = 13 * tau(d)

_MAX_ROUNDS = 6
_MAX_DISTANCE_SEARCH = 51  # busca d ímpar de 3 até esse limite por rodada


@dataclass
class DistillationRound:
    level: int
    distance: int
    unit_type: str
    qubits_per_copy: int
    copies: int
    time_us: float
    output_error: float


@dataclass
class MagicStateFactory:
    rounds: list = field(default_factory=list)  # list[DistillationRound]
    output_error: float = 0.0     # P_T(D) = Q_R — Eq. C1
    qubits: int = 0                # n(D) = max_r(c_r * n(M_r)) — Eq. C3
    time_us: float = 0.0           # tau(D) = soma dos tempos de rodada — Eq. C2


def _logical_error_rate(p_phys: float, d: int, A: float = 0.03, p_th: float = 0.01) -> float:
    """P_sur(d) = A*(p/p_th)^((d+1)/2) — Tabela V, Surface Code (gate-based)."""
    return A * (p_phys / p_th) ** ((d + 1) / 2)


def _n_tile(d: int) -> int:
    """n_sur(d) = 2d² — Tabela V."""
    return 2 * d * d


def _tau_tile_us(d: int, t_gate_ns: float, t_meas_ns: Optional[float] = None) -> float:
    """tau_sur(d) = (4*t_gate + 2*t_meas)*d — Tabela V (gate-based)."""
    t_meas_ns = t_gate_ns if t_meas_ns is None else t_meas_ns
    return (4 * t_gate_ns + 2 * t_meas_ns) * d / 1000  # ns -> us


def _round_output_error(q_in: float, p_logical: float) -> float:
    """Q_r = 35*Q_(r-1)^3 + 7.1*P_r — Tabela VI, unidade 15-para-1 lógica."""
    return 35 * q_in**3 + 7.1 * p_logical


def _round_candidates(q_in: float, p_phys: float, t_gate_ns: float,
                       t_meas_ns: Optional[float], unit_type: str):
    """Gera (cost, d, qubits, time_us, q_out) para toda distância que reduz o erro."""
    for d in range(3, _MAX_DISTANCE_SEARCH + 1, 2):
        p_logical = _logical_error_rate(p_phys, d)
        q_out = _round_output_error(q_in, p_logical)
        if q_out >= q_in:
            continue  # essa distância não melhora o erro — pular
        n_d = _n_tile(d)
        tau_d = _tau_tile_us(d, t_gate_ns, t_meas_ns)
        qubits = _UNIT_QUBIT_MULTIPLIER[unit_type] * n_d
        time_us = _UNIT_TIME_MULTIPLIER * tau_d
        yield (qubits * time_us, d, qubits, time_us, q_out)


def _best_round(q_in: float, p_phys: float, t_gate_ns: float, t_meas_ns: Optional[float],
                 unit_type: str, target_error: float):
    """
    Estratégia de 2 fases, replicando o padrão observado nos exemplos da
    Tabela VII (Beverland et al. 2022): primeiro tenta TERMINAR nesta rodada
    (menor custo entre as distâncias que já atingem target_error); se
    nenhuma distância atinge o alvo ainda, cai para a mais barata que ao
    menos reduz o erro (rodada intermediária "barata", que só prepara
    entrada de qualidade suficiente pra rodada seguinte terminar o serviço).
    """
    candidates = list(_round_candidates(q_in, p_phys, t_gate_ns, t_meas_ns, unit_type))
    finishing = [c for c in candidates if c[4] <= target_error]
    if finishing:
        return min(finishing, key=lambda c: c[0])
    if candidates:
        return min(candidates, key=lambda c: c[0])
    return None


def build_magic_state_factory(
    p_phys: float,
    t_gate_ns: float,
    target_error: float,
    t_meas_ns: Optional[float] = None,
    unit_type: str = "space-eff",
    p_t_state: Optional[float] = None,
) -> MagicStateFactory:
    """
    Constrói uma fábrica de destilação multi-rodada (15-para-1) até atingir
    target_error. Levanta ValueError se não convergir — nunca retorna um
    número silenciosamente errado.

    p_t_state (opcional): erro de injeção do T-state físico, se diferente
    de p_phys (ver nota de simplificação no docstring do módulo). None
    (padrão) usa p_phys, preservando o comportamento antigo.
    """
    if p_phys <= 0:
        raise ValueError(f"p_phys={p_phys} deve ser positivo")
    if not (0 < target_error < 1):
        raise ValueError(
            f"target_error={target_error} deve estar em (0, 1) (é uma "
            f"probabilidade de erro). Achado testando entrada inválida: "
            f"valores >= 1 eram aceitos silenciosamente e produziam uma "
            f"fábrica de aparência normal, já que qualquer distância "
            f"trivialmente satisfaz um alvo de erro que já nem é uma "
            f"probabilidade válida. magic_state_resources() já valida "
            f"isso antes de chamar esta função, mas quem chama "
            f"build_magic_state_factory() diretamente não tinha proteção."
        )
    if p_t_state is not None and not (0 < p_t_state < 1):
        raise ValueError(
            f"p_t_state={p_t_state} deve estar em (0, 1) ou ser None. "
            f"Achado testando entrada inválida: p_t_state >= 1 não era "
            f"rejeitado aqui e produzia um erro de convergência confuso, "
            f"apontando incorretamente para p_phys em vez do p_t_state "
            f"realmente inválido."
        )

    q = p_t_state if p_t_state is not None else p_phys  # Q_0
    rounds = []
    for level in range(1, _MAX_ROUNDS + 1):
        best = _best_round(q, p_phys, t_gate_ns, t_meas_ns, unit_type, target_error)
        if best is None:
            raise ValueError(
                f"Destilação não converge no nível {level} (p_phys={p_phys:.2e} "
                f"alto demais para qualquer distância testada)"
            )
        _, d, qubits, time_us, q_out = best
        rounds.append(DistillationRound(
            level=level, distance=d, unit_type=unit_type,
            qubits_per_copy=qubits, copies=1, time_us=time_us, output_error=q_out,
        ))
        q = q_out
        if q <= target_error:
            break
    else:
        raise ValueError(
            f"Destilação não atingiu erro-alvo {target_error:.2e} em {_MAX_ROUNDS} "
            f"níveis (erro alcançado: {q:.2e}) — alvo pode ser baixo demais"
        )

    # Rodadas intermediárias precisam de várias cópias em paralelo pra
    # alimentar a próxima rodada com T-states suficientes (15 por unidade
    # 15-para-1, mais margem de segurança contra rejeição por pós-seleção).
    # 16 cópias é o padrão usado nos exemplos da Tabela VII do paper para
    # toda rodada não-final; a rodada final usa 1 cópia (M(D)=1, ver
    # docstring do módulo).
    for i, r in enumerate(rounds):
        r.copies = 1 if i == len(rounds) - 1 else 16

    return MagicStateFactory(
        rounds=rounds,
        output_error=q,
        qubits=max(r.qubits_per_copy * r.copies for r in rounds),  # Eq. C3
        time_us=sum(r.time_us for r in rounds),  # Eq. C2 (tempo não multiplica por copies — rodam em paralelo)
    )


def magic_state_resources(
    t_count: int,
    p_phys: float,
    t_gate_ns: float,
    target_t_state_error: float,
    data_circuit_time_us: float,
    t_meas_ns: Optional[float] = None,
    p_t_state: Optional[float] = None,
):
    """
    Recursos totais de destilação para um circuito com `t_count` T-gates.
    Retorna (extra_qubits, n_factories, factory) — ver Eqs. E4-E6.
    Se t_count==0, retorna (0, 0, None) sem construir fábrica.

    p_t_state (opcional): repassado a build_magic_state_factory() — ver lá.
    """
    if t_count < 0:
        raise ValueError(
            f"t_count deve ser >= 0 (contagem de T-gates não pode ser "
            f"negativa), recebido {t_count}. Achado testando entrada "
            f"inválida: t_count=-1 produzia extra_qubits/n_factories "
            f"negativos sem erro, encolhendo silenciosamente qualquer "
            f"total de qubits que somasse este resultado."
        )
    if not (0 < target_t_state_error < 1):
        raise ValueError(
            f"target_t_state_error deve estar em (0, 1) (é uma "
            f"probabilidade de erro), recebido {target_t_state_error}. "
            f"Achado testando entrada inválida: valores >= 1 eram aceitos "
            f"silenciosamente (ex.: 1.5 produzia (1000, 1) sem erro), "
            f"porque qualquer distância satisfaz um alvo de erro que já "
            f"nem é uma probabilidade válida."
        )
    if data_circuit_time_us < 0:
        raise ValueError(
            f"data_circuit_time_us deve ser >= 0, recebido "
            f"{data_circuit_time_us}. Achado testando entrada inválida: "
            f"valores negativos eram aceitos silenciosamente (ex.: -500 "
            f"produzia (48400, 10) sem erro) porque max(1, floor(...)) "
            f"mascara o sinal negativo, escondendo um tempo de circuito "
            f"fisicamente sem sentido."
        )
    if t_count == 0:
        return 0, 0, None

    factory = build_magic_state_factory(p_phys, t_gate_ns, target_t_state_error,
                                         t_meas_ns, p_t_state=p_t_state)

    # F = ceil(M * tau(D) / (M(D) * t)) — Eq. E5, com M(D)=1 (simplificação, ver docstring)
    invocations_available = max(1, math.floor(data_circuit_time_us / factory.time_us))
    n_factories = math.ceil(t_count / invocations_available)

    extra_qubits = n_factories * factory.qubits  # Eq. E6 (parte da fábrica)
    return extra_qubits, n_factories, factory
