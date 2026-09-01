import time

import pandas as pd
import pytest

from clustering import (
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
    même si A~C ou A~D ne sont jamais explicitement listés (cas que
    l'ancienne logique de déduplication un-à-un ne détectait pas)."""
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


def test_validate_row_count_under_limit_returns_none():
    df = pd.DataFrame({"Mot-clé": ["a", "b"]})
    assert validate_row_count(df, max_rows=10) is None


def test_validate_row_count_over_limit_returns_message():
    df = pd.DataFrame({"Mot-clé": list(range(15))})
    message = validate_row_count(df, max_rows=10)
    assert message is not None
    assert "15" in message


def test_build_clusters_average_similarity_matches_bruteforce():
    """Non-régression : la version optimisée (bucketing en un seul passage sur
    les arêtes, O(E)) doit renvoyer exactement la même similarité moyenne que
    l'ancienne implémentation en force brute (O(k²) par cluster)."""
    df = pd.DataFrame(
        {
            "Mot-clé": ["A", "B", "C", "D"],
            "Vol. mensuel": [100, 80, 60, 40],
            "_entries": [
                [("B", 80, 30.0), ("C", 60, 50.0)],
                [("A", 100, 30.0), ("D", 40, 70.0)],
                [("A", 100, 50.0)],
                [("B", 80, 70.0)],
            ],
        }
    )

    from clustering import UnionFind

    known = set(df["Mot-clé"])
    uf = UnionFind(known)
    edge_similarities = {}
    for _, row in df.iterrows():
        primary = row["Mot-clé"]
        for keyword, _volume, similarity in row["_entries"]:
            if keyword in known and keyword != primary:
                uf.union(primary, keyword)
                pair = tuple(sorted((primary, keyword)))
                edge_similarities[pair] = max(edge_similarities.get(pair, 0), similarity)

    clusters = {}
    for kw in known:
        clusters.setdefault(uf.find(kw), []).append(kw)

    brute_force_avg = {}
    for root, members in clusters.items():
        sims = [
            edge_similarities[tuple(sorted((a, b)))]
            for i, a in enumerate(members)
            for b in members[i + 1 :]
            if tuple(sorted((a, b))) in edge_similarities
        ]
        brute_force_avg[root] = sum(sims) / len(sims) if sims else 0.0

    result = build_clusters(df, "Mot-clé", "Vol. mensuel", "_entries")
    for _, row in result.iterrows():
        root = uf.find(row["Mot-clé principal"])
        assert row["Similarité moyenne (%)"] == round(brute_force_avg[root], 2)


def test_build_clusters_scales_on_large_interconnected_cluster():
    """Non-régression de performance : un cluster de 300 mots-clés tous liés
    entre eux doit se calculer en moins d'une seconde grâce au bucketing en
    un seul passage sur les arêtes (au lieu d'une comparaison par paires)."""
    n = 300
    keywords = [f"kw{i}" for i in range(n)]
    rows = []
    for i, kw in enumerate(keywords):
        others = " | ".join(f"{o} (10): 30.00 %" for o in keywords if o != kw)
        rows.append({"Mot-clé": kw, "Vol. mensuel": 10, "Liste MC et %": others})
    df = pd.DataFrame(rows)
    df["_entries"] = df["Liste MC et %"].apply(lambda x: parse_keywords(x, 25))

    start = time.perf_counter()
    result = build_clusters(df, "Mot-clé", "Vol. mensuel", "_entries")
    elapsed = time.perf_counter() - start

    assert len(result) == 1
    assert elapsed < 1.0


def test_load_and_clean_impl_merges_duplicates_and_flags_ghosts():
    """Vérifie l'intégration bout-à-bout : _load_and_clean_impl doit à la fois
    fusionner les mots-clés dupliqués et signaler les mots-clés fantômes,
    sans dépendre du décorateur de cache Streamlit."""
    import io

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
    from clustering import build_clusters, parse_keywords
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
