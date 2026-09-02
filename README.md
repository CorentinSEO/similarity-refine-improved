# Similarity Refine

Application Streamlit pour filtrer et **fusionner des clusters de mots-clés SEO**
à partir d'un export de similarité sémantique (ex. Ahrefs, outil de clustering interne, etc.).

Ce repo est une version améliorée de [Psimon8/similarity-refine](https://github.com/Psimon8/similarity-refine),
avec un clustering par détection de communautés (Louvain), la prise en charge
du CSV, une meilleure robustesse, l'analyse multi-fichiers et un export en mémoire.

## Format de fichier attendu

Le fichier importé (`.xlsx`, `.xls` ou `.csv`) doit contenir 3 colonnes :

| Colonne | Description |
|---|---|
| `Mot-clé` | Le mot-clé principal |
| `Vol. mensuel` | Son volume de recherche mensuel (les espaces de milliers et virgules décimales sont tolérés) |
| `Liste MC et %` | Liste de mots-clés proches au format `mot-clé (volume): xx.xx %`, séparés par ` | ` |

Exemple de contenu de `Liste MC et %` :

```
road trip en italie (320): 22.22 % | visiter italie en 10 jours (10): 22.22 %
```

**Limites connues** :
- Un mot-clé cité uniquement dans `Liste MC et %` mais qui n'a jamais sa propre
  ligne `Mot-clé` dans le fichier n'est pas intégré au clustering. L'application
  détecte ces "mots-clés fantômes" et affiche un avertissement listant les
  plus importants (par volume rapporté).
- **Chaque fichier importé est limité à 1000 lignes.** Au-delà, l'application
  refuse ce fichier avec un message explicite (voir `clustering.MAX_ROWS`), les
  autres fichiers du batch restant traités normalement. Scindez le fichier en
  plusieurs exports plus petits si nécessaire.

## Fonctionnement

1. **Import** d'un ou plusieurs fichiers (CSV ou Excel), avec validation des
   colonnes requises et de la taille de chaque fichier (1000 lignes max).
2. **Déduplication** des mots-clés apparaissant plusieurs fois dans un même
   fichier source : le volume maximal est conservé et toutes leurs relations
   de similarité sont fusionnées. Un avertissement liste les mots-clés concernés.
3. **Détection des mots-clés fantômes**, avec avertissement listant les plus
   gros volumes non intégrés.
4. **Nettoyage** automatique de la colonne volume (espaces, virgules, valeurs invalides → 0).
5. **Seuil de similarité** ajustable via un slider (0 à 100 %), commun à tous
   les fichiers du batch : seuls les mots-clés dont la similarité dépasse le
   seuil sont retenus comme candidats à la fusion.
6. **Clustering par détection de communautés (Louvain)**, exécuté séparément
   pour chaque fichier : les mots-clés sont regroupés par optimisation de la
   densité de connexions internes, avec pour représentant le mot-clé au
   volume le plus élevé.
7. **Résultat** : un tableau par fichier, plus un tableau combiné (colonne
   `Fichier source`) avec le mot-clé principal, les mots-clés fusionnés, le
   volume cumulé du cluster et la similarité moyenne (calculée uniquement sur
   les relations internes au cluster).
8. **Export**, au choix, dans un seul classeur Excel généré en mémoire
   (aucune écriture disque) :
   - **Multi-feuilles** : une feuille par fichier source, plus une feuille
     "Tous les fichiers" avec le tableau combiné ;
   - **Agrégé** : une seule feuille contenant toutes les lignes de tous les
     fichiers, avec la colonne `Fichier source` pour tracer l'origine.

Le chargement et le clustering de chaque fichier sont mis en cache
(`st.cache_data`) pour éviter de tout recalculer à chaque déplacement du slider.

## Analyse multi-fichiers

L'application accepte plusieurs fichiers en une seule importation
(`st.file_uploader(..., accept_multiple_files=True)`). Chaque fichier est :

- **traité de façon totalement indépendante** des autres : la déduplication,
  la détection de mots-clés fantômes et le clustering Louvain de chaque
  fichier ne prennent en compte que les mots-clés et relations de ce fichier
  (voir `clustering.process_dataframe`). Aucune similarité n'est jamais
  comparée entre deux fichiers différents ;
- affiché individuellement (aperçu, avertissements, métriques) dans un volet
  dépliable, pour garder une trace claire de ce qui a été détecté par fichier ;
- rassemblé avec les autres dans un tableau combiné unique (colonne
  `Fichier source`) via `clustering.combine_cluster_results`, pour disposer
  d'une vue d'ensemble sans quitter l'application.

Un fichier invalide (colonnes manquantes ou plus de 1000 lignes) n'empêche pas
le traitement des autres fichiers du batch : son erreur est affichée dans son
propre volet, les autres résultats restent disponibles.

### Choix du format d'export

Un bouton radio permet de choisir, avant le téléchargement, entre deux formats
d'export Excel (un seul fichier `.xlsx` dans les deux cas) :

| Format | Contenu | Fonction |
|---|---|---|
| Multi-feuilles | 1 feuille par fichier source + 1 feuille "Tous les fichiers" | `clustering.to_excel_bytes_multi` |
| Agrégé | 1 feuille unique avec toutes les lignes de tous les fichiers | `clustering.to_excel_bytes` |

Le mode multi-feuilles est utile pour retrouver rapidement le détail d'un
fichier précis ; le mode agrégé est plus pratique pour un tri/filtre global
(ex. TCD Excel) sur l'ensemble des clusters, tous fichiers confondus.

## Pourquoi Louvain plutôt qu'un clustering par composantes connexes ?

Les versions précédentes utilisaient un clustering par composantes connexes
(union-find) : tout mot-clé relié par une chaîne de relations était fusionné,
même si chaque relation individuelle était faible. Sur des fichiers denses
(beaucoup de relations par mot-clé), cet effet de chaîne pouvait fusionner des
thématiques distinctes (ex. une entité ville et une entité région) dès qu'un
pont faible existait entre les deux groupes, même au-dessus du seuil retenu.

L'algorithme de **Louvain** (détection de communautés par optimisation de
modularité) résout ce problème : un cluster n'est formé que si la densité de
connexions internes est significativement plus forte que les connexions vers
l'extérieur. Un pont isolé et faible entre deux groupes densement connectés ne
suffit plus à les fusionner (voir le test
`test_build_clusters_resists_weak_bridge_between_dense_groups`).

