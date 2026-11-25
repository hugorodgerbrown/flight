# Flight offers Claude no note tools

Status: accepted (2026-11-25, RAS-128)

## Context

The Titan template's MCP endpoint ships two example tools, `list_notes` and
`add_note`, with a `ui://notes/list` view, and describes the server as one
that "keeps short notes". Live in Claude, Flight's connector introduced
itself that way and offered the note tools next to `where_is`, which is
what a person connects Flight for. A connector that says it is about notes
makes Claude less likely to reach for `where_is`, and offers tools that
have nothing to do with flights.

## Decision

Flight's MCP endpoint lists only `where_is` and the public pages
(`privacy_policy`, `terms_of_service`, `help`). The note tools, their view
(`notes_list.html`, `notes_list.js`) and their tests are gone, and the
server's instructions describe flight lookups. The template's generic tests
for the endpoint (errors, events, views) now call `where_is` instead.

The notes app at `/app/` itself stays for now: removing it, and putting
the watch list in its place, is its own issue.

## Consequences

- `copier update` can conflict in `apps/mcp/tools.py`, `resources.py`,
  `views.py` and their tests where the template changes the note tools.
  Keep Flight's side: no note tools.
- Each tool Flight adds replaces an example rather than sitting next to it.
