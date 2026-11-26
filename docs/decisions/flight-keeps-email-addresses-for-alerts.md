# Flight keeps email addresses, for alerts

Status: accepted (2026-11-26, RAS-144). Uses the override in
accounts-keep-a-key-not-an-email-address.md.

## Context

Titan accounts keep a keyed hash of the address by default, so an app
can't email anyone except while they sign in. Flight's alerts are emailed
when a flight takes off and lands, long after any sign-in.

## Decision

`ACCOUNTS_KEEP_EMAIL = True`. Hugo chose it on RAS-144 over push-only
alerts. The privacy notice follows the setting, and also names the flights
followed and the push subscriptions kept.

## Consequences

- An account made before this stores its address at its next sign-in.
  Until then its Email toggles are off, saying "Sign out and in again".
- The template's accounts tests still check its default: they run with the
  setting off (`tests/accounts/conftest.py`), and the ones about the
  setting set it themselves.
- A copy of the database now holds addresses: deleting an account still
  removes it with everything else.
