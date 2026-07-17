"""
AutoQ Recommender — rankeamento automático de código+hardware
para um dado circuito e alvo de fidelidade.
"""
import math
from dataclasses import dataclass
from typing import Optional
from .qec_estimator import CodeResult, CircuitProfile

@dataclass
class Recommendation:
    rank: int
    hardware: str
    code: str
    total_physical_qubits: int
    execution_time_us: float
    fidelity_circuit: float
    score: float          # menor = melhor (normalizado); não decide a ordem
                           # entre camadas, só dentro de cada uma (ver rank())
    bottleneck: str       # o que domina o custo; para meets_fidelity_target=False,
                           # também explica o motivo do não-atingimento do alvo
    magic_state_qubits: Optional[int] = None
    magic_state_factories: Optional[int] = None
    magic_state_t_state_error: Optional[float] = None
    # False quando fidelity_circuit < fidelity_target (readout_error/T2_us
    # derrubaram a fidelidade abaixo do que foi pedido, mesmo com o código
    # QEC "viável" por erro de porta sozinho -- ver rank(), que nunca deixa
    # uma dessas competir por #1 contra quem realmente atinge o alvo.
    meets_fidelity_target: Optional[bool] = None

def _find_calibration(hw_name: str, hw_t_gate_ns: float, hw_p_phys: float,
                       calibrations: dict):
    """
    Localiza a CalibratedHardware correspondente a um HardwareProfile.
    HardwareProfile.name é escolhido livremente pelo usuário e não tem
    relação garantida com as chaves de `calibrations` (ex.: HARDWARE_PROFILES
    usa "IBM_Eagle_r3", mas um usuário pode nomear seu HardwareProfile
    "IBM_Eagle"). Por isso, primeiro tenta casar por nome; se falhar, casa
    pelas características numéricas (t_gate_ns e p_phys), que é como
    HardwareProfile costuma ser derivado de uma CalibratedHardware na prática.
    """
    if hw_name in calibrations:
        return calibrations[hw_name]
    for cal in calibrations.values():
        if (math.isclose(cal.t_2q_ns, hw_t_gate_ns, rel_tol=1e-6)
                and math.isclose(cal.p_phys, hw_p_phys, rel_tol=1e-6)):
            return cal
    return None


