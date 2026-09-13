==============================
Delivery Carrier Mondial Relay
==============================

Rate, ship and track parcels with **Mondial Relay** from Odoo 19: Point
Relais, Locker and home delivery.

This module plugs into Odoo's native delivery framework (``delivery`` /
``stock_delivery``) and adds a ``mondialrelay`` carrier type that can:

* **Rate** a shipment using a Mondial Relay tariff grid (weight by zone) or
  Odoo's rule-based pricing, refusing countries Mondial Relay does not serve,
  Point Relais delivery outside the covered countries and parcels above the
  weight limit.
* **Ship**: create the shipment and its label through the Mondial Relay
  **Connect API** (API V2, production or sandbox). The label (PDF 10x15, A4,
  A5 or ZPL code) is attached to the delivery order with the shipment
  number. Zero-weight parcels, incomplete addresses, a missing Point Relais
  or a missing phone number for home delivery are rejected with a clear
  message before anything is sent.
* **Track**: expose the Mondial Relay tracking link to the customer.
* **Points Relais**: search nearby Points Relais and Lockers through the
  Mondial Relay web service (``WSI4_PointRelais_Recherche``) and select one
  on the sale order or the delivery order. A point chosen on the order is
  carried onto the delivery at confirmation and sent on the shipment.
* **Test the connection** from the carrier form: the Point Relais search is
  called on the company address, and the Connect API credentials are
  validated without creating a shipment.

Pricing
=======

Mondial Relay does not expose a live rating API, so prices come from data you
control:

* **Tariff grid** *(default)*: weight brackets per zone, edited directly on
  the carrier. Zones: metropolitan France (with Monaco), Europe zone 1
  (Belgium, Luxembourg, Netherlands, Germany), Europe zone 2 (Spain, United
  Kingdom) and Europe zone 3 (Italy, Portugal, Austria).
* **Odoo pricing rules**: the standard ``base_on_rule`` engine.

``delivery.carrier._mondialrelay_get_live_price`` is a fail-closed extension
point. Override it to plug a rating endpoint (for example a third-party
aggregator) without touching the rest of the flow.

Demo data ships three carriers with indicative 2026 public rates (Point
Relais, Locker, Domicile). Professional rates are negotiated per contract:
replace them with yours.

Requirements
============

* Python ``zeep`` for live Point Relais search.
* A Mondial Relay merchant code (*Code Enseigne*) and the web service private
  key (API V1), for the Point Relais search.
* A Mondial Relay Connect API login and password (API V2), for shipments and
  labels. The API is called with ``requests`` and ``lxml``, shipped with
  Odoo.

Rating and labels work with no external library. ``zeep`` is optional,
imported on demand, and the Point Relais search fails closed with a clear
message if it is missing.

Deploy the module on the ``addons_path`` (Odoo.sh or On-Premise). The
*Apps > Import Module* zip upload is data-only: it never loads Python models,
so it fails on the first model reference. On Odoo Online (SaaS) Python
libraries cannot be installed either, so the live Point Relais search needs
Odoo.sh or On-Premise.

Configuration
=============

#. Go to *Inventory > Configuration > Shipping Methods*.
#. Create a shipping method with provider **Mondial Relay**.
#. Fill the merchant code, the web service private key, the Connect API
   login and password, tick *Sandbox* while validating, then click **Test
   connection**.
#. Choose the delivery mode (Point Relais, Locker, home, merchant), the
   collection mode and the label format.
#. Choose a pricing method and fill the tariff grid (or the pricing rules).
#. Set *Integration Level* to **Get Rate and Create Shipment** to generate
   labels on delivery validation.
#. Make sure the company address is complete: it is the parcel sender.

Access rights
=============

A **Mondial Relay Delivery** privilege provides two groups: *User* (ship,
track, pick Points Relais) and *Administrator* (configure carriers,
credentials and grids). The private key and the Connect API credentials are
readable by administrators only, secrets are masked in error messages, and a
record rule isolates tariff grids per company. Sales users can pick a Point
Relais on quotations. The main administrator is added to the *Administrator*
group at install.

Credits
=======

Authors
-------

* ROEKISH

Contributors
------------

* Alexis Maison (`alexis2m <https://github.com/alexis2m>`_), ROEKISH

This module follows the design of the ROEKISH ``roekish_delivery_laposte``
module. It does not depend on Odoo's ``delivery_mondialrelay`` website
widget and can be installed next to it.

License
=======

AGPL-3. See ``LICENSE`` / http://www.gnu.org/licenses/agpl.html.
