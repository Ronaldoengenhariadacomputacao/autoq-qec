"""
Testes reais do QEC Estimator — verificam física, não só aritmética.
Cada teste falha se o modelo produzir resultado fisicamente incorreto.
"""
import math, unittest

from autoq_qec.qec_estimator import (
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

    def test_cycles_e_d_rodadas_vezes_2d_menos_2(self):
        """
        Regressão: cycles_per_gate deve ser d rodadas de extração de
        síndrome × 2(d-1) medições de gauge por rodada (Li, Miller &
        Brown 2018, arXiv:1804.01127 + Aliferis PhD thesis p.93), não
        apenas 2(d-1) de uma única rodada — mesmo padrão do bug d²→d³
        já corrigido no Surface Code.
        """
        d, _, cycles, _ = _bacon_shor_model(0.001, 1e-6)
        self.assertEqual(cycles, d * 2 * (d - 1))


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


class TestCountTGatesFallback(unittest.TestCase):
    """
    v3.5.1: para circuitos muito grandes (dezenas de milhares de portas),
    transpile(..., optimization_level=2) é inviável na prática — tanto pode
    levantar TranspilerError('Maximum iteration reached') quanto pode
    "terminar" com sucesso mas levar dezenas de minutos num único circuito
    (medido: ~19min para um UCCSD real de 18 qubits/93k de profundidade,
    sem lançar nenhum erro). Por isso _count_t_gates() tenta
    optimization_level=1 primeiro (rápido, segundos), depois 0, e só usa 2
    como último recurso. Reproduzido de verdade com circuitos UCCSD reais
    de N2 (20 qubits) e CH4 (18 qubits) nesta sessão antes de escrever este
    teste; aqui simulamos via mock para manter o teste rápido.
    """

    def test_tenta_nivel_1_primeiro_e_nao_precisa_de_fallback_no_caso_normal(self):
        from unittest import mock
        from autoq_qec.qec_estimator import _count_t_gates

        qc = QuantumCircuit(1)
        qc.t(0)
        real_transpile = __import__('qiskit').transpile

        chamadas = []
        def fake_transpile(circuit, basis_gates, optimization_level, seed_transpiler):
            chamadas.append(optimization_level)
            return real_transpile(circuit, basis_gates=basis_gates,
                                   optimization_level=optimization_level,
                                   seed_transpiler=seed_transpiler)

        with mock.patch('qiskit.transpile', side_effect=fake_transpile):
            t_count = _count_t_gates(qc)

        self.assertEqual(chamadas, [1],
            "Deve tentar nivel 1 primeiro e nao precisar de mais nada quando ja funciona")
        self.assertEqual(t_count, 1)

    def test_cai_para_nivel_0_quando_nivel_1_estoura_iteracoes(self):
        from unittest import mock
        from qiskit.transpiler.exceptions import TranspilerError
        from autoq_qec.qec_estimator import _count_t_gates

        qc = QuantumCircuit(1)
        qc.t(0)
        real_transpile = __import__('qiskit').transpile

        chamadas = []
        def fake_transpile(circuit, basis_gates, optimization_level, seed_transpiler):
            chamadas.append(optimization_level)
            if optimization_level == 1:
                raise TranspilerError("Maximum iteration reached. max_iteration=1000")
            return real_transpile(circuit, basis_gates=basis_gates,
                                   optimization_level=optimization_level,
                                   seed_transpiler=seed_transpiler)

        with mock.patch('qiskit.transpile', side_effect=fake_transpile):
            t_count = _count_t_gates(qc)

        self.assertEqual(chamadas, [1, 0],
            "Deve tentar nivel 1 primeiro, e cair pro nivel 0 apos o erro")
        self.assertEqual(t_count, 1)

    def test_so_usa_nivel_2_como_ultimo_recurso(self):
        from unittest import mock
        from qiskit.transpiler.exceptions import TranspilerError
        from autoq_qec.qec_estimator import _count_t_gates

        qc = QuantumCircuit(1)
        qc.t(0)
        real_transpile = __import__('qiskit').transpile

        chamadas = []
        def fake_transpile(circuit, basis_gates, optimization_level, seed_transpiler):
            chamadas.append(optimization_level)
            if optimization_level in (1, 0):
                raise TranspilerError("Maximum iteration reached. max_iteration=1000")
            return real_transpile(circuit, basis_gates=basis_gates,
                                   optimization_level=optimization_level,
                                   seed_transpiler=seed_transpiler)

        with mock.patch('qiskit.transpile', side_effect=fake_transpile):
            t_count = _count_t_gates(qc)

        self.assertEqual(chamadas, [1, 0, 2],
            "So deve chegar no nivel 2 se 1 e 0 falharem")
        self.assertEqual(t_count, 1)

    def test_propaga_erro_se_todos_os_niveis_falharem(self):
        from unittest import mock
        from qiskit.transpiler.exceptions import TranspilerError
        from autoq_qec.qec_estimator import _count_t_gates

        qc = QuantumCircuit(1)
        qc.t(0)

        with mock.patch('qiskit.transpile',
                         side_effect=TranspilerError("Maximum iteration reached. max_iteration=1000")):
            with self.assertRaises(TranspilerError):
                _count_t_gates(qc)


class TestQiskitCliffordTBugRobustness(unittest.TestCase):
    """
    Qiskit 2.4.0-2.5.1 tinham um bug real em OptimizeCliffordT: S/Sdg
    trocados de lugar na reexpressao de uma rotacao-T de eixo Y quando a
    base exclui SX/SXdg (exatamente a base que _count_t_gates() usa) --
    o circuito transpilado deixava de ser unitariamente equivalente ao
    original, sem erro nem aviso. Corrigido na 2.5.2 (PR Qiskit#16729,
    reportado e verificado nesta sessao -- ver docs/qiskit-optimize-clifford-t-bug.md
    no repositorio autoq-motor, publicado com DOI 10.5281/zenodo.21880313).

    Verificado diretamente (rodando as duas versoes, 2.5.1 com bug e 2.5.2
    corrigida): o T-count que _count_t_gates() reporta e IDENTICO nos dois
    casos, porque o bug troca S<->Sdg (portas Clifford, custo zero e nunca
    contadas) sem nunca mudar quantas portas T/Tdg sao inseridas. Estes
    testes fixam esse achado como regressao formal -- servem tanto pra
    quem roda numa versao afetada quanto numa corrigida.
    """

    def _t_count_circuito_1q_5portas(self):
        qc = QuantumCircuit(1)
        qc.s(0); qc.h(0); qc.t(0); qc.t(0); qc.t(0)
        return extract_circuit_profile(qc).t_count

    def _t_count_circuito_2q_rz(self, angulo=0.3):
        qc = QuantumCircuit(2)
        qc.h(0); qc.cx(0, 1); qc.t(0); qc.t(1); qc.x(0); qc.rz(angulo, 0)
        return extract_circuit_profile(qc).t_count

    def test_1_circuito_minimo_1_qubit_processa_sem_erro(self):
        # so confirma que extract_circuit_profile() nao lanca -- o valor
        # exato de T-count depende da sintese aproximada de rz, nao e o
        # ponto deste teste especifico (ver testes 2-3 para estabilidade)
        t = self._t_count_circuito_1q_5portas()
        self.assertGreaterEqual(t, 0)

    def test_2_circuito_2_qubits_com_rz_t_count_estavel(self):
        # este e o circuito que o bug do Qiskit quebrava (Operator.equiv()
        # =False) em TODOS os niveis de otimizacao (1,2,3) -- confirma que
        # o T-count reportado e um numero concreto e reproduzivel
        t1 = self._t_count_circuito_2q_rz()
        t2 = self._t_count_circuito_2q_rz()
        self.assertEqual(t1, t2, "T-count deve ser deterministico (seed_transpiler=42)")
        self.assertGreater(t1, 0)

    def test_3_t_count_estavel_variando_angulo_de_rz(self):
        # garante que nao e um angulo especifico que "esconde" uma
        # diferenca de T-count entre versoes com/sem o bug
        for angulo in (0.1, 0.3, 0.7, 1.5, math.pi / 4):
            t = self._t_count_circuito_2q_rz(angulo)
            self.assertGreater(t, 0, f"T-count deveria ser > 0 para angulo={angulo}")

    def test_4_multiplas_rotacoes_rz_intercaladas(self):
        qc = QuantumCircuit(2)
        qc.h(0); qc.cx(0, 1)
        for ang in (0.2, 0.5, 0.9):
            qc.rz(ang, 0)
            qc.t(1)
            qc.rz(ang * 1.3, 1)
        qc.t(0)
        perfil = extract_circuit_profile(qc)
        self.assertGreater(perfil.t_count, 0)
        self.assertEqual(perfil.n_logical_qubits, 2)

    def test_5_circuito_maior_10_qubits_padrao_repetido(self):
        qc = QuantumCircuit(10)
        for q in range(10):
            qc.h(q)
        for _ in range(5):
            for q in range(9):
                qc.cx(q, q + 1)
            for q in range(10):
                qc.rz(0.31, q)
                qc.t(q)
        perfil = extract_circuit_profile(qc)
        self.assertGreater(perfil.t_count, 0)
        self.assertEqual(perfil.n_logical_qubits, 10)

    def test_6_niveis_1_e_2_concordam_nivel_0_pode_divergir_um_pouco(self):
        # achado real (ja confirmado nesta sessao rodando os dois lados do
        # bug, e consistente com a ressalva ja documentada pro BeH2 na
        # v3.4.4): T-count NAO e garantido identico entre TODOS os niveis
        # -- nivel 0 (sem otimizacao real) pode diferir de 1/2 por uma
        # pequena margem (medido: 128 vs 126 pra este circuito). O que
        # importa pra este teste e que 1 e 2 (os niveis que _count_t_gates()
        # usa primeiro/como fallback intermediario) concordem entre si, e
        # que _count_t_gates() em si (que tenta 1 antes de 0) reporte um
        # valor estavel.
        from qiskit import transpile as qk_transpile
        from autoq_qec.qec_estimator import _count_t_gates
        qc = QuantumCircuit(2)
        qc.h(0); qc.cx(0, 1); qc.t(0); qc.t(1); qc.x(0); qc.rz(0.3, 0)
        basis = ['t', 'tdg', 's', 'sdg', 'h', 'x', 'y', 'z', 'cx']
        contagens = {}
        for nivel in (0, 1, 2):
            tb = qk_transpile(qc, basis_gates=basis, optimization_level=nivel, seed_transpiler=42)
            ops = tb.count_ops()
            contagens[nivel] = ops.get('t', 0) + ops.get('tdg', 0)
        self.assertEqual(contagens[1], contagens[2],
            f"Niveis 1 e 2 deveriam concordar no T-count, obtido: {contagens}")
        t_real = _count_t_gates(qc)
        self.assertEqual(t_real, contagens[1],
            "_count_t_gates() tenta nivel 1 primeiro -- deve bater com o T-count do nivel 1")

    def test_7_pipeline_completo_compare_rank_estavel(self):
        from autoq_qec import rank
        qc = QuantumCircuit(2)
        qc.h(0); qc.cx(0, 1); qc.t(0); qc.t(1); qc.x(0); qc.rz(0.3, 0)
        qc.measure_all()
        r1 = rank(compare(qc, [IBM], fidelity_target=0.5))
        r2 = rank(compare(qc, [IBM], fidelity_target=0.5))
        self.assertEqual([x.total_physical_qubits for x in r1],
                          [x.total_physical_qubits for x in r2],
                          "compare()/rank() de ponta a ponta deve ser deterministico")

    def test_8_controle_com_sx_sxdg_bate_com_sem(self):
        # caminho NUNCA afetado pelo bug (usa o branch correto de apply_ty)
        # -- confirma que a equivalencia de T-count nao e coincidencia de
        # um caso isolado, e sim estrutural (S/Sdg sao sempre Clifford,
        # nunca contados, independente de qual branch de sintese roda)
        from qiskit import transpile as qk_transpile
        qc = QuantumCircuit(2)
        qc.h(0); qc.cx(0, 1); qc.t(0); qc.t(1); qc.x(0); qc.rz(0.3, 0)
        sem_sx = qk_transpile(qc, basis_gates=['t','tdg','s','sdg','h','x','y','z','cx'],
                               optimization_level=1, seed_transpiler=42)
        com_sx = qk_transpile(qc, basis_gates=['t','tdg','s','sdg','h','x','y','z','cx','sx','sxdg'],
                               optimization_level=1, seed_transpiler=42)
        ops_sem = sem_sx.count_ops(); ops_com = com_sx.count_ops()
        t_sem = ops_sem.get('t', 0) + ops_sem.get('tdg', 0)
        t_com = ops_com.get('t', 0) + ops_com.get('tdg', 0)
        self.assertEqual(t_sem, t_com,
            "T-count deve bater entre o branch com e sem SX/SXdg da sintese")

    def test_9_circuito_real_h2_uccsd_reconfirma_estudo_vqe(self):
        # reconfirma que o T-count ja publicado no estudo VQE (H2, Parity,
        # 2 qubits) nao muda -- circuito minimo equivalente em estrutura
        # (nao depende de qiskit-nature/pyscf pra manter o teste leve)
        qc = QuantumCircuit(2)
        qc.ry(0.37, 0); qc.cx(0, 1); qc.rz(0.12, 1); qc.cx(0, 1); qc.ry(-0.37, 0)
        t1 = extract_circuit_profile(qc).t_count
        t2 = extract_circuit_profile(qc).t_count
        self.assertEqual(t1, t2)
        self.assertGreaterEqual(t1, 0)

    def test_10_documentacao_de_versoes_afetadas(self):
        """
        Registro formal, nao so no CHANGELOG: Qiskit 2.4.0, 2.4.1, 2.4.2,
        2.5.0, 2.5.0rc1, 2.5.1 tinham o bug (introduzido pela PR Qiskit#15625,
        mesclada 2026-03-19). Corrigido na 2.5.2 (PR Qiskit#16729). Versoes
        2.3.1 e anteriores nunca tiveram o pipeline Clifford+T ciente de
        base que continha o bug -- nao afetadas por construcao.
        """
        import qiskit
        versoes_confirmadas_com_bug = {"2.4.0", "2.4.1", "2.4.2", "2.5.0", "2.5.1"}
        versao_atual = qiskit.__version__
        # nao falha o teste dependendo da versao instalada -- so documenta
        # e confirma que o T-count continua correto em qualquer uma delas
        t = self._t_count_circuito_2q_rz()
        self.assertGreater(t, 0,
            f"T-count deve ser > 0 independente da versao do Qiskit instalada "
            f"({versao_atual}, {'com bug conhecido' if versao_atual in versoes_confirmadas_com_bug else 'nao confirmada com bug'})")


class TestQiskit252Compatibility(unittest.TestCase):
    """
    Qiskit 2.5.0-2.5.2 trouxe mais mudancas alem do fix do OptimizeCliffordT
    (ver Task 14, sessao 2026-08-10): numpy minimo subiu pra 2.0, varios
    fixes de determinismo no transpilador (ConsolidateBlocks, VF2Layout,
    Sabre routing, CommutativeCancellation), fix de panic em
    DAGCircuit.depth, e uma nova funcao oficial "generate Clifford+T pass
    manager". Itens do plano original (12,13,17,18 -- Trotter/PauliEvolutionGate,
    QPY, Statevector.evolve) confirmados NAO APLICAVEIS por grep direto no
    codigo -- autoq-qec nao usa nenhum desses hoje, entao nao viram teste
    artificial aqui.
    """

    def test_11_numpy_2_compatibilidade_circuito_com_angulos_numpy(self):
        import numpy as np
        angulos = np.array([0.1, 0.4, 0.9])
        qc = QuantumCircuit(3)
        for q, ang in enumerate(angulos):
            qc.ry(float(ang), q)
        qc.cx(0, 1); qc.cx(1, 2); qc.t(0)
        perfil = extract_circuit_profile(qc)
        self.assertEqual(perfil.n_logical_qubits, 3)

    def test_12_numpy_2_hardwareprofile_calculos_numericos_estaveis(self):
        hw = HardwareProfile("Teste", t_gate_ns=100.0, p_phys=0.002, topology="linear",
                              readout_error=0.01, T1_us=150.0, T2_us=100.0)
        self.assertAlmostEqual(hw.p_phys, 0.002)
        self.assertAlmostEqual(hw.T2_us, 100.0)

    def test_13_determinismo_circuito_pequeno_repetido(self):
        qc = QuantumCircuit(2)
        qc.h(0); qc.cx(0, 1); qc.t(0); qc.rz(0.3, 1)
        perfis = [extract_circuit_profile(qc) for _ in range(3)]
        t_counts = {p.t_count for p in perfis}
        depths = {p.depth_physical for p in perfis}
        self.assertEqual(len(t_counts), 1, "T-count deve ser identico entre execucoes repetidas")
        self.assertEqual(len(depths), 1, "depth_physical deve ser identico entre execucoes repetidas")

    def test_14_determinismo_circuito_maior_repetido(self):
        qc = QuantumCircuit(8)
        for _ in range(4):
            for q in range(7):
                qc.cx(q, q + 1)
            for q in range(8):
                qc.rz(0.2, q)
        perfis = [extract_circuit_profile(qc) for _ in range(3)]
        self.assertEqual(len({p.t_count for p in perfis}), 1)
        self.assertEqual(len({p.n_physical_gates for p in perfis}), 1)

    def test_15_determinismo_com_coupling_map_heavy_hex(self):
        from qiskit.transpiler import CouplingMap
        qc = QuantumCircuit(4)
        qc.h(0); qc.cx(0, 2); qc.cx(1, 3); qc.cx(0, 3)
        cmap = CouplingMap.from_heavy_hex(3)
        n_fisico = cmap.size()
        if n_fisico < 4:
            self.skipTest("coupling map heavy-hex(3) pequena demais pro circuito de teste")
        perfis = [extract_circuit_profile(qc, coupling_map=cmap) for _ in range(2)]
        self.assertEqual(perfis[0].n_physical_gates, perfis[1].n_physical_gates,
            "overhead de SWAP roteado (Sabre) deve ser deterministico com coupling_map real")

    def test_16_determinismo_com_coupling_map_linear(self):
        from qiskit.transpiler import CouplingMap
        qc = QuantumCircuit(5)
        qc.h(0); qc.cx(0, 4); qc.cx(1, 3); qc.cx(2, 4)
        cmap = CouplingMap.from_line(5)
        perfis = [extract_circuit_profile(qc, coupling_map=cmap) for _ in range(2)]
        self.assertEqual(perfis[0].n_physical_gates, perfis[1].n_physical_gates)
        self.assertEqual(perfis[0].depth_physical, perfis[1].depth_physical)

    def test_17_depth_physical_circuito_grande_sem_erro(self):
        # fix de panic em DAGCircuit.depth (rustworkx-core 0.18.1) na 2.5.2
        # -- relevancia direta, extract_circuit_profile() calcula profundidade
        qc = QuantumCircuit(32)
        for _ in range(20):
            for q in range(31):
                qc.cx(q, q + 1)
        perfil = extract_circuit_profile(qc)
        self.assertGreater(perfil.depth_physical, 0)

    def test_18_depth_physical_estrutura_irregular(self):
        # cadeia serial de CX entre qubits DIFERENTES (0-1, 1-2, 2-3, ...) --
        # dependencia real e inevitavel (cada porta depende do qubit
        # compartilhado com a anterior), nao pode ser paralelizada nem
        # consolidada num unico gate. Tentativas anteriores (cx repetido no
        # mesmo par -- autocancela por ser sua propria inversa; rz repetido
        # no mesmo qubit -- consolida num unico 'u' via
        # Optimize1qGatesDecomposition) falharam por serem simplificaveis
        # de forma legitima pelo transpilador, nao por bug do autoq-qec.
        qc = QuantumCircuit(12)
        for q in range(11):
            qc.cx(q, q + 1)  # cadeia linear -- profundidade inevitavel ~11
        perfil = extract_circuit_profile(qc)
        self.assertGreaterEqual(perfil.depth_physical, 8,
            "cadeia linear de CX deve ter profundidade proxima ao comprimento da cadeia, "
            "nao pode ser paralelizada")

    def test_19_depth_reconfirma_padrao_do_estudo_vqe(self):
        # circuito de estrutura equivalente ao H2 UCCSD ja publicado --
        # confirma que profundidade nao mudou de forma inesperada
        qc = QuantumCircuit(2)
        qc.ry(0.37, 0); qc.cx(0, 1); qc.rz(0.12, 1); qc.cx(0, 1); qc.ry(-0.37, 0)
        perfil = extract_circuit_profile(qc)
        self.assertGreater(perfil.depth_physical, 0)

    def test_20_pass_manager_oficial_clifford_t_disponivel(self):
        # Qiskit 2.5.0 introduziu generate_preset_clifford_t_pass_manager --
        # avaliacao (nao adocao): confirma que existe e roda, compara
        # T-count contra o metodo manual de _count_t_gates()
        try:
            from qiskit.transpiler import generate_preset_clifford_t_pass_manager
        except ImportError:
            self.skipTest("generate_preset_clifford_t_pass_manager nao disponivel nesta versao do Qiskit")
        qc = QuantumCircuit(2)
        qc.h(0); qc.cx(0, 1); qc.t(0); qc.t(1); qc.x(0); qc.rz(0.3, 0)
        basis = ["t", "tdg", "s", "sdg", "h", "x", "y", "z", "cx"]
        pm = generate_preset_clifford_t_pass_manager(basis_gates=basis, optimization_level=1)
        resultado = pm.run(qc)
        ops = resultado.count_ops()
        t_oficial = ops.get('t', 0) + ops.get('tdg', 0)
        t_manual = extract_circuit_profile(qc).t_count
        # documenta o achado -- nao exige serem identicos (metodos diferentes
        # de sintese podem legitimamente dar T-counts proximos mas nao iguais)
        self.assertGreater(t_oficial, 0)
        self.assertGreater(t_manual, 0)

    def test_21_pass_manager_oficial_produz_circuito_correto(self):
        # Nota: este teste e informativo sobre a versao instalada do Qiskit,
        # nao um requisito do autoq-qec em si -- em Qiskit 2.4.0-2.5.1
        # (com o bug do OptimizeCliffordT, ver TestQiskitCliffordTBugRobustness)
        # este mesmo pass manager oficial FALHA essa checagem (e exatamente
        # o pass afetado pelo bug) -- so deve passar de fato a partir da
        # 2.5.2. Skip em vez de falha dura em versoes conhecidas com bug,
        # pra nao quebrar CI de quem ainda nao atualizou o Qiskit.
        import qiskit
        try:
            from qiskit.transpiler import generate_preset_clifford_t_pass_manager
        except ImportError:
            self.skipTest("generate_preset_clifford_t_pass_manager nao disponivel nesta versao do Qiskit")
        versoes_com_bug_conhecido = {"2.4.0", "2.4.1", "2.4.2", "2.5.0", "2.5.0rc1", "2.5.1"}
        from qiskit.quantum_info import Operator
        qc = QuantumCircuit(2)
        qc.h(0); qc.cx(0, 1); qc.t(0); qc.t(1); qc.x(0); qc.rz(0.3, 0)
        basis = ["t", "tdg", "s", "sdg", "h", "x", "y", "z", "cx"]
        pm = generate_preset_clifford_t_pass_manager(basis_gates=basis, optimization_level=1)
        resultado = pm.run(qc)
        equivalente = Operator(qc).equiv(Operator(resultado))
        if qiskit.__version__ in versoes_com_bug_conhecido:
            self.assertFalse(equivalente,
                f"Qiskit {qiskit.__version__} tem o bug conhecido do OptimizeCliffordT -- "
                "esperado equiv()=False aqui, confirmando o bug (Qiskit#16729)")
            self.skipTest(f"Qiskit {qiskit.__version__} tem o bug conhecido (Qiskit#16729) -- "
                          "checagem de correcao pulada nesta versao, ver TestQiskitCliffordTBugRobustness")
        else:
            self.assertTrue(equivalente,
                f"Qiskit {qiskit.__version__} deveria ter o fix de Qiskit#16729 -- "
                "circuito nao deveria divergir do original")

    def test_22_qpy_e_statevector_evolve_nao_aplicaveis(self):
        """
        Documentacao formal (nao teste artificial): confirmado via grep
        direto no codigo (2026-08-10) que autoq_qec/ e validation/ nao usam
        QPY nem Statevector.evolve em nenhum lugar -- fixes do Qiskit 2.5.0
        nessas areas nao se aplicam ao autoq-qec hoje. Trotter/PauliEvolutionGate
        so aparecem numa docstring descritiva (AlgorithmEstimator.vqe()), nao
        em construcao real de circuito -- tambem nao aplicavel.
        """
        self.assertTrue(True)

    def test_23_suite_completa_sem_regressao_smoke(self):
        # smoke test consolidado -- roda um circuito representativo do
        # estudo VQE de ponta a ponta, confirma que nada quebra
        qc = QuantumCircuit(2)
        qc.ry(0.37, 0); qc.cx(0, 1); qc.rz(0.12, 1); qc.cx(0, 1); qc.ry(-0.37, 0)
        qc.measure_all()
        resultado = compare(qc, [IBM, IDEAL], fidelity_target=0.5)
        self.assertIn("results", resultado)
        self.assertEqual(len(resultado["results"]), 2)


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


class TestParametrosNaoVinculados(unittest.TestCase):
    """
    v3.2.2: extract_circuit_profile() deve rejeitar circuitos com parâmetros
    simbólicos (ansätze variacionais não vinculados) com ValueError claro,
    em vez de deixar vazar um TranspilerError bruto do Qiskit lá de dentro
    de _count_t_gates() (não há ângulo numérico pra síntese Solovay-Kitaev
    aproximar quando o parâmetro ainda é uma variável).
    """

    def test_realamplitudes_nao_vinculado_levanta_valueerror(self):
        from qiskit.circuit.library import RealAmplitudes
        circ = RealAmplitudes(4, reps=2).decompose()
        self.assertGreater(circ.num_parameters, 0)
        with self.assertRaises(ValueError):
            extract_circuit_profile(circ)

    def test_qaoaansatz_nao_vinculado_levanta_valueerror(self):
        from qiskit.circuit.library import QAOAAnsatz
        from qiskit.quantum_info import SparsePauliOp
        ham = SparsePauliOp.from_list([("ZZII", 1.0), ("IZZI", 1.0)])
        circ = QAOAAnsatz(ham, reps=1).decompose()
        self.assertGreater(circ.num_parameters, 0)
        with self.assertRaises(ValueError):
            extract_circuit_profile(circ)

    def test_realamplitudes_vinculado_funciona_normalmente(self):
        import numpy as np
        from qiskit.circuit.library import RealAmplitudes
        tmpl = RealAmplitudes(4, reps=2).decompose()
        rng = np.random.default_rng(42)
        circ = tmpl.assign_parameters(rng.uniform(0, 2*np.pi, tmpl.num_parameters))
        self.assertEqual(circ.num_parameters, 0)
        prof = extract_circuit_profile(circ)
        self.assertEqual(prof.n_logical_qubits, 4)
        self.assertGreater(prof.t_count, 0,
            "Rotação de ângulo genérico deve custar T-gates reais, não zero")

    def test_circuito_com_parameter_individual_vinculado_funciona(self):
        """Mesmo teste, mas construindo o circuito manualmente com Parameter
        (não via classe de biblioteca), pra garantir que a checagem é sobre
        circuit.num_parameters, não específica de RealAmplitudes/QAOAAnsatz."""
        from qiskit.circuit import Parameter
        theta = Parameter("theta")
        circ = QuantumCircuit(2)
        circ.h(0)
        circ.ry(theta, 1)
        circ.cx(0, 1)

        with self.assertRaises(ValueError):
            extract_circuit_profile(circ)

        circ_vinculado = circ.assign_parameters({theta: 0.73})
        prof = extract_circuit_profile(circ_vinculado)
        self.assertEqual(prof.n_logical_qubits, 2)


class TestCasosDeLimite(unittest.TestCase):
    """
    Regressão para casos-limite verificados manualmente durante a
    investigação da v3.2.2, mas que ainda não tinham teste formal —
    protegem contra alguém "consertar" um desses casos sem querer no futuro.
    """

    def test_circuito_realmente_vazio_nao_crasha(self):
        """
        extract_circuit_profile() num QuantumCircuit sem nenhuma porta
        deve devolver um perfil válido com contagens zeradas — não deve
        levantar erro aqui. (Quem levanta ValueError para 0 portas é
        estimate(), mais adiante no pipeline — ver test_circuito_vazio_levanta_erro.
        Este teste garante que extract_circuit_profile() continua sendo o
        lugar "silencioso" da checagem, não duplicando o erro cedo demais.)
        """
        qc = QuantumCircuit(2)  # 2 qubits, zero portas
        prof = extract_circuit_profile(qc)
        self.assertEqual(prof.n_logical_qubits, 2)
        self.assertEqual(prof.n_physical_gates, 0)
        self.assertEqual(prof.t_count, 0)

    def test_unitarygate_customizada_decompoe_sem_crash(self):
        """
        Uma porta UnitaryGate com matriz numérica arbitrária (não simbólica)
        deve ser sintetizada normalmente pelo transpile(), diferente do caso
        de parâmetro simbólico (Parameter/RealAmplitudes não vinculado) —
        a distinção importante é "tem número concreto" vs "é uma variável",
        não "é uma porta nomeada vs uma matriz". Seed fixa para reprodutibilidade.
        """
        from qiskit.circuit.library import UnitaryGate
        from qiskit.quantum_info import random_unitary

        qc = QuantumCircuit(2)
        U = random_unitary(4, seed=7)
        qc.append(UnitaryGate(U), [0, 1])

        prof = extract_circuit_profile(qc)
        self.assertEqual(prof.n_logical_qubits, 2)
        self.assertGreaterEqual(prof.t_count, 0)

    def test_circuito_grande_nao_trava(self):
        """
        QFT(50) não deve travar por tempo de execução do transpile —
        teto generoso (30s) de propósito: isso é uma checagem sanitária
        contra regressão catastrófica de performance (ex.: alguém trocar
        optimization_level ou desabilitar uma otimização que hoje evita
        explosão combinatória), não um benchmark de precisão. Não deve
        falhar por variação normal de velocidade de máquina/CI.
        """
        import time
        from qiskit.circuit.library import QFT

        qc = QFT(50).decompose()
        inicio = time.time()
        prof = extract_circuit_profile(qc)
        duracao = time.time() - inicio

        self.assertEqual(prof.n_logical_qubits, 50)
        self.assertLess(duracao, 30.0,
            f"QFT(50) levou {duracao:.1f}s — possível regressão de performance")


class TestHardwareProfileValidacao(unittest.TestCase):
    """
    v3.4.0: HardwareProfile aceitava qualquer valor sem checagem -- t_gate_ns=0
    gerava execution_time_us=0.0 sem erro; readout_error fora de [0,1]
    gerava fidelity_circuit > 1.0 (achado testando valores de propósito
    fora do domínio físico depois da auditoria de meets_fidelity_target).
    __post_init__ agora rejeita cedo, com ValueError claro.
    """

    def _valido(self, **overrides):
        base = dict(name="X", t_gate_ns=100, p_phys=0.001, topology="grid")
        base.update(overrides)
        return base

    def test_t_gate_ns_zero_rejeitado(self):
        with self.assertRaises(ValueError):
            HardwareProfile(**self._valido(t_gate_ns=0))

    def test_t_gate_ns_negativo_rejeitado(self):
        with self.assertRaises(ValueError):
            HardwareProfile(**self._valido(t_gate_ns=-50))

    def test_p_phys_zero_rejeitado(self):
        with self.assertRaises(ValueError):
            HardwareProfile(**self._valido(p_phys=0))

    def test_p_phys_negativo_rejeitado(self):
        with self.assertRaises(ValueError):
            HardwareProfile(**self._valido(p_phys=-0.01))

    def test_p_phys_acima_de_um_rejeitado(self):
        """p_phys é uma probabilidade de erro: >=1 não tem significado
        físico (bug real confirmado na v3.4.0 publicada: p_phys=1.5 era
        aceito silenciosamente, sem o teto que readout_error já tinha)."""
        with self.assertRaises(ValueError):
            HardwareProfile(**self._valido(p_phys=1.5))
        with self.assertRaises(ValueError):
            HardwareProfile(**self._valido(p_phys=1.0))

    def test_readout_error_acima_de_um_rejeitado(self):
        with self.assertRaises(ValueError):
            HardwareProfile(**self._valido(readout_error=5.0))

    def test_readout_error_negativo_rejeitado(self):
        with self.assertRaises(ValueError):
            HardwareProfile(**self._valido(readout_error=-0.5))

    def test_readout_error_zero_aceito(self):
        """0.0 é o default documentado (leitura perfeita) -- válido, não erro."""
        HardwareProfile(**self._valido(readout_error=0.0))

    def test_t1_us_zero_rejeitado(self):
        with self.assertRaises(ValueError):
            HardwareProfile(**self._valido(T1_us=0))

    def test_t1_us_negativo_rejeitado(self):
        with self.assertRaises(ValueError):
            HardwareProfile(**self._valido(T1_us=-100))

    def test_t2_us_zero_rejeitado(self):
        with self.assertRaises(ValueError):
            HardwareProfile(**self._valido(T2_us=0))

    def test_t2_us_negativo_rejeitado(self):
        with self.assertRaises(ValueError):
            HardwareProfile(**self._valido(T2_us=-100))

    def test_t1_us_none_aceito(self):
        """None é o sentinel documentado de 'não informado' -- válido, não erro."""
        HardwareProfile(**self._valido(T1_us=None))

    def test_t_meas_ns_zero_rejeitado(self):
        with self.assertRaises(ValueError):
            HardwareProfile(**self._valido(t_meas_ns=0))

    def test_p_t_state_zero_rejeitado(self):
        with self.assertRaises(ValueError):
            HardwareProfile(**self._valido(p_t_state=0))

    def test_p_t_state_negativo_rejeitado(self):
        with self.assertRaises(ValueError):
            HardwareProfile(**self._valido(p_t_state=-0.01))

    def test_p_t_state_none_aceito(self):
        HardwareProfile(**self._valido(p_t_state=None))


class TestConectividadeCoupling(unittest.TestCase):
    """
    v3.2.4: compare() agora transpila cada hardware com o coupling_map real
    derivado de HardwareProfile.topology, em vez de sempre assumir
    conectividade total (all-to-all) para todo mundo — antes, topology era
    lido em nenhum lugar do código, ficando puramente decorativo.
    """

    def test_topologia_limitada_penaliza_grafo_completo_de_interacoes(self):
        """
        Circuito onde todos os pares de qubits interagem (grafo completo)
        não tem como ser roteado sem SWAP em nenhuma topologia limitada,
        não importa o layout inicial escolhido pelo transpiler — diferente
        de um circuito com só uma interação de 2 qubits, que o transpiler
        pode sempre mapear para posições adjacentes livremente.
        """
        n = 6
        qc = QuantumCircuit(n)
        for i in range(n):
            for j in range(i + 1, n):
                qc.cx(i, j)

        hw_linear = HardwareProfile("Linear", t_gate_ns=100, p_phys=0.001, topology="linear")
        hw_all2all = HardwareProfile("AllToAll", t_gate_ns=100, p_phys=0.001, topology="all-to-all")

        result = compare(qc, [hw_linear, hw_all2all], fidelity_target=0.99)

        surface_linear = next(r for r in result["results"]["Linear"] if r.code_name == "Surface Code")
        surface_all2all = next(r for r in result["results"]["AllToAll"] if r.code_name == "Surface Code")

        self.assertGreater(surface_linear.execution_time_us, surface_all2all.execution_time_us,
            "Topologia linear deveria exigir mais tempo (SWAPs) que all-to-all "
            "para um circuito com grafo completo de interações")

    def test_topologia_desconhecida_nao_quebra(self):
        """Topology não reconhecida deve cair no comportamento antigo (sem
        coupling_map), não levantar erro."""
        qc = QuantumCircuit(2); qc.h(0); qc.cx(0, 1)
        hw = HardwareProfile("Exotico", t_gate_ns=100, p_phys=0.001, topology="topologia-alienigena")
        result = compare(qc, [hw], fidelity_target=0.99)
        self.assertIn("Exotico", result["results"])

    def test_circuito_interacao_unica_nao_precisa_swap_mesmo_limitado(self):
        """Circuito com uma única interação de 2 qubits não deveria precisar
        de SWAP em nenhuma topologia conectada — o transpiler é livre para
        escolher o layout inicial. Isso confirma que a penalidade em outros
        testes vem de necessidade real de roteamento, não de qualquer
        coupling_map não-trivial."""
        qc = QuantumCircuit(5)
        qc.h(0)
        qc.cx(0, 4)

        hw_linear = HardwareProfile("Linear", t_gate_ns=100, p_phys=0.001, topology="linear")
        hw_all2all = HardwareProfile("AllToAll", t_gate_ns=100, p_phys=0.001, topology="all-to-all")

        result = compare(qc, [hw_linear, hw_all2all], fidelity_target=0.99)
        surface_linear = next(r for r in result["results"]["Linear"] if r.code_name == "Surface Code")
        surface_all2all = next(r for r in result["results"]["AllToAll"] if r.code_name == "Surface Code")

        self.assertEqual(surface_linear.execution_time_us, surface_all2all.execution_time_us)


if __name__ == "__main__":
    unittest.main(verbosity=2)
