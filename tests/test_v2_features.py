"""
Testes do v2.0.0 — Fix 1 (T-count), Fix 2 (overhead d³), Fix 3 (filtro T1),
Floquet Code e Algorithm Estimator.
"""
import math
import unittest

from qiskit import QuantumCircuit

from autoq_qec.qec_estimator import (
    extract_circuit_profile, estimate, compare,
    _surface_code_model, _floquet_code_model,
    HardwareProfile,
)
from autoq_qec.recommender import rank
from autoq_qec.real_hardware import HARDWARE_PROFILES
from autoq_qec.algorithm_estimator import AlgorithmEstimator


class TestFix1TCount(unittest.TestCase):

    def test_bell_state_clifford_puro(self):
        """H+CX são Clifford: t_count deve ser 0."""
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        prof = extract_circuit_profile(qc)
        self.assertEqual(prof.t_count, 0,
            f"Bell state não tem T-gates, obtido {prof.t_count}")

    def test_h_s_cx_clifford_puro(self):
        """H, S, CX são todos Clifford: t_count deve ser 0."""
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1); qc.s(0)
        prof = extract_circuit_profile(qc)
        self.assertEqual(prof.t_count, 0)

    def test_t_gate_unico_contado(self):
        """Um T-gate isolado: t_count deve ser 1."""
        qc = QuantumCircuit(1); qc.t(0)
        prof = extract_circuit_profile(qc)
        self.assertEqual(prof.t_count, 1)

    def test_h_t_cx_tem_um_t(self):
        """H+T+CX: apenas 1 T-gate real."""
        qc = QuantumCircuit(2); qc.h(0); qc.t(0); qc.cx(0, 1)
        prof = extract_circuit_profile(qc)
        self.assertEqual(prof.t_count, 1)

    def test_tdg_contado(self):
        """T† também é T-gate: deve contar."""
        qc = QuantumCircuit(1); qc.tdg(0)
        prof = extract_circuit_profile(qc)
        self.assertEqual(prof.t_count, 1)

    def test_t_tdg_cancela(self):
        """T seguido de T† cancela para identidade: t_count deve ser 0."""
        qc = QuantumCircuit(1); qc.t(0); qc.tdg(0)
        prof = extract_circuit_profile(qc)
        self.assertEqual(prof.t_count, 0)


class TestFix2GateOverhead(unittest.TestCase):

    def test_overhead_e_d_cubico_no_resultado_final(self):
        """
        CodeResult.gate_overhead_per_logical (o que o usuário final vê,
        via estimate()) deve ser d³, não d nem d² — testa o pipeline
        completo, não só _surface_code_model() isolado.
        """
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        prof = extract_circuit_profile(qc)
        hw = HardwareProfile("test", t_gate_ns=100, p_phys=0.001, topology="grid")
        results = estimate(prof, hw, fidelity_target=0.99)
        sc = next(r for r in results if r.code_name == "Surface Code")
        self.assertEqual(sc.gate_overhead_per_logical, sc.distance**3,
            f"Esperado d³={sc.distance**3}, obtido {sc.gate_overhead_per_logical}")

    def test_qubit_count_inalterado(self):
        """Qubits por lógico = 2d²-1: não muda com este fix."""
        d, q, _, _ = _surface_code_model(0.001, 1e-6)
        self.assertEqual(q, 2*d**2 - 1)

    def test_tempo_escala_corretamente_com_hardware(self):
        """t_circuit ∝ gate_overhead × n_gates × t_gate — razão de tempo não muda com o fix."""
        hw1 = HardwareProfile("fast", t_gate_ns=50,  p_phys=0.001, topology="grid")
        hw2 = HardwareProfile("slow", t_gate_ns=500, p_phys=0.001, topology="grid")
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        prof = extract_circuit_profile(qc)
        r1 = next(r for r in estimate(prof, hw1, 0.99)
                  if r.code_name == "Surface Code" and r.feasible)
        r2 = next(r for r in estimate(prof, hw2, 0.99)
                  if r.code_name == "Surface Code" and r.feasible)
        ratio = r2.execution_time_us / r1.execution_time_us
        self.assertAlmostEqual(ratio, 10.0, places=5)


