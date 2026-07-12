"""
AutoQ Recommender — rankeamento automático de código+hardware
para um dado circuito e alvo de fidelidade.
"""
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
    score: float          # menor = melhor (normalizado)
    bottleneck: str       # o que domina o custo

def rank(compare_result: dict,
         weight_qubits: float = 0.5,
         weight_time: float = 0.3,
         weight_fidelity: float = 0.2) -> list[Recommendation]:
    """
    Rankeia combinações hardware+código por score ponderado.
    Apenas combinações viáveis entram no ranking.
    Weights: soma deve ser 1.0 (normaliza internamente se não for).
    """
    if abs(weight_qubits + weight_time + weight_fidelity - 1.0) > 1e-9:
        total = weight_qubits + weight_time + weight_fidelity
        weight_qubits  /= total
        weight_time    /= total
        weight_fidelity /= total

    prof: CircuitProfile = compare_result["circuit_profile"]
    candidatos = []

    for hw_name, code_results in compare_result["results"].items():
        for r in code_results:
            if r.feasible:
                candidatos.append((hw_name, r))

    if not candidatos:
        return []

    # Normalizar métricas para [0,1]
    qubits_vals = [r.total_physical_qubits for _, r in candidatos]
    time_vals   = [r.execution_time_us      for _, r in candidatos]
    fid_vals    = [r.fidelity_circuit        for _, r in candidatos]

    q_min, q_max = min(qubits_vals), max(qubits_vals)
    t_min, t_max = min(time_vals),   max(time_vals)
    f_min, f_max = min(fid_vals),    max(fid_vals)

    def norm(v, lo, hi):
        return 0.0 if hi == lo else (v - lo) / (hi - lo)

    recommendations = []
    for hw_name, r in candidatos:
        q_norm = norm(r.total_physical_qubits, q_min, q_max)
        t_norm = norm(r.execution_time_us, t_min, t_max)
        f_norm = 1 - norm(r.fidelity_circuit, f_min, f_max)  # inverso: maior fid = menor custo

        score = (weight_qubits * q_norm
                 + weight_time * t_norm
                 + weight_fidelity * f_norm)

        # Bottleneck: qual fator domina?
        contributions = {
            "qubits":    weight_qubits * q_norm,
            "tempo":     weight_time * t_norm,
            "fidelidade":weight_fidelity * f_norm,
        }
        bottleneck = max(contributions, key=contributions.get)
        bottleneck_pct = contributions[bottleneck] / score * 100 if score > 0 else 0

        recommendations.append(Recommendation(
            rank=0,  # preenchido abaixo
            hardware=hw_name,
            code=r.code_name,
            total_physical_qubits=r.total_physical_qubits,
            execution_time_us=r.execution_time_us,
            fidelity_circuit=r.fidelity_circuit,
            score=score,
            bottleneck=f"{bottleneck} ({bottleneck_pct:.0f}% do score)",
        ))

    recommendations.sort(key=lambda x: x.score)
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
