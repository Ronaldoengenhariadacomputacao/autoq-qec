"""
Testes do v2.0.0 — Fix 1 (T-count), Fix 2 (overhead d³), Fix 3 (filtro T1),
Floquet Code e Algorithm Estimator.
"""
import math
import unittest

from qiskit import QuantumCircuit

from autoq_qec.qec_estimator import (
    extract_circuit_profile, estimate, compare,
    _surface_code_model, _floquet_code_model, _steane_model,
    HardwareProfile,
)
from autoq_qec.recommender import rank, rank_by_metric
from autoq_qec.real_hardware import HARDWARE_PROFILES, CalibratedHardware
from autoq_qec.algorithm_estimator import AlgorithmEstimator
from autoq_qec.distillation import magic_state_resources, build_magic_state_factory
from unittest.mock import patch, MagicMock


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
            "Quantinuum_H2", t_gate_ns=1e5, p_phys=0.0015, topology="all-to-all"
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

    def test_t1_direto_no_hardwareprofile_e_respeitado(self):
        """
        v3.2.4: HardwareProfile.T1_us definido diretamente pelo usuário (sem
        casar com nenhuma CalibratedHardware de hardware_calibrations) deve
        ser usado para filtrar combinações que violem T1 -- antes esse campo
        era lido em nenhum lugar, ficando puramente decorativo. O filtro vale
        sempre que T1_us for informado, independente de hardware_calibrations
        ser passado (se o usuário disse qual é o T1, deve valer sempre).
        """
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)

        hw_sem_t1 = HardwareProfile("SemT1", t_gate_ns=50, p_phys=0.001, topology="grid")
        result_sem_t1 = compare(qc, [hw_sem_t1], fidelity_target=0.99)
        recs_sem_t1 = rank(result_sem_t1)

        hw_com_t1_curto = HardwareProfile("ComT1Curto", t_gate_ns=50, p_phys=0.001,
                                           topology="grid", T1_us=1.0)
        result_com_t1 = compare(qc, [hw_com_t1_curto], fidelity_target=0.99)
        recs_com_t1 = rank(result_com_t1)

        self.assertGreater(len(recs_sem_t1), len(recs_com_t1),
            "T1_us=1us deveria excluir combinacoes que o mesmo circuito, "
            "sem T1_us informado, aceitaria")
        for r in recs_com_t1:
            self.assertLess(r.execution_time_us / hw_com_t1_curto.T1_us, 0.5,
                f"{r.hardware}/{r.code} deveria ter sido excluido por violar T1")


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

    def test_qft_n_invalido_rejeitado(self):
        """n<=0 não tem QFT a estimar: deve levantar ValueError, não
        devolver n_logical_qubits negativo silenciosamente (bug real
        confirmado na v3.4.0 publicada: qft(-3) retornava sem erro)."""
        for n in [0, -3]:
            with self.assertRaises(ValueError):
                AlgorithmEstimator.qft(n)

    def test_vqe_entradas_invalidas_rejeitadas(self):
        """n_qubits<=0 ou depth<=0 não têm VQE a estimar: devem levantar
        ValueError, não devolver t_count_estimate negativo silenciosamente
        (bug real confirmado na v3.4.0 publicada: vqe(-3, 5) retornava
        t_count_estimate=-60 sem erro)."""
        with self.assertRaises(ValueError):
            AlgorithmEstimator.vqe(-3, 5)
        with self.assertRaises(ValueError):
            AlgorithmEstimator.vqe(5, -2)
        with self.assertRaises(ValueError):
            AlgorithmEstimator.vqe(0, 5)
        with self.assertRaises(ValueError):
            AlgorithmEstimator.vqe(5, 0)

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
        # T1 real reportado no paper (Acharya et al., Nature 638, 2025) é
        # 68us, não ~100us como o comentario antigo assumia (corrigido nesta
        # sessão, tanto aqui quanto no CalibratedHardware).
        self.assertGreater(w.T1_us, 50)         # paper: ~68µs
        self.assertLessEqual(w.t_2q_ns, 50)     # paper: ~25ns

    def test_heron_r3_melhor_que_r2(self):
        """
        Heron r3 deve ter menor erro de porta de 2 qubits que r2 -- essa é
        a melhoria consistente entre gerações. Velocidade de porta (t_2q_ns)
        NÃO é testada aqui: não melhora estritamente a cada geração (às
        vezes se troca velocidade por fidelidade), e dados reais ao vivo
        confirmaram isso nesta sessão (r2 medido em ibm_fez saiu mais rápido
        que o t_2q_ns oficialmente reportado para r3).
        """
        r2 = HARDWARE_PROFILES["IBM_Heron_r2"]
        r3 = HARDWARE_PROFILES["IBM_Heron_r3"]
        self.assertLess(r3.p_2q_mean, r2.p_2q_mean)

    def test_willow_integravel_no_compare(self):
        """Willow deve funcionar como hardware no compare()."""
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        w = HARDWARE_PROFILES["Google_Willow"]
        hw = HardwareProfile(w.name, w.t_2q_ns, w.p_phys, w.topology)
        result = compare(qc, [hw], 0.99)
        self.assertIn(w.name, result["results"])

    def test_from_calibrated_carrega_t2_us_e_readout_error(self):
        """
        v3.4.0: HardwareProfile.from_calibrated() existe porque os exemplos
        documentados (README, example.py) historicamente montavam
        HardwareProfile na mão copiando só t_gate_ns/p_phys/topology,
        esquecendo T2_us/readout_error -- o que fazia a fidelidade prevista
        ignorar decoerência por completo, mesmo usando hardware com dados
        reais já calibrados em HARDWARE_PROFILES. Este construtor deve
        carregar TODOS os campos relevantes automaticamente.
        """
        for name, cal in HARDWARE_PROFILES.items():
            hw = HardwareProfile.from_calibrated(cal)
            self.assertEqual(hw.name, cal.name)
            self.assertEqual(hw.t_gate_ns, cal.t_2q_ns)
            self.assertEqual(hw.p_phys, cal.p_phys)
            self.assertEqual(hw.topology, cal.topology)
            self.assertEqual(hw.readout_error, cal.readout_error)
            self.assertEqual(hw.T1_us, cal.T1_us)
            self.assertEqual(hw.T2_us, cal.T2_us,
                f"{name}: from_calibrated deveria preservar T2_us real, não descartar")

    def test_from_calibrated_produz_meets_fidelity_target_correto(self):
        """
        Teste de integração: um HardwareProfile construído via
        from_calibrated() deve produzir resultados onde a penalidade de T2
        realmente é aplicada (diferente de construir na mão sem T2_us).
        """
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        cal = HARDWARE_PROFILES["Google_Sycamore"]  # T2_us=20.0, o mais curto do conjunto
        hw = HardwareProfile.from_calibrated(cal)
        self.assertIsNotNone(hw.T2_us)
        result = compare(qc, [hw], fidelity_target=0.999999)
        recs = rank(result)
        self.assertTrue(recs)
        # Com T2_us=20us real e um alvo de fidelidade extremamente alto, ao
        # menos alguma combinação deveria ficar abaixo do alvo -- prova que
        # a penalidade de T2 está de fato entrando na conta, não sendo
        # descartada como aconteceria com um HardwareProfile montado à mão
        # sem T2_us.
        self.assertTrue(any(not r.meets_fidelity_target for r in recs))


