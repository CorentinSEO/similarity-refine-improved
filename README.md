# Similarity Refine

Application Streamlit pour filtrer et **fusionner des clusters de mots-clés SEO**
à partir d'un export de similarité sémantique (ex. Ahrefs, outil de clustering interne, etc.).

Ce repo est une version améliorée de [Psimon8/similarity-refine](https://github.com/Psimon8/similarity-refine),
avec un vrai clustering par composantes connexes, la prise en charge du CSV, une
meilleure robustesse et un export en mémoire.

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

**Limite connue** : un mot-clé cité uniquement dans `Liste MC et %` mais qui n'a
jamais sa propre ligne `Mot-clé` dans le fichier n'est pas intégré au clustering
(il n'existe pas de volume propre pour ce mot-clé dans le fichier).

## Fonctionnement

1. **Import** du fichier (CSV ou Excel), avec validation des colonnes requises.
2. **Nettoyage** automatique de la colonne volume (espaces, virgules, valeurs invalides → 0).
3. **Aperçu** des données brutes avant traitement.
4. **Seuil de similarité** ajustable via un slider (0 à 100 %) : seuls les mots-clés
   dont la similarité dépasse le seuil sont retenus comme candidats à la fusion.
5. **Clustering par composantes connexes** : les mots-clés liés (directement ou
   via une chaîne de similarités, ex. A~B~C) sont regroupés dans un même cluster,
   avec pour représentant le mot-clé au volume le plus élevé.
6. **Résultat** : un tableau avec le mot-clé principal, les mots-clés fusionnés,
   le volume cumulé du cluster et la similarité moyenne.
7. **Export** du résultat en Excel, généré en mémoire (aucune écriture disque).

Le chargement du fichier et le clustering sont mis en cache (`st.cache_data`)
pour éviter de tout recalculer à chaque déplacement du slider.

## Structure du projet

```
.
├── streamlit_app.py       # Interface Streamlit (UI uniquement)
├── clustering.py          # Logique métier pure (parsing, clustering, export)
├── test_clustering.py     # Tests unitaires (pytest)
├── requirements.txt       # Dépendances de production
├── requirements-dev.txt   # Dépendances de développement (pytest)
├── .streamlit/config.toml # Thème Streamlit (dark, violet)
└── todo.txt                # Roadmap
```

## Améliorations par rapport à la version d'origine

- Support des fichiers CSV en plus de l'Excel.
- Regex de parsing tolérante aux décimales avec virgule (`44,44 %`) ou point (`44.44 %`).
- Validation explicite des colonnes requises avec message d'erreur clair.
- Clustering par composantes connexes (union-find) au lieu d'une déduplication
  un-à-un, pour fusionner correctement les chaînes de mots-clés similaires.
- Traçabilité : la colonne `Mots-clés fusionnés` liste les mots-clés absorbés
  par chaque cluster.
- Export Excel en mémoire (`io.BytesIO`) au lieu d'une écriture sur disque.
- Aperçu du fichier importé avant traitement.
- Slider de seuil au lieu d'un champ numérique, avec valeur par défaut plus
  réaliste (25 % au lieu de 40 %).
- Libellés entièrement en français.
- **Nouveau** : fichier de thème déplacé vers `.streamlit/config.toml` (l'ancien
  emplacement à la racine n'était jamais lu par Streamlit).
- **Nouveau** : nettoyage robuste des volumes (espaces, virgules, valeurs invalides).
- **Nouveau** : mise en cache (`st.cache_data`) du chargement et du clustering.
- **Nouveau** : logique métier extraite dans `clustering.py`, testée par 8 tests unitaires.
- **Nouveau** : `.gitignore` et licence MIT.

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
