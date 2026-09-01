"""Implémentation expérimentale du clustering par l'algorithme de Leiden.

Leiden (Traag, Waltman & van Eck, 2019) est le successeur direct de Louvain :
il corrige un défaut théorique connu de Louvain (qui peut occasionnellement
produire des communautés internes mal connectées) en garantissant que chaque
communauté retournée est toujours connexe, pour une vitesse comparable ou
meilleure.

Ce module est volontairement séparé de clustering.py : il dépend de
igraph et leidenalg, deux paquets plus lourds (igraph a une extension
compilée) qui ne sont pour l'instant que des dépendances de développement
(voir requirements-dev.txt), en attente de validation par la CI avant un
éventuel passage en production à la place de build_clusters() (Louvain).
"""
from __future__ import annotations

import igraph as ig
import leidenalg as la
import networkx as nx
import pandas as pd

LEIDEN_SEED = 42


def build_clusters_leiden(df: pd.DataFrame, keyword_col: str, volume_col: str, entries_col: str) -> pd.DataFrame:
    """Regroupe les mots-clés en clusters via l'algorithme de Leiden.

    Interface et format de sortie strictement identiques à
    clustering.build_clusters (Louvain), pour permettre une comparaison
    directe des deux algorithmes sur un même fichier.
    """
    known_keywords = set(df[keyword_col])
    edge_similarities: dict[tuple[str, str], float] = {}

    for _, row in df.iterrows():
        primary = row[keyword_col]
        for keyword, _volume, similarity in row[entries_col]:
            if keyword in known_keywords and keyword != primary:
                pair = tuple(sorted((primary, keyword)))
                edge_similarities[pair] = max(edge_similarities.get(pair, 0), similarity)

    nx_graph = nx.Graph()
    nx_graph.add_nodes_from(known_keywords)
    for (a, b), similarity in edge_similarities.items():
        nx_graph.add_edge(a, b, weight=similarity)

    ig_graph = ig.Graph.from_networkx(nx_graph)

    # Le nom d'origine du noeud networkx est conservé par igraph, mais le nom
    # de l'attribut a varié selon les versions ("_nx_name" ou "name").
    name_attr = "_nx_name" if "_nx_name" in ig_graph.vs.attributes() else "name"

    if ig_graph.ecount() > 0:
        # leidenalg leve un KeyError sur l'attribut d'arete "weight" si le
        # graphe n'a aucune arete (l'attribut n'a alors jamais ete cree).
        partition = la.find_partition(
            ig_graph,
            la.RBConfigurationVertexPartition,
            weights="weight",
            seed=LEIDEN_SEED,
        )
        communities = [
            {ig_graph.vs[idx][name_attr] for idx in community} for community in partition
        ]
    else:
        # Aucune relation de similarite retenue : chaque mot-cle est isole.
        communities = [{ig_graph.vs[idx][name_attr]} for idx in range(ig_graph.vcount())]

    community_index: dict[str, int] = {}
    for idx, members in enumerate(communities):
        for member in members:
            community_index[member] = idx

    cluster_similarities: dict[int, list[float]] = {}
    for (a, b), similarity in edge_similarities.items():
        idx = community_index[a]
        cluster_similarities.setdefault(idx, []).append(similarity)

    volume_map = dict(zip(df[keyword_col], df[volume_col]))
    rows = []
    for members in communities:
        members_sorted = sorted(members, key=lambda m: volume_map.get(m, 0), reverse=True)
        representative = members_sorted[0]
        merged = members_sorted[1:]
        total_volume = sum(volume_map.get(m, 0) for m in members_sorted)

        idx = community_index[representative]
        sims = cluster_similarities.get(idx, [])
        avg_sim = sum(sims) / len(sims) if sims else 0.0

        rows.append(
            {
                "Mot-clé principal": representative,
                "Volume mot-clé principal": volume_map.get(representative, 0),
                "Mots-clés fusionnés": ", ".join(merged) if merged else "",
                "Nb mots-clés fusionnés": len(merged),
                "Volume total du cluster": total_volume,
                "Similarité moyenne (%)": round(avg_sim, 2),
            }
        )

    result = pd.DataFrame(rows).sort_values("Volume total du cluster", ascending=False)
    return result.reset_index(drop=True)
