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
| `Vol. mensuel` | Son volume de recherche mensuel |
| `Liste MC et %` | Liste de mots-clés proches au format `mot-clé (volume): xx.xx %`, séparés par ` | ` |

Exemple de contenu de `Liste MC et %` :

```
road trip en italie (320): 22.22 % | visiter italie en 10 jours (10): 22.22 %
```

## Fonctionnement

1. **Import** du fichier (CSV ou Excel), avec validation des colonnes requises.
2. **Aperçu** des données brutes avant traitement.
3. **Seuil de similarité** ajustable via un slider (0 à 100 %) : seuls les mots-clés
   dont la similarité dépasse le seuil sont retenus comme candidats à la fusion.
4. **Clustering par composantes connexes** : les mots-clés liés (directement ou
   via une chaîne de similarités, ex. A~B~C) sont regroupés dans un même cluster,
   avec pour représentant le mot-clé au volume le plus élevé.
5. **Résultat** : un tableau avec le mot-clé principal, les mots-clés fusionnés,
   le volume cumulé du cluster et la similarité moyenne.
6. **Export** du résultat en Excel, généré en mémoire (aucune écriture disque).

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

## Installation locale

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Roadmap

- [ ] Ajout d'une pondération par intention de recherche (informationnelle,
  transactionnelle...) en plus du volume.
- [ ] Export du détail des similarités par paire de mots-clés (audit qualité).
- [ ] Support multi-feuilles Excel (sélection de la feuille à traiter).