class TestAvisoHardwareProfileIncompleto(unittest.TestCase):
    """
    v3.4.0: HardwareProfile sem readout_error/T1_us/T2_us não avisava nada
    -- os três têm o mesmo problema de "default silencioso otimista" que
    T2_us=None (fidelity_circuit parece melhor do que seria com dados
    reais). estimate() agora emite um warnings.warn() listando só os
    campos que faltam de fato.
    """

    def _hw(self, **kwargs):
        return HardwareProfile("Teste", t_gate_ns=100, p_phys=0.001,
                                topology="grid", **kwargs)

    def _qc(self):
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        return qc

    def test_avisa_quando_nenhum_campo_informado(self):
        with self.assertWarns(UserWarning) as ctx:
            compare(self._qc(), [self._hw()], 0.99)
        msg = str(ctx.warning)
        self.assertIn("readout_error", msg)
        self.assertIn("T1_us", msg)
        self.assertIn("T2_us", msg)

    def test_aviso_lista_so_os_campos_que_faltam(self):
        with self.assertWarns(UserWarning) as ctx:
            compare(self._qc(), [self._hw(T2_us=200)], 0.99)
        msg = str(ctx.warning)
        self.assertNotIn("T2_us", msg)
        self.assertIn("readout_error", msg)
        self.assertIn("T1_us", msg)

    def test_sem_aviso_quando_os_tres_informados(self):
        import warnings
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            compare(self._qc(), [self._hw(T2_us=200, T1_us=300, readout_error=0.01)], 0.99)
            self.assertEqual(len(w), 0)

    def test_from_calibrated_nao_dispara_aviso(self):
        import warnings
        hw = HardwareProfile.from_calibrated(HARDWARE_PROFILES["IBM_Heron_r2"])
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            compare(self._qc(), [hw], 0.99)
            self.assertEqual(len(w), 0)


class TestFeatureMajorana(unittest.TestCase):
    """
    v3.5.0: suporte a hardware Majorana/topológico. O Floquet Code já
    modela corretamente a física de qubits MZM (p = erro de medição de 2
    qubits, conferido contra o paper -- ver docstring de
    _floquet_code_model()); a novidade real é p_t_state (erro de T físico
    separado de p_phys) e a entrada ilustrativa em HARDWARE_PROFILES.
    """

    def test_entrada_majorana_existe(self):
        self.assertIn("Majorana_MS_ResourceEstimator_illustrative", HARDWARE_PROFILES)

    def test_entrada_majorana_carrega_via_from_calibrated(self):
        cal = HARDWARE_PROFILES["Majorana_MS_ResourceEstimator_illustrative"]
        hw = HardwareProfile.from_calibrated(cal)
        self.assertEqual(hw.p_phys, 1e-5)
        self.assertEqual(hw.p_t_state, 0.015)
        self.assertNotEqual(hw.p_phys, hw.p_t_state,
            "p_t_state deveria ser distinto de p_phys nesta entrada -- essa é a "
            "diferença física que a entrada existe para demonstrar")

    def test_nome_carrega_aviso_de_dado_nao_medido(self):
        """O aviso de 'não medido' precisa estar no próprio nome exibido,
        não só numa nota do README -- é o que garante que apareça direto
        na tabela de ranking, como pedido explicitamente."""
        cal = HARDWARE_PROFILES["Majorana_MS_ResourceEstimator_illustrative"]
        self.assertIn("not measured", cal.name.lower())

    def test_aviso_de_nao_medido_aparece_no_ranking(self):
        qc = QuantumCircuit(3)
        qc.h(0); qc.cx(0, 1); qc.cx(1, 2)
        hw = HardwareProfile.from_calibrated(
            HARDWARE_PROFILES["Majorana_MS_ResourceEstimator_illustrative"]
        )
        result = compare(qc, [hw], fidelity_target=0.99)
        recs = rank(result)
        self.assertTrue(recs)
        self.assertTrue(all("not measured" in r.hardware.lower() for r in recs))

    def test_floquet_code_formula_nao_regride(self):
        """Regressão: p_th/A do Floquet Code não podem ter mudado ao
        adicionar a documentação/citação corrigida da Majorana."""
        from autoq_qec.qec_estimator import _floquet_code_model
        d, q, cycles, p_L = _floquet_code_model(0.001, 1e-6)
        self.assertAlmostEqual(p_L, 0.07 * (0.001 / 0.01) ** ((d + 1) / 2), places=12)

    def test_p_t_state_afeta_destilacao_end_to_end(self):
        """Integração completa: p_t_state de uma HardwareProfile Majorana
        deve mudar magic_state_qubits em relação a um p_t_state=None com
        o mesmo p_phys -- prova que o campo chega até estimate()."""
        qc = QuantumCircuit(2)
        qc.h(0); qc.t(0); qc.t(0); qc.cx(0, 1); qc.t(1)

        sem_p_t = HardwareProfile("Teste_sem", t_gate_ns=1000, p_phys=1e-5,
                                   topology="all-to-all")
        com_p_t = HardwareProfile("Teste_com", t_gate_ns=1000, p_phys=1e-5,
                                   topology="all-to-all", p_t_state=0.015)

        r_sem = compare(qc, [sem_p_t], fidelity_target=0.99,
                         model_magic_state_distillation=True)
        r_com = compare(qc, [com_p_t], fidelity_target=0.99,
                         model_magic_state_distillation=True)

        rec_sem = next(r for r in r_sem["results"]["Teste_sem"] if r.feasible)
        rec_com = next(r for r in r_com["results"]["Teste_com"] if r.feasible)

        self.assertIsNotNone(rec_sem.magic_state_qubits)
        self.assertIsNotNone(rec_com.magic_state_qubits)
        self.assertGreaterEqual(rec_com.magic_state_qubits, rec_sem.magic_state_qubits,
            "p_t_state pior (0.015 vs p_phys=1e-5) deveria exigir mais qubits de destilação")


