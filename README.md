# Similarity Refine

Application Streamlit pour filtrer et **fusionner des clusters de mots-clés SEO**
à partir d'un export de similarité sémantique (ex. Ahrefs, outil de clustering interne, etc.).

Ce repo est une version améliorée de [Psimon8/similarity-refine](https://github.com/Psimon8/similarity-refine),
avec un clustering par détection de communautés (Louvain), la prise en charge
du CSV, une meilleure robustesse et un export en mémoire.

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
- **Le fichier importé est limité à 1000 lignes.** Au-delà, l'application
  refuse le fichier avec un message explicite (voir `clustering.MAX_ROWS`).
  Scindez le fichier en plusieurs exports plus petits si nécessaire.

## Fonctionnement

1. **Import** du fichier (CSV ou Excel), avec validation des colonnes requises
   et de la taille du fichier (1000 lignes max).
2. **Déduplication** des mots-clés apparaissant plusieurs fois dans le fichier
   source : le volume maximal est conservé et toutes leurs relations de
   similarité sont fusionnées. Un avertissement liste les mots-clés concernés.
3. **Détection des mots-clés fantômes**, avec avertissement listant les plus
   gros volumes non intégrés.
4. **Nettoyage** automatique de la colonne volume (espaces, virgules, valeurs invalides → 0).
5. **Aperçu** des données brutes avant traitement.
6. **Seuil de similarité** ajustable via un slider (0 à 100 %) : seuls les mots-clés
   dont la similarité dépasse le seuil sont retenus comme candidats à la fusion.
7. **Clustering par détection de communautés (Louvain)** : les mots-clés sont
   regroupés par optimisation de la densité de connexions internes, avec pour
   représentant le mot-clé au volume le plus élevé.
8. **Résultat** : un tableau avec le mot-clé principal, les mots-clés fusionnés,
   le volume cumulé du cluster et la similarité moyenne (calculée uniquement
   sur les relations internes au cluster).
9. **Export** du résultat en Excel, généré en mémoire (aucune écriture disque).

Le chargement du fichier et le clustering sont mis en cache (`st.cache_data`)
pour éviter de tout recalculer à chaque déplacement du slider.

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
l'extérieur. Un pont isolé et faible entre deux groupes densément connectés ne
suffit plus à les fusionner (voir le test
`test_build_clusters_resists_weak_bridge_between_dense_groups`).

Coût : Louvain est plus lourd que l'union-find (optimisation itérative de la
modularité), mais reste largement praticable pour la limite de 1000 lignes
retenue (quelques centaines de ms au pire cas testé, avec relations denses).

## Structure du projet

```
.
├── streamlit_app.py       # Interface Streamlit (UI + orchestration mise en cache)
├── clustering.py          # Logique métier pure (parsing, dedup, clustering Louvain, export)
├── test_clustering.py     # Tests unitaires (pytest)
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
- Traçabilité : la colonne `Mots-clés fusionnés` liste les mots-clés absorbés
  par chaque cluster.
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
- Garde-fou sur la taille de fichier (**1000 lignes max**).
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
- [ ] Support multi-feuilles Excel (sélection de la feuille à traiter).

## Licence

Ce projet est sous licence [MIT](LICENSE).