def rank(compare_result: dict,
         hardware_calibrations: dict = None,
         weight_qubits: float = 0.5,
         weight_time: float = 0.3,
         weight_fidelity: float = 0.2) -> list[Recommendation]:
    """
    Rankeia combinações hardware+código em duas camadas. Apenas combinações
    feasible=True entram; nenhuma é excluída por causa da fidelidade.
    Weights: soma deve ser 1.0 (normaliza internamente se não for).

    Camada A (meets_fidelity_target=True): ranking ponderado normal por
    score (qubits/tempo/fidelidade) -- #1 só vem daqui.
    Camada B (meets_fidelity_target=False): nunca fica acima da Camada A,
    não importa os pesos; ordenada só por fidelity_circuit decrescente,
    já que qubits/tempo baratos não têm valor numa combinação que não
    entrega a fidelidade pedida. Ver "Two-tier ranking" no README.

    Se `hardware_calibrations` for fornecido (dict nome→CalibratedHardware,
    ex. HARDWARE_PROFILES), combinações que violem o limite de T1
    (t_circuit >= 0.5×T1) são excluídas do ranking.
    """
    if abs(weight_qubits + weight_time + weight_fidelity - 1.0) > 1e-9:
        total = weight_qubits + weight_time + weight_fidelity
        weight_qubits  /= total
        weight_time    /= total
        weight_fidelity /= total

    prof: CircuitProfile = compare_result["circuit_profile"]
    hardware_profiles: dict = compare_result.get("hardware_profiles", {})
    candidatos = []

    for hw_name, code_results in compare_result["results"].items():
        hw = hardware_profiles.get(hw_name)
        cal = None
        if hardware_calibrations and hw is not None:
            cal = _find_calibration(
                hw_name, hw.t_gate_ns, hw.p_phys, hardware_calibrations
            )

        for r in code_results:
            if not r.feasible:
                continue

            if r.gate_overhead_per_logical:
                if cal is not None:
                    check = cal.t1_constraint(
                        n_physical_gates=prof.n_physical_gates,
                        gate_overhead=r.gate_overhead_per_logical,
                        # Usa o tempo real (inclui overhead de destilação de
                        # estado mágico, se model_magic_state_distillation=True
                        # foi usado em estimate()) em vez de recalcular só a
                        # partir de N×gate_overhead, que ignoraria esse tempo.
                        execution_time_us=r.execution_time_us,
                    )
                    if not check["feasible"]:
                        continue
                elif hw is not None and hw.T1_us is not None:
                    # Nenhuma CalibratedHardware casada (hardware_calibrations
                    # não informado, ou sem correspondência numérica) -- mas
                    # o próprio HardwareProfile do usuário já traz T1_us.
                    # Checar isso diretamente em vez de ignorar silenciosamente
                    # (bug corrigido na v3.2.4: T1_us de HardwareProfile nunca
                    # era lido em lugar nenhum).
                    ratio = r.execution_time_us / hw.T1_us
                    if ratio >= 0.5:
                        continue

            candidatos.append((hw_name, r))

    if not candidatos:
        return []

    fidelity_target = compare_result.get("fidelity_target")

    # Ranking em duas camadas (v3.4.0): feasible=True só garante que o
    # código QEC escolhido cobre o erro de porta (p_L <= p_L_target) --
    # não garante que fidelity_circuit (que também inclui readout_error e
    # a penalidade de decoerência T2_us) realmente bate o fidelity_target
    # pedido. Achado auditando rank() com T2_us ativado: combinações com
    # fidelidade ~0% apareciam misturadas e às vezes na frente de
    # combinações com fidelidade real, só por gastarem menos qubits/tempo.
    #
    # Camada A ("meets_fidelity_target=True"): ranking ponderado normal
    # (qubits/tempo/fidelidade) -- é uma disputa legítima entre opções que
    # já entregam o que foi pedido.
    # Camada B ("meets_fidelity_target=False"): não excluídas, mas nunca
    # competem pelo #1 contra a Camada A -- ordenadas só pela fidelidade
    # real, da mais próxima do alvo pra mais longe, já que qubits/tempo são
    # irrelevantes para uma combinação que não funciona.
    candidatos_ok = [(hw, r) for hw, r in candidatos if r.meets_fidelity_target]
    candidatos_abaixo = [(hw, r) for hw, r in candidatos if not r.meets_fidelity_target]

    def _construir_recomendacoes(grupo, meets_target):
        if not grupo:
            return []
        qubits_vals = [r.total_physical_qubits for _, r in grupo]
        time_vals   = [r.execution_time_us      for _, r in grupo]
        fid_vals    = [r.fidelity_circuit        for _, r in grupo]

        q_min, q_max = min(qubits_vals), max(qubits_vals)
        t_min, t_max = min(time_vals),   max(time_vals)
        f_min, f_max = min(fid_vals),    max(fid_vals)

        def norm(v, lo, hi):
            return 0.0 if hi == lo else (v - lo) / (hi - lo)

        recs = []
        for hw_name, r in grupo:
            q_norm = norm(r.total_physical_qubits, q_min, q_max)
            t_norm = norm(r.execution_time_us, t_min, t_max)
            f_norm = 1 - norm(r.fidelity_circuit, f_min, f_max)  # inverso: maior fid = menor custo

            score = (weight_qubits * q_norm
                     + weight_time * t_norm
                     + weight_fidelity * f_norm)

            contributions = {
                "qubits":    weight_qubits * q_norm,
                "tempo":     weight_time * t_norm,
                "fidelidade":weight_fidelity * f_norm,
            }
            bottleneck_key = max(contributions, key=contributions.get)
            bottleneck_pct = contributions[bottleneck_key] / score * 100 if score > 0 else 0
            bottleneck = f"{bottleneck_key} ({bottleneck_pct:.0f}% do score)"
            if not meets_target:
                alvo_str = f"{fidelity_target:.4f}" if fidelity_target is not None else "pedido"
                bottleneck = (f"NÃO atinge fidelity_target={alvo_str} "
                              f"(fidelidade real: {r.fidelity_circuit:.4f}) — {bottleneck}")

            recs.append(Recommendation(
                rank=0,  # preenchido abaixo
                hardware=hw_name,
                code=r.code_name,
                total_physical_qubits=r.total_physical_qubits,
                execution_time_us=r.execution_time_us,
                fidelity_circuit=r.fidelity_circuit,
                score=score,
                bottleneck=bottleneck,
                meets_fidelity_target=meets_target,
                magic_state_qubits=r.magic_state_qubits,
                magic_state_factories=r.magic_state_factories,
                magic_state_t_state_error=r.magic_state_t_state_error,
            ))
        return recs

    recs_ok = _construir_recomendacoes(candidatos_ok, True)
    recs_ok.sort(key=lambda x: x.score)

    recs_abaixo = _construir_recomendacoes(candidatos_abaixo, False)
    recs_abaixo.sort(key=lambda x: x.fidelity_circuit, reverse=True)

    recommendations = recs_ok + recs_abaixo
    for i, rec in enumerate(recommendations):
        rec.rank = i + 1

    return recommendations


