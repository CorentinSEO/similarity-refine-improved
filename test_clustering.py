import pandas as pd
import pytest

from clustering import (
    build_clusters,
    clean_volume_column,
    parse_keywords,
    summarize_row,
    validate_columns,
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
