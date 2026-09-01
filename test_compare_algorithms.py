"""Comparaison qualitative Leiden vs Louvain sur des fichiers reels.

Ce test n'est pas un test de non-regression classique : il imprime un
rapport comparatif detaille dans les logs de la CI (voir le flag -s ajoute
a la commande pytest dans .github/workflows/tests.yml), afin de permettre
une inspection humaine des differences entre les deux algorithmes sur des
fichiers SEO reels (Italie, Pouilles), au-dela des assertions automatiques.

Ignore (skip) si python-igraph / leidenalg ne sont pas installes.
"""
import pandas as pd
import pytest

from clustering import parse_keywords, build_clusters

leiden_module = pytest.importorskip(
    "clustering_leiden", reason="python-igraph / leidenalg non installes"
)
build_clusters_leiden = leiden_module.build_clusters_leiden

THRESHOLD = 25.0
FIXTURES = {
    "Italie": "fixtures/italie.csv",
    "Pouilles": "fixtures/pouilles.csv",
}


def _prepare(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["_entries"] = df["Liste MC et %"].apply(lambda x: parse_keywords(x, THRESHOLD))
    return df


def _report(name: str, result: pd.DataFrame) -> dict:
    sizes = sorted(result["Nb mots-clés fusionnés"].tolist(), reverse=True)
    biggest_row = result.loc[result["Nb mots-clés fusionnés"].idxmax()]
    biggest_members = {biggest_row["Mot-clé principal"]} | set(
        biggest_row["Mots-clés fusionnés"].split(", ") if biggest_row["Mots-clés fusionnés"] else []
    )
    mixes_bari_pouilles = any("bari" in str(m) for m in biggest_members) and any(
        "pouilles" in str(m) for m in biggest_members
    )
    return {
        "algo": name,
        "nb_clusters": len(result),
        "top5_tailles_fusion": sizes[:5],
        "plus_gros_cluster": sorted(biggest_members),
        "melange_bari_pouilles": mixes_bari_pouilles,
    }


def test_compare_leiden_vs_louvain_on_real_files():
    print("\n" + "=" * 78)
    print("COMPARAISON QUALITATIVE : LOUVAIN vs LEIDEN (seuil 25%)")
    print("=" * 78)

    for file_label, path in FIXTURES.items():
        df = _prepare(path)

        louvain_result = build_clusters(df, "Mot-clé", "Vol. mensuel", "_entries")
        leiden_result = build_clusters_leiden(df, "Mot-clé", "Vol. mensuel", "_entries")

        louvain_report = _report("Louvain", louvain_result)
        leiden_report = _report("Leiden", leiden_result)

        print(f"\n--- Fichier : {file_label} ({len(df)} mots-clés) ---")
        for report in (louvain_report, leiden_report):
            print(
                f"  {report['algo']:8} | clusters: {report['nb_clusters']:4} | "
                f"top5 tailles fusion: {report['top5_tailles_fusion']} | "
                f"melange bari/pouilles: {report['melange_bari_pouilles']}"
            )
            print(f"           plus gros cluster: {report['plus_gros_cluster']}")

        if file_label == "Pouilles":
            assert not leiden_report["melange_bari_pouilles"], (
                "Leiden ne devrait pas melanger les entites bari/pouilles "
                "dans son plus gros cluster, comme Louvain."
            )

    print("\n" + "=" * 78)
