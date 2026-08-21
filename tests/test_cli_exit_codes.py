from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

import jobharness.sources.api.remoteok as remoteok_mod
from jobharness.cli import main
from jobharness.models import RawJob


def _write_profile(tmp_path):
    p = tmp_path / "p.yaml"
    p.write_text(
        "name: t\nroles: [Backend Engineer]\nkeywords: [python]\nexcludes: [manager]\n"
        "remote: true\nllm_provider: gemini\ntop_n: 5\nsources:\n  remoteok: true\n",
        encoding="utf-8",
    )
    return p


def _make_raw():
    return [
        RawJob(
            source_name="remoteok",
            source_url="https://remoteok.com/l/1",
            title="Senior Backend Engineer",
            company="Acme",
            location="Remote",
            description="We need a backend engineer with 5 years experience. Python, API.",
            posted_date="2023-11-14",
            apply_url="https://remoteok.com/l/1",
        )
    ]


def _offline_pipeline(monkeypatch, tmp_path):
    monkeypatch.setattr("jobharness.cli.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(remoteok_mod.RemoteOKAdapter, "fetch", lambda self, p: _make_raw())
    monkeypatch.setattr(
        "jobharness.runner.enabled_adapters",
        lambda profile: [remoteok_mod.RemoteOKAdapter()],
    )


def test_main_run_dry_run_returns_zero(tmp_path, monkeypatch):
    _offline_pipeline(monkeypatch, tmp_path)
    profile = _write_profile(tmp_path)
    rc = main(
        ["run", "--profile", str(profile), "--source", "remoteok", "--top", "1",
         "--dry-run", "--no-llm"]
    )
    assert rc == 0


def test_main_unknown_source_exits_2(tmp_path, monkeypatch):
    monkeypatch.setattr("jobharness.cli.PROJECT_ROOT", tmp_path)
    profile = _write_profile(tmp_path)
    rc = main(["run", "--profile", str(profile), "--source", "not_a_source", "--dry-run", "--no-llm"])
    assert rc == 2


def test_main_missing_profile_exits_2(tmp_path, monkeypatch):
    monkeypatch.setattr("jobharness.cli.PROJECT_ROOT", tmp_path)
    rc = main(
        ["run", "--profile", str(tmp_path / "missing.yaml"), "--source", "remoteok",
         "--dry-run", "--no-llm"]
    )
    assert rc == 2


def test_main_invalid_yaml_exits_2(tmp_path, monkeypatch):
    monkeypatch.setattr("jobharness.cli.PROJECT_ROOT", tmp_path)
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: [unclosed\n", encoding="utf-8")
    rc = main(["run", "--profile", str(bad), "--source", "remoteok", "--dry-run", "--no-llm"])
    assert rc == 2


def test_main_unexpected_failure_exits_1(tmp_path, monkeypatch):
    monkeypatch.setattr("jobharness.cli.PROJECT_ROOT", tmp_path)
    profile = _write_profile(tmp_path)

    def boom(*a, **kw):
        raise RuntimeError("pipeline exploded")

    monkeypatch.setattr("jobharness.cli.run_once", boom)
    rc = main(["run", "--profile", str(profile), "--source", "remoteok", "--dry-run", "--no-llm"])
    assert rc == 1


def test_setup_logging_console_only_when_log_dir_unwritable(tmp_path, monkeypatch):
    import jobharness.logging as logging_mod

    blocker = tmp_path / "blocker"
    blocker.write_text("", encoding="utf-8")
    monkeypatch.setattr(logging_mod, "_configured", False)

    root = logging.getLogger()
    fh_before = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]

    logging_mod.setup_logging(log_dir=str(blocker / "logs"))

    assert logging_mod._configured is True
    assert logging_mod._file_logging is False
    assert [h for h in root.handlers if isinstance(h, RotatingFileHandler)] == fh_before


def test_main_survives_read_only_cwd(tmp_path, monkeypatch):
    import jobharness.logging as logging_mod

    _offline_pipeline(monkeypatch, tmp_path)
    profile = _write_profile(tmp_path)
    monkeypatch.setattr(logging_mod, "_configured", False)
    real_mkdir = logging_mod.Path.mkdir

    def denied_mkdir(self, *args, **kwargs):
        if self == logging_mod.Path("logs"):
            raise PermissionError("read-only CWD")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(logging_mod.Path, "mkdir", denied_mkdir)
    rc = main(
        ["run", "--profile", str(profile), "--source", "remoteok", "--top", "1",
         "--dry-run", "--no-llm"]
    )
    assert rc == 0
    assert logging_mod._configured is True
    assert logging_mod._file_logging is False