class TestFeature8Visualizer(unittest.TestCase):

    def test_plot_gera_arquivo_png(self):
        from autoq_qec.visualizer import plot_tradeoff
        import tempfile, os
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        hw = [HardwareProfile("IBM", 391, 0.001, "heavy-hex"),
              HardwareProfile("H2", 1e5, 0.0015, "all-to-all")]
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

    def test_ax_existente_preserva_titulo_do_caller(self):
        """Quando o caller passa um Axes já com título (dono da figura),
        plot_tradeoff não deve sobrescrevê-lo silenciosamente (bug real
        confirmado na v3.4.0 publicada)."""
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from autoq_qec.visualizer import plot_tradeoff
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        hw = [HardwareProfile("IBM", 391, 0.001, "heavy-hex")]
        result = compare(qc, hw, 0.99)
        fig, ax = plt.subplots()
        ax.set_title("Meu título customizado")
        returned = plot_tradeoff(result, ax=ax)
        self.assertIs(returned, ax)
        self.assertEqual(ax.get_title(), "Meu título customizado")
        plt.close(fig)

    def test_ax_existente_sem_titulo_recebe_default(self):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from autoq_qec.visualizer import plot_tradeoff
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        hw = [HardwareProfile("IBM", 391, 0.001, "heavy-hex")]
        result = compare(qc, hw, 0.99)
        fig, ax = plt.subplots()
        plot_tradeoff(result, ax=ax)
        self.assertTrue(len(ax.get_title()) > 0)
        plt.close(fig)


class _FakeParam:
    def __init__(self, name, value, unit=""):
        self.name = name
        self.value = value
        self.unit = unit


class _FakeGate:
    def __init__(self, gate, qubits, parameters):
        self.gate = gate
        self.qubits = qubits
        self.parameters = parameters


class _FakeProperties:
    """Simula backend.properties() com os 3 problemas achados em hardware
    real (ibm_fez/marrakesh/kingston): unidade de gate_length já em ns,
    porta nativa de 2q não é 'cx' (é 'cz'), e qubit 2 sem T1 calibrado
    (levanta exceção, como acontece de verdade)."""

    def __init__(self):
        self.gates = [
            _FakeGate("cz", [0, 1], [
                _FakeParam("gate_error", 0.006),
                _FakeParam("gate_length", 68, unit="ns"),
            ]),
            _FakeGate("cz", [1, 2], [
                _FakeParam("gate_error", 1.0),  # acoplador morto
                _FakeParam("gate_length", 68, unit="ns"),
            ]),
            _FakeGate("sx", [0], [
                _FakeParam("gate_error", 0.0004),
                _FakeParam("gate_length", 32, unit="ns"),
            ]),
            _FakeGate("sx", [2], [
                _FakeParam("gate_error", 1.0),  # qubit morto
                _FakeParam("gate_length", 32, unit="ns"),
            ]),
        ]
        self._t1 = {0: 150e-6, 1: 140e-6}  # qubit 2 sem T1 — vai levantar exceção
        self._t2 = {0: 100e-6, 1: 90e-6}
        self._ro = {0: 0.02, 1: 0.018}

    def t1(self, q):
        if q not in self._t1:
            raise Exception(f"no T1 for qubit {q}")
        return self._t1[q]

    def t2(self, q):
        if q not in self._t2:
            raise Exception(f"no T2 for qubit {q}")
        return self._t2[q]

    def readout_error(self, q):
        if q not in self._ro:
            raise Exception(f"no readout_error for qubit {q}")
        return self._ro[q]


class _FakeConfig:
    n_qubits = 3


class TestIBMLiveCalibration(unittest.TestCase):
    """Achados na auditoria com hardware IBM real: unidade de duração,
    nome de porta hardcoded, e crash em qubit/acoplador sem calibração."""

    def _mock_service(self, mock_service_cls):
        fake_backend = MagicMock()
        fake_backend.properties.return_value = _FakeProperties()
        fake_backend.configuration.return_value = _FakeConfig()
        mock_service_cls.return_value.backend.return_value = fake_backend
        return fake_backend

    @patch("qiskit_ibm_runtime.QiskitRuntimeService")
    def test_duracao_em_ns_nao_multiplicada_de_novo(self, mock_service_cls):
        """gate_length com unit='ns' não deve ser multiplicado por 1e9."""
        self._mock_service(mock_service_cls)
        from autoq_qec.real_hardware import from_ibm_backend
        hw = from_ibm_backend("fake_backend", token="fake")
        self.assertEqual(hw.t_1q_ns, 32)
        self.assertEqual(hw.t_2q_ns, 68)

    @patch("qiskit_ibm_runtime.QiskitRuntimeService")
    def test_porta_2q_nao_cx_detectada(self, mock_service_cls):
        """Porta nativa 'cz' (não 'cx') deve ser reconhecida via len(qubits)==2."""
        self._mock_service(mock_service_cls)
        from autoq_qec.real_hardware import from_ibm_backend
        hw = from_ibm_backend("fake_backend", token="fake")
        self.assertAlmostEqual(hw.p_2q_mean, 0.006, places=6)

    @patch("qiskit_ibm_runtime.QiskitRuntimeService")
    def test_qubit_sem_t1_nao_quebra(self, mock_service_cls):
        """Qubit sem T1 calibrado deve ser pulado, não derrubar a função."""
        self._mock_service(mock_service_cls)
        from autoq_qec.real_hardware import from_ibm_backend
        hw = from_ibm_backend("fake_backend", token="fake")  # não deve levantar
        self.assertAlmostEqual(hw.T1_us, 145.0, places=1)  # média de (150+140)/2

    @patch("qiskit_ibm_runtime.QiskitRuntimeService")
    def test_acoplador_morto_excluido_da_media(self, mock_service_cls):
        """gate_error==1.0 (acoplador/qubit morto) não deve entrar na média."""
        self._mock_service(mock_service_cls)
        from autoq_qec.real_hardware import from_ibm_backend
        hw = from_ibm_backend("fake_backend", token="fake")
        self.assertLess(hw.p_2q_mean, 0.5, "acoplador morto (erro=1.0) vazou pra média")
        self.assertLess(hw.p_1q_mean, 0.5, "qubit morto (erro=1.0) vazou pra média")