class TestFix3T1Filter(unittest.TestCase):

    def test_eagle_excluido_para_circuito_profundo(self):
        """Eagle T1=198µs: excluído quando t_circuit >> T1, mesmo nomeando
        o HardwareProfile diferente da chave de HARDWARE_PROFILES (como no
        README, que usa 'IBM_Eagle' em vez de 'IBM_Eagle_r3')."""
        qc = QuantumCircuit(3)
        for _ in range(50):
            qc.h(0); qc.cx(0, 1); qc.cx(1, 2)
        eagle_hw = HardwareProfile(
            "IBM_Eagle", t_gate_ns=391, p_phys=0.0062, topology="heavy-hex"
        )
        result = compare(qc, [eagle_hw], fidelity_target=0.99)
        recs = rank(result, hardware_calibrations=HARDWARE_PROFILES)
        eagle_recs = [r for r in recs if "IBM_Eagle" in r.hardware]
        self.assertEqual(len(eagle_recs), 0,
            "IBM Eagle deve ser excluído: t_circuit >> T1")

    def test_quantinuum_sempre_viavel(self):
        """Quantinuum T1~horas: nunca excluído por T1."""
        qc = QuantumCircuit(3)
        for _ in range(50):
            qc.h(0); qc.cx(0, 1); qc.cx(1, 2)
        h2_hw = HardwareProfile(
            "Quantinuum_H2", t_gate_ns=1e5, p_phys=0.00029, topology="all-to-all"
        )
        result = compare(qc, [h2_hw], fidelity_target=0.99)
        recs = rank(result, hardware_calibrations=HARDWARE_PROFILES)
        self.assertGreater(len(recs), 0,
            "Quantinuum deve sempre ter candidatos viáveis")

    def test_razao_t1_calculada_corretamente(self):
        """t1_constraint() deve retornar ratio correto."""
        eagle = HARDWARE_PROFILES["IBM_Eagle_r3"]
        check = eagle.t1_constraint(n_physical_gates=147, gate_overhead=1331)
        self.assertIn("ratio", check)
        self.assertGreater(check["ratio"], 1)

    def test_sem_calibracao_nao_filtra(self):
        """Sem calibrações, rank() não filtra por T1 (backward compat.)."""
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        hw = HardwareProfile("generico", t_gate_ns=391, p_phys=0.001, topology="grid")
        result = compare(qc, [hw], 0.99)
        recs = rank(result, hardware_calibrations=None)
        self.assertGreater(len(recs), 0)


class TestFeature4FloquetCode(unittest.TestCase):

    def test_threshold_rejeitado(self):
        with self.assertRaises(ValueError):
            _floquet_code_model(0.01, 1e-6)
        with self.assertRaises(ValueError):
            _floquet_code_model(0.05, 1e-6)

    def test_d_impar(self):
        for p in [0.001, 0.003, 0.005, 0.009]:
            d, *_ = _floquet_code_model(p, 1e-6)
            self.assertEqual(d % 2, 1, f"d={d} deve ser ímpar para p={p}")

    def test_p_L_abaixo_do_alvo(self):
        for p_target in [1e-4, 1e-6, 1e-9]:
            _, _, _, p_L = _floquet_code_model(0.001, p_target)
            self.assertLessEqual(p_L, p_target)

    def test_qubit_formula_correta(self):
        """q = 4d² + 8(d-1) — Gidney & Fowler 2022."""
        d, q, _, _ = _floquet_code_model(0.001, 1e-6)
        self.assertEqual(q, 4*d**2 + 8*(d-1))

    def test_overhead_menor_que_surface(self):
        """Floquet overhead d/2 < Surface overhead d³ (pós-fix)."""
        _, _, ov_fl, _ = _floquet_code_model(0.001, 1e-6)
        d_sc, _, _, _ = _surface_code_model(0.001, 1e-6)
        self.assertLess(ov_fl, d_sc**3,
            "Floquet deve ter overhead de tempo menor que Surface Code")

    def test_floquet_aparece_no_compare(self):
        """Floquet Code deve aparecer no output de compare()."""
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        hw = [HardwareProfile("IBM", t_gate_ns=391, p_phys=0.001, topology="grid")]
        result = compare(qc, hw, 0.99)
        codes = [r.code_name for results in result["results"].values()
                 for r in results]
        self.assertIn("Floquet Code", codes)


