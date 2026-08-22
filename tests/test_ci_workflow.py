from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _workflow_on():
    """Load the CI workflow and return the parsed 'on' trigger dict.
    YAML 1.1 treats 'on' as a boolean True, so we check both keys."""
    ci = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    return ci.get("on") or ci.get(True)


def test_ci_workflow_triggers_on_push_and_pull_request():
    on = _workflow_on()
    assert "push" in on
    assert "pull_request" in on


def test_ci_workflow_runs_for_v4_branch():
    """The workflow must fire for a branch named v4: either the branch
    filter is absent (all branches run) or the list contains v4."""
    on = _workflow_on()
    branches = on["push"].get("branches") if isinstance(on["push"], dict) else None
    assert branches is None or "v4" in branches
