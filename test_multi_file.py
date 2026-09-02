"""Tests pour le traitement multi-fichiers (voir clustering.process_dataframe,
combine_cluster_results, to_excel_bytes et to_excel_bytes_multi).

Ces tests vérifient en particulier que les fichiers restent isolés les uns
des autres : aucune relation de similarité ne doit jamais être comparée
entre deux fichiers différents, même traités dans le même run. Ils
vérifient aussi les deux formats d'export disponibles (multi-feuilles et
agrégé en une seule feuille).
"""
import pandas as pd
import pytest

from clustering import (
    _safe_sheet_name,
    combine_cluster_results,
    process_dataframe,
    to_excel_bytes,
    to_excel_bytes_multi,
)


def _sample_df():
    return pd.DataFrame(
        {
            "Mot-clé": ["a", "b", "c"],
            "Vol. mensuel": [100, 80, 60],
            "Liste MC et %": [
                "b (80): 40.00 %",
                "a (100): 40.00 %",
                "",
            ],
        }
    )


def test_process_dataframe_returns_clusters_tagged_with_source():
    result = process_dataframe(_sample_df(), threshold=25.0, source_label="fichier_a.csv")
    assert result["missing_columns"] == []
    assert result["size_error"] is None
    assert result["clusters"] is not None
    assert (result["clusters"]["Fichier source"] == "fichier_a.csv").all()
    assert result["clusters"].columns[0] == "Fichier source"


def test_process_dataframe_reports_missing_columns():
    df = pd.DataFrame({"Mot-clé": ["a"]})
    result = process_dataframe(df, threshold=25.0, source_label="incomplet.csv")
    assert result["clusters"] is None
    assert "Vol. mensuel" in result["missing_columns"]


def test_process_dataframe_reports_size_error():
    df = pd.DataFrame({"Mot-clé": list(range(5)), "Vol. mensuel": [1] * 5, "Liste MC et %": [""] * 5})
    result = process_dataframe(df, threshold=25.0, source_label="trop_gros.csv", max_rows=3)
    assert result["clusters"] is None
    assert result["size_error"] is not None
    assert "5" in result["size_error"]


def test_process_dataframe_detects_duplicates_and_ghosts_independently_per_file():
    df = pd.DataFrame(
        {
            "Mot-clé": ["a", "a"],
            "Vol. mensuel": [100, 999],
            "Liste MC et %": ["ghost (500): 90.00 %", ""],
        }
    )
    result = process_dataframe(df, threshold=25.0, source_label="fichier_b.csv")
    assert result["duplicated_keywords"] == ["a"]
    assert result["ghost_keywords"] == [("ghost", 500)]


def test_combine_cluster_results_concatenates_independent_files():
    result_a = process_dataframe(_sample_df(), threshold=25.0, source_label="fichier_a.csv")
    result_b = process_dataframe(_sample_df(), threshold=25.0, source_label="fichier_b.csv")

    combined = combine_cluster_results(
        {"fichier_a.csv": result_a["clusters"], "fichier_b.csv": result_b["clusters"]}
    )

    assert set(combined["Fichier source"].unique()) == {"fichier_a.csv", "fichier_b.csv"}
    assert len(combined) == len(result_a["clusters"]) + len(result_b["clusters"])


def test_combine_cluster_results_does_not_mix_similarities_across_files():
    """Régression clé du multi-fichiers : deux fichiers contenant les mêmes
    mots-clés mais des relations différentes ne doivent jamais être
    comparés entre eux. Le clustering de chaque fichier doit rester
    strictement identique à ce qu'il serait en traitement isolé."""
    df_a = pd.DataFrame(
        {
            "Mot-clé": ["x", "y"],
            "Vol. mensuel": [100, 50],
            "Liste MC et %": ["y (50): 90.00 %", "x (100): 90.00 %"],
        }
    )
    df_b = pd.DataFrame(
        {
            "Mot-clé": ["x", "y"],
            "Vol. mensuel": [100, 50],
            "Liste MC et %": ["", ""],
        }
    )

    result_a = process_dataframe(df_a, threshold=25.0, source_label="a.csv")
    result_b = process_dataframe(df_b, threshold=25.0, source_label="b.csv")
    combined = combine_cluster_results({"a.csv": result_a["clusters"], "b.csv": result_b["clusters"]})

    cluster_a = combined[combined["Fichier source"] == "a.csv"]
    cluster_b = combined[combined["Fichier source"] == "b.csv"]

    assert len(cluster_a) == 1
    assert len(cluster_b) == 2


def test_combine_cluster_results_empty_dict_returns_empty_dataframe():
    assert combine_cluster_results({}).empty


def test_safe_sheet_name_truncates_long_names():
    name = "a" * 50
    result = _safe_sheet_name(name, set())
    assert len(result) <= 31


def test_safe_sheet_name_replaces_forbidden_characters():
    result = _safe_sheet_name("fichier:test*2024.xlsx", set())
    assert ":" not in result and "*" not in result


def test_safe_sheet_name_deduplicates_identical_names():
    used = set()
    first = _safe_sheet_name("rapport", used)
    second = _safe_sheet_name("rapport", used)
    assert first != second


def test_to_excel_bytes_multi_creates_one_sheet_per_entry():
    """Format d'export 'multi-feuilles' : une feuille par entrée du dict."""
    sheets = {
        "fichier_a.csv": pd.DataFrame({"Mot-clé principal": ["a"], "Volume total du cluster": [100]}),
        "fichier_b.csv": pd.DataFrame({"Mot-clé principal": ["b"], "Volume total du cluster": [50]}),
    }
    excel_bytes = to_excel_bytes_multi(sheets)
    assert isinstance(excel_bytes, bytes)
    assert len(excel_bytes) > 0

    import io
    workbook = pd.ExcelFile(io.BytesIO(excel_bytes))
    assert workbook.sheet_names == ["fichier_a.csv", "fichier_b.csv"]


def test_to_excel_bytes_produces_single_aggregated_sheet():
    """Format d'export 'agrégé' : une seule feuille avec toutes les lignes
    de tous les fichiers (via combine_cluster_results en amont)."""
    result_a = process_dataframe(_sample_df(), threshold=25.0, source_label="fichier_a.csv")
    result_b = process_dataframe(_sample_df(), threshold=25.0, source_label="fichier_b.csv")
    combined = combine_cluster_results(
        {"fichier_a.csv": result_a["clusters"], "fichier_b.csv": result_b["clusters"]}
    )

    excel_bytes = to_excel_bytes(combined)

    import io
    workbook = pd.ExcelFile(io.BytesIO(excel_bytes))
    assert workbook.sheet_names == ["Clusters"]
    reloaded = pd.read_excel(io.BytesIO(excel_bytes), sheet_name="Clusters")
    assert len(reloaded) == len(combined)
    assert set(reloaded["Fichier source"].unique()) == {"fichier_a.csv", "fichier_b.csv"}
