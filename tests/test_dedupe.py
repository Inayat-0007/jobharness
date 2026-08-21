from __future__ import annotations

from jobharness.dedupe import DedupeStore
from jobharness.models import VALID_AUTHENTIC, Job


def make_job(source="remoteok"):
    j = Job(title="Backend Engineer", company="Acme", location="Remote")
    j.source_name = source
    j.apply_url_direct = "https://acme.com/j/1"
    j.authentic_status = VALID_AUTHENTIC
    j.compute_hash()
    return j


def test_first_insert_is_new(tmp_path):
    store = DedupeStore(tmp_path / "t.db")
    job = make_job()
    assert store.upsert(job) is True
    assert job.genuinely_new is True
    store.close()


def test_second_insert_same_job_not_new(tmp_path):
    store = DedupeStore(tmp_path / "t.db")
    store.upsert(make_job())
    job2 = make_job(source="weworkremotely")
    assert store.upsert(job2) is False
    assert job2.genuinely_new is False
    assert "weworkremotely" in job2.seen_sources
    assert "remoteok" in job2.seen_sources
    store.close()


def test_different_jobs_get_different_hashes():
    a = make_job()
    b = Job(title="Frontend Engineer", company="Acme", location="Remote")
    b.source_name = "remoteok"
    b.apply_url_direct = "x"
    b.compute_hash()
    assert a.job_id_hash != b.job_id_hash
