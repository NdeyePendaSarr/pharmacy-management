# 💊 PharmaNPS-Alou — Gestion de pharmacie

[![CI](https://github.com/NdeyePendaSarr/pharmacy-management/actions/workflows/ci.yml/badge.svg)](https://github.com/NdeyePendaSarr/pharmacy-management/actions/workflows/ci.yml) [![Licence : MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)

> Application web de gestion d'une pharmacie : **stock des médicaments**, **caisse**, **clients**, **ordonnances**, **facturation** et **suivi de l'activité commerciale**.

Développée avec **Django 5.2** et **PostgreSQL**, déployée sur **Render** avec une base **Neon**. Le projet met l'accent sur l'exactitude des règles métier : un prix, un stock ou un encours de crédit ne peut pas être faussé depuis le navigateur, et chaque règle est couverte par un test automatisé.

> **🔗 Démo en ligne : [PharmaNPS-Alou](https://pharmanps-aloucoding-b8ex.onrender.com/)**
> Compte de démonstration au rôle **Vendeur** : identifiant `demo`, mot de passe `Pharma-Visite-2026`.
> Toutes les données de la démo (médicaments, clients, ventes, ordonnances) sont **fictives** et peuvent être modifiées par les visiteurs.

---

## 🖼️ Aperçu

| Accueil | Panier | Facture |
| :---: | :---: | :---: |
| ![Accueil](public/accueil.png) | ![Panier](public/panier.png) | ![Facture](public/facture.png) |

| Facture | Catégories | Chiffre d'affaires |
| :---: | :---: | :---: |
| ![Facture variante](public/facture-bis.png) | ![Catégories](public/categorie.png) | ![Chiffre d'affaires](public/chiffre-affaire.png) |

| Clients | Connexion | Médicaments |
| :---: | :---: | :---: |
| ![Clients](public/clients.png) | ![Connexion](public/login.png) | ![Médicaments](public/medicaments.png) |

---

## 🔐 Comptes et rôles

L'inscription publique est **fermée** : les comptes sont créés par un administrateur. Deux groupes sont définis dans le code ([`users/roles.py`](users/roles.py)) et recréés après chaque `migrate`.

| Action | Pharmacien | Vendeur |
|---|:---:|:---:|
| Caisse, ventes, factures | ✅ | ✅ |
| Consulter médicaments, catégories, clients | ✅ | ✅ |
| Créer ou modifier un médicament, un prix, une catégorie | ✅ | ❌ |
| Mouvements de stock (entrée, perte, ajustement…) | ✅ | ❌ |
| Créer ou modifier une fiche client | ✅ | ❌ |
| Voir les conditions médicales et la date de naissance | ✅ | ❌ |
| Supprimer quoi que ce soit | ✅ | ❌ |

- Les permissions sont vérifiées **dans chaque vue** (`permission_required`), pas seulement dans les gabarits : un Vendeur qui appelle directement l'URL de modification d'un médicament reçoit une erreur 403.
- Un compte sans groupe peut se connecter mais n'a accès à rien.
- Après **5 échecs de connexion** pour un même identifiant depuis une même adresse IP, ce couple est bloqué 15 minutes (django-axes).
- La déconnexion se fait uniquement en `POST`.
- Dans l'**admin Django**, les ventes, lignes de vente et ordonnances sont en **consultation seule** (même pour un superutilisateur) et l'encours de crédit d'un client n'est pas modifiable : seule la caisse les écrit, avec le stock et le crédit dans la même transaction.

---

## ✨ Fonctionnalités

### 💊 Médicaments
Nom, DCI, code-barres unique, catégorie, forme galénique, dosage, prix d'achat et de vente, seuil d'alerte, date de péremption, emplacement, image (Cloudinary). Formulaires validés côté serveur : prix strictement positifs, prix de vente au moins égal au prix d'achat, date de péremption valide.

Filtres de la liste : stock faible, périmés, bientôt périmés (30 jours).

### 📦 Stock
Le stock ne change **que par un mouvement**, toujours tracé :

| Augmente le stock | Diminue le stock |
|---|---|
| Entrée (réception) | Sortie (vente) |
| Retour client | Perte / casse |
| Ajustement + (inventaire) | Retrait périmé |
| | Ajustement − (inventaire) |

La quantité d'un mouvement est toujours positive, le sens vient de son type. Un mouvement qui ferait passer le stock sous zéro est refusé. La quantité n'est pas modifiable depuis la fiche du médicament : à la création, le stock initial est enregistré comme une entrée.

### 🛒 Caisse
- Recherche instantanée par nom, DCI ou code-barres ; les médicaments **périmés** ou épuisés ne sont pas proposés.
- Client cherché **à la demande** par nom, prénom ou téléphone (2 caractères minimum, 10 résultats, clients archivés exclus), au clavier comme à la souris ; sans client choisi, la vente est anonyme.
- Remise de 0 à 20 % ; paiement en espèces (monnaie rendue calculée), carte, mobile money ou **crédit**.
- Médicament **sur ordonnance** : la vente exige un client et une ordonnance (médecin, date de prescription **de moins de 3 mois**), enregistrée, liée à la vente et rappelée sur la fiche de vente et la facture.
- Facture imprimable.

### 👥 Clients
Particulier, entreprise ou assurance ; coordonnées, limite de crédit et encours. Les données médicales ne sont visibles que par un Pharmacien.

Un client n'est **jamais supprimé avec son historique** : ses ventes et ses ordonnances le protègent (`on_delete=PROTECT`), et l'admin refuse la suppression, avec un message qui en donne la raison, s'il a des ventes, des ordonnances ou un encours de crédit. Pour le retirer de l'usage courant, l'action « Archiver » le masque de la liste et de la caisse (une vente à son nom est refusée) ; sa fiche, ses ventes, ses ordonnances et son encours restent consultables, et « Réactiver » le remet en service. Seule une fiche sans aucun historique peut être supprimée.

### 📊 Tableau de bord
Chiffre d'affaires du jour, de la semaine, du mois et total, ventes des 7 derniers jours, top 5 des produits vendus et alertes de stock (graphiques Chart.js).

---

## 🧠 Règles métier

### Une vente est calculée par le serveur
Le navigateur n'envoie que des intentions : quels médicaments, combien, quelle remise, quel mode de paiement. Le service [`sales/services.py`](sales/services.py) fait le reste dans **une seule transaction** :

```text
Verrouillage des médicaments (SELECT … FOR UPDATE)
  → refus si périmé, stock insuffisant ou ordonnance manquante ou expirée (plus de 3 mois)
  → prix lus en base, totaux recalculés en Decimal et arrondis au franc CFA, remise bornée
  → contrôle du paiement (espèces suffisantes, crédit disponible)
  → vente, lignes de vente, mouvements de sortie, ordonnance
```

Si une étape échoue, rien n'est enregistré. Un message d'erreur inattendu n'est jamais renvoyé au navigateur : il est journalisé côté serveur.

Chaque panier porte un **jeton** tiré par la caisse : un double clic ou une relance après une coupure réseau renvoie la vente déjà créée au lieu d'en enregistrer une seconde. Le bouton « Finaliser la vente » est aussi désactivé pendant l'envoi.

### Stock sans course
Toute écriture du stock passe par [`medications/stock.py`](medications/stock.py) : verrou sur la ligne, contrôle « jamais sous zéro », mise à jour avec `F()`. Deux ventes simultanées du dernier article ne peuvent pas réussir toutes les deux. La base impose aussi `stock ≥ 0` et `quantité de mouvement > 0` (contraintes `CHECK`).

### Paiements
- **Espèces** : refusé si le montant remis est inférieur au total ; monnaie = montant remis − total.
- **Carte, mobile money** : le montant encaissé est le total.
- **Crédit** : client obligatoire ; la vente est refusée si elle dépasse le crédit disponible ; l'encours du client est mis à jour dans la même transaction.

### Numéro de vente et bénéfice
Le numéro est dérivé de l'identifiant de la vente (`V20261020-000123`) : il reste unique même si deux ventes sont enregistrées au même instant. Chaque ligne de vente garde le **prix d'achat du moment** : le bénéfice d'une vente passée ne change pas si le prix d'achat évolue ensuite.

---

## 🗃️ Modèles de données

| Application | Modèle | Rôle |
|---|---|---|
| `medications` | `Category` | Catégorie de médicaments |
| | `Medication` | Médicament, prix, stock (≥ 0), péremption |
| | `StockMovement` | Historique des variations de stock |
| `sales` | `Customer` | Client, crédit, données médicales |
| | `Sale` | Vente : numéro, remise, paiement, totaux |
| | `SaleItem` | Ligne de vente : quantité, prix de vente et coût d'achat figés |
| | `Prescription` | Ordonnance liée à un client et à une vente |

---

## 🧱 Stack technique

| Couche | Technologie |
|---|---|
| Backend | **Django 5.2** (Python 3.13) |
| Base de données | **PostgreSQL** hébergé chez **Neon** (SQLite possible en développement) |
| Frontend | Gabarits Django, **Tailwind CSS**, **Chart.js** |
| Sécurité | Rôles par permissions Django, **django-axes**, HTTPS/HSTS, **Content-Security-Policy** (django-csp, nonces), SRI sur les CDN, hôte autorisé exact |
| Médias | **Cloudinary** |
| Fichiers statiques | **WhiteNoise** (compression, noms par empreinte) |
| Tests et CI | Tests Django, **GitHub Actions** avec PostgreSQL |
| Hébergement | **Render** (Gunicorn) |

---

## 🏗️ Organisation du code

```text
pharmanps_alou/        Réglages, URL, lanceur de tests, outils de test partagés
users/                 Connexion, tableau de bord, rôles (roles.py), init_admin, init_demo
medications/           Médicaments, catégories, formulaires
  stock.py             Seul point d'écriture du stock
  management/commands/seed_data.py
sales/                 Caisse, ventes, clients, ordonnances, formulaires
  services.py          Création d'une vente (calculs, contrôles, transaction)
templates/             Interface (dont 403, partials/form_errors.html)
.github/workflows/     Intégration continue
build.sh, render.yaml  Déploiement sur Render
```

Chaque application a un dossier `tests/`.

---

## 🧪 Tests et intégration continue

**176 tests automatisés** (`python manage.py test`), lancés par GitHub Actions à chaque push et pull request avec une vraie base PostgreSQL, après `pip-audit`, `check --deploy` et `makemigrations --check`. Couverture mesurée : 93 % du code (hors migrations et tests).

| Domaine | Ce qui est vérifié |
|---|---|
| Prix et totaux | Prix falsifié ignoré, montants exacts en Decimal et arrondis au franc CFA (paiement du montant affiché accepté, prix entiers), remise hors limites refusée, total jamais négatif, quantités entières > 0, aucune fuite de message d'erreur interne |
| Accès | **Page de connexion** : « Se souvenir de moi » fixe vraiment la durée de session (fermeture du navigateur sinon), aucun lien mort ; **matrice complète** : chaque page testée en GET pour anonyme, compte sans rôle, Vendeur, Pharmacien et superutilisateur, et toute nouvelle route doit y être ajoutée ; formulaires réservés envoyés par un Vendeur refusés (403) sans aucun changement en base ; inscription fermée, 403 pour un Vendeur sur la modification ou la suppression d'un médicament, données médicales masquées, compte sans rôle bloqué, déconnexion en POST, compte de démonstration idempotent, admin : ventes, lignes et ordonnances en lecture seule et encours de crédit non modifiable, même pour un superutilisateur |
| XSS | Un médicament nommé `</script><script>alert(1)</script>` s'affiche comme du texte au tableau de bord et à la caisse ; CSP stricte sur toutes les pages (admin comprise) : chaque script intégré porte le nonce, aucun attribut `onclick`/`onchange`, seuls les CDN autorisés, avec SRI ; un autre service `*.onrender.com` est refusé |
| Périmés et ordonnances | Périmé absent de la caisse et refusé par le serveur, client et ordonnance exigés, ordonnance de plus de 3 mois refusée (fins de mois comprises), ordonnance liée à la vente et affichée sur la facture |
| Stock | Sortie supérieure au stock refusée, ajustements dans les deux sens, historique égal au stock, **deux ventes, deux sorties, ou une vente et une sortie manuelle simultanées** (fils d'exécution concurrents sur PostgreSQL) |
| Ventes | Numéros uniques en concurrence, monnaie, espèces insuffisantes, crédit (client, plafond, encours, **deux ventes à crédit simultanées qui dépasseraient ensemble le plafond**), coût d'achat figé, **double envoi** (même jeton de caisse, y compris en simultané) = une seule vente |
| Formulaires | Prix, quantités, code-barres unique, dates, catégorie en double, champs sensibles non modifiables sans permission |
| Accessibilité | Chaque champ de formulaire a un libellé associé (`for`/`id` ou `aria-label`), messages de la caisse dans une zone `aria-live` au lieu d'`alert()`, boutons de paiement avec `aria-pressed`, menu limité aux liens autorisés pour le rôle |
| Réglages | Stockages de production, `check --deploy` sans avertissement, verrouillage après 5 échecs de connexion |
| Performance | Tableau de bord en 9 requêtes, quel que soit le volume (`assertNumQueries`) ; listes des ventes, clients, médicaments et catégories en un nombre de requêtes constant ; pagination qui garde recherche et filtres |
| Déploiement | `init_admin` et `seed_data` reconstruisent la démo sur une base vide, sans doublon s'ils sont relancés |
| Clients | Suppression d'un client avec ventes, ordonnances ou crédit refusée (code et admin, message explicite), fiche sans historique supprimable, archivage et réactivation, client archivé masqué et refusé à la caisse, migration 0006 appliquée puis défaite sans perte |
| Caisse | Clients cherchés à la demande : par nom, prénom ou téléphone, clients archivés exclus, 10 résultats au plus, aucune donnée médicale renvoyée, droits de la caisse exigés ; la page de caisse n'embarque plus aucun client et son nombre de requêtes ne dépend pas du nombre de clients |

Les tests de concurrence nécessitent PostgreSQL ; ils sont ignorés avec SQLite.

---

## 🚀 Installation locale

```bash
git clone https://github.com/NdeyePendaSarr/pharmacy-management.git
cd pharmacy-management
python -m venv venv
source venv/bin/activate        # Windows : venv\Scripts\activate
pip install -r requirements.txt
```

Créer un fichier `.env` à la racine (lu par python-decouple) :

```dotenv
SECRET_KEY=une-cle-locale-longue-et-aleatoire
DEBUG=True
# Facultatif : sans DATABASE_URL, la base est un fichier SQLite local.
DATABASE_URL=postgres://utilisateur:motdepasse@localhost:5432/pharmanps
```

```bash
python manage.py migrate          # crée aussi les groupes Pharmacien et Vendeur
python manage.py createsuperuser
python manage.py seed_data        # données de démonstration fictives (base vide uniquement)
python manage.py runserver
python manage.py test             # 176 tests
```

La feuille de style `static/css/output.css` est générée par Tailwind CSS à partir de `static/css/input.css` (voir `build.sh`).

---

## 🌍 Déploiement sur Render

`render.yaml` décrit le service web ; la base PostgreSQL est hébergée chez Neon et reliée par `DATABASE_URL`. À chaque déploiement, `build.sh` exécute :

```text
pip install → Tailwind CSS → collectstatic → migrate (+ groupes)
→ init_admin → init_demo → seed_data
```

Les trois commandes d'initialisation sont **idempotentes** : relancées, elles ne créent ni doublon ni incohérence. `seed_data` ne fait rien si la base contient déjà des médicaments.

| Variable | Rôle |
|---|---|
| `SECRET_KEY`, `DEBUG=False`, `DATABASE_URL` | Réglages Django |
| `ALLOWED_HOSTS` | Adresse(s) acceptée(s), séparées par des virgules ; `render.yaml` y met l'adresse du service (Render fournit aussi `RENDER_EXTERNAL_HOSTNAME`, ajoutée automatiquement) |
| `CLOUDINARY_CLOUD_NAME`, `CLOUDINARY_API_KEY`, `CLOUDINARY_API_SECRET` | Stockage des médias |
| `ADMIN_USERNAME`, `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Superutilisateur créé par `init_admin` |
| `DEMO_USERNAME`, `DEMO_PASSWORD` | Compte de démonstration Vendeur créé par `init_demo` |
| `ALLOW_REGISTRATION` | `False` par défaut ; `True` rouvre l'inscription publique (comptes sans rôle) |

### Base de données (Neon)

La base n'est plus une base Render gratuite (elle expire au bout de quelques semaines) : c'est une base PostgreSQL **Neon**, région Francfort, comme le service web. Dans `render.yaml`, `DATABASE_URL` est en `sync: false` : sa valeur se saisit dans le tableau de bord Render et n'est jamais commitée.

- Utiliser la chaîne de connexion **directe** de Neon (hôte sans `-pooler`) terminée par `?sslmode=require` : l'application garde des connexions persistantes (`conn_max_age=600`), ce que le pooler de Neon en mode transaction ne permet pas.
- Une **base vide suffit** : au déploiement suivant, `migrate` crée les tables et les rôles, `init_admin` et `init_demo` les comptes, `seed_data` les données fictives.
- Sur une base neuve, le superutilisateur n'existe que si `ADMIN_USERNAME` et `ADMIN_PASSWORD` sont définies ; les autres comptes (Pharmaciens) sont à recréer depuis l'admin.
- Changer de base déconnecte tout le monde (les sessions sont en base).

---

## ⚠️ Limites connues

- Les **points de fidélité** sont enregistrés et affichés, mais aucune règle ne les attribue encore.
- Le statut de vente « annulée » existe, mais il n'y a pas encore de parcours d'annulation ni de remise en stock.
- La caisse charge encore d'un coup tous les médicaments vendables (les clients sont cherchés à la demande, les autres listes sont paginées).

## 🔮 Pistes d'amélioration

- Annulation et remboursement d'une vente, avec mouvement de retour en stock et diminution de l'encours de crédit.
- Règles d'attribution des points de fidélité.
- Règlement de l'encours de crédit d'un client depuis l'interface.

---

## 🎓 Compétences mises en pratique

Django et PostgreSQL ; modélisation relationnelle et migrations de données ; transactions et verrouillage (`select_for_update`) ; contrôle d'accès par rôles ; prévention des failles XSS et de la falsification de montants ; validation de formulaires ; optimisation des requêtes (agrégations groupées) ; tests automatisés, y compris de concurrence ; intégration continue ; déploiement sur Render avec WhiteNoise et Cloudinary.

---

## 🔗 Liens

- **Application en ligne :** https://pharmanps-aloucoding-b8ex.onrender.com/
- **Dépôt GitHub :** https://github.com/NdeyePendaSarr/pharmacy-management

---

## 👥 Équipe

Projet académique réalisé **en binôme** (2025), puis repris et développé par Ndeye Penda Sarr (2026).

- **Ndeye Penda Sarr** — Développeuse Web Full-Stack · Business Intelligence & Data. Conception et développement de l'application ; reprise en 2026 : audit, sécurité, gestion de la concurrence, tests, intégration continue et déploiement.
- **Alassane Ndour** ([@AlouCoding](https://github.com/AlouCoding)) — binôme du projet académique ; publication et documentation (README) de la version de décembre 2025 : [AlouCoding/PharmaNPS-Alou](https://github.com/AlouCoding/PharmaNPS-Alou).

© 2025–2026 Ndeye Penda Sarr — code sous licence [MIT](LICENSE).
