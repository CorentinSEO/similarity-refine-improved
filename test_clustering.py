import time

import pandas as pd
import pytest

from clustering import (
    MAX_ROWS,
    build_clusters,
    clean_volume_column,
    deduplicate_keywords,
    find_ghost_keywords,
    parse_keywords,
    summarize_row,
    validate_columns,
    validate_row_count,
)


def test_parse_keywords_basic():
    entries = parse_keywords("chat noir (100): 50.00 % | chien noir (40): 10.00 %", threshold=30)
    assert entries == [("chat noir", 100, 50.0)]


def test_parse_keywords_tolerates_comma_decimal():
    entries = parse_keywords("chat noir (100): 50,00 %", threshold=10)
    assert entries == [("chat noir", 100, 50.0)]


def test_parse_keywords_empty_or_invalid():
    assert parse_keywords(None, 10) == []
    assert parse_keywords("", 10) == []
    assert parse_keywords("texte sans le bon format", 10) == []


def test_summarize_row():
    entries = [("a", 100, 50.0), ("b", 50, 30.0)]
    formatted, total_volume, avg_similarity, count = summarize_row(entries)
    assert total_volume == 150
    assert avg_similarity == 40.0
    assert count == 2
    assert formatted == ["a (100): 50.00 %", "b (50): 30.00 %"]


def test_validate_columns_missing():
    df = pd.DataFrame({"Mot-clé": ["a"], "Vol. mensuel": [10]})
    missing = validate_columns(df)
    assert missing == ["Liste MC et %"]


def test_clean_volume_column_handles_thousands_and_comma():
    df = pd.DataFrame({"Vol. mensuel": ["8 100", "1,5", "abc", None]})
    cleaned = clean_volume_column(df, "Vol. mensuel")
    assert cleaned["Vol. mensuel"].tolist() == [8100, 1, 0, 0]


def test_build_clusters_merges_transitive_chain():
    """Vérifie qu'une chaîne A~B, B~C, B~D est fusionnée en un seul cluster,
    même si A~C ou A~D ne sont jamais explicitement listés."""
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
    result = build_clusters(df, "Mot-clé", "Vol. mensuel", "_entries")

    assert len(result) == 2  # cluster {A,B,C,D} + cluster isolé {E}
    main_cluster = result[result["Mot-clé principal"] == "A"].iloc[0]
    assert main_cluster["Volume total du cluster"] == 1000 + 500 + 100 + 700
    assert set(main_cluster["Mots-clés fusionnés"].split(", ")) == {"D", "B", "C"}

    isolated = result[result["Mot-clé principal"] == "E"].iloc[0]
    assert isolated["Nb mots-clés fusionnés"] == 0


def test_build_clusters_no_relations_keeps_all_rows():
    df = pd.DataFrame(
        {
            "Mot-clé": ["A", "B"],
            "Vol. mensuel": [100, 200],
            "_entries": [[], []],
        }
    )
    result = build_clusters(df, "Mot-clé", "Vol. mensuel", "_entries")
    assert len(result) == 2
    assert (result["Nb mots-clés fusionnés"] == 0).all()


def test_build_clusters_resists_weak_bridge_between_dense_groups():
    """Régression clé du passage à Louvain : deux groupes densément
    connectés reliés par UN pont faible (mais au-dessus du seuil) ne
    doivent PAS être fusionnés en un seul cluster. L'ancien algorithme par
    composantes connexes (union-find) fusionnait tout dès qu'une chaîne de
    relations existait, même très faible sur un seul lien ; Louvain
    privilégie la densité de connexions internes et résiste à ce pont
    isolé, produisant deux clusters distincts et sémantiquement cohérents.
    """
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
    # Pont faible entre les deux groupes, juste au-dessus du seuil retenu (25 %).
    entries_by_kw["A1"].append(("B1", 10, 26.0))
    entries_by_kw["B1"].append(("A1", 10, 26.0))

    df = pd.DataFrame(
        {
            "Mot-clé": group_a + group_b,
            "Vol. mensuel": [10] * 8,
            "_entries": [entries_by_kw[kw] for kw in group_a + group_b],
        }
    )
    result = build_clusters(df, "Mot-clé", "Vol. mensuel", "_entries")

    assert len(result) == 2  # et non 1 cluster fusionné de 8 mots-clés
    for _, row in result.iterrows():
        members = {row["Mot-clé principal"]} | set(
            row["Mots-clés fusionnés"].split(", ") if row["Mots-clés fusionnés"] else []
        )
        assert members == set(group_a) or members == set(group_b)


def test_build_clusters_average_similarity_is_correct():
    """Vérifie que la similarité moyenne d'un cluster est bien la moyenne
    des relations internes au cluster (et non des relations externes)."""
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
    result = build_clusters(df, "Mot-clé", "Vol. mensuel", "_entries")
    assert len(result) == 1
    assert result.iloc[0]["Similarité moyenne (%)"] == 40.0  # moyenne de 30.0 et 50.0


def test_deduplicate_keywords_no_duplicates_returns_same_rows():
    df = pd.DataFrame(
        {
            "Mot-clé": ["a", "b"],
            "Vol. mensuel": [100, 50],
            "Liste MC et %": ["b (50): 40.00 %", ""],
        }
    )
    deduped, duplicates = deduplicate_keywords(df)
    assert duplicates == []
    assert len(deduped) == 2