class TestFeature7AlgorithmEstimator(unittest.TestCase):

    def test_shor_N_invalido_rejeitado(self):
        """N<=2 não tem fatoração não-trivial: deve levantar ValueError,
        não devolver um t_count fixo e plausível (achado na auditoria v2)."""
        for N in [2, 1, 0, -5]:
            with self.assertRaises(ValueError):
                AlgorithmEstimator.shor(N)

    def test_grover_N_invalido_rejeitado(self):
        """N<=1 não tem busca não-trivial: deve levantar ValueError."""
        for N in [1, 0, -3]:
            with self.assertRaises(ValueError):
                AlgorithmEstimator.grover(N)

    def test_shor_escala_cubica(self):
        e1 = AlgorithmEstimator.shor(15)    # n=4
        e2 = AlgorithmEstimator.shor(255)   # n=8
        ratio = e2.t_count_estimate / e1.t_count_estimate
        self.assertAlmostEqual(ratio, (8/4)**3, delta=1)

    def test_shor_n15_ordem_grandeza(self):
        """Shor N=15: estimativa deve estar dentro de ±10× do real (6057)."""
        est = AlgorithmEstimator.shor(15)
        real = 6057
        self.assertGreater(est.t_count_estimate, real / 10)
        self.assertLess(est.t_count_estimate, real * 10)

    def test_grover_escala_corretamente(self):
        """
        A razão de T-count entre dois N não é só √(N2/N1): a fórmula usa
        t_per_iter=7n (n=⌈log2 N⌉), que também cresce com N. A razão
        correta é (n2·it2)/(n1·it1), não apenas √(N2/N1). Re-derivamos a
        partir da definição para não assumir uma escala fisicamente errada
        (√N puro) como o teste original do V2_RELEASE.md fazia — aquele
        teste falharia por assumir só a escala com as iterações.
        """
        for N1, N2 in [(100, 400), (256, 1024)]:
            e1 = AlgorithmEstimator.grover(N1)
            e2 = AlgorithmEstimator.grover(N2)
            n1 = math.ceil(math.log2(N1)); it1 = math.ceil(math.pi/4*math.sqrt(N1))
            n2 = math.ceil(math.log2(N2)); it2 = math.ceil(math.pi/4*math.sqrt(N2))
            expected_ratio = (n2 * it2) / (n1 * it1)
            ratio = e2.t_count_estimate / e1.t_count_estimate
            self.assertAlmostEqual(ratio, expected_ratio, places=6)
            self.assertGreater(e2.t_count_estimate, e1.t_count_estimate)

    def test_qft_escala_quadratica(self):
        e1 = AlgorithmEstimator.qft(4)
        e2 = AlgorithmEstimator.qft(8)
        ratio = e2.t_count_estimate / e1.t_count_estimate
        self.assertAlmostEqual(ratio, 4.0, delta=0.5)

    def test_incerteza_documentada(self):
        for est in [
            AlgorithmEstimator.shor(15),
            AlgorithmEstimator.grover(1000),
            AlgorithmEstimator.qft(10),
            AlgorithmEstimator.vqe(10, 5),
        ]:
            self.assertIn("×", est.t_count_uncertainty)
            self.assertGreater(len(est.notes), 10)

    def test_qubits_logicos_razoaveis(self):
        for est in [
            AlgorithmEstimator.shor(2048),
            AlgorithmEstimator.grover(1000000),
        ]:
            self.assertGreater(est.n_logical_qubits, 0)
            self.assertLess(est.n_logical_qubits, 10000)


class TestFeature56Hardware(unittest.TestCase):

    def test_willow_existe(self):
        self.assertIn("Google_Willow", HARDWARE_PROFILES)

    def test_heron_r3_existe(self):
        self.assertIn("IBM_Heron_r3", HARDWARE_PROFILES)

    def test_willow_parametros_bounds(self):
        w = HARDWARE_PROFILES["Google_Willow"]
        self.assertEqual(w.n_qubits, 105)
        self.assertLess(w.p_2q_mean, 0.005)    # paper: ~0.3%
        self.assertGreater(w.T1_us, 80)         # paper: ~100µs
        self.assertLessEqual(w.t_2q_ns, 50)     # paper: ~25ns

    def test_heron_r3_melhor_que_r2(self):
        """Heron r3 deve ter menor p_2q e maior velocidade que Heron r2."""
        r2 = HARDWARE_PROFILES["IBM_Heron_r2"]
        r3 = HARDWARE_PROFILES["IBM_Heron_r3"]
        self.assertLess(r3.p_2q_mean, r2.p_2q_mean)
        self.assertLessEqual(r3.t_2q_ns, r2.t_2q_ns)

    def test_willow_integravel_no_compare(self):
        """Willow deve funcionar como hardware no compare()."""
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        w = HARDWARE_PROFILES["Google_Willow"]
        hw = HardwareProfile(w.name, w.t_2q_ns, w.p_phys, w.topology)
        result = compare(qc, [hw], 0.99)
        self.assertIn(w.name, result["results"])


class TestFeature8Visualizer(unittest.TestCase):

    def test_plot_gera_arquivo_png(self):
        from autoq_qec.visualizer import plot_tradeoff
        import tempfile, os
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        hw = [HardwareProfile("IBM", 391, 0.001, "heavy-hex"),
              HardwareProfile("H2", 1e5, 0.00029, "all-to-all")]
        result = compare(qc, hw, 0.99)
        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "test.png")
            plot_tradeoff(result, output=output)
            self.assertTrue(os.path.exists(output))
            self.assertGreater(os.path.getsize(output), 5000)

    def test_sem_combinacoes_viaveis_levanta_erro(self):
        from autoq_qec.visualizer import plot_tradeoff
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        hw = [HardwareProfile("ruim", t_gate_ns=1000, p_phys=0.02, topology="linear")]
        result = compare(qc, hw, 0.99)
        with self.assertRaises(ValueError):
            plot_tradeoff(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
