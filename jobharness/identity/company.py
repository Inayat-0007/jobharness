from __future__ import annotations

from .. import algo
from ..urlutil import apply_url_domain

# Company-name aliases: normalize_company handles suffix stripping; this map
# folds known brand names into a single canonical entity.
COMPANY_ALIASES = {
    "ibm": "international business machines",
    "meta": "facebook",
    "gm": "general motors",
    "at&t": "at and t",
}


def company_identity(job) -> tuple[str, str]:
    """(canonical_name, domain) for a job's employer.

    canonical_name: suffix-stripped + alias-mapped company name.
    domain: employer_domain if known, else the apply URL's host.
    """
    name = algo.normalize_company(getattr(job, "company", "") or "")
    name = COMPANY_ALIASES.get(name, name)
    domain = getattr(job, "employer_domain", "") or apply_url_domain(
        getattr(job, "apply_url_direct", "") or ""
    )
    return name, domain
