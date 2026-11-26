# Flight launches with MCP locked to staff

Status: accepted (2026-11-26, RAS-148)

## Context

Hugo decided on 25 November that Flight launches locked: the public pages
and the connector listing are visible, but only people he lets in can use
it. Every Flightradar24 lookup spends credits (about 4 to 5 of the 60,000 a
month on the Explorer plan), and there is no per-account cap yet. The
template's default, `mcp_auth.policy.active_user`, lets any account connect,
and anyone can make an account with an emailed code.

## Decision

`MCP_AUTH["CAN_CONNECT"]` is `apps.mcp.policy.staff_only`. Hugo lets
someone in by ticking Staff status on their user in the admin. The policy
runs on the consent page and on every MCP call, so unticking it cuts that
person's clients off at once. A reviewer account for Claude's or ChatGPT's
directory is made staff too. Signing in to the website stays open: an
account on its own spends no credits.

## Consequences

Staff status also opens the admin (with no model permissions unless they
are granted) and the design page, which is acceptable for a handful of
invited people. It is a stopgap: an invite list and a daily lookup cap per
account replace it in their own issue, and this record is superseded then.
