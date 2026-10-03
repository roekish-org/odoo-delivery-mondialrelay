# Changelog

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/).
Ce projet suit le versionnage des modules Odoo (`19.0.x.y.z`).

## [19.0.1.2.0] - 2026-10-03

### Ajouté

- **Étiquettes de démonstration** : case à cocher sur le transporteur.
  Activée, la validation d'un bon de livraison joint une étiquette PDF 10x15
  « SPÉCIMEN » générée localement (adresses, poids, référence, Point Relais,
  code-barres) avec un faux numéro de suivi `DEMO…`, sans appel à l'API
  Connect : aucun envoi créé, rien de facturé, code enseigne non requis.
  Les autres contrôles du colis (poids, destination, adresse, Point Relais,
  téléphone/e-mail) restent appliqués. Un bandeau signale le mode sur la
  fiche transporteur ; pas de lien de suivi pour les numéros `DEMO`.

## [19.0.1.1.0] - 2026-09-13

### Ajouté

- **Délai de livraison** annoncé, en jours ouvrés : champs min / max sur le
  transporteur, surcharge par zone sur les lignes de la grille tarifaire,
  valeurs de démo indicatives.
- Chaque cotation (`rate_shipment`) renvoie `delay_min` et `delay_max` avec
  le prix, pour choisir un transporteur sur le coût et le délai ; la phrase
  « Livraison en X à Y jours ouvrés » s'affiche dans l'assistant d'ajout de
  livraison et est conservée sur le devis.
- Tests du délai (grille, surcharge par zone, règles Odoo, point d'entrée
  générique).

## [19.0.1.0.0] - 2026-09-13

### Ajouté

- Type de transporteur `mondialrelay` sur le framework de livraison natif
  d'Odoo, modes Point Relais, Point Relais XL / Locker, domicile et livraison
  chez le commerçant.
- Tarification par grille Mondial Relay (zones FR, Europe 1, 2 et 3) ou par
  règles Odoo, avec un point d'extension `_mondialrelay_get_live_price`. Les
  pays non desservis, le Point Relais hors pays couverts et les colis trop
  lourds sont refusés avec un message explicite.
- Génération d'étiquettes via l'API Connect (API V2) de Mondial Relay,
  production ou bac à sable : PDF 10x15, A4, A5 ou code ZPL, numéro
  d'expédition sur le bon de livraison. Aucune librairie externe.
- Sélection de Point Relais sur le devis et le bon de livraison, avec
  propagation à la confirmation (web service `WSI4_PointRelais_Recherche`
  signé, points de démonstration sans identifiants).
- Bouton de test de connexion : recherche de Points Relais sur l'adresse de
  la société et validation des identifiants de l'API Connect sans créer
  d'expédition.
- Lien de suivi Mondial Relay pour le client.
- Contrôles avant appel : poids nul, adresse incomplète, code enseigne
  manquant, Point Relais absent, téléphone absent à domicile, contact
  absent, adresse expéditeur incomplète.
- Grilles indicatives 2026 en données de démonstration (Point Relais,
  Locker, Domicile).
- Droits d'accès fins (groupes Utilisateur et Administrateur), masquage des
  secrets, isolation multi-société.
- Pile Docker de démonstration, suite de tests (24 tests), intégration
  continue.
