"""Fonctions pures de parsing, nettoyage et clustering pour Similarity Refine.

Ce module ne dépend pas de Streamlit afin de rester testable unitairement
(voir test_clustering.py) et réutilisable en dehors de l'UI.
"""
from __future__ import annotations

import io
from typing import Iterable

import networkx as nx
import pandas as pd
import re

REQUIRED_COLUMNS = ["Mot-clé", "Vol. mensuel", "Liste MC et %"]

KEYWORD_PATTERN = re.compile(r"(.+?)\s*\((\d+)\)\s*:\s*([\d.,]+)\s*%")

# Nombre maximal de lignes supportées par l'application (contrainte produit).
MAX_ROWS = 1000

# Graine fixe pour Louvain : résultats reproductibles d'un run à l'autre sur
# un même fichier (l'algorithme est stochastique par défaut).
LOUVAIN_SEED = 42


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


def validate_row_count(df: pd.DataFrame, max_rows: int = MAX_ROWS) -> str | None:
    """Retourne un message d'erreur si le fichier dépasse la taille maximale
    supportée par l'application, sinon None."""
    if len(df) > max_rows:
        return (
            f"Le fichier contient {len(df):,} lignes, ce qui dépasse la limite "
            f"de {max_rows:,} lignes supportée par cette application. "
            "Scindez le fichier en plusieurs exports plus petits."
        ).replace(",", " ")
    return None


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


def deduplicate_keywords(
    df: pd.DataFrame,
    keyword_col: str = "Mot-clé",
    volume_col: str = "Vol. mensuel",
    entries_col: str = "Liste MC et %",
) -> tuple[pd.DataFrame, list[str]]:
    """Fusionne les lignes ayant le même mot-clé principal avant le clustering.

    Sans cette étape, un mot-clé dupliqué dans le fichier source écrase
    silencieusement le volume et les relations de similarité des autres
    occurrences (seule la dernière ligne rencontrée est conservée). Cette
    fonction :
      - conserve le volume maximal parmi les occurrences dupliquées ;
      - concatène toutes les relations de similarité listées pour ce mot-clé,
        pour ne perdre aucune relation ;
      - retourne la liste des mots-clés dupliqués détectés, pour affichage
        d'un avertissement à l'utilisateur.
    """
    dup_mask = df[keyword_col].duplicated(keep=False)
    duplicated_keywords = sorted(df.loc[dup_mask, keyword_col].astype(str).unique().tolist())
    if not duplicated_keywords:
        return df.reset_index(drop=True), []

    order: list[str] = []
    volumes: dict[str, float] = {}
    entries: dict[str, list[str]] = {}

    for _, row in df.iterrows():
        kw = row[keyword_col]
        vol = row[volume_col]
        entry = row[entries_col]

        if kw not in volumes:
            order.append(kw)
            volumes[kw] = vol if pd.notna(vol) else 0
            entries[kw] = []
        else:
            if pd.notna(vol) and vol > volumes[kw]:
                volumes[kw] = vol

        if isinstance(entry, str) and entry.strip():
            entries[kw].append(entry.strip())

    deduped = pd.DataFrame(
        {
            keyword_col: order,
            volume_col: [volumes[kw] for kw in order],
            entries_col: [" | ".join(entries[kw]) for kw in order],
        }
    )
    return deduped, duplicated_keywords


def find_ghost_keywords(
    df: pd.DataFrame,
    keyword_col: str = "Mot-clé",
    entries_col: str = "Liste MC et %",
) -> list[tuple[str, int]]:
    """Détecte les mots-clés référencés dans la colonne des relations de
    similarité mais qui n'ont jamais leur propre ligne dans keyword_col.

    Ces mots-clés "fantômes" sont ignorés par le clustering (aucun volume
    propre disponible), ce qui peut sous-estimer silencieusement le volume
    réel d'un cluster. Retourne la liste (mot-clé, volume rapporté dans la
    relation) triée par volume décroissant, pour affichage d'un avertissement.
    """
    known = set(df[keyword_col])
    ghosts: dict[str, int] = {}
    for entries_str in df[entries_col]:
        if not isinstance(entries_str, str) or not entries_str.strip():
            continue
        for chunk in entries_str.split("|"):
            chunk = chunk.strip()
            if not chunk:
                continue
            match = KEYWORD_PATTERN.match(chunk)
            if not match:
                continue
            keyword, volume, _similarity = match.groups()
            keyword = keyword.strip()
            if keyword not in known:
                try:
                    volume = int(volume)
                except ValueError:
                    volume = 0
                ghosts[keyword] = max(ghosts.get(keyword, 0), volume)
    return sorted(ghosts.items(), key=lambda kv: kv[1], reverse=True)


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
# Clustering par détection de communautés (Louvain)
# ---------------------------------------------------------------------------

def build_clusters(df: pd.DataFrame, keyword_col: str, volume_col: str, entries_col: str) -> pd.DataFrame:
    """Regroupe les mots-clés en clusters à partir des relations de
    similarité retenues, via l'algorithme de Louvain (détection de
    communautés par optimisation de modularité).

    Les mots-clés dupliqués dans keyword_col doivent avoir été fusionnés au
    préalable via deduplicate_keywords, sinon seule la dernière occurrence de
    volume sera retenue.
    """
    known_keywords = set(df[keyword_col])
    edge_similarities: dict[tuple[str, str], float] = {}

    for _, row in df.iterrows():
        primary = row[keyword_col]
        for keyword, _volume, similarity in row[entries_col]:
            if keyword in known_keywords and keyword != primary:
                pair = tuple(sorted((primary, keyword)))
                edge_similarities[pair] = max(edge_similarities.get(pair, 0), similarity)

    graph = nx.Graph()
    graph.add_nodes_from(known_keywords)
    for (a, b), similarity in edge_similarities.items():
        graph.add_edge(a, b, weight=similarity)

    communities = nx.community.louvain_communities(graph, weight="weight", seed=LOUVAIN_SEED)

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

        rows.append({
            "Mot-clé principal": representative,
            "Volume mot-clé principal": volume_map.get(representative, 0),
            "Mots-clés fusionnés": ", ".join(merged) if merged else "",
            "Nb mots-clés fusionnés": len(merged),
            "Volume total du cluster": total_volume,
            "Similarité moyenne (%)": round(avg_sim, 2),
        })

    result = pd.DataFrame(rows).sort_values("Volume total du cluster", ascending=False)
    return result.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Traitement multi-fichiers (chaque fichier reste isolé des autres)