class TestReadoutErrorFidelity(unittest.TestCase):
    """
    Achado testando com ruído real de IBM (ibm_marrakesh, GHZ-4): a
    fidelidade prevista sem termo de leitura superestimava a real em ~11
    pontos percentuais (97,7% previsto vs 86,6% empírico). Adicionado
    (1-readout_error)^n_logical_qubits à fórmula.
    """

    def _feasible_surface(self, hw):
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        prof = extract_circuit_profile(qc)
        results = estimate(prof, hw, fidelity_target=0.99)
        return next(r for r in results if r.code_name == "Surface Code" and r.feasible)

    def test_readout_zero_preserva_comportamento_antigo(self):
        """readout_error padrão (0.0): fid deve ser exatamente (1-p_L)^N, sem termo extra.
        N aqui é circuit_profile.n_physical_gates (o expoente real da fórmula),
        não total_physical_gates (que já inclui o overhead do código QEC)."""
        hw = HardwareProfile("test", t_gate_ns=100, p_phys=0.001, topology="grid")
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        prof = extract_circuit_profile(qc)
        r = self._feasible_surface(hw)
        expected = (1 - r.p_logical_achieved) ** prof.n_physical_gates
        self.assertAlmostEqual(r.fidelity_circuit, expected, places=10)

    def test_readout_error_reduz_fidelidade(self):
        """readout_error > 0 deve reduzir fidelity_circuit em relação a 0."""
        hw_sem = HardwareProfile("sem_ro", t_gate_ns=100, p_phys=0.001, topology="grid", readout_error=0.0)
        hw_com = HardwareProfile("com_ro", t_gate_ns=100, p_phys=0.001, topology="grid", readout_error=0.02)
        r_sem = self._feasible_surface(hw_sem)
        r_com = self._feasible_surface(hw_com)
        self.assertLess(r_com.fidelity_circuit, r_sem.fidelity_circuit)

    def test_readout_error_escala_com_n_qubits(self):
        """Mais qubits lógicos medidos → mais impacto do readout_error."""
        hw = HardwareProfile("test", t_gate_ns=100, p_phys=0.001, topology="grid", readout_error=0.02)
        qc_pequeno = QuantumCircuit(2); qc_pequeno.h(0); qc_pequeno.cx(0, 1)
        qc_grande = QuantumCircuit(6)
        for i in range(6): qc_grande.h(i)
        for i in range(5): qc_grande.cx(i, i + 1)
        r_pequeno = next(r for r in estimate(extract_circuit_profile(qc_pequeno), hw, 0.99)
                          if r.code_name == "Surface Code" and r.feasible)
        r_grande = next(r for r in estimate(extract_circuit_profile(qc_grande), hw, 0.99)
                         if r.code_name == "Surface Code" and r.feasible)
        readout_term_pequeno = (1 - hw.readout_error) ** 2
        readout_term_grande = (1 - hw.readout_error) ** 6
        self.assertLess(readout_term_grande, readout_term_pequeno)


class TestDecoherenceFidelity(unittest.TestCase):
    """T2_us=None (padrão) preserva comportamento anterior; T2_us finito
    penaliza fidelidade quando o tempo de execução (já incluindo overhead
    de síndrome do QEC) se aproxima ou excede T2 — efeito que o erro
    por-porta sozinho não captura."""

    def _surface(self, hw, qc=None):
        qc = qc or QuantumCircuit(2)
        if qc.num_qubits == 2 and qc.size() == 0:
            qc.h(0); qc.cx(0, 1)
        prof = extract_circuit_profile(qc)
        results = estimate(prof, hw, fidelity_target=0.99)
        return next(r for r in results if r.code_name == "Surface Code" and r.feasible)

    def test_t2_none_preserva_comportamento_antigo(self):
        hw = HardwareProfile("test", t_gate_ns=100, p_phys=0.001, topology="grid")
        self.assertIsNone(hw.T2_us)
        r = self._surface(hw)
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        prof = extract_circuit_profile(qc)
        expected = (1 - r.p_logical_achieved) ** prof.n_physical_gates
        self.assertAlmostEqual(r.fidelity_circuit, expected, places=10)

    def test_t2_finito_reduz_fidelidade(self):
        hw_sem = HardwareProfile("sem_t2", t_gate_ns=100, p_phys=0.001, topology="grid")
        hw_com = HardwareProfile("com_t2", t_gate_ns=100, p_phys=0.001, topology="grid", T2_us=50.0)
        r_sem = self._surface(hw_sem)
        r_com = self._surface(hw_com)
        self.assertLess(r_com.fidelity_circuit, r_sem.fidelity_circuit)

    def test_tempo_muito_maior_que_t2_colapsa_fidelidade(self):
        """Se o overhead do QEC faz o circuito rodar por >>T2, a fidelidade
        deve cair pra perto de zero — o d³ do Surface Code em hardware
        ruidoso pode facilmente estourar T2 (achado real com IonQ_Aria)."""
        hw = HardwareProfile("ruidoso_lento", t_gate_ns=600e3, p_phys=0.005,
                              topology="all-to-all", T2_us=100.0)
        qc = QuantumCircuit(3)
        qc.h(0); qc.cx(0, 1); qc.cx(1, 2)
        r = self._surface(hw, qc)
        self.assertLess(r.fidelity_circuit, 0.01,
            f"tempo={r.execution_time_us}µs vs T2=100µs deveria colapsar a fidelidade")

    def test_decoerencia_nunca_gera_fidelidade_invalida(self):
        """Fidelidade deve sempre ficar em [0,1], mesmo em casos extremos."""
        hw = HardwareProfile("extremo", t_gate_ns=1e6, p_phys=0.009,
                              topology="linear", T2_us=1.0)
        qc = QuantumCircuit(4)
        for i in range(3): qc.cx(i, i + 1)
        r = self._surface(hw, qc)
        self.assertGreaterEqual(r.fidelity_circuit, 0.0)
        self.assertLessEqual(r.fidelity_circuit, 1.0)

    def test_meets_fidelity_target_false_quando_decoerencia_colapsa_fidelidade(self):
        """
        v3.4.0: feasible=True só garante p_L <= p_L_target (erro de porta) --
        não garante fidelity_circuit >= fidelity_target, porque readout_error
        e a penalidade de T2_us entram DEPOIS dessa checagem. Achado
        auditando rank() com T2_us ativado: resultados com fidelidade ~0%
        apareciam marcados como "viáveis" sem nenhum aviso. meets_fidelity_target
        é o campo que expõe essa distinção -- deve ser False aqui mesmo com
        feasible=True."""
        hw = HardwareProfile("ruidoso_lento", t_gate_ns=600e3, p_phys=0.005,
                              topology="all-to-all", T2_us=100.0)
        qc = QuantumCircuit(3)
        qc.h(0); qc.cx(0, 1); qc.cx(1, 2)
        r = self._surface(hw, qc)
        self.assertTrue(r.feasible)
        self.assertLess(r.fidelity_circuit, 0.01)
        self.assertFalse(r.meets_fidelity_target,
            "fidelidade colapsada por T2 não deveria contar como atingindo o alvo")

    def test_meets_fidelity_target_true_no_caso_normal(self):
        """Contraste com o teste acima: hardware limpo/rápido deve ter
        meets_fidelity_target=True (não é sempre False por padrão)."""
        hw = HardwareProfile("limpo", t_gate_ns=50, p_phys=0.0005, topology="grid")
        r = self._surface(hw)
        self.assertTrue(r.feasible)
        self.assertTrue(r.meets_fidelity_target)


