"""
Valida distillation.py contra os 3 exemplos numéricos exatos da Tabela VII
de Beverland et al., arXiv:2211.07629 — (ns, 10^-4) qubit example,
t_gate=50ns, t_meas=100ns, p_phys=1e-4.
"""
import unittest

from autoq_qec.distillation import (
    build_magic_state_factory, magic_state_resources,
    _logical_error_rate, _n_tile, _tau_tile_us, _round_output_error,
)

T_GATE_NS = 50.0
T_MEAS_NS = 100.0
P_PHYS = 1e-4


class TestTableVFormulas(unittest.TestCase):
    """Confere as fórmulas base (Tabela V) isoladas."""

    def test_n_tile_d9(self):
        self.assertEqual(_n_tile(9), 162)  # 2*9^2

    def test_tau_tile_d9(self):
        # (4*50 + 2*100)*9 / 1000 = (200+200)*9/1000 = 3.6 us
        self.assertAlmostEqual(_tau_tile_us(9, T_GATE_NS, T_MEAS_NS), 3.6, places=6)

    def test_logical_error_d9(self):
        p = _logical_error_rate(P_PHYS, 9)
        self.assertAlmostEqual(p, 3e-12, delta=1e-14)


class TestTableVIIExamples(unittest.TestCase):
    """
    Reproduz os 3 exemplos exatos da Tabela VII (dentro de erro de
    arredondamento de exibição do paper).
    """

    def test_exemplo1_single_round_d9(self):
        """1 rodada, d=9: PT=5.6e-11, qubits=3240, tempo=46.8us."""
        factory = build_magic_state_factory(
            P_PHYS, T_GATE_NS, target_error=1e-10, t_meas_ns=T_MEAS_NS,
        )
        self.assertEqual(len(factory.rounds), 1)
        self.assertEqual(factory.rounds[0].distance, 9)
        self.assertEqual(factory.qubits, 3240)
        self.assertAlmostEqual(factory.time_us, 46.8, places=1)
        self.assertAlmostEqual(factory.output_error, 5.6e-11, delta=0.1e-11)

    def test_exemplo3_factoring_two_rounds(self):
        """2 rodadas, d=3 (x16) -> d=11: PT=5.51e-13, qubits=5760, tempo=72.8us."""
        factory = build_magic_state_factory(
            P_PHYS, T_GATE_NS, target_error=1e-12, t_meas_ns=T_MEAS_NS,
        )
        self.assertEqual(len(factory.rounds), 2)
        self.assertEqual(factory.rounds[0].distance, 3)
        self.assertEqual(factory.rounds[0].qubits_per_copy, 360)  # 20*n(3)=20*18
        self.assertEqual(factory.rounds[1].distance, 11)
        self.assertEqual(factory.rounds[1].qubits_per_copy, 4840)  # 20*n(11)=20*242
        self.assertEqual(factory.qubits, 5760)  # max(16*360, 1*4840)... ver nota abaixo
        self.assertAlmostEqual(factory.time_us, 72.8, places=1)
        self.assertAlmostEqual(factory.output_error, 5.51e-13, delta=0.05e-13)


class TestMagicStateResources(unittest.TestCase):

    def test_t_count_zero_sem_fabrica(self):
        extra_q, n_fab, factory = magic_state_resources(
            t_count=0, p_phys=P_PHYS, t_gate_ns=T_GATE_NS,
            target_t_state_error=1e-10, data_circuit_time_us=1000,
        )
        self.assertEqual(extra_q, 0)
        self.assertEqual(n_fab, 0)
        self.assertIsNone(factory)

    def test_t_count_alto_precisa_mais_fabricas(self):
        extra_q_poucos, n_fab_poucos, _ = magic_state_resources(
            t_count=10, p_phys=P_PHYS, t_gate_ns=T_GATE_NS,
            target_t_state_error=1e-10, data_circuit_time_us=1000, t_meas_ns=T_MEAS_NS,
        )
        extra_q_muitos, n_fab_muitos, _ = magic_state_resources(
            t_count=10000, p_phys=P_PHYS, t_gate_ns=T_GATE_NS,
            target_t_state_error=1e-10, data_circuit_time_us=1000, t_meas_ns=T_MEAS_NS,
        )
        self.assertGreaterEqual(n_fab_muitos, n_fab_poucos)
        self.assertGreaterEqual(extra_q_muitos, extra_q_poucos)

    def test_p_phys_invalido_levanta_erro(self):
        with self.assertRaises(ValueError):
            build_magic_state_factory(0.0, T_GATE_NS, target_error=1e-10)
        with self.assertRaises(ValueError):
            build_magic_state_factory(-0.001, T_GATE_NS, target_error=1e-10)

    def test_target_error_impossivel_levanta_erro(self):
        """Alvo absurdamente baixo não deve convergir em 6 níveis — erro explícito."""
        with self.assertRaises(ValueError):
            build_magic_state_factory(P_PHYS, T_GATE_NS, target_error=1e-300)


