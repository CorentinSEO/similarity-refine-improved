import streamlit as st
import pandas as pd
import re
import io

st.set_page_config(page_title="Similarity Refine", layout="wide")

REQUIRED_COLUMNS = ["Mot-clé", "Vol. mensuel", "Liste MC et %"]

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

KEYWORD_PATTERN = re.compile(r"(.+?)\s*\((\d+)\)\s*:\s*([\d.,]+)\s*%")


def parse_keywords(list_str: str, threshold: float):
    """Parse la colonne 'Liste MC et %' et retourne la liste des mots-clés
    secondaires dont la similarité est >= threshold.

    Chaque entrée retournée est un tuple (keyword, volume, similarity).
    Tolère les décimales avec point ou virgule (ex: 44.44 % ou 44,44 %).
    """
    if not isinstance(list_str, str) or not list_str.strip():
        return []

    entries = []
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


def summarize_row(entries):
    """Calcule volume total, similarité moyenne et nombre de mots-clés retenus."""
    if not entries:
        return [], 0, 0.0, 0
    total_volume = sum(e[1] for e in entries)
    avg_similarity = sum(e[2] for e in entries) / len(entries)
    formatted = [f"{k} ({v}): {s:.2f} %" for k, v, s in entries]
    return formatted, total_volume, avg_similarity, len(entries)


# ---------------------------------------------------------------------------
# Clustering (composantes connexes) - remplace la simple déduplication
# ---------------------------------------------------------------------------

class UnionFind:
    def __init__(self, items):
        self.parent = {item: item for item in items}

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def build_clusters(df: pd.DataFrame, keyword_col: str, volume_col: str, entries_col: str):
    """Regroupe les mots-clés en clusters (composantes connexes) à partir des
    relations de similarité retenues, au lieu d'une simple suppression de
    doublons un-à-un. Un cluster peut ainsi fusionner des chaînes A~B~C~D.
    """
    known_keywords = set(df[keyword_col])
    uf = UnionFind(known_keywords)
    edge_similarities = {}

    for _, row in df.iterrows():
        primary = row[keyword_col]
        for keyword, _volume, similarity in row[entries_col]:
            if keyword in known_keywords:
                uf.union(primary, keyword)
                pair = tuple(sorted((primary, keyword)))
                edge_similarities[pair] = max(edge_similarities.get(pair, 0), similarity)

    clusters = {}
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
# Chargement de fichier (xlsx et csv)
# ---------------------------------------------------------------------------

def load_uploaded_file(uploaded_file):
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)
    if name.endswith((".xlsx", ".xls")):
        return pd.read_excel(uploaded_file)
    raise ValueError("Format de fichier non supporté. Utilisez un fichier .xlsx, .xls ou .csv.")


def validate_columns(df: pd.DataFrame):
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    return missing


# ---------------------------------------------------------------------------
# Export en mémoire (pas d'écriture disque)
# ---------------------------------------------------------------------------

def to_excel_bytes(df: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Clusters")
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Application principale
# ---------------------------------------------------------------------------

def main():
    st.title("Similarity Refine – Analyse et fusion de clusters SEO")
    st.caption(
        "Importez un export de similarité sémantique (colonnes 'Mot-clé', "
        "'Vol. mensuel', 'Liste MC et %') pour filtrer les clusters par seuil "
        "de similarité et fusionner automatiquement les mots-clés proches."
    )

    uploaded_file = st.file_uploader("Choisissez un fichier", type=["xlsx", "xls", "csv"])
    if uploaded_file is None:
        st.info("En attente d'un fichier .xlsx, .xls ou .csv.")
        return

    try:
        df = load_uploaded_file(uploaded_file)
    except Exception as exc:
        st.error(f"Impossible de lire le fichier : {exc}")
        return

    missing = validate_columns(df)
    if missing:
        st.error(
            "Colonnes manquantes dans le fichier importé : "
            f"{', '.join(missing)}. Colonnes attendues : {', '.join(REQUIRED_COLUMNS)}."
        )
        return

    with st.expander("Aperçu du fichier importé", expanded=True):
        st.dataframe(df.head(10), use_container_width=True)
        st.caption(f"{len(df)} lignes importées.")

    threshold = st.slider(
        "Seuil de similarité (%)",
        min_value=0.0,
        max_value=100.0,
        value=25.0,
        step=0.5,
        help="Seuls les mots-clés dont la similarité est supérieure ou égale à ce seuil seront fusionnés.",
    )

    df = df.copy()
    df["_entries"] = df["Liste MC et %"].apply(lambda x: parse_keywords(x, threshold))
    summary = df["_entries"].apply(summarize_row)
    df[["Mots-clés filtrés", "Volume secondaire", "Similarité moyenne brute", "Nb mots-clés filtrés"]] = pd.DataFrame(
        summary.tolist(), index=df.index
    )

    clusters_df = build_clusters(df, "Mot-clé", "Vol. mensuel", "_entries")

    nb_lignes_avant = len(df)
    nb_lignes_apres = len(clusters_df)
    nb_fusionnes = int(clusters_df["Nb mots-clés fusionnés"].sum())

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Lignes avant fusion", nb_lignes_avant)
        st.metric("Lignes après fusion", nb_lignes_apres)
    with col2:
        st.text("Mots-clés fusionnés")
        st.bar_chart(
            pd.DataFrame(
                {"Valeurs": [nb_lignes_avant - nb_fusionnes, nb_fusionnes]},
                index=["Restants", "Fusionnés"],
            )
        )
    with col3:
        st.text("Volume de recherche")
        st.bar_chart(
            pd.DataFrame(
                {
                    "Valeurs": [
                        clusters_df["Volume mot-clé principal"].sum(),
                        clusters_df["Volume total du cluster"].sum()
                        - clusters_df["Volume mot-clé principal"].sum(),
                    ]
                },
                index=["Principaux", "Secondaires"],
            )
        )

    st.subheader("Résultat des clusters fusionnés")
    st.dataframe(clusters_df, use_container_width=True)

    excel_bytes = to_excel_bytes(clusters_df)
    st.download_button(
        label="Télécharger le résultat (Excel)",
        data=excel_bytes,
        file_name=f"clusters_seuil_{int(threshold)}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    main()
