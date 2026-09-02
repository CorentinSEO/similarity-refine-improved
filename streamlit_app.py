import streamlit as st
import pandas as pd

from clustering import (
    REQUIRED_COLUMNS,
    build_clusters,
    clean_volume_column,
    combine_cluster_results,
    deduplicate_keywords,
    find_ghost_keywords,
    load_uploaded_file,
    parse_keywords,
    process_dataframe,
    summarize_row,
    to_excel_bytes,
    to_excel_bytes_multi,
    validate_columns,
    validate_row_count,
)

st.set_page_config(page_title="Similarity Refine", layout="wide")


def _load_and_clean_impl(file_bytes: bytes, file_name: str):
    """Charge, valide et nettoie un fichier importé (comportement mono-fichier
    conservé à l'identique des versions précédentes, pour compatibilité avec
    test_clustering.py). Le flux multi-fichiers de main() utilise désormais
    process_dataframe / _process_uploaded_file_impl ci-dessous, qui encapsule
    une logique équivalente réutilisable par fichier.

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
    """Parsing + clustering pour un DataFrame déjà nettoyé (conservé pour
    compatibilité avec test_clustering.py)."""
    df = df.copy()
    df["_entries"] = df["Liste MC et %"].apply(lambda x: parse_keywords(x, threshold))
    summary = df["_entries"].apply(summarize_row)
    df[["Mots-clés filtrés", "Volume secondaire", "Similarité moyenne brute", "Nb mots-clés filtrés"]] = pd.DataFrame(
        summary.tolist(), index=df.index
    )
    return build_clusters(df, "Mot-clé", "Vol. mensuel", "_entries")


def _process_uploaded_file_impl(file_bytes: bytes, file_name: str, threshold: float) -> dict:
    """Charge et traite intégralement un fichier importé (validation,
    dédoublonnage, mots-clés fantômes, clustering Louvain).

    Fonction pure (aucun appel st.*) afin de rester testable directement,
    indépendamment du décorateur de cache Streamlit appliqué ci-dessous.
    Chaque appel est totalement indépendant : aucune comparaison de
    similarité n'a jamais lieu entre deux fichiers différents.
    """
    import io

    class _NamedBytes(io.BytesIO):
        name = file_name

    uploaded = _NamedBytes(file_bytes)
    uploaded.name = file_name
    df_raw = load_uploaded_file(uploaded)
    return process_dataframe(df_raw, threshold=threshold, source_label=file_name)


# Wrapper mis en cache par Streamlit (une entrée de cache par (contenu du
# fichier, nom du fichier, seuil)), utilisé par l'UI ci-dessous.
cached_process_uploaded_file = st.cache_data(show_spinner=False)(_process_uploaded_file_impl)


def main():
    st.title("Similarity Refine – Analyse et fusion de clusters SEO")
    st.caption(
        "Importez un ou plusieurs exports de similarité sémantique (colonnes "
        "'Mot-clé', 'Vol. mensuel', 'Liste MC et %') pour filtrer les clusters "
        "par seuil de similarité et fusionner automatiquement les mots-clés "
        "proches. **Chaque fichier est analysé indépendamment** : aucune "
        "similarité n'est jamais comparée entre deux fichiers différents."
    )

    uploaded_files = st.file_uploader(
        "Choisissez un ou plusieurs fichiers",
        type=["xlsx", "xls", "csv"],
        accept_multiple_files=True,
    )
    if not uploaded_files:
        st.info(
            "En attente d'un ou plusieurs fichiers .xlsx, .xls ou .csv "
            "(1000 lignes maximum chacun)."
        )
        return

    threshold = st.slider(
        "Seuil de similarité (%)",
        min_value=0.0,
        max_value=100.0,
        value=25.0,
        step=0.5,
        help="Seuls les mots-clés dont la similarité est supérieure ou égale à ce seuil seront fusionnés.",
    )

    cluster_frames = {}
    global_stats = []

    for uploaded_file in uploaded_files:
        file_name = uploaded_file.name
        with st.expander(f"📄 {file_name}", expanded=len(uploaded_files) == 1):
            try:
                result = cached_process_uploaded_file(
                    uploaded_file.getvalue(), file_name, threshold
                )
            except Exception as exc:
                st.error(f"Impossible de lire le fichier : {exc}")
                continue

            if result["missing_columns"]:
                st.error(
                    "Colonnes manquantes dans le fichier importé : "
                    f"{', '.join(result['missing_columns'])}. "
                    f"Colonnes attendues : {', '.join(REQUIRED_COLUMNS)}."
                )
                continue

            if result["size_error"]:
                st.error(result["size_error"])
                continue

            duplicated_keywords = result["duplicated_keywords"]
            ghost_keywords = result["ghost_keywords"]

            if duplicated_keywords:
                st.warning(
                    f"{len(duplicated_keywords)} mot(s)-clé(s) dupliqué(s) fusionné(s) "
                    "automatiquement (volume maximal conservé, relations regroupées) : "
                    + ", ".join(duplicated_keywords[:20])
                    + (f" (+{len(duplicated_keywords) - 20} autres)" if len(duplicated_keywords) > 20 else "")
                )

            if ghost_keywords:
                lost_volume = sum(volume for _, volume in ghost_keywords)
                st.warning(
                    f"{len(ghost_keywords)} mot(s)-clé(s) fantôme(s) ignoré(s) du clustering "
                    f"(volume cumulé non intégré : {lost_volume:,}".replace(",", " ") + "). "
                    "Exemples : " + ", ".join(f"{k} ({v})" for k, v in ghost_keywords[:10])
                )

            clusters_df = result["clusters"]
            cluster_frames[file_name] = clusters_df

            nb_lignes_avant = result["row_count"]
            nb_lignes_apres = len(clusters_df)
            nb_fusionnes = int(clusters_df["Nb mots-clés fusionnés"].sum())
            global_stats.append(
                {
                    "Fichier": file_name,
                    "Lignes importées": nb_lignes_avant,
                    "Clusters obtenus": nb_lignes_apres,
                    "Mots-clés fusionnés": nb_fusionnes,
                }
            )

            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Lignes importées", nb_lignes_avant)
            with col2:
                st.metric("Clusters obtenus", nb_lignes_apres)
            with col3:
                st.metric("Mots-clés fusionnés", nb_fusionnes)

            st.dataframe(
                clusters_df.drop(columns=["Fichier source"]),
                use_container_width=True,
            )

    if not cluster_frames:
        st.warning("Aucun fichier n'a pu être analysé (voir les erreurs ci-dessus).")
        return

    st.subheader("Synthèse par fichier")
    st.dataframe(pd.DataFrame(global_stats), use_container_width=True)

    combined_df = combine_cluster_results(cluster_frames)

    st.subheader("Résultat des clusters fusionnés (tous fichiers)")
    st.caption(
        "Chaque ligne provient d'un clustering réalisé indépendamment sur son "
        "fichier d'origine (colonne 'Fichier source') : aucun mot-clé n'a été "
        "comparé entre deux fichiers différents."
    )
    st.dataframe(combined_df, use_container_width=True)

    st.subheader("Export des résultats")
    export_mode = st.radio(
        "Format d'export Excel",
        options=[
            "Multi-feuilles (1 feuille par fichier + 1 feuille combinée)",
            "Agrégé (1 seule feuille, tous fichiers)",
        ],
        index=0,
        help=(
            "Multi-feuilles : conserve le détail par fichier (une feuille par fichier "
            "source, plus une feuille 'Tous les fichiers'). "
            "Agrégé : un seul tableau, toutes les lignes de tous les fichiers "
            "réunies avec la colonne 'Fichier source'."
        ),
    )

    if export_mode.startswith("Multi-feuilles"):
        sheets = dict(cluster_frames)
        sheets["Tous les fichiers"] = combined_df
        excel_bytes = to_excel_bytes_multi(sheets)
        file_name_suffix = "multi_feuilles"
    else:
        excel_bytes = to_excel_bytes(combined_df)
        file_name_suffix = "agrege"

    st.download_button(
        label=f"Télécharger tous les résultats ({len(cluster_frames)} fichier(s), 1 export Excel)",
        data=excel_bytes,
        file_name=f"clusters_{file_name_suffix}_seuil_{int(threshold)}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


if __name__ == "__main__":
    main()
