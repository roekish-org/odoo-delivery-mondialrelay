# Odoo 19 image with the Python dependencies needed by roekish_delivery_mondialrelay.
FROM odoo:19.0

USER root
# zeep -> Mondial Relay Point Relais search (SOAP web service).
RUN pip3 install --no-cache-dir --break-system-packages zeep
USER odoo
