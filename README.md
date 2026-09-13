<p align="center">
  <img src="docs/logo.svg" alt="roekish_delivery_mondialrelay" width="480">
</p>

<h1 align="center">roekish_delivery_mondialrelay</h1>

<p align="center">
  <strong>Expédiez avec Mondial Relay depuis Odoo 19 : Point Relais, Locker, domicile.</strong><br>
  Tarification, étiquettes, suivi, Points Relais.
</p>

<p align="center">
  <a href="LICENSE"><img src="https://img.shields.io/badge/licence-AGPL--3.0-blue.svg" alt="Licence AGPL-3.0"></a>
  <img src="https://img.shields.io/badge/Odoo-19.0-875A7B.svg" alt="Odoo 19.0">
  <img src="https://img.shields.io/badge/Python-3.12-3776AB.svg" alt="Python 3.12">
  <a href="https://github.com/roekish-org/odoo-delivery-mondialrelay/actions/workflows/ci.yml"><img src="https://github.com/roekish-org/odoo-delivery-mondialrelay/actions/workflows/ci.yml/badge.svg?branch=19.0" alt="CI"></a>
  <img src="https://img.shields.io/badge/PRs-bienvenues-brightgreen.svg" alt="PRs bienvenues">
</p>

---

## Fonctionnalités

| | |
|---|---|
| **Tarification** | Prix calculé depuis une **grille tarifaire Mondial Relay** (poids × zone) ou les **règles de prix natives** d'Odoo. Point d'extension `_mondialrelay_get_live_price` (fail-closed) pour un futur service de cotation. |
| **Étiquettes** | Création de l'expédition et de l'étiquette via l'**API Connect** (API V2) de Mondial Relay, production ou bac à sable : PDF 10x15, A4, A5 ou code ZPL ; numéro d'expédition enregistré sur le bon de livraison. |
| **Points Relais** | Recherche des Points Relais et Lockers proches (web service `WSI4_PointRelais_Recherche`), sélectionnable sur le **devis** et le **bon de livraison**, propagé à la validation. |
| **Suivi** | Lien de suivi Mondial Relay pour le client. |
| **Modes** | Point Relais, Point Relais XL / Locker, livraison à domicile, livraison chez le commerçant ; collecte chez le commerçant ou dépôt en Point Relais. |

Bâti sur le framework de livraison natif d'Odoo (`delivery` / `stock_delivery`).
Une **seule dépendance** de module ; `zeep` est importé à la demande et
**fail-closed** s'il manque. Les étiquettes n'ont besoin d'aucune librairie
externe. Le module reste léger et installable.

## Transporteurs et zones

Grilles indicatives 2026 fournies en démo, **éditables** par vos utilisateurs :
France, Europe zone 1 (Belgique, Luxembourg, Pays-Bas, Allemagne), Europe
zone 2 (Espagne, Royaume-Uni), Europe zone 3 (Italie, Portugal, Autriche).
Trois transporteurs prêts à l'emploi :

`Point Relais` &nbsp; `Locker` &nbsp; `Domicile`

Les tarifs professionnels Mondial Relay sont négociés par contrat. Remplacez
les grilles de démo par les vôtres.

## Installation

```bash
pip install zeep          # optionnel : recherche de Points Relais
```

Copiez `roekish_delivery_mondialrelay/` dans votre `addons_path`, puis
installez le module depuis *Applications*. La tarification et les étiquettes
fonctionnent **sans aucune librairie externe** : l'API Connect est appelée
avec `requests`, déjà fourni par Odoo.

> Déployez le module via l'`addons_path` uniquement (Odoo.sh ou On-Premise).
> *Applications > Importer un module* (zip) ne charge que les données, jamais
> les modèles Python : l'installation échoue dès la première référence à un
> modèle.

## Démo locale (Docker)

Pile Odoo 19 + PostgreSQL fournie pour tester immédiatement :

```bash
make init   # image + base de démo avec données
make up     # http://localhost:8069  (admin / admin)
make test   # suite de tests du module
```

## Sécurité

- Clé privée du web service et identifiants de l'API Connect réservés au
  groupe **Administrateur Mondial Relay** ; secrets masqués dans les messages
  d'erreur.
- Droits d'accès fins : groupes **Utilisateur** et **Administrateur** dédiés.
- Isolation multi-société sur les grilles tarifaires.

## Documentation

- [DEVELOPMENT.md](DEVELOPMENT.md) : mise en production, bac à sable,
  vérification, droits d'accès.
- [Wiki](https://github.com/roekish-org/odoo-delivery-mondialrelay/wiki) :
  installation, configuration, grilles, Points Relais, go-live.
- [roekish_delivery_mondialrelay/README.rst](roekish_delivery_mondialrelay/README.rst) : fiche du module.

Modules frères : [odoo-delivery-laposte](https://github.com/roekish-org/odoo-delivery-laposte)
(Colissimo, Delivengo) et
[odoo-delivery-dpd](https://github.com/roekish-org/odoo-delivery-dpd).

## Contribuer

Les contributions sont bienvenues. Lisez le
[guide de contribution](CONTRIBUTING.md) et le
[code de conduite](CODE_OF_CONDUCT.md). Ouvrez une *issue* pour discuter d'une
évolution, ou proposez une *pull request* sur la branche `19.0`.

## Licence

[AGPL-3.0](LICENSE). © 2026 [ROEKISH](https://github.com/roekish-org).
Maintenu par [alexis2m](https://github.com/alexis2m).