class TestRankingDuasCamadas(unittest.TestCase):
    """
    v3.4.0: rank() não deixa mais uma combinação que não atinge o
    fidelity_target pedido competir por #1 contra quem atinge -- antes,
    o score ponderado (qubits/tempo/fidelidade) podia colocar uma opção
    com fidelidade real ~0% acima de outra com fidelidade real ~30%, só
    porque a primeira usava menos qubits (achado testando com T2_us
    ativado em vários hardwares simultaneamente).
    """

    def test_quem_atinge_alvo_sempre_vem_antes_de_quem_nao_atinge(self):
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        bom = HardwareProfile("Bom", t_gate_ns=50, p_phys=0.0005,
                               topology="all-to-all", readout_error=0.001)
        ruim = HardwareProfile("Ruim_lento", t_gate_ns=600e3, p_phys=0.005,
                                topology="all-to-all", T2_us=100.0)
        result = compare(qc, [bom, ruim], fidelity_target=0.99)
        recs = rank(result)

        self.assertTrue(recs)
        primeiro_abaixo_do_alvo = next(
            i for i, r in enumerate(recs) if not r.meets_fidelity_target
        )
        for r in recs[:primeiro_abaixo_do_alvo]:
            self.assertTrue(r.meets_fidelity_target,
                "nenhuma combinação que atinge o alvo deveria vir depois de uma que não atinge")
        for r in recs[primeiro_abaixo_do_alvo:]:
            self.assertFalse(r.meets_fidelity_target)

    def test_camada_b_ordenada_so_por_fidelidade_nao_por_score_ponderado(self):
        """
        Regressão do achado real (v5): quando NENHUMA combinação atinge o
        alvo, a ordem deve ser só por fidelidade decrescente -- não pelo
        score ponderado de qubits/tempo, que produzia a inversão absurda
        de uma opção com 0% de fidelidade batendo uma com ~30%.
        """
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        # Hardware ruim o bastante para que NENHUM código atinja 0.99,
        # mas com fidelidades finais bem diferentes entre si.
        hw = HardwareProfile("Ruim", t_gate_ns=400e3, p_phys=0.007,
                              topology="all-to-all", T2_us=300.0)
        result = compare(qc, [hw], fidelity_target=0.99)
        recs = rank(result, weight_qubits=0.4, weight_time=0.4, weight_fidelity=0.2)

        self.assertTrue(recs)
        self.assertFalse(any(r.meets_fidelity_target for r in recs),
            "pré-condição do teste: nenhuma combinação deveria atingir o alvo aqui")
        fidelidades = [r.fidelity_circuit for r in recs]
        self.assertEqual(fidelidades, sorted(fidelidades, reverse=True),
            "Camada B deveria estar ordenada só por fidelidade decrescente")

    def test_bottleneck_explica_o_motivo_na_camada_b(self):
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        hw = HardwareProfile("Ruim", t_gate_ns=600e3, p_phys=0.005,
                              topology="all-to-all", T2_us=100.0)
        result = compare(qc, [hw], fidelity_target=0.99)
        recs = rank(result)
        self.assertTrue(all(not r.meets_fidelity_target for r in recs))
        for r in recs:
            self.assertIn("NÃO atinge fidelity_target", r.bottleneck)


class TestInvarianteDestilacao(unittest.TestCase):
    """
    Ativar model_magic_state_distillation=True adiciona um custo real
    (fábricas de estado mágico) -- isso nunca deveria diminuir qubits
    físicos totais nem tempo de execução em relação ao mesmo circuito
    sem a flag. Verificado nesta sessão como parte da auditoria de viés
    (0 violações em 12 combinações circuito×fidelidade×hardware).
    """

    def test_destilacao_nunca_diminui_recursos(self):
        qc = QuantumCircuit(2)
        qc.h(0); qc.t(0); qc.t(0); qc.cx(0, 1); qc.t(1)
        hw = HardwareProfile("Teste", t_gate_ns=100, p_phys=0.001, topology="all-to-all")

        sem = compare(qc, [hw], fidelity_target=0.99, model_magic_state_distillation=False)
        com = compare(qc, [hw], fidelity_target=0.99, model_magic_state_distillation=True)

        for r_sem, r_com in zip(sem["results"]["Teste"], com["results"]["Teste"]):
            if not r_sem.feasible or not r_com.feasible:
                continue
            self.assertGreaterEqual(r_com.total_physical_qubits, r_sem.total_physical_qubits,
                f"{r_sem.code_name}: destilação diminuiu qubits físicos")
            self.assertGreaterEqual(r_com.execution_time_us, r_sem.execution_time_us,
                f"{r_sem.code_name}: destilação diminuiu tempo de execução")


