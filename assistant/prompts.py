"""System prompt assembly for the dashboard help assistant.

Ordering matters here. The knowledge base is byte-identical for every request,
so it goes first and carries the cache breakpoint; the per-user role line is
volatile and goes last. Putting the role first would change the prefix per user
and defeat prompt caching entirely.
"""
from functools import lru_cache
from pathlib import Path

from site_cars.permissions import SECTIONS, allowed_sections, is_site_admin

KNOWLEDGE_DIR = Path(__file__).resolve().parent / "knowledge"

_SECTION_LABELS = {key: label for key, label, _help in SECTIONS}

INSTRUCTIONS = """\
You are the in-dashboard help assistant for a car dealership website built on a \
multi-tenant Django platform. You help the site's own staff and admins operate \
their dashboard.

Answer in the language the admin writes in. They are Arabic speakers, so Arabic \
is the norm — reply in clear Modern Standard Arabic unless they write to you in \
English. Refer to buttons and fields by the exact Arabic label they see on \
screen; those labels are quoted in the guide below.

Ground every answer in the guide below. It describes this specific dashboard. \
Do not invent a page, button, field, or menu that isn't in the guide — if the \
guide doesn't cover what they asked, say plainly that you don't have that \
information and suggest they contact support. A confident wrong answer costs \
them far more than "I don't know".

Be concrete and short. Give the steps in order, name the fields they must fill, \
and mention the path to the page. Two or three sentences plus a short numbered \
list is usually right. Skip preamble — start with the answer.

Never claim to have performed an action. You explain how; the admin clicks. You \
cannot see their cars, their data, or their screen, so don't guess at what's \
currently on it — if the answer depends on what they're looking at, ask.

Stay on the subject of operating this dashboard. If asked about something else \
entirely, say that's outside what you can help with here."""

ROLE_TEMPLATE = """\
About the person asking right now:

- Role: {role}
- Dashboard sections they can reach: {sections}

Only explain what this person can actually reach. If they ask how to do \
something that needs a section they don't have, tell them their account doesn't \
have access to it and that their site admin can grant it — do not walk them \
through steps that will land on a 403."""


#: Section key -> what a `<key>.md` guide file covers, for the scope line.
_TOPIC_NAMES = {
    "cars": "cars and inventory",
    "sales": "invoices, receipts, contracts and shipping",
    "orders": "customer orders",
    "reviews": "ratings, questions and the FAQ",
}


@lru_cache(maxsize=1)
def knowledge_base() -> str:
    """The concatenated guide, prefixed with what it does and doesn't cover.

    The scope line is derived from the filenames on disk rather than written
    into any guide. Hand-written scope notes go stale the moment a new file is
    added — a leftover "invoices aren't covered yet" makes the model refuse
    questions it can now answer. Dropping a new .md in this directory is
    therefore the only step needed to widen the assistant's scope.
    """
    paths = sorted(KNOWLEDGE_DIR.glob("*.md"))
    if not paths:
        raise RuntimeError(f"No knowledge files found in {KNOWLEDGE_DIR}")

    covered = [_TOPIC_NAMES.get(p.stem, p.stem) for p in paths]
    scope = (
        "This guide currently covers: "
        + "; ".join(covered)
        + ". Anything else in the dashboard (staff accounts, the page builder, "
        "site settings, billing/subscription, Telegram, imports) is NOT covered "
        "— for those, say you don't have the information and suggest support."
    )
    body = "\n\n---\n\n".join(p.read_text(encoding="utf-8").strip() for p in paths)
    return f"{scope}\n\n---\n\n{body}"


def _describe_role(user) -> tuple[str, str]:
    granted = allowed_sections(user)
    if is_site_admin(user):
        role = "Site admin (owner of this site — full dashboard access)"
    else:
        role = "Limited staff member"
    if granted:
        sections = "، ".join(
            f"{_SECTION_LABELS[key]} ({key})" for key in sorted(granted)
        )
    else:
        sections = "none"
    return role, sections


def build_system_prompt(user) -> list[dict]:
    """System blocks: stable instructions+guide first, volatile role last.

    The cache_control marker sits on the guide, the last stable block. Below
    ~4096 tokens Haiku silently won't cache it (no error, no charge) — it starts
    paying off on its own once the guide grows past that, which it will as the
    remaining dashboard sections get written.
    """
    role, sections = _describe_role(user)
    return [
        {"type": "text", "text": INSTRUCTIONS},
        {
            "type": "text",
            "text": f"# Dashboard guide\n\n{knowledge_base()}",
            "cache_control": {"type": "ephemeral"},
        },
        {"type": "text", "text": ROLE_TEMPLATE.format(role=role, sections=sections)},
    ]
