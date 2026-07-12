"""
Testes reais do QEC Estimator — verificam física, não só aritmética.
Cada teste falha se o modelo produzir resultado fisicamente incorreto.
"""
import math, sys, unittest
sys.path.insert(0, '/home/claude/autoq_v2')

from qec_estimator import (
    _surface_code_model, _bacon_shor_model, _steane_model,
    extract_circuit_profile, estimate, compare,
    HardwareProfile, CircuitProfile
)
from qiskit import QuantumCircuit

IBM   = HardwareProfile("IBM",        t_gate_ns=50,    p_phys=0.001, topology="heavy-hex")
ION   = HardwareProfile("IonQ",       t_gate_ns=200e3, p_phys=0.0005,topology="all-to-all")
NISQ  = HardwareProfile("Fotônico",   t_gate_ns=1000,  p_phys=0.011, topology="linear")
IDEAL = HardwareProfile("Ideal",      t_gate_ns=1,     p_phys=0.0001,topology="all-to-all")


class TestSurfaceCodeModel(unittest.TestCase):

    def test_threshold_rejeitado(self):
        """p >= p_th deve levantar ValueError — não retornar número incorreto."""
        with self.assertRaises(ValueError):
            _surface_code_model(0.01, 1e-6)   # exatamente no threshold
        with self.assertRaises(ValueError):
            _surface_code_model(0.05, 1e-6)   # acima

    def test_d_impar(self):
        """Surface Code rotacionado requer d ímpar."""
        for p in [0.001, 0.003, 0.005, 0.007, 0.009]:
            d, *_ = _surface_code_model(p, 1e-6)
            self.assertEqual(d % 2, 1, f"d={d} deveria ser ímpar para p={p}")

    def test_d_minimo_3(self):
        """d mínimo é 3 — não existe Surface Code com d<3."""
        d, *_ = _surface_code_model(0.0001, 1e-3)  # p muito baixo → d pequeno
        self.assertGreaterEqual(d, 3)

    def test_p_L_abaixo_do_alvo(self):
        """p_L calculado deve ser <= p_L_target para garantir fidelidade."""
        for p_target in [1e-4, 1e-6, 1e-9, 1e-12]:
            d, _, _, p_L = _surface_code_model(0.001, p_target)
            self.assertLessEqual(p_L, p_target,
                f"p_L={p_L:.2e} > alvo={p_target:.2e} para p=0.001")

    def test_qubits_formula_fowler(self):
        """Qubits por lógico = 2d²-1 (Fowler 2012)."""
        d, q, *_ = _surface_code_model(0.001, 1e-6)
        self.assertEqual(q, 2*d**2 - 1)

    def test_maior_p_exige_maior_d(self):
        """Ruído maior → distância maior (monotonicidade)."""
        d1, *_ = _surface_code_model(0.001, 1e-8)
        d2, *_ = _surface_code_model(0.005, 1e-8)
        self.assertLess(d1, d2, "p maior deveria exigir d maior")


class TestBaconShorModel(unittest.TestCase):

    def test_threshold_rejeitado(self):
        with self.assertRaises(ValueError):
            _bacon_shor_model(0.008, 1e-6)
        with self.assertRaises(ValueError):
            _bacon_shor_model(0.02, 1e-6)

    def test_p_L_abaixo_do_alvo(self):
        for p_target in [1e-4, 1e-6, 1e-9]:
            d, _, _, p_L = _bacon_shor_model(0.001, p_target)
            self.assertLessEqual(p_L, p_target)

    def test_qubits_d_quadrado(self):
        """Bacon-Shor [[d²,1,d]]: qubits = d²."""
        d, q, *_ = _bacon_shor_model(0.001, 1e-6)
        self.assertEqual(q, d**2)

    def test_d_minimo_2(self):
        d, *_ = _bacon_shor_model(0.0001, 1e-2)
        self.assertGreaterEqual(d, 2)


class TestSteaneModel(unittest.TestCase):

    def test_threshold_rejeitado(self):
        with self.assertRaises(ValueError):
            _steane_model(0.007, 1e-6)

    def test_distancia_fixa_3(self):
        """Steane [[7,1,3]] tem d=3 fixo."""
        d, q, ov, p_L = _steane_model(0.001, 1e-3)
        self.assertEqual(d, 3)
        self.assertEqual(q, 13)  # 7 data + 6 ancilla

    def test_alvo_muito_baixo_rejeitado(self):
        """Se p_L = 21*p² > p_L_target, deve rejeitar."""
        with self.assertRaises(ValueError):
            _steane_model(0.001, 1e-10)  # 21*(0.001)² = 2.1e-5 >> 1e-10