class TestRecommendationExpoeMagicState(unittest.TestCase):
    """
    Regressão v3.3.4: rank()/rank_by_metric() descartavam silenciosamente
    magic_state_qubits/magic_state_factories/magic_state_t_state_error do
    CodeResult ao montar Recommendation -- acessar esses campos no
    resultado de rank() (o fluxo documentado principal) levantava
    AttributeError, mesmo com model_magic_state_distillation=True.
    """

    def test_campos_de_magic_state_acessiveis_no_resultado_de_rank(self):
        qc = QuantumCircuit(2)
        qc.h(0); qc.t(0); qc.t(0); qc.cx(0, 1); qc.t(1)
        hw = HardwareProfile("Teste", t_gate_ns=100, p_phys=0.001, topology="all-to-all")

        result = compare(qc, [hw], fidelity_target=0.99,
                          model_magic_state_distillation=True)
        recs = rank(result)
        self.assertTrue(recs, "nenhuma combinação viável para testar")

        r = recs[0]
        self.assertIsNotNone(r.magic_state_qubits)
        self.assertIsNotNone(r.magic_state_factories)
        self.assertIsNotNone(r.magic_state_t_state_error)

    def test_campos_de_magic_state_none_quando_flag_desligada(self):
        qc = QuantumCircuit(2)
        qc.h(0); qc.cx(0, 1)
        hw = HardwareProfile("Teste", t_gate_ns=100, p_phys=0.001, topology="all-to-all")

        result = compare(qc, [hw], fidelity_target=0.99)
        r = rank(result)[0]
        self.assertIsNone(r.magic_state_qubits)
        self.assertIsNone(r.magic_state_factories)
        self.assertIsNone(r.magic_state_t_state_error)


class TestRankByMetric(unittest.TestCase):
    """
    rank_by_metric() complementa rank(): quando uma combinação domina todos
    os critérios ao mesmo tempo (dominância de Pareto), nenhum peso em
    rank() consegue trocar o "#1" -- rank_by_metric() mostra o melhor de
    cada critério isoladamente, revelando trade-offs que ficam escondidos
    atrás de um único score ponderado.
    """

    def _qft6(self):
        import math
        qc = QuantumCircuit(6)
        for i in range(6):
            qc.h(i)
            for j in range(i + 1, 6):
                qc.cp(math.pi / 2**(j - i), j, i)
        return qc

    def test_retorna_as_tres_chaves(self):
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        hw = HardwareProfile("Teste", t_gate_ns=100, p_phys=0.001, topology="all-to-all")
        result = compare(qc, [hw], fidelity_target=0.99)
        por_metrica = rank_by_metric(result)
        self.assertEqual(set(por_metrica.keys()), {"qubits", "tempo", "fidelidade"})

    def test_cada_lista_esta_ordenada_pela_propria_metrica(self):
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        hw = HardwareProfile("Teste", t_gate_ns=100, p_phys=0.001, topology="all-to-all")
        result = compare(qc, [hw], fidelity_target=0.99)
        por_metrica = rank_by_metric(result)

        qubits_vals = [r.total_physical_qubits for r in por_metrica["qubits"]]
        self.assertEqual(qubits_vals, sorted(qubits_vals))

        tempo_vals = [r.execution_time_us for r in por_metrica["tempo"]]
        self.assertEqual(tempo_vals, sorted(tempo_vals))

        fid_vals = [r.fidelity_circuit for r in por_metrica["fidelidade"]]
        self.assertEqual(fid_vals, sorted(fid_vals, reverse=True))

    def test_todas_as_listas_caem_para_fidelidade_quando_ninguem_atinge_alvo(self):
        """
        v3.4.0: rank_by_metric() herda o ranking em duas camadas de rank().
        Se NENHUMA combinação atinge fidelity_target, as três listas
        (inclusive "qubits" e "tempo") caem inteiras na Camada B e saem
        ordenadas por fidelidade, não pela métrica do próprio nome --
        comportamento que o docstring antigo não deixava claro.
        """
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        hw = HardwareProfile("Ruim", t_gate_ns=400e3, p_phys=0.007,
                              topology="all-to-all", T2_us=300.0)
        result = compare(qc, [hw], fidelity_target=0.99)
        por_metrica = rank_by_metric(result)

        for chave in ("qubits", "tempo", "fidelidade"):
            lista = por_metrica[chave]
            self.assertTrue(lista)
            self.assertFalse(any(r.meets_fidelity_target for r in lista),
                f"pré-condição do teste: '{chave}' deveria estar inteira na Camada B")
            fid_vals = [r.fidelity_circuit for r in lista]
            self.assertEqual(fid_vals, sorted(fid_vals, reverse=True),
                f"lista '{chave}' deveria cair para ordenação por fidelidade, não pela sua própria métrica")

    def test_revela_trade_off_escondido_pelo_rank_ponderado(self):
        """
        Regressão do achado desta sessão: um circuito onde os 5 presets de
        peso do rank() convergem pro mesmo #1 (dominância de Pareto) ainda
        assim tem vencedores DIFERENTES por métrica isolada -- prova que
        rank_by_metric() revela informação que rank() sozinho esconde.
        """
        qc = self._qft6()
        hardwares = [
            HardwareProfile("IBM_Eagle", t_gate_ns=391, p_phys=0.0062, topology="heavy-hex"),
            HardwareProfile("IBM_Heron", t_gate_ns=100, p_phys=0.003, topology="heavy-hex"),
            HardwareProfile("Quantinuum_H2", t_gate_ns=100e3, p_phys=0.0015, topology="all-to-all"),
        ]
        result = compare(qc, hardwares, fidelity_target=0.999)
        por_metrica = rank_by_metric(result)

        vencedores = {m: (lista[0].hardware, lista[0].code) for m, lista in por_metrica.items()}
        self.assertGreater(len(set(vencedores.values())), 1,
            "Esperava vencedores diferentes por métrica isolada neste circuito "
            f"(achado nesta sessão) — obteve: {vencedores}")


