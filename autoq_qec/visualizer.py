"""
AutoQ QEC — visualização de trade-offs qubits × tempo × fidelidade.
Dependência opcional: matplotlib (pip install "autoq-qec[viz]").
"""

_MARKERS = {
    "Surface Code": "o",
    "Bacon-Shor": "s",
    "Steane [[7,1,3]]": "^",
    "Floquet Code": "*",
}


def plot_tradeoff(compare_result: dict, output: str = None, ax=None):
    """
    Gráfico log-log de qubits físicos × tempo de execução para todas as
    combinações viáveis hardware+código de um compare(). Cor = fidelidade
    do circuito, marcador = código QEC.

    - output: se fornecido, salva PNG nesse caminho.
    - ax: eixo matplotlib existente para desenhar (opcional); se omitido,
      cria uma figura nova e a exibe (a menos que `output` seja passado).
    """
    try:
        import matplotlib.pyplot as plt
        import matplotlib.colors as mcolors
    except ImportError:
        raise ImportError('pip install matplotlib (ou: pip install "autoq-qec[viz]")')

    points = [
        (hw_name, r)
        for hw_name, code_results in compare_result["results"].items()
        for r in code_results
        if r.feasible
    ]
    if not points:
        raise ValueError("Nenhuma combinação hardware+código viável para plotar")

    fids = [r.fidelity_circuit for _, r in points]
    f_min, f_max = min(fids), max(fids)
    norm = mcolors.Normalize(vmin=f_min, vmax=f_max) if f_min != f_max else mcolors.Normalize(vmin=f_min - 1e-9, vmax=f_max + 1e-9)
    cmap = plt.get_cmap("RdYlGn")

    created_fig = ax is None
    if created_fig:
        fig, ax = plt.subplots(figsize=(8, 6))

    for hw_name, r in points:
        marker = _MARKERS.get(r.code_name, "x")
        color = cmap(norm(r.fidelity_circuit))
        ax.scatter(
            r.total_physical_qubits, r.execution_time_us,
            marker=marker, color=color, s=110,
            edgecolors="black", linewidths=0.6,
        )
        ax.annotate(
            f"{hw_name}\n{r.code_name}",
            (r.total_physical_qubits, r.execution_time_us),
            fontsize=7, xytext=(5, 5), textcoords="offset points",
        )

    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_xlabel("Qubits físicos totais")
    ax.set_ylabel("Tempo de execução (µs)")
    ax.set_title("AutoQ QEC — trade-off qubits × tempo × fidelidade")

    sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
    sm.set_array([])
    if created_fig:
        fig.colorbar(sm, ax=ax, label="Fidelidade do circuito")

    if output:
        plt.savefig(output, dpi=150, bbox_inches="tight")
        if created_fig:
            plt.close(fig)
    elif created_fig:
        plt.show()

    return ax
