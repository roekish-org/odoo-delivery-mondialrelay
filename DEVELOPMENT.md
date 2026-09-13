# roekish_delivery_mondialrelay: Development & Go-Live Guide

Odoo 19 delivery carrier for **Mondial Relay**: Point Relais, Locker and home
delivery (rating, labels through the Connect API, tracking, Point Relais
search). Owned by **ROEKISH**.

---

## 1. Requirements

- Docker and Docker Compose (v2).
- No local Python/Postgres needed, everything runs in containers.

The stack (`docker-compose.yml`): Postgres 16 + Odoo 19 with `zeep` (Point
Relais search) baked into the image (`docker/Dockerfile`).

---

## 2. Quick start

```bash
make init   # build the image + create the demo DB with the module & demo data
make up     # start Odoo  ->  http://localhost:8069   (login: admin / admin)
```

Other targets:

| Command | What it does |
|---|---|
| `make test` | Run the module test suite |
| `make shell` | Open an Odoo shell on the demo DB |
| `make logs` | Follow the Odoo logs |
| `make down` | Stop the stack |
| `make reset` | Drop the demo database (then `make init` to rebuild) |

The demo database is `mondialrelay` (override with `make init DB=mydb`).

---

## 3. What the demo ships

Three ready-to-use carriers under *Inventory → Configuration → Shipping
Methods*, each with an indicative, editable grid:

- **Mondial Relay Point Relais** (mode `24R`): France grid, drives the
  Point Relais selector.
- **Mondial Relay Locker** (mode `24L`): same grid, Lockers and Point Relais
  XL.
- **Mondial Relay Domicile** (mode `HOM`): France grid plus Europe zones 1,
  2 and 3.

Demo prices are the public mondialrelay.fr grid for France and comparison
site figures for Europe (2026, taxes included). Professional rates are
negotiated per contract: your users **copy a carrier and edit its grid**.

---

## 4. Going live with a real Mondial Relay account

Mondial Relay hands out two sets of credentials with a professional offer:

- the **merchant code** (*Code Enseigne*, 8 characters) and the **web
  service private key** of the historical Web Service (API V1), used here to
  sign the Point Relais search;
- a **login** and **password** for the **Connect API** (API V2), used to
  create shipments and labels. New merchants are onboarded on API V2 only:
  the legacy `WSI2_CreationEtiquette` label method is closed to new accounts.

1. Open the carrier (e.g. *Mondial Relay Point Relais*) → **Mondial Relay**
   tab.
2. **Mondial Relay account**: enter the merchant code, the private key, the
   Connect API login and password (the secrets are readable only by Mondial
   Relay *Administrators*, see §6).
3. Tick **Sandbox** to create shipments on
   `connect-api-sandbox.mondialrelay.com` while validating, then untick it.
4. Click **Test connection**: it runs a Point Relais search on your company
   address (validates the merchant code and private key) and posts an empty
   shipment list to the Connect API (validates the login and password without
   creating anything). Errors come back with Mondial Relay's own code and
   message (`10001`: invalid login or password; STAT `97`: invalid security
   key).
5. Set the **delivery mode** (Point Relais `24R`, Point Relais XL / Locker
   `24L`, home delivery `HOM`, merchant delivery `LCC`), the **collection
   mode** (`CCC` collected at the merchant, `REL` dropped in a Point Relais)
   and the **label format** (PDF 10x15, A4, A5, or ZPL for a label printer).
6. Set **Integration Level = Get Rate and Create Shipment** so labels generate
   on delivery validation.
7. Make sure your **company address** is complete (street, ZIP, city,
   country). It is the parcel sender.

### Sender/recipient data
Addresses are built from `res.partner` (company for the sender, delivery
contact for the recipient). The contact name is split into first name and
last name (companies go to the last name), `street2` goes to
`AddressAdd1`, the company name of a contact to `AddressAdd2`, the phone to
`PhoneNo` and, when it is a French mobile, to `MobileNo`. Home delivery
requires a phone number; Point Relais delivery requires a Point Relais chosen
on the delivery and a phone or an email.

### Labels & tracking
On delivery validation Odoo posts a `ShipmentCreationRequest` (XML) to the
Connect API with one shipment per picking: order reference (`OrderNo`, sale
order name), delivery and collection modes, the Point Relais as
`Location="<country>-<number>"`, the weight in grams, sender and recipient.
The answer carries the shipment number (`ShipmentNumber`, stored in
`carrier_tracking_ref`) and the label: a PDF URL that the module downloads
and attaches, or the raw ZPL code attached as a `.zpl` file. Status nodes at
`Error` or `Critical error` level raise with their message. The customer
tracking link points to `mondialrelay.fr/suivi-de-colis` with the shipment
number and the recipient ZIP.

> The Connect API request and the `zeep` search call are the version-sensitive
> external boundaries. Validate them once against the sandbox (see the
> go-live checklist in §8).

---

## 5. Pricing model

`mondialrelay_rate_shipment` first refuses destinations Mondial Relay does
not serve, Point Relais delivery outside France, Belgium, Luxembourg, the
Netherlands, Spain and Portugal, and parcels above 30 kg (20 kg for a
Locker). It then resolves a price in this order:

1. `_mondialrelay_get_live_price(order)`: a fail-closed hook. Mondial Relay
   exposes no live rating API, so it returns `None` by default. Override it
   to plug a real endpoint without touching the rest.
