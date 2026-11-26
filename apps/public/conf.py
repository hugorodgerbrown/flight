"""The site's links and whose copyright it is.

The website's pages end with them in a footer, and the app shows them on
its account page (DESIGN.md, "The website has a footer; the app has its
links"); the tags in ``templatetags/site_footer.py`` draw them. Set once by
the project template from its answers; edit freely.
"""

# Who runs the site, as the terms and privacy notice name them: the
# controller under UK GDPR. Hugo's choice (2026-11-26): the role, not a
# name. Like the other Titan apps, no postal address: the contact address
# below is the way to reach us. Set OPERATOR_ADDRESS to add one.
OPERATOR = "Data Controller"
OPERATOR_ADDRESS = ""

# The date the terms and privacy notice last changed; bump it with them.
LEGAL_UPDATED = "26 November 2026"

# Where people write to us: the help page, the terms and the privacy
# notice all give this address.
CONTACT_EMAIL = "flight@ultraniche.ai"

# The footer's copyright line: "© <this year> <holder>. All rights reserved."
COPYRIGHT_HOLDER = "Hugo Rodger-Brown"

# The links, in order: (label, URL name). A "#fragment" after the
# name links to a part of that page, as "Use with Claude" does: the help
# page's steps for Claude and ChatGPT (DESIGN.md, "The front page").
# Keep the terms and privacy notice: a site without them isn't legit.
LINKS: list[tuple[str, str]] = [
    ("Home", "public:home"),
    ("Help", "public:help"),
    ("Use with Claude", "public:help#use-with-ai"),
    ("Terms", "public:terms"),
    ("Privacy", "public:privacy"),
]
