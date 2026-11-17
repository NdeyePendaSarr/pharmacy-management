# 💊 PharmaNPS-Alou — Gestion de pharmacie

[![CI](https://github.com/NdeyePendaSarr/pharmacy-management/actions/workflows/ci.yml/badge.svg)](https://github.com/NdeyePendaSarr/pharmacy-management/actions/workflows/ci.yml)

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
- Remise de 0 à 20 % ; paiement en espèces (monnaie rendue calculée), carte, mobile money ou **crédit**.
- Médicament **sur ordonnance** : la vente exige un client et une ordonnance (médecin, date de prescription), enregistrée et liée à la vente.
- Facture imprimable.

### 👥 Clients
Particulier, entreprise ou assurance ; coordonnées, limite de crédit et encours. Les données médicales ne sont visibles que par un Pharmacien.

### 📊 Tableau de bord
Chiffre d'affaires du jour, de la semaine, du mois et total, ventes des 7 derniers jours, top 5 des produits vendus et alertes de stock (graphiques Chart.js).

---

## 🧠 Règles métier

### Une vente est calculée par le serveur
Le navigateur n'envoie que des intentions : quels médicaments, combien, quelle remise, quel mode de paiement. Le service [`sales/services.py`](sales/services.py) fait le reste dans **une seule transaction** :

```text
Verrouillage des médicaments (SELECT … FOR UPDATE)
  → refus si périmé, stock insuffisant ou ordonnance manquante
  → prix lus en base, totaux recalculés en Decimal, remise bornée
  → contrôle du paiement (espèces suffisantes, crédit disponible)
  → vente, lignes de vente, mouvements de sortie, ordonnance
```

Si une étape échoue, rien n'est enregistré. Un message d'erreur inattendu n'est jamais renvoyé au navigateur : il est journalisé côté serveur.

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
| Sécurité | Rôles par permissions Django, **django-axes**, HTTPS/HSTS |
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

**88 tests automatisés** (`python manage.py test`), lancés par GitHub Actions à chaque push et pull request avec une vraie base PostgreSQL, après `check --deploy` et `makemigrations --check`.

| Domaine | Ce qui est vérifié |
|---|---|
| Prix et totaux | Prix falsifié ignoré, montants exacts en Decimal, remise hors limites refusée, total jamais négatif, quantités entières > 0, aucune fuite de message d'erreur interne |
| Accès | Inscription fermée, 403 pour un Vendeur sur la modification ou la suppression d'un médicament, données médicales masquées, compte sans rôle bloqué, déconnexion en POST, compte de démonstration idempotent |
| XSS | Un médicament nommé `</script><script>alert(1)</script>` s'affiche comme du texte au tableau de bord et à la caisse |
| Périmés et ordonnances | Périmé absent de la caisse et refusé par le serveur, client et ordonnance exigés, ordonnance liée à la vente |
| Stock | Sortie supérieure au stock refusée, ajustements dans les deux sens, historique égal au stock, **deux ventes et deux sorties simultanées** (fils d'exécution concurrents sur PostgreSQL) |
| Ventes | Numéros uniques en concurrence, monnaie, espèces insuffisantes, crédit (client, plafond, encours), coût d'achat figé |
| Formulaires | Prix, quantités, code-barres unique, dates, catégorie en double, champs sensibles non modifiables sans permission |
| Réglages | Stockages de production, `check --deploy` sans avertissement, verrouillage après 5 échecs de connexion |
| Performance | Tableau de bord en 9 requêtes, quel que soit le volume (`assertNumQueries`) |
| Déploiement | `init_admin` et `seed_data` reconstruisent la démo sur une base vide, sans doublon s'ils sont relancés |

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
python manage.py test             # 88 tests
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
- Les listes (médicaments, ventes, clients) ne sont pas paginées.

## 🔮 Pistes d'amélioration

- Annulation et remboursement d'une vente, avec mouvement de retour en stock et diminution de l'encours de crédit.
- Règles d'attribution des points de fidélité.
- Pagination des listes.
- Règlement de l'encours de crédit d'un client depuis l'interface.

---

## 🎓 Compétences mises en pratique

Django et PostgreSQL ; modélisation relationnelle et migrations de données ; transactions et verrouillage (`select_for_update`) ; contrôle d'accès par rôles ; prévention des failles XSS et de la falsification de montants ; validation de formulaires ; optimisation des requêtes (agrégations groupées) ; tests automatisés, y compris de concurrence ; intégration continue ; déploiement sur Render avec WhiteNoise et Cloudinary.

---

## 🔗 Liens

- **Application en ligne :** https://pharmanps-aloucoding-b8ex.onrender.com/
- **Dépôt GitHub :** https://github.com/NdeyePendaSarr/pharmacy-management

---

## 👩‍💻 Auteure

**Ndeye Penda Sarr** — Développeuse Web Full-Stack · Business Intelligence & Data

© 2025–2026 Ndeye Penda Sarr