2. **Pricing method = Tariff grid** → looks up `(zone, weight)` in the
   carrier's grid. Zone is derived from the destination country
   (`_mondialrelay_get_zone`).
3. **Pricing method = Odoo rules** → falls back to the standard
   `base_on_rule` engine (rules editable on the same tab).

Prices are expressed in the carrier company currency.

Zone → country mapping lives in `models/delivery_carrier.py`
(`FR_COUNTRY_CODES`, `EU1`, `EU2`, `EU3`, `PICKUP_COUNTRY_CODES`). It follows
the public grids; align it with your contract before finalizing
international pricing.

---

## 6. Access rights

A dedicated **Mondial Relay Delivery** privilege (Settings → Users) with two
groups:

- **User**: generate labels, track parcels, pick Points Relais (implies
  *Inventory / User*).
- **Administrator**: configure carriers, credentials and tariff grids
  (implies *User* + *Inventory / Administrator*).

On install, the main administrator (`base.user_admin`) is added to
**Administrator** automatically (via `post_init_hook`) so the module is usable
out of the box. Assign the groups to your other users under *Settings → Users*.

Security notes:
- The private key and the Connect API login and password are locked to
  **Administrator** at the ORM level, and a plain user reading them gets an
  `AccessError`. The label and search flows read them with `sudo`, so any
  Mondial Relay user can ship.
- All carrier error messages pass through a secret masker that redacts the
  password, the private key and any `<Password>` XML node.
- A global record rule isolates tariff grids per company.

---

## 7. Points Relais

For Point Relais and Locker carriers, a **Choose Point Relais** button
appears on the **sale order** and the **delivery order**. It opens a wizard
that searches nearby points and lets the user select one.

- With the merchant code and private key set → live
  `WSI4_PointRelais_Recherche` SOAP call (`zeep`), signed with the MD5
  security hash of the parameters and the private key. A non-zero `STAT`
  is surfaced with its meaning.
- Without credentials → three clearly-labelled demo points, so the flow is
  testable offline.

A point chosen on the sale order **propagates to the delivery order** on
confirmation, and is sent to Mondial Relay as the delivery `Location` on the
shipment.

---

## 8. Go-live checklist

- [ ] `make init && make up`, log in, confirm the three demo carriers load.
- [ ] Enter the merchant code, private key, Connect API login and password;
      tick **Sandbox**; click **Test connection**.
- [ ] Replace demo grid lines with your contract tariffs; align the zones.
- [ ] Generate one label on the sandbox end-to-end (confirm a delivery with
      the carrier), check the PDF and the shipment number.
- [ ] Test one Point Relais selection with the real credentials, then one
      Point Relais label with that point.
- [ ] Untick **Sandbox**.

---

## 9. Project layout

```
odoo-delivery-mondialrelay/
├── docker-compose.yml               # Postgres + Odoo 19 stack
├── docker/                          # Dockerfile (zeep) + odoo.conf
├── Makefile                         # init / up / test / shell / reset
└── roekish_delivery_mondialrelay/   # the Odoo module
    ├── models/               # carrier, tariff, pickup mixin, sale, picking
    ├── wizards/              # Point Relais search wizard
    ├── views/                # carrier, sale order, picking forms
    ├── security/             # groups, privilege, ACLs, record rule
    ├── demo/                 # indicative 2026 tariff grids
    └── tests/                # rating, zones, points, propagation, labels
```

The runtime dep (`zeep`) is imported lazily and is **not** declared as a
hard `external_dependency`: the module installs light and the Point Relais
search fails closed with a clear message if the library is missing.

---

## 10. Sandbox & verifying it works

### Mondial Relay test access
- **Connect API**: a sandbox (`connect-api-sandbox.mondialrelay.com`) exists;
  Mondial Relay enables the credentials of your offer on it. Tick
  **Sandbox** on the carrier to use it.
- **Web Service (search)**: Mondial Relay documents a public test merchant
  (`BDTEST13`, private key `TestAPI1key`) that answers Point Relais searches.

### What is already verified (no account needed)
- `make test` runs the module suite (24 tests): zone mapping, grid and
  rule-based rating with the served countries and weight limits, tracking
  link, cancellation, secret masking, demo and offline points, the security
  hash against the documented algorithm, sale→delivery point propagation,
  the `STAT` handling and non-administrator access to the search (with a
  mocked SOAP client), the Connect API request XML, the fail-closed guards
  (zero weight, incomplete address, missing point, missing phone, missing
  credentials, shared carrier without company), and a **mocked shipment
  creation** for PDF and ZPL outputs (`test_send_shipping_pdf_mocked`,
  `test_send_shipping_zpl_and_sandbox`) that drives the real
  `send_shipping` code against the Connect API response shape and asserts
  the label is attached and the shipment number stored.
- The **Connect API path is verified against the live sandbox**: an empty
  request with wrong credentials answers `Status Code="10001" Level="Critical
  error"`, which we surface as an error (the API returns errors in the body
  with HTTP 200, so this is checked explicitly).

### What still needs a real account
- Creating an actual shipment end-to-end (valid Connect API credentials).
- Listing real Points Relais with your own merchant code.

### How to check a real account
1. Enter the credentials on a carrier → **Test connection**. Success means
   both APIs accept them; an error shows the exact Mondial Relay code/message.
2. Tick **Sandbox**, confirm a delivery with the carrier to create one test
   shipment, and verify the shipment number and the attached label on the
   transfer.