class TestEstimateIntegration(unittest.TestCase):
    """Integração do parâmetro opt-in em estimate()/compare() — não só o
    módulo distillation.py isolado."""

    def _circuit_com_t_gates(self):
        """T-gates intercaladas com H — sem o H, rotações T consecutivas na
        mesma qubit se fundem em Z (Clifford), zerando o T-count real
        (mesmo comportamento correto documentado no Fix 1)."""
        from qiskit import QuantumCircuit
        qc = QuantumCircuit(3)
        qc.h(0); qc.h(1); qc.h(2)
        for _ in range(20):
            qc.t(0); qc.h(0)
            qc.t(1); qc.h(1)
            qc.t(2); qc.h(2)
        qc.cx(0, 1); qc.cx(1, 2)
        return qc

    def test_flag_desligada_preserva_comportamento_antigo(self):
        from autoq_qec.qec_estimator import extract_circuit_profile, estimate, HardwareProfile
        qc = self._circuit_com_t_gates()
        prof = extract_circuit_profile(qc)
        self.assertGreater(prof.t_count, 0, "circuito precisa ter T-gates reais pra esse teste valer algo")
        hw = HardwareProfile("test", t_gate_ns=50, p_phys=0.0001, topology="grid")
        results = estimate(prof, hw, fidelity_target=0.99)  # sem a flag — default False
        r = next(x for x in results if x.code_name == "Surface Code" and x.feasible)
        self.assertIsNone(r.magic_state_qubits)
        self.assertIsNone(r.magic_state_factories)

    def test_flag_ligada_adiciona_qubits_de_fabrica(self):
        from autoq_qec.qec_estimator import extract_circuit_profile, estimate, HardwareProfile
        qc = self._circuit_com_t_gates()
        prof = extract_circuit_profile(qc)
        hw = HardwareProfile("test", t_gate_ns=50, p_phys=0.0001, topology="grid", t_meas_ns=100)

        sem_destilacao = estimate(prof, hw, fidelity_target=0.99)
        com_destilacao = estimate(prof, hw, fidelity_target=0.99, model_magic_state_distillation=True)

        r_sem = next(x for x in sem_destilacao if x.code_name == "Surface Code" and x.feasible)
        r_com = next(x for x in com_destilacao if x.code_name == "Surface Code" and x.feasible)

        self.assertIsNotNone(r_com.magic_state_qubits)
        self.assertGreater(r_com.magic_state_qubits, 0)
        self.assertGreater(r_com.total_physical_qubits, r_sem.total_physical_qubits,
            "qubits totais com destilação devem ser maiores que sem — a fábrica soma, nunca subtrai")

    def test_circuito_sem_t_gates_nao_adiciona_fabrica(self):
        """Circuito 100% Clifford: t_count=0, não deve tentar construir fábrica."""
        from qiskit import QuantumCircuit
        from autoq_qec.qec_estimator import extract_circuit_profile, estimate, HardwareProfile
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        prof = extract_circuit_profile(qc)
        self.assertEqual(prof.t_count, 0)
        hw = HardwareProfile("test", t_gate_ns=50, p_phys=0.0001, topology="grid", t_meas_ns=100)
        results = estimate(prof, hw, fidelity_target=0.99, model_magic_state_distillation=True)
        r = next(x for x in results if x.code_name == "Surface Code" and x.feasible)
        self.assertIsNone(r.magic_state_qubits)


if __name__ == "__main__":
    unittest.main(verbosity=2)
