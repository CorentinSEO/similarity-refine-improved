"""Tests du module expérimental clustering_leiden.

Ces tests reprennent volontairement les mêmes scénarios que ceux utilisés
pour valider Louvain (voir test_clustering.py), afin de permettre une
comparaison directe des deux algorithmes une fois exécutés par la CI.

Nécessitent python-igraph et leidenalg (voir requirements-dev.txt). Si ces
paquets ne sont pas installés, les tests de ce fichier sont ignorés (skip)
plutôt que de faire échouer toute la suite.
"""
import time

import pandas as pd
import pytest

_leiden_module = pytest.importorskip(
    "clustering_leiden", reason="python-igraph / leidenalg non installes"
)
build_clusters_leiden = _leiden_module.build_clusters_leiden


def test_leiden_merges_transitive_chain():
    """Même scénario que test_build_clusters_merges_transitive_chain
    (Louvain) : une chaîne A~B, B~C, B~D doit être fusionnée en un cluster,
    E isolé doit rester seul."""
    df = pd.DataFrame(
        {
            "Mot-clé": ["A", "B", "C", "D", "E"],
            "Vol. mensuel": [1000, 500, 100, 700, 50],
            "_entries": [
                [("B", 500, 40.0)],
                [("A", 1000, 40.0), ("C", 100, 40.0), ("D", 700, 40.0)],
                [("B", 500, 40.0)],
                [("B", 500, 40.0)],
                [],
            ],
        }
    )
    result = build_clusters_leiden(df, "Mot-clé", "Vol. mensuel", "_entries")

    assert len(result) == 2
    main_cluster = result[result["Mot-clé principal"] == "A"].iloc[0]
    assert main_cluster["Volume total du cluster"] == 1000 + 500 + 100 + 700
    assert set(main_cluster["Mots-clés fusionnés"].split(", ")) == {"D", "B", "C"}

    isolated = result[result["Mot-clé principal"] == "E"].iloc[0]
    assert isolated["Nb mots-clés fusionnés"] == 0


def test_leiden_resists_weak_bridge_between_dense_groups():
    """Même scénario que test_build_clusters_resists_weak_bridge_between_dense_groups
    (Louvain) : Leiden doit lui aussi résister au pont faible entre deux
    groupes densément connectés."""
    group_a = ["A1", "A2", "A3", "A4"]
    group_b = ["B1", "B2", "B3", "B4"]
    strong_edges = {}
    for i, a in enumerate(group_a):
        for b in group_a[i + 1:]:
            strong_edges[(a, b)] = 80.0
    for i, a in enumerate(group_b):
        for b in group_b[i + 1:]:
            strong_edges[(a, b)] = 80.0

    entries_by_kw = {kw: [] for kw in group_a + group_b}
    for (a, b), sim in strong_edges.items():
        entries_by_kw[a].append((b, 10, sim))
        entries_by_kw[b].append((a, 10, sim))
    entries_by_kw["A1"].append(("B1", 10, 26.0))
    entries_by_kw["B1"].append(("A1", 10, 26.0))

    df = pd.DataFrame(
        {
            "Mot-clé": group_a + group_b,
            "Vol. mensuel": [10] * 8,
            "_entries": [entries_by_kw[kw] for kw in group_a + group_b],
        }
    )
    result = build_clusters_leiden(df, "Mot-clé", "Vol. mensuel", "_entries")

    assert len(result) == 2
    for _, row in result.iterrows():
        members = {row["Mot-clé principal"]} | set(
            row["Mots-clés fusionnés"].split(", ") if row["Mots-clés fusionnés"] else []
        )
        assert members == set(group_a) or members == set(group_b)


def test_leiden_average_similarity_is_correct():
    """Même scénario que test_build_clusters_average_similarity_is_correct
    (Louvain)."""
    df = pd.DataFrame(
        {
            "Mot-clé": ["A", "B", "C"],
            "Vol. mensuel": [100, 80, 60],
            "_entries": [
                [("B", 80, 30.0), ("C", 60, 50.0)],
                [("A", 100, 30.0)],
                [("A", 100, 50.0)],
            ],
        }
    )
    result = build_clusters_leiden(df, "Mot-clé", "Vol. mensuel", "_entries")
    assert len(result) == 1
    assert result.iloc[0]["Similarité moyenne (%)"] == 40.0


def test_leiden_no_relations_keeps_all_rows():
    df = pd.DataFrame(
        {
            "Mot-clé": ["A", "B"],
            "Vol. mensuel": [100, 200],
            "_entries": [[], []],
        }
    )
    result = build_clusters_leiden(df, "Mot-clé", "Vol. mensuel", "_entries")
    assert len(result) == 2
    assert (result["Nb mots-clés fusionnés"] == 0).all()


def test_leiden_scales_within_max_rows_limit():
    """Même scénario que test_build_clusters_scales_within_max_rows_limit
    (Louvain) : 1000 mots-clés, densité de relations réaliste. Timeout
    généreux (5s) tant que le profil de performance réel de Leiden n'a pas
    été observé (première exécution via la CI)."""
    import random

    random.seed(0)
    n = 1000
    keywords = [f"kw{i}" for i in range(n)]
    rows = []
    for kw in keywords:
        n_rel = random.randint(0, 15)
        others = random.sample([k for k in keywords if k != kw], min(n_rel, n - 1))
        entries = [(o, 10, float(random.randint(10, 90))) for o in others]
        rows.append({"Mot-clé": kw, "Vol. mensuel": random.randint(10, 1000), "_entries": entries})
    df = pd.DataFrame(rows)

    start = time.perf_counter()
    result = build_clusters_leiden(df, "Mot-clé", "Vol. mensuel", "_entries")
    elapsed = time.perf_counter() - start

    assert len(result) > 0
    assert elapsed < 5.0
