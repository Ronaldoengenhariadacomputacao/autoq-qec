"""
AutoQ QEC — Algorithm Estimator
Estimativas analíticas de T-count para algoritmos quânticos conhecidos.
ATENÇÃO: estimativas de ordem de grandeza. Usar circuito real quando possível.
"""
import math
from dataclasses import dataclass


@dataclass
class AlgorithmEstimate:
    algorithm: str
    n_logical_qubits: int
    t_count_estimate: int
    t_count_uncertainty: str   # "±5×" ou "±2×"
    source: str
    notes: str


class AlgorithmEstimator:

    @staticmethod
    def shor(N: int) -> AlgorithmEstimate:
        """
        Shor factoring de N.
        T-count ≈ 20n³ onde n = ⌈log₂N⌉.
        Fonte: Beauregard (2003) + síntese de portas fault-tolerant.
        Incerteza: ±5× dependendo da implementação de aritmética modular
        (verificado contra Shor N=15 real: fórmula subestima ~4,7×).
        """
        if N <= 2:
            raise ValueError(
                f"Shor requer N > 2 (N={N} não tem fatoração não-trivial a estimar)"
            )
        n = math.ceil(math.log2(N))
        t_count = 20 * n**3
        return AlgorithmEstimate(
            algorithm=f"Shor N={N}",
            n_logical_qubits=2*n + 3,
            t_count_estimate=t_count,
            t_count_uncertainty="±5×",
            source="Beauregard, QIC 3:175 (2003); Fowler gate synthesis",
            notes=f"n={n} bits. Implementações simples podem ter até 5× mais T-gates.",
        )

    @staticmethod
    def grover(N: int) -> AlgorithmEstimate:
        """
        Grover search em N itens.
        T-count ≈ 7n por iteração × ⌈π/4·√N⌉ iterações, com n=⌈log₂N⌉.
        Nota: como n cresce com log₂N, o T-count total escala com √N·log₂N,
        não apenas √N — o fator log₂N vem do custo do oracle genérico por
        iteração, não só do número de iterações.
        Fonte: estimativa com oracle genérico.
        """
        if N <= 1:
            raise ValueError(f"Grover requer N > 1 itens de busca (N={N})")
        n = math.ceil(math.log2(N))
        iterations = math.ceil(math.pi/4 * math.sqrt(N))
        t_per_iter = 7 * n
        t_count = t_per_iter * iterations
        return AlgorithmEstimate(
            algorithm=f"Grover N={N}",
            n_logical_qubits=n + 1,
            t_count_estimate=t_count,
            t_count_uncertainty="±10×",
            source="Estimativa com oracle genérico de n T-gates",
            notes="Depende fortemente do oracle. Incerteza alta sem oracle específico.",
        )

    @staticmethod
    def qft(n: int) -> AlgorithmEstimate:
        """
        QFT em n qubits.
        T-count ≈ n²/2 (rotações CP com síntese Solovay-Kitaev).
        """
        t_count = n*n // 2
        return AlgorithmEstimate(
            algorithm=f"QFT n={n}",
            n_logical_qubits=n,
            t_count_estimate=t_count,
            t_count_uncertainty="±2×",
            source="Rotações CP decompostas em Clifford+T",
            notes="CP(π/2^k) para k>2 requer síntese com T-gates.",
        )

    @staticmethod
    def vqe(n_qubits: int, depth: int) -> AlgorithmEstimate:
        """
        VQE com n_qubits e profundidade depth.
        T-count ≈ 4 · n · depth (Trotterizado).
        """
        t_count = 4 * n_qubits * depth
        return AlgorithmEstimate(
            algorithm=f"VQE n={n_qubits} d={depth}",
            n_logical_qubits=n_qubits,
            t_count_estimate=t_count,
            t_count_uncertainty="±3×",
            source="Hamiltoniano Trotterizado com RZZ gates",
            notes="Depende do Hamiltoniano. Incerteza moderada.",
        )