def print_report(compare_result: dict, recommendations: list[Recommendation]):
    """Imprime relatório completo."""
    prof = compare_result["circuit_profile"]
    print(f"\n{'═'*72}")
    print(f"  RELATÓRIO AutoQ QEC Estimator")
    print(f"{'═'*72}")
    print(f"  Circuito: {prof.n_logical_qubits} qubits lógicos | "
          f"{prof.n_physical_gates} portas físicas (CX+U) | "
          f"profundidade {prof.depth_physical}")
    print(f"  CX: {prof.cx_count}  U: {prof.t_count}")

    print(f"\n  {'#':>3} {'Hardware':<20} {'Código':<22} "
          f"{'Qubits':>8} {'Tempo(µs)':>12} {'Fidelidade':>11} "
          f"{'Score':>7}  Gargalo")
    print(f"  {'─'*100}")

    for r in recommendations:
        marker = " ◀ MELHOR" if r.rank == 1 else ""
        print(f"  {r.rank:>3} {r.hardware:<20} {r.code:<22} "
              f"{r.total_physical_qubits:>8} {r.execution_time_us:>12.2f} "
              f"{r.fidelity_circuit:>11.4f} {r.score:>7.4f}  "
              f"{r.bottleneck}{marker}")

    if recommendations:
        best = recommendations[0]
        print(f"\n  RECOMENDAÇÃO: {best.hardware} + {best.code}")
        print(f"  → {best.total_physical_qubits} qubits físicos | "
              f"{best.execution_time_us:.2f} µs | "
              f"fidelidade {best.fidelity_circuit:.4f}")
        print(f"  → Gargalo principal: {best.bottleneck}")


def rank_by_metric(compare_result: dict, hardware_calibrations: dict = None
                    ) -> dict[str, list[Recommendation]]:
    """
    Rankeia cada métrica isoladamente (qubits, tempo, fidelidade), sem
    combinar num único score ponderado. Complementa rank(): quando uma
    combinação domina todos os critérios ao mesmo tempo (dominância de
    Pareto), nenhum peso em rank() consegue trocar o "#1" — essa função
    mostra diretamente o melhor de cada critério, sem depender de peso
    nenhum, então não sofre desse problema.

    Reaproveita rank() internamente com peso 1.0 isolado em cada métrica
    (as outras duas em 0.0) — dentro da Camada A (quem atinge
    fidelity_target), isso faz o score ficar determinado inteiramente por
    aquela métrica, então ordenar por score == ordenar pela métrica pura.
    Usa a mesma checagem de viabilidade/T1 e o mesmo ranking em duas
    camadas que rank() normal, sem duplicar lógica -- inclusive a
    consequência disso: se NENHUMA combinação atinge fidelity_target, as
    três listas (mesmo "qubits" e "tempo") caem inteiras na Camada B e
    saem ordenadas por fidelidade, não pela métrica pedida -- confira
    meets_fidelity_target antes de assumir que uma lista está de fato
    ordenada pelo critério do seu nome.

    Retorna {"qubits": [...], "tempo": [...], "fidelidade": [...]},
    cada lista ordenada (melhor primeiro) só por aquele critério dentro
    da Camada A; a Camada B, quando presente, vem depois ordenada por
    fidelidade em todas as três listas.
    """
    return {
        "qubits": rank(compare_result, hardware_calibrations,
                       weight_qubits=1.0, weight_time=0.0, weight_fidelity=0.0),
        "tempo": rank(compare_result, hardware_calibrations,
                      weight_qubits=0.0, weight_time=1.0, weight_fidelity=0.0),
        "fidelidade": rank(compare_result, hardware_calibrations,
                           weight_qubits=0.0, weight_time=0.0, weight_fidelity=1.0),
    }
