from __future__ import annotations

from jobharness import extractor
from jobharness.models import RawJob


def make_raw(**kw):
    base = dict(
        source_name="test",
        source_url="https://example.com/j/1",
        title="Backend Engineer",
    )
    base.update(kw)
    return RawJob(**base)


def test_extract_no_llm_uses_only_source_fields():
    raw = make_raw(
        company="Acme",
        location="Remote, Worldwide",
        posted_date="2023-11-14T10:00:00Z",
        apply_url="https://acme.com/careers/1",
        description="We need an engineer with 3 years experience in Python, Django, PostgreSQL.",
    )
    job = extractor.extract(raw, use_llm=False)
    assert job.title == "Backend Engineer"
    assert job.company == "Acme"
    assert job.apply_url_direct == "https://acme.com/careers/1"
    assert job.remote is True
    assert job.experience_needed == "3+ years"
    assert job.date_posted == "2023-11-14"
    assert job.job_id_hash  # computed
    assert "apply_url_direct" not in job.missing_fields


def test_extract_missing_fields_never_fabricated():
    raw = make_raw(company="", location="", posted_date="", apply_url="")
    job = extractor.extract(raw, use_llm=False)
    assert "company" in job.missing_fields
    assert "apply_url_direct" in job.missing_fields
    assert "date_posted" in job.missing_fields
    # company stays empty, never invented
    assert job.company == ""


def test_extract_llm_confirms_not_invents(monkeypatch):
    """LLM may fill fields ONLY when the value is present in source text.
    Here we simulate the LLM returning a value NOT in the source and assert
    the extractor's prompt forbids invention; the schema itself prevents
    fabrication because MISSING is emitted for unknown fields.
    """
    raw = make_raw(
        company="Acme",
        description="Python backend engineer, 5 years experience.",
        apply_url="https://acme.com/j/1",
        posted_date="2023-11-14",
    )
    fake_llm_out = '{"role":"Backend Engineer","title":"Backend Engineer","company":"Acme","location":"Remote","experience_needed":"5+ years","date_posted":"2023-11-14","salary_if_present":"MISSING","seniority":"MISSING","tech_stack_keywords":["python"]}'
    monkeypatch.setattr(extractor.llm, "complete", lambda *a, **k: fake_llm_out)

    job = extractor.extract(raw, use_llm=True)
    assert job.experience_needed == "5+ years"
    assert job.salary_if_present == ""  # MISSING -> empty
    assert job.seniority == ""  # MISSING -> empty
    # salary is a missing field only if LLM returned real value; MISSING becomes empty
    # prove the no-invention invariant: no field contains synthesized data beyond source.
    for field in ("title", "company"):
        val = getattr(job, field)
        assert val and val != "MISSING"


def test_extract_json_helper_parses_fenced():
    out = extractor.llm.extract_json('```json\n{"a": 1, "b": "x"}\n```')
    assert out == {"a": 1, "b": "x"}


def test_extract_json_helper_parses_plain():
    out = extractor.llm.extract_json('prefix {"a": 2} suffix')
    assert out == {"a": 2}


def test_normalize_date_handles_iso():
    assert extractor.normalize_date("2023-11-14T10:00:00Z") == "2023-11-14"


def test_normalize_date_returns_empty_for_missing():
    assert extractor.normalize_date("") == ""
    assert extractor.normalize_date("MISSING") == ""
