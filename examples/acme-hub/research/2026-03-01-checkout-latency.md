# Checkout latency (2026-03-01)

p95 of `POST /v1/checkout` went from 380 ms to 910 ms after orders-api v87. The tax lookup is
called once per line item instead of once per cart (introduced by the multi-currency change).
Next: batch the lookup; measure on staging with a 30-item cart.
