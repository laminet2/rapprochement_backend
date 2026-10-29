# Rapprochement — backend

API Django REST de rapprochement entre **relevés bancaires** et **relevés Valorix**
(ou tout autre document de transactions).

```bash
pip install -r requirement.txt
cd rapprochement
cp .env.example .env        # puis renseigner OPENAI_API_KEY
python manage.py migrate
python manage.py runserver
python manage.py test        # 128 tests
```

> Les permissions sont volontairement désactivées pendant la phase de
> développement des API (aucune authentification requise).

## Parcours

1. **Importer** : le fichier est lu et renvoyé en JSON *sans rien enregistrer*.
2. **Vérifier** : le front affiche les lignes (erreurs et doublons signalés), l'utilisateur corrige.
3. **Valider** : le JSON vérifié est envoyé à `save/` → création d'un **lot d'import**.
4. **Générer** les propositions (règles actives, 1-1 / 1-N / N-1).
5. **Réviser** : rejeter certaines propositions, puis *valider tout le reste* — ou rapprocher à la main.
6. **Non rapprochées** : lister, supprimer.

## Endpoints

| Méthode | URL | Rôle |
|---|---|---|
| POST | `/rbc/compte/<id>/` | PDF bancaire → lignes à vérifier (`fichier`) |
| POST | `/rbc/save/` | Enregistre les lignes vérifiées (`compte`, `nom_fichier`, `ignorer_doublons`, `transactions`) |
| GET/POST/… | `/rbc/comptes/`, `/rbc/banques/` | Comptes et banques |
| GET/PATCH/DELETE | `/rbc/transactions/` | Filtres : `compte`, `type_transaction`, `lot`, `q`, `date_min`, `date_max`, `sens`, `rapprochee` |
| POST | `/valorix/` | Relevé Valorix `.xlsx` ou `.pdf` → lignes à vérifier |
| POST | `/valorix/save/` | Enregistre les lignes vérifiées du journal de caisse |
| GET/POST/PATCH/DELETE | `/documents/types/` | Types de document nommés (« Orange Money »…) : `nom`, `sens`, `types_valorix` (crée les règles) |
| POST | `/documents/types/<id>/extraire/` | Fichier `.xlsx`/`.csv`/`.pdf` → lignes à vérifier (rien n'est enregistré) |
| POST | `/documents/save/` | `{type_document, nom_fichier, ignorer_doublons, transactions:[{numero_compte, date_transaction, montant}]}` |
| GET | `/documents/modele/` · `/documents/colonnes/` | Modèle Excel · colonnes obligatoires |
| GET/PATCH/DELETE | `/documents/lignes/` | Lignes de documents : `type_document`, `lot`, `q`, `date_min`, `date_max`, `sens`, `rapprochee` |
| GET/PATCH/DELETE | `/valorix/transactions/` | Filtres : `types`, `lot`, `q`, `date_min`, `date_max`, `sens`, `rapprochee` |
| GET | `/imports/` · POST `/imports/<id>/annuler/` | Historique des imports, annulation d'un lot |
| GET/POST/PATCH | `/rapprochements/regles/` | Une règle par type de transaction |
| POST | `/rapprochements/regles/par-defaut/` | Crée les règles manquantes |
| POST | `/rapprochements/generer/` | `lot_valorix`, `lot_banque`, `lot_document`, `types`, `inclure_regroupements` (tout optionnel) |
| GET | `/rapprochements/` | Liste paginée : `statut_validation`, `resultat`, `origine`, `score_min`, `score_max`, `type_rapprochement`, `type_valorix`, `source=banque`, `type_document`, `lot_valorix`, `lot_banque`, `lot_document`, `q`, `ordering`, `page`, `page_size` |
| GET | `/rapprochements/<id>/` | Détail (+ `score_details` avec explications pour l'infobulle) |
| POST | `/rapprochements/<id>/valider/` · `rejeter/` · `annuler/` | `rejeter` et `annuler` demandent `{"motif": "..."}` |
| POST | `/rapprochements/decision-groupee/` | `{"ids_rejetes": [...], "motif_rejet": "...", "lot_valorix": [...]}` : rejette puis valide le reste |
| POST | `/rapprochements/manuel/apercu/` | Totaux / écart / tolérance. Corps : `transactions_valorix` + `transactions_bancaires`, ou `type_document` + `lignes_document` |
| POST | `/rapprochements/manuel/` | Rapprochement manuel (`forcer` + `motif` si écart hors tolérance) |
| GET | `/rapprochements/non-rapprochees/?source=banque\|valorix\|document` | Lignes sans rapprochement validé (`type_document` pour un document) |
| POST | `/rapprochements/non-rapprochees/supprimer/` | `{"source": "banque\|valorix\|document", "ids": [...]}` |
| POST | `/rapprochements/nettoyer-bloquees/` | Annule les propositions devenues impossibles |
| GET | `/rapprochements/statistiques/` | Compteurs et taux de rapprochement |

## Modèle : Valorix est la référence

Le journal de caisse **Valorix** est la base. Chaque ligne Valorix est rapprochée avec une
**contrepartie**, qui est soit un relevé bancaire, soit un **document nommé** (« Orange Money »,
« Wave »…). Un type de document se crée une fois (nom, sens des montants, types Valorix
concernés) ; on importe ensuite autant de fichiers que nécessaire sous ce type. Ses colonnes
obligatoires : **Numéro compte client**, **Date transaction**, **Montant net**.

## Règles

Une règle par **type Valorix et par contrepartie** (banque, ou un type de document) : sens
attendu, fenêtre de dates, tolérance fixe et en %, `regroupement_max` (1 = 1-1 uniquement)
et `actif`. Pour un document, le sens est celui du type de document. Les paramètres sont
recopiés dans chaque proposition (`regle_snapshot`).

## Rapprochements 1-1, 1-N, N-1

La tolérance s'applique à la **somme** des montants. Les regroupements ne sont cherchés
que pour les lignes sans candidat 1-1, et une ligne n'est utilisée que dans une proposition
de regroupement par génération. La recherche est bornée (40 candidats, 200 000 nœuds).
Le rapprochement manuel accepte aussi N-M. Une même ligne Valorix peut être proposée à la
banque et à un document : le conflit est signalé et tranché à la revue.

## Score (0-100)

Montant 30 · date 15 · référence 25 · compte 15 · nom 10 · sens 5, **normalisé sur les critères
disponibles** : face à un document (ni libellé, ni référence, ni nom), seuls montant, date,
compte et sens comptent, et un candidat parfait fait 100. Chaque critère du `score_details`
contient `score`, `maximum`, `disponible` et `explication`.

## Rapprochements : contrepartie

Chaque rapprochement expose `source_contrepartie` (`BANQUE` ou `DOCUMENT` + nom), la liste
unifiée `contrepartie`, `total_contrepartie` et `nombre_contrepartie`.