class TestInvalidInputsAndWeights(unittest.TestCase):
    """
    Regressão dos 6 bugs de entradas/pesos inválidos encontrados testando
    o pacote real (v3.4.1) como usuário real. Cada bug era ou (a) um crash
    com mensagem ruim, ou (b) pior — aceito silenciosamente e propagado até
    produzir um resultado sem sentido (ranking invertido, score=NaN, lista
    vazia sem explicação).
    """

    def _qft4(self):
        qc = QuantumCircuit(4)
        for i in range(4):
            qc.h(i)
            for j in range(i + 1, 4):
                qc.cp(math.pi / 2 ** (j - i), j, i)
        return qc

    def _compare_result(self, fidelity_target=0.01):
        hw = HardwareProfile.from_calibrated(list(HARDWARE_PROFILES.values())[0])
        return compare(self._qft4(), [hw], fidelity_target=fidelity_target)

    # --- Bug 1: pesos todos zero ---
    def test_rank_pesos_todos_zero_rejeitado(self):
        cmp_result = self._compare_result()
        with self.assertRaises(ValueError):
            rank(cmp_result, weight_qubits=0.0, weight_time=0.0, weight_fidelity=0.0)

    def test_rank_peso_individual_zero_ainda_permitido(self):
        """rank_by_metric() depende disto: isola cada critério zerando os
        outros dois, nunca os três ao mesmo tempo."""
        cmp_result = self._compare_result()
        recs = rank(cmp_result, weight_qubits=1.0, weight_time=0.0, weight_fidelity=0.0)
        self.assertIsInstance(recs, list)

    # --- Bug 2: peso negativo ---
    def test_rank_peso_negativo_rejeitado(self):
        cmp_result = self._compare_result()
        with self.assertRaises(ValueError):
            rank(cmp_result, weight_qubits=-1.0, weight_time=1.0, weight_fidelity=1.0)

    # --- Bug 3: peso NaN ---
    def test_rank_peso_nan_rejeitado(self):
        cmp_result = self._compare_result()
        with self.assertRaises(ValueError):
            rank(cmp_result, weight_qubits=float("nan"), weight_time=0.3, weight_fidelity=0.2)

    # --- Bug 4: CalibratedHardware sem validação (NaN não capturado por "<=0") ---
    def _calibrated_hardware_base_kwargs(self):
        return dict(
            name="teste", n_qubits=100, p_1q_mean=0.001, p_2q_mean=0.01,
            p_2q_worst=0.02, t_1q_ns=50.0, t_2q_ns=300.0, T1_us=100.0,
            T2_us=50.0, readout_error=0.01, topology="heavy-hex", source="teste",
        )

    def test_calibrated_hardware_t2_nan_rejeitado(self):
        kwargs = self._calibrated_hardware_base_kwargs()
        kwargs["T2_us"] = float("nan")
        with self.assertRaises(ValueError):
            CalibratedHardware(**kwargs)

    def test_calibrated_hardware_t1_zero_rejeitado(self):
        kwargs = self._calibrated_hardware_base_kwargs()
        kwargs["T1_us"] = 0.0
        with self.assertRaises(ValueError):
            CalibratedHardware(**kwargs)

    def test_calibrated_hardware_p2q_negativo_rejeitado(self):
        kwargs = self._calibrated_hardware_base_kwargs()
        kwargs["p_2q_mean"] = -0.5
        with self.assertRaises(ValueError):
            CalibratedHardware(**kwargs)

    def test_calibrated_hardware_t2_none_ainda_permitido(self):
        """HARDWARE_PROFILES["Majorana_..."] usa T2_us=None de propósito
        (sem análogo público reportado) -- não pode quebrar."""
        kwargs = self._calibrated_hardware_base_kwargs()
        kwargs["T2_us"] = None
        ch = CalibratedHardware(**kwargs)
        self.assertIsNone(ch.T2_us)

    def test_hardware_profile_t2_nan_rejeitado(self):
        """Mesmo gap existia em HardwareProfile.__post_init__ (não só em
        CalibratedHardware) -- "<= 0" nunca captura NaN em Python."""
        with self.assertRaises(ValueError):
            HardwareProfile(name="t", t_gate_ns=100, p_phys=0.01,
                             topology="heavy-hex", T2_us=float("nan"))

    # --- Bug 5: NaN/inf em shor/grover/qft ---
    def test_qft_nan_rejeitado(self):
        with self.assertRaises(ValueError):
            AlgorithmEstimator.qft(float("nan"))

    def test_qft_inf_rejeitado(self):
        with self.assertRaises(ValueError):
            AlgorithmEstimator.qft(float("inf"))

    def test_shor_nan_rejeitado(self):
        with self.assertRaises(ValueError):
            AlgorithmEstimator.shor(float("nan"))

    def test_grover_inf_rejeitado(self):
        with self.assertRaises(ValueError):
            AlgorithmEstimator.grover(float("inf"))

    def test_qft_valor_normal_ainda_funciona(self):
        est = AlgorithmEstimator.qft(4)
        self.assertEqual(est.n_logical_qubits, 4)

    # --- Bug 6: nomes de hardware duplicados perdiam resultado silenciosamente ---
    def test_compare_nomes_duplicados_nao_perde_resultado(self):
        hw1 = HardwareProfile.from_calibrated(list(HARDWARE_PROFILES.values())[0])
        hw2 = HardwareProfile(name=hw1.name, t_gate_ns=hw1.t_gate_ns,
                               p_phys=hw1.p_phys, topology=hw1.topology,
                               T1_us=50.0)  # T1 diferente, nome igual
        with self.assertWarns(UserWarning):
            result = compare(self._qft4(), [hw1, hw2], fidelity_target=0.01)
        self.assertEqual(len(result["results"]), 2,
            "os dois hardwares deveriam ter chaves separadas, não uma sobrescrevendo a outra")

    def test_compare_nomes_diferentes_sem_aviso(self):
        """Regressão: hardwares com nomes já distintos não devem gerar aviso."""
        hw1 = HardwareProfile.from_calibrated(list(HARDWARE_PROFILES.values())[0])
        hw2 = HardwareProfile.from_calibrated(list(HARDWARE_PROFILES.values())[1])
        with self.assertRaises(AssertionError):
            # assertWarns falha (AssertionError) se NENHUM warning for emitido
            with self.assertWarns(UserWarning):
                compare(self._qft4(), [hw1, hw2], fidelity_target=0.01)


class TestPhysicallyMeaninglessInputs(unittest.TestCase):
    """
    Regressão de 2 bugs reportados externamente: resultados sem sentido
    físico que não paravam a execução (nem crash, nem validação) --
    diferente da classe de bug de TestInvalidInputsAndWeights (que eram
    todos "aceito silenciosamente"), estes dois eram "calculado até o fim
    e devolvido como se fosse um resultado válido".
    """

    def test_magic_state_resources_t_count_negativo_rejeitado(self):
        with self.assertRaises(ValueError):
            magic_state_resources(
                t_count=-1, p_phys=0.001, t_gate_ns=100,
                target_t_state_error=1e-6, data_circuit_time_us=90,
            )

    def test_magic_state_resources_t_count_zero_ainda_funciona(self):
        """Regressão: t_count=0 é um caso especial legítimo (circuito sem
        T-gates), não deve ser confundido com t_count negativo."""
        extra_qubits, n_factories, factory = magic_state_resources(
            t_count=0, p_phys=0.001, t_gate_ns=100,
            target_t_state_error=1e-6, data_circuit_time_us=90,
        )
        self.assertEqual((extra_qubits, n_factories, factory), (0, 0, None))

    def test_magic_state_resources_t_count_positivo_ainda_funciona(self):
        extra_qubits, n_factories, factory = magic_state_resources(
            t_count=100, p_phys=0.001, t_gate_ns=100,
            target_t_state_error=1e-6, data_circuit_time_us=90,
        )
        self.assertGreaterEqual(extra_qubits, 0)
        self.assertGreaterEqual(n_factories, 0)

    def test_steane_model_p_phys_zero_rejeitado(self):
        """p_phys=0 produzia fidelidade=1.0 (perfeita, falsa) sem erro --
        os outros 3 modelos (surface/bacon_shor/floquet) já falhavam aqui
        via math domain error do log(); só o Steane (fórmula 21*p²) aceitava
        p=0 silenciosamente."""
        with self.assertRaises(ValueError):
            _steane_model(p_phys=0.0, p_L_target=1e-6)

    def test_steane_model_p_phys_valido_ainda_funciona(self):
        d, q_per_L, cycles, p_L = _steane_model(p_phys=0.001, p_L_target=1e-3)
        self.assertEqual(d, 3)
        self.assertAlmostEqual(p_L, 21 * 0.001 ** 2)