# ---------------------------------------------------------------------------

def process_dataframe(
    df_raw: pd.DataFrame,
    threshold: float,
    source_label: str = "",
    max_rows: int = MAX_ROWS,
) -> dict:
    """Exécute le pipeline complet (validation, dédoublonnage, mots-clés
    fantômes, nettoyage, clustering Louvain) sur un seul DataFrame déjà
    chargé.

    Cette fonction est le point d'entrée utilisé pour analyser plusieurs
    fichiers en une seule fois : chaque appel reste totalement indépendant
    des autres, aucune relation de similarité n'est jamais comparée entre
    deux fichiers différents.

    Retourne un dict :
      - "clusters" : DataFrame des clusters avec une colonne "Fichier source"
        en première position, ou None si le fichier est invalide.
      - "missing_columns" : colonnes obligatoires manquantes.
      - "duplicated_keywords" : mots-clés dupliqués fusionnés automatiquement.
      - "ghost_keywords" : mots-clés référencés mais jamais présents en ligne
        principale (ignorés du clustering).
      - "size_error" : message d'erreur si le fichier dépasse max_rows.
      - "row_count" : nombre de lignes importées (avant dédoublonnage).
    """
    missing = validate_columns(df_raw)
    if missing:
        return {
            "clusters": None,
            "missing_columns": missing,
            "duplicated_keywords": [],
            "ghost_keywords": [],
            "size_error": None,
            "row_count": len(df_raw),
        }

    size_error = validate_row_count(df_raw, max_rows=max_rows)
    if size_error:
        return {
            "clusters": None,
            "missing_columns": [],
            "duplicated_keywords": [],
            "ghost_keywords": [],
            "size_error": size_error,
            "row_count": len(df_raw),
        }

    df_dedup, duplicated_keywords = deduplicate_keywords(df_raw)
    ghost_keywords = find_ghost_keywords(df_dedup)
    df_clean = clean_volume_column(df_dedup, "Vol. mensuel")

    df_clean = df_clean.copy()
    df_clean["_entries"] = df_clean["Liste MC et %"].apply(lambda x: parse_keywords(x, threshold))
    clusters = build_clusters(df_clean, "Mot-clé", "Vol. mensuel", "_entries")
    clusters.insert(0, "Fichier source", source_label)

    return {
        "clusters": clusters,
        "missing_columns": [],
        "duplicated_keywords": duplicated_keywords,
        "ghost_keywords": ghost_keywords,
        "size_error": None,
        "row_count": len(df_raw),
    }


def combine_cluster_results(results_by_file: "dict[str, pd.DataFrame | None]") -> pd.DataFrame:
    """Concatène les tableaux de clusters de plusieurs fichiers déjà traités
    indépendamment (voir process_dataframe) en un seul tableau de résultats,
    portant la colonne "Fichier source" pour tracer l'origine de chaque
    cluster.

    Ne recalcule et ne mélange aucune similarité entre fichiers : chaque
    ligne du résultat combiné provient d'un clustering réalisé isolément sur
    son propre fichier.
    """
    frames = [df for df in results_by_file.values() if df is not None and not df.empty]
    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    return combined.sort_values(
        ["Fichier source", "Volume total du cluster"], ascending=[True, False]
    ).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Export en mémoire
# ---------------------------------------------------------------------------

def to_excel_bytes(df: pd.DataFrame) -> bytes:
    """Génère un fichier Excel en mémoire (aucune écriture disque), une
    seule feuille "Clusters". Utilisé pour l'export mono-fichier, ou pour
    l'export multi-fichiers en mode "agrégé" (une seule feuille combinée)."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Clusters")
    return buffer.getvalue()


def _safe_sheet_name(name: str, used_names: set) -> str:
    """Nettoie un nom de feuille Excel (31 caractères max, caractères
    interdits remplacés) et garantit son unicité dans le classeur."""
    forbidden = set('[]:*?/\\')
    cleaned = "".join(c if c not in forbidden else "_" for c in str(name))[:31]
    base = cleaned or "Feuille"
    candidate = base
    suffix = 1
    while candidate in used_names:
        suffix_str = f"_{suffix}"
        candidate = base[: 31 - len(suffix_str)] + suffix_str
        suffix += 1
    used_names.add(candidate)
    return candidate


def to_excel_bytes_multi(sheets: "dict[str, pd.DataFrame]") -> bytes:
    """Génère un classeur Excel unique en mémoire (aucune écriture disque)
    avec une feuille par entrée du dict `sheets`. Utilisé pour l'export
    multi-fichiers en mode "multi-feuilles" (une feuille par fichier source,
    plus une feuille combinée), dans l'ordre fourni.
    """
    buffer = io.BytesIO()
    used_names: set = set()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for name, df in sheets.items():
            safe_name = _safe_sheet_name(name, used_names)
            df.to_excel(writer, index=False, sheet_name=safe_name)
    return buffer.getvalue()
