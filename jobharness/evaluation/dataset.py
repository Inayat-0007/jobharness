"""JSONL labeled-pair dataset for dedup evaluation.

Format per line:
{"a": {...job fields...}, "b": {...}, "label": 0|1, "notes": "..."}

label=1 -> the pair is the same job (duplicate); label=0 -> distinct jobs.

The generator seeds ~200 pairs: positive pairs are synthetic rewrites of base
jobs (title rewords, company aliases, location variants, description
rewordings); negative pairs are genuinely different jobs. Fully offline and
deterministic (fixed seed) — extend with manually labeled real pairs.
"""

from __future__ import annotations

import json
import random

JOB_FIELDS = ("title", "company", "location", "description", "apply_url_direct")

TITLE_REWORDS = {
    "Backend Engineer": (
        "Backend Engineer (Remote)",
        "Senior Backend Engineer",
        "Backend Engineer, Payments",
        "Backend Platform Engineer",
        "Software Engineer - Backend",
        "Backend Software Engineer",
    ),
    "Frontend Engineer": (
        "Frontend Engineer (Remote)",
        "Frontend Developer",
        "Frontend Platform Engineer",
        "Senior Frontend Engineer",
    ),
    "Data Scientist": (
        "Data Scientist (Remote)",
        "Senior Data Scientist",
        "Data Science Engineer",
        "Data Scientist - Analytics",
    ),
}

COMPANY_ALIASES = {
    "Acme": ("Acme Inc", "Acme Corporation", "Acme Technologies"),
    "Globex": ("Globex Corp", "Globex Corporation", "Globex Inc"),
    "IBM": ("IBM Corporation", "International Business Machines"),
}

LOCATION_VARIANTS = {
    "Remote": ("Worldwide", "Anywhere", "Remote (US)"),
    "New York, NY": ("New York", "NYC", "New York City"),
    "London, UK": ("London", "London, England", "London UK"),
}

DESC_BASE = (
    "We are looking for a {title_lower} to join our team. "
    "You will build and maintain our platform with python and api services. "
    "5+ years experience required. Salary competitive, benefits included."
)

DESC_REWORDS = (
    "Our team needs a {title_lower}. You will own platform services built on python and apis. 5+ years experience. Competitive salary and benefits.",
    "{Title} wanted: build and maintain platform products in python, apis. Requires 5+ years. Great salary and benefits package.",
)


def job_dict(title: str, company: str, location: str, description: str, url: str) -> dict:
    return {
        "title": title,
        "company": company,
        "location": location,
        "description": description,
        "apply_url_direct": url,
    }


def _base_jobs() -> list[dict]:
    jobs = []
    for title in TITLE_REWORDS:
        for company in ("Acme", "Globex"):
            for location in ("Remote", "New York, NY"):
                desc = DESC_BASE.format(title_lower=title.lower())
                jobs.append(
                    job_dict(title, company, location, desc, f"https://{company.lower()}.com/jobs/1")
                )
    return jobs


def _positive_pairs(rng: random.Random, count: int) -> list[dict]:
    """Synthetic rewrites of base jobs (title rewords, company aliases,
    location variants, occasional description rewordings)."""
    bases = _base_jobs()
    pairs = []
    while len(pairs) < count:
        base = rng.choice(bases)
        title_v = rng.choice(TITLE_REWORDS[base["title"]])
        company_v = rng.choice((base["company"],) + COMPANY_ALIASES.get(base["company"], ()))
        loc_v = rng.choice((base["location"],) + LOCATION_VARIANTS.get(base["location"], ()))
        if rng.random() < 0.6:
            desc_v = base["description"]
        elif rng.random() < 0.5:
            desc_v = DESC_REWORDS[0].format(title_lower=base["title"].lower())
        else:
            desc_v = DESC_REWORDS[1].format(Title=base["title"])
        url_v = base["apply_url_direct"] if rng.random() < 0.5 else base["apply_url_direct"] + "?src=feed"
        b = job_dict(title_v, company_v, loc_v, desc_v, url_v)
        pairs.append({"a": base, "b": b, "label": 1, "notes": f"synthetic rewrite of {base['title']}"})
    return pairs


def _negative_pairs(rng: random.Random, count: int) -> list[dict]:
    jobs = _base_jobs()
    pairs = []
    while len(pairs) < count:
        x, y = rng.sample(jobs, 2)
        if x["title"].split()[0] == y["title"].split()[0] and x["company"] == y["company"]:
            continue
        pairs.append({"a": x, "b": y, "label": 0, "notes": "distinct jobs"})
    return pairs


def generate_dataset(seed: int = 42, n_pairs: int = 200) -> list[dict]:
    """Deterministic labeled-pair set (~n_pairs entries, balanced)."""
    rng = random.Random(seed)
    half = n_pairs // 2
    positives = _positive_pairs(rng, half)
    negatives = _negative_pairs(rng, n_pairs - len(positives))
    pairs = positives + negatives
    rng.shuffle(pairs)
    return pairs


def write_dataset(pairs: list[dict], path) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        for p in pairs:
            fh.write(json.dumps(p) + "\n")


def load_dataset(path) -> list[dict]:
    pairs = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                pairs.append(json.loads(line))
    return pairs