def test_deduplicate_keywords_merges_volume_and_relations():
    """Reproduit le bug corrigé : un mot-clé dupliqué ne doit plus perdre de
    volume ni de relations de similarité silencieusement."""
    df = pd.DataFrame(
        {
            "Mot-clé": ["a", "a", "b"],
            "Vol. mensuel": [100, 999, 50],
            "Liste MC et %": ["b (50): 40.00 %", "", ""],
        }
    )
    deduped, duplicates = deduplicate_keywords(df)
    assert duplicates == ["a"]
    assert len(deduped) == 2

    row_a = deduped[deduped["Mot-clé"] == "a"].iloc[0]
    assert row_a["Vol. mensuel"] == 999  # volume maximal conservé
    assert row_a["Liste MC et %"] == "b (50): 40.00 %"  # relation conservée


def test_find_ghost_keywords_detects_missing_reference():
    df = pd.DataFrame(
        {
            "Mot-clé": ["a"],
            "Liste MC et %": ["ghost keyword (500): 90.00 % | a (100): 50.00 %"],
        }
    )
    ghosts = find_ghost_keywords(df)
    assert ghosts == [("ghost keyword", 500)]


def test_find_ghost_keywords_empty_when_all_present():
    df = pd.DataFrame(
        {
            "Mot-clé": ["a", "b"],
            "Liste MC et %": ["b (50): 40.00 %", "a (100): 40.00 %"],
        }
    )
    assert find_ghost_keywords(df) == []


def test_max_rows_constant_is_1000():
    """Verrouille la contrainte produit : 1000 lignes maximum par fichier importe."""
    assert MAX_ROWS == 1000


def test_validate_row_count_under_limit_returns_none():
    df = pd.DataFrame({"Mot-clé": ["a", "b"]})
    assert validate_row_count(df, max_rows=10) is None


def test_validate_row_count_over_limit_returns_message():
    df = pd.DataFrame({"Mot-clé": list(range(15))})
    message = validate_row_count(df, max_rows=10)
    assert message is not None
    assert "15" in message


def test_validate_row_count_uses_default_max_rows_of_1000():
    df = pd.DataFrame({"Mot-clé": list(range(1001))})
    assert validate_row_count(df) is not None
    df_ok = pd.DataFrame({"Mot-clé": list(range(1000))})
    assert validate_row_count(df_ok) is None


def test_build_clusters_scales_within_max_rows_limit():
    """Non-régression de performance : au volume maximal supporté (1000
    mots-clés, MAX_ROWS), même avec une densité de relations élevée, le
    clustering Louvain doit rester praticable (quelques centaines de ms au
    plus) pour une UI Streamlit interactive."""
    import random

    random.seed(0)
    n = MAX_ROWS
    keywords = [f"kw{i}" for i in range(n)]
    rows = []
    for kw in keywords:
        n_rel = random.randint(0, 15)
        others = random.sample([k for k in keywords if k != kw], min(n_rel, n - 1))
        entries = [(o, 10, float(random.randint(10, 90))) for o in others]
        rows.append({"Mot-clé": kw, "Vol. mensuel": random.randint(10, 1000), "_entries": entries})
    df = pd.DataFrame(rows)

    start = time.perf_counter()
    result = build_clusters(df, "Mot-clé", "Vol. mensuel", "_entries")
    elapsed = time.perf_counter() - start

    assert len(result) > 0
    assert elapsed < 3.0


def test_load_and_clean_impl_merges_duplicates_and_flags_ghosts():
    """Vérifie l'intégration bout-à-bout : _load_and_clean_impl doit à la fois
    fusionner les mots-clés dupliqués et signaler les mots-clés fantômes,
    sans dépendre du décorateur de cache Streamlit."""
    from streamlit_app import _load_and_clean_impl

    csv_content = (
        "Mot-clé,Vol. mensuel,Liste MC et %\n"
        "a,100,\n"
        "a,999,ghost (500): 90.00 %\n"
        "b,50,\n"
    ).encode("utf-8")

    df, missing, duplicated, ghosts, size_error = _load_and_clean_impl(csv_content, "test.csv")

    assert missing == []
    assert size_error is None
    assert duplicated == ["a"]
    assert ghosts == [("ghost", 500)]

    row_a = df[df["Mot-clé"] == "a"].iloc[0]
    assert row_a["Vol. mensuel"] == 999


def test_cluster_impl_matches_build_clusters_directly():
    """Vérifie que _cluster_impl (fonction pure sous-jacente, hors cache
    Streamlit) produit le même résultat qu'un appel direct à build_clusters."""
    from streamlit_app import _cluster_impl

    df = pd.DataFrame(
        {
            "Mot-clé": ["a", "b"],
            "Vol. mensuel": [100, 50],
            "Liste MC et %": ["b (50): 40.00 %", ""],
        }
    )

    result = _cluster_impl(df, 25.0)

    df_expected = df.copy()
    df_expected["_entries"] = df_expected["Liste MC et %"].apply(lambda x: parse_keywords(x, 25.0))
    expected = build_clusters(df_expected, "Mot-clé", "Vol. mensuel", "_entries")

    pd.testing.assert_frame_equal(
        result.reset_index(drop=True),
        expected.reset_index(drop=True),
    )