Coût : Louvain est plus lourd que l'union-find (optimisation itérative de la
modularité), mais reste largement praticable pour la limite de 1000 lignes
retenue par fichier (quelques centaines de ms au pire cas testé, avec
relations denses).

## Structure du projet

```
.
├── streamlit_app.py       # Interface Streamlit (UI multi-fichiers + choix export + cache)
├── clustering.py          # Logique métier pure (parsing, dedup, clustering Louvain, multi-fichiers, export)
├── test_clustering.py     # Tests unitaires (pytest) - pipeline mono-fichier
├── test_multi_file.py     # Tests unitaires (pytest) - traitement multi-fichiers et export combiné
├── requirements.txt       # Dépendances de production (streamlit, pandas, openpyxl, networkx)
├── requirements-dev.txt   # Dépendances de développement (pytest)
├── .streamlit/config.toml # Thème Streamlit (dark, violet)
├── .github/workflows/     # CI : exécution des tests à chaque push/PR
└── todo.txt                # Roadmap
```

## Améliorations par rapport à la version d'origine

- Support des fichiers CSV en plus de l'Excel.
- Regex de parsing tolérante aux décimales avec virgule (`44,44 %`) ou point (`44.44 %`).
- Validation explicite des colonnes requises avec message d'erreur clair.
- **Clustering par détection de communautés (Louvain)** au lieu d'une simple
  déduplication un-à-un ou d'un clustering par composantes connexes, pour
  éviter la sur-fusion de thématiques distinctes reliées par un pont faible.
- **Analyse multi-fichiers** : import de plusieurs fichiers en une fois,
  traités indépendamment, avec un tableau de résultats combiné et **un choix
  entre export Excel multi-feuilles (1 par fichier + 1 combinée) ou export
  agrégé en 1 seule feuille**.
- Traçabilité : la colonne `Mots-clés fusionnés` liste les mots-clés absorbés
  par chaque cluster, et la colonne `Fichier source` trace l'origine de
  chaque cluster en mode multi-fichiers.
- Export Excel en mémoire (`io.BytesIO`) au lieu d'une écriture sur disque.
- Aperçu du fichier importé avant traitement.
- Slider de seuil au lieu d'un champ numérique, avec valeur par défaut plus
  réaliste (25 % au lieu de 40 %).
- Libellés entièrement en français.
- Fichier de thème déplacé vers `.streamlit/config.toml`.
- Nettoyage robuste des volumes (espaces, virgules, valeurs invalides).
- Mise en cache (`st.cache_data`) du chargement et du clustering.
- Logique métier extraite dans `clustering.py`, testée par des tests unitaires.
- `.gitignore` et licence MIT.
- Déduplication automatique des mots-clés en double (volume max conservé,
  relations fusionnées) avec avertissement dans l'UI.
- Détection et affichage des mots-clés "fantômes" (référencés mais jamais
  présents comme ligne principale), avec volume cumulé non intégré.
- Garde-fou sur la taille de fichier (**1000 lignes max par fichier**).
- Tests couvrant `streamlit_app.py` (fonctions d'orchestration extraites du
  décorateur de cache, testables indépendamment de Streamlit).
- Intégration continue (GitHub Actions) exécutant la suite de tests à chaque
  push et pull request.

## Installation locale

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

## Roadmap

- [ ] Ajout d'une pondération par intention de recherche (informationnelle,
  transactionnelle...) en plus du volume.
- [ ] Export du détail des similarités par paire de mots-clés (audit qualité).
- [ ] Support multi-feuilles Excel en import (sélection de la feuille à traiter).

## Licence

Ce projet est sous licence [MIT](LICENSE).