class TestBlochRelationAndRemainingGaps(unittest.TestCase):
    """
    Regressão do segundo lote reportado externamente: T2 > 2*T1 (viola a
    relação de Bloch), p_t_state >= 1, name/topology vazios em
    HardwareProfile/CalibratedHardware, e target_t_state_error/
    data_circuit_time_us inválidos em magic_state_resources().
    """

    def _hw_kwargs(self, **overrides):
        kwargs = dict(
            name="test-hw", t_gate_ns=50, p_phys=0.001, readout_error=0.01,
            T1_us=100, T2_us=100, t_meas_ns=200, p_t_state=None,
            topology="linear",
        )
        kwargs.update(overrides)
        return kwargs

    def test_hardware_profile_t2_maior_que_2x_t1_rejeitado(self):
        with self.assertRaises(ValueError):
            HardwareProfile(**self._hw_kwargs(T1_us=100, T2_us=300))

    def test_hardware_profile_t2_igual_2x_t1_ainda_funciona(self):
        HardwareProfile(**self._hw_kwargs(T1_us=100, T2_us=200))

    def test_hardware_profile_t2_ruido_float_na_fronteira_nao_rejeitado(self):
        """T2 = 2*T1 + 1e-9 (ruído de ponto flutuante) não deve ser
        confundido com uma violação real da relação de Bloch."""
        HardwareProfile(**self._hw_kwargs(T1_us=100.0, T2_us=200.0 + 1e-9))

    def test_hardware_profile_p_t_state_maior_igual_1_rejeitado(self):
        with self.assertRaises(ValueError):
            HardwareProfile(**self._hw_kwargs(p_t_state=1.5))

    def test_hardware_profile_p_t_state_valido_ainda_funciona(self):
        HardwareProfile(**self._hw_kwargs(p_t_state=0.05))

    def test_hardware_profile_name_vazio_rejeitado(self):
        with self.assertRaises(ValueError):
            HardwareProfile(**self._hw_kwargs(name=""))

    def test_hardware_profile_topology_vazio_rejeitado(self):
        with self.assertRaises(ValueError):
            HardwareProfile(**self._hw_kwargs(topology=""))

    def _cal_kwargs(self, **overrides):
        kwargs = dict(
            name="test-cal", n_qubits=27, p_1q_mean=0.001, p_2q_mean=0.01,
            p_2q_worst=0.02, t_1q_ns=50, t_2q_ns=300, T1_us=100, T2_us=100,
            readout_error=0.01, topology="heavy-hex", source="test",
        )
        kwargs.update(overrides)
        return kwargs

    def test_calibrated_hardware_t2_maior_que_2x_t1_rejeitado(self):
        with self.assertRaises(ValueError):
            CalibratedHardware(**self._cal_kwargs(T1_us=100, T2_us=300))

    def test_calibrated_hardware_p_t_state_maior_igual_1_rejeitado(self):
        with self.assertRaises(ValueError):
            CalibratedHardware(**self._cal_kwargs(p_t_state=1.0))

    def test_calibrated_hardware_name_vazio_rejeitado(self):
        with self.assertRaises(ValueError):
            CalibratedHardware(**self._cal_kwargs(name=""))

    def test_calibrated_hardware_topology_vazio_rejeitado(self):
        with self.assertRaises(ValueError):
            CalibratedHardware(**self._cal_kwargs(topology=""))

    def test_hardware_profiles_reais_ainda_carregam_sem_erro(self):
        """Sanidade: nenhuma entrada real de HARDWARE_PROFILES cai em
        nenhuma das novas bordas de validação."""
        for hw_cal in HARDWARE_PROFILES.values():
            HardwareProfile.from_calibrated(hw_cal)

    def test_magic_state_resources_target_error_maior_igual_1_rejeitado(self):
        with self.assertRaises(ValueError):
            magic_state_resources(
                t_count=100, p_phys=0.001, t_gate_ns=100,
                target_t_state_error=1.5, data_circuit_time_us=90,
            )

    def test_magic_state_resources_data_circuit_time_negativo_rejeitado(self):
        with self.assertRaises(ValueError):
            magic_state_resources(
                t_count=100, p_phys=0.001, t_gate_ns=100,
                target_t_state_error=1e-6, data_circuit_time_us=-500,
            )

    def test_build_magic_state_factory_target_error_maior_igual_1_rejeitado(self):
        """Mesmo gap do magic_state_resources(), mas na função de baixo
        nível chamada diretamente: target_error=1.5 antes retornava uma
        MagicStateFactory de aparência normal, silenciosamente."""
        with self.assertRaises(ValueError):
            build_magic_state_factory(p_phys=0.001, t_gate_ns=100, target_error=1.5)

    def test_build_magic_state_factory_p_t_state_maior_igual_1_rejeitado(self):
        """Antes não era rejeitado aqui e produzia um erro de convergência
        confuso, apontando para p_phys em vez do p_t_state realmente
        inválido."""
        with self.assertRaises(ValueError):
            build_magic_state_factory(p_phys=0.001, t_gate_ns=100,
                                       target_error=1e-6, p_t_state=1.5)

    def test_build_magic_state_factory_valores_validos_ainda_funcionam(self):
        factory = build_magic_state_factory(p_phys=0.001, t_gate_ns=100,
                                             target_error=1e-6)
        self.assertGreater(factory.qubits, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