class TestCircuitProfile(unittest.TestCase):

    def test_bell_state(self):
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0,1)
        prof = extract_circuit_profile(qc)
        self.assertEqual(prof.n_logical_qubits, 2)
        self.assertEqual(prof.n_logical_gates, 2)
        self.assertGreater(prof.n_physical_gates, 0)
        self.assertGreater(prof.depth_physical, 0)

    def test_circuito_vazio_detectado(self):
        """Circuito de 400×H(i%14) colapsa para ~8 portas — não deve dar 400."""
        qc = QuantumCircuit(14)
        for i in range(400): qc.h(i % 14)
        prof = extract_circuit_profile(qc)
        self.assertLess(prof.n_physical_gates, 20,
            "400 H em 14 qubits devem colapsar — não são 400 portas reais")

    def test_portas_cx_contadas(self):
        qc = QuantumCircuit(3)
        qc.cx(0,1); qc.cx(1,2); qc.cx(0,2)
        prof = extract_circuit_profile(qc)
        self.assertEqual(prof.cx_count, 3)


class TestEstimate(unittest.TestCase):

    def test_nisq_acima_threshold_inviavel(self):
        """p=1.1% (NISQ fotônico) deve ser inviável para todos os códigos."""
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0,1)
        prof = extract_circuit_profile(qc)
        results = estimate(prof, NISQ, fidelity_target=0.99)
        for r in results:
            self.assertFalse(r.feasible,
                f"{r.code_name} não deveria ser viável com p=1.1%")

    def test_ibm_viavel(self):
        """IBM p=0.1% deve ter ao menos Surface Code viável."""
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0,1)
        prof = extract_circuit_profile(qc)
        results = estimate(prof, IBM, fidelity_target=0.99)
        viaveis = [r for r in results if r.feasible]
        self.assertGreater(len(viaveis), 0)

    def test_fidelidade_circuito_dentro_alvo(self):
        """Para códigos viáveis, fidelidade_circuito >= fidelidade_target."""
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0,1)
        prof = extract_circuit_profile(qc)
        results = estimate(prof, IBM, fidelity_target=0.99)
        for r in results:
            if r.feasible:
                self.assertGreaterEqual(r.fidelity_circuit, 0.99,
                    f"{r.code_name} tem fidelidade {r.fidelity_circuit:.4f} < 0.99")

    def test_mais_qubits_com_mais_ruido(self):
        """Hardware mais ruidoso deve precisar de mais qubits para mesmo alvo."""
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0,1)
        prof = extract_circuit_profile(qc)
        hw_limpo  = HardwareProfile("clean", t_gate_ns=50, p_phys=0.001, topology="grid")
        hw_ruidoso= HardwareProfile("noisy", t_gate_ns=50, p_phys=0.005, topology="grid")
        r_limpo  = next(r for r in estimate(prof, hw_limpo,  0.99) if r.code_name=="Surface Code" and r.feasible)
        r_ruidoso= next(r for r in estimate(prof, hw_ruidoso, 0.99) if r.code_name=="Surface Code" and r.feasible)
        self.assertLess(r_limpo.total_physical_qubits, r_ruidoso.total_physical_qubits,
            "Hardware mais ruidoso deve exigir mais qubits (d maior)")

    def test_circuito_vazio_levanta_erro(self):
        """Circuito destruído pelo transpile (0 portas) deve levantar ValueError."""
        prof = CircuitProfile(n_logical_qubits=2, n_logical_gates=0,
                              n_physical_gates=0, depth_physical=0,
                              t_count=0, cx_count=0)
        with self.assertRaises(ValueError):
            estimate(prof, IBM, fidelity_target=0.99)

    def test_tempo_escala_com_t_gate(self):
        """Hardware 10× mais lento → tempo 10× maior."""
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0,1)
        prof = extract_circuit_profile(qc)
        hw_rapido = HardwareProfile("fast", t_gate_ns=50,  p_phys=0.001, topology="grid")
        hw_lento  = HardwareProfile("slow", t_gate_ns=500, p_phys=0.001, topology="grid")
        r_rapido = next(r for r in estimate(prof, hw_rapido, 0.99) if r.code_name=="Surface Code" and r.feasible)
        r_lento  = next(r for r in estimate(prof, hw_lento,  0.99) if r.code_name=="Surface Code" and r.feasible)
        ratio = r_lento.execution_time_us / r_rapido.execution_time_us
        self.assertAlmostEqual(ratio, 10.0, places=5,
            msg=f"Esperado ratio=10, obtido {ratio:.4f}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
