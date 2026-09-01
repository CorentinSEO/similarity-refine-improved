import streamlit as st
import pandas as pd

from clustering import (
    REQUIRED_COLUMNS,
    build_clusters,
    clean_volume_column,
    deduplicate_keywords,
    find_ghost_keywords,
    load_uploaded_file,
    parse_keywords,
    summarize_row,
    to_excel_bytes,
    validate_columns,
    validate_row_count,
)

st.set_page_config(page_title="Similarity Refine", layout="wide")


def _load_and_clean_impl(file_bytes: bytes, file_name: str):
    """Charge, valide et nettoie le fichier importé.

    Fonction pure (aucun appel st.*) afin de rester testable directement,
    indépendamment du décorateur de cache Streamlit appliqué ci-dessous.

    Retourne (df_nettoyé, colonnes_manquantes, mots_clés_dupliqués,
    mots_clés_fantômes, message_erreur_taille).
    """
    import io

    class _NamedBytes(io.BytesIO):
        name = file_name

    uploaded = _NamedBytes(file_bytes)
    uploaded.name = file_name
    df = load_uploaded_file(uploaded)

    missing = validate_columns(df)
    if missing:
        return df, missing, [], [], None

    size_error = validate_row_count(df)
    if size_error:
        return df, missing, [], [], size_error

    df, duplicated_keywords = deduplicate_keywords(df)
    ghost_keywords = find_ghost_keywords(df)
    df = clean_volume_column(df, "Vol. mensuel")
    return df, missing, duplicated_keywords, ghost_keywords, None


def _cluster_impl(df: pd.DataFrame, threshold: float) -> pd.DataFrame:
    """Parsing + clustering. Fonction pure, testable indépendamment du cache."""
    df = df.copy()
    df["_entries"] = df["Liste MC et %"].apply(lambda x: parse_keywords(x, threshold))
    summary = df["_entries"].apply(summarize_row)
    df[["Mots-clés filtrés", "Volume secondaire", "Similarité moyenne brute", "Nb mots-clés filtrés"]] = pd.DataFrame(
        summary.tolist(), index=df.index
    )
    return build_clusters(df, "Mot-clé", "Vol. mensuel", "_entries")


# Wrappers mis en cache par Streamlit (une entrée de cache par (fichier, seuil)
# ou par (contenu du fichier, nom du fichier)), utilisés par l'UI ci-dessous.
cached_load_and_clean = st.cache_data(show_spinner="Lecture du fichier...")(_load_and_clean_impl)
cached_cluster = st.cache_data(show_spinner="Analyse des clusters...")(_cluster_impl)


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
        df, missing, duplicated_keywords, ghost_keywords, size_error = cached_load_and_clean(
            uploaded_file.getvalue(), uploaded_file.name
        )
    except Exception as exc:
        st.error(f"Impossible de lire le fichier : {exc}")
        return

    if missing:
        st.error(
            "Colonnes manquantes dans le fichier importé : "
            f"{', '.join(missing)}. Colonnes attendues : {', '.join(REQUIRED_COLUMNS)}."
        )
        return

    if size_error:
        st.error(size_error)
        return

    if duplicated_keywords:
        st.warning(
            f"{len(duplicated_keywords)} mot(s)-clé(s) dupliqué(s) dans le fichier importé ont été "
            "fusionnés automatiquement (volume maximal conservé, relations de similarité regroupées) : "
            + ", ".join(duplicated_keywords[:20])
            + (f" (+{len(duplicated_keywords) - 20} autres)" if len(duplicated_keywords) > 20 else "")
        )

    if ghost_keywords:
        lost_volume = sum(volume for _, volume in ghost_keywords)
        st.warning(
            f"{len(ghost_keywords)} mot(s)-clé(s) référencé(s) dans la colonne 'Liste MC et %' "
            "n'ont jamais leur propre ligne dans le fichier et sont donc ignorés du clustering "
            f"(volume cumulé non intégré : {lost_volume:,}".replace(",", " ") + "). "
            "Exemples : " + ", ".join(f"{k} ({v})" for k, v in ghost_keywords[:10])
        )

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

    clusters_df = cached_cluster(df, threshold)

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
