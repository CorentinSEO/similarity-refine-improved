"""Fonctions pures de parsing, nettoyage et clustering pour Similarity Refine.

Ce module ne dépend pas de Streamlit afin de rester testable unitairement
(voir tests/test_clustering.py) et réutilisable en dehors de l'UI.
"""
from __future__ import annotations

import io
import re
from typing import Iterable

import pandas as pd

REQUIRED_COLUMNS = ["Mot-clé", "Vol. mensuel", "Liste MC et %"]

KEYWORD_PATTERN = re.compile(r"(.+?)\s*\((\d+)\)\s*:\s*([\d.,]+)\s*%")


# ---------------------------------------------------------------------------
# Chargement et validation
# ---------------------------------------------------------------------------

def load_uploaded_file(uploaded_file) -> pd.DataFrame:
    """Charge un fichier CSV ou Excel importé via st.file_uploader."""
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(uploaded_file)
    raise ValueError("Format de fichier non supporté. Utilisez un fichier .xlsx, .xls ou .csv.")


def validate_columns(df: pd.DataFrame) -> list[str]:
    """Retourne la liste des colonnes obligatoires manquantes."""
    return [c for c in REQUIRED_COLUMNS if c not in df.columns]


def clean_volume_column(df: pd.DataFrame, volume_col: str = "Vol. mensuel") -> pd.DataFrame:
    """Nettoie la colonne de volume : supprime les espaces (séparateurs de
    milliers), remplace les virgules décimales et convertit en numérique.
    Les valeurs invalides deviennent 0 au lieu de faire planter l'app.
    """
    df = df.copy()
    cleaned = (
        df[volume_col]
        .astype(str)
        .str.replace("\u00a0", "", regex=False)  # espace insécable
        .str.replace(" ", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    df[volume_col] = pd.to_numeric(cleaned, errors="coerce").fillna(0).astype(int)
    return df


# ---------------------------------------------------------------------------
# Parsing des mots-clés similaires
# ---------------------------------------------------------------------------

def parse_keywords(list_str: str, threshold: float) -> list[tuple[str, int, float]]:
    """Parse la colonne 'Liste MC et %' et retourne les mots-clés secondaires
    dont la similarité est >= threshold, sous forme de tuples
    (keyword, volume, similarity). Tolère les décimales avec point ou virgule.
    """
    if not isinstance(list_str, str) or not list_str.strip():
        return []

    entries: list[tuple[str, int, float]] = []
    for chunk in list_str.split("|"):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = KEYWORD_PATTERN.match(chunk)
        if not match:
            continue
        keyword, volume, similarity = match.groups()
        try:
            volume = int(volume)
            similarity = float(similarity.replace(",", "."))
        except ValueError:
            continue
        if similarity >= threshold:
            entries.append((keyword.strip(), volume, similarity))
    return entries


def summarize_row(entries: Iterable[tuple[str, int, float]]):
    """Calcule volume total, similarité moyenne et nombre de mots-clés retenus
    pour une ligne, à partir des entrées renvoyées par parse_keywords."""
    entries = list(entries)
    if not entries:
        return [], 0, 0.0, 0
    total_volume = sum(e[1] for e in entries)
    avg_similarity = sum(e[2] for e in entries) / len(entries)
    formatted = [f"{k} ({v}): {s:.2f} %" for k, v, s in entries]
    return formatted, total_volume, avg_similarity, len(entries)


# ---------------------------------------------------------------------------
# Clustering par composantes connexes
# ---------------------------------------------------------------------------

class UnionFind:
    """Structure union-find (disjoint-set) avec compression de chemin."""

    def __init__(self, items: Iterable[str]):
        self.parent = {item: item for item in items}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def build_clusters(df: pd.DataFrame, keyword_col: str, volume_col: str, entries_col: str) -> pd.DataFrame:
    """Regroupe les mots-clés en clusters (composantes connexes) à partir des
    relations de similarité retenues, au lieu d'une simple suppression de
    doublons un-à-un. Un cluster peut ainsi fusionner des chaînes A~B~C~D.

    Les mots-clés dupliqués dans keyword_col sont dédupliqués en amont ; le
    dernier volume rencontré pour un doublon est celui conservé.
    """
    known_keywords = set(df[keyword_col])
    uf = UnionFind(known_keywords)
    edge_similarities: dict[tuple[str, str], float] = {}

    for _, row in df.iterrows():
        primary = row[keyword_col]
        for keyword, _volume, similarity in row[entries_col]:
            if keyword in known_keywords and keyword != primary:
                uf.union(primary, keyword)
                pair = tuple(sorted((primary, keyword)))
                edge_similarities[pair] = max(edge_similarities.get(pair, 0), similarity)

    clusters: dict[str, list[str]] = {}
    for kw in known_keywords:
        root = uf.find(kw)
        clusters.setdefault(root, []).append(kw)

    volume_map = dict(zip(df[keyword_col], df[volume_col]))
    rows = []
    for members in clusters.values():
        members_sorted = sorted(members, key=lambda m: volume_map.get(m, 0), reverse=True)
        representative = members_sorted[0]
        merged = members_sorted[1:]
        total_volume = sum(volume_map.get(m, 0) for m in members_sorted)

        sims = [
            edge_similarities[tuple(sorted((a, b)))]
            for i, a in enumerate(members_sorted)
            for b in members_sorted[i + 1:]
            if tuple(sorted((a, b))) in edge_similarities
        ]
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


# ---------------------------------------------------------------------------
# Export en mémoire
# ---------------------------------------------------------------------------

def to_excel_bytes(df: pd.DataFrame) -> bytes:
    """Génère un fichier Excel en mémoire (aucune écriture disque)."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Clusters")
    return buffer.getvalue()
