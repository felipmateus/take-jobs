"""Search term to URL slug (`_spec.md` > Integration Points)."""

from take_jobs.domain.rules import normalize


def slugify_term(term: str) -> str:
    """Normalize the term (rule 4) and join its words with `-`.

    Example: `desenvolvedor .net` -> `desenvolvedor-net`. Both sites accept this slug for every
    default term (checked against the live sites on 2026-10-30).
    """
    return "-".join(normalize(term).split())
