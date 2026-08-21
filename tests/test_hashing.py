from __future__ import annotations

from jobharness.models import _norm, job_id_hash


def _hash(title: str) -> str:
    return job_id_hash(title, "Acme", "Remote")


def test_cpp_vs_csharp_tokens():
    assert _norm("C++") == "cpp"
    assert _norm("C#") == "csharp"


def test_cpp_vs_csharp_produce_different_hashes():
    assert _hash("C++ Developer") != _hash("C# Developer")


def test_cpp_spelling_variants_collide():
    assert _hash("C++ Developer") == _hash("cpp developer")


def test_node_js_variants_normalize_same_token():
    assert _norm("Node.js") == _norm("Nodejs") == _norm("Node js") == "nodejs"


def test_node_js_variants_same_hash():
    a = _hash("Node.js Developer")
    b = _hash("Nodejs Developer")
    c = _hash("Node js Developer")
    assert a == b == c


def test_python_case_insensitive():
    assert _norm("Python") == _norm("python") == "python"
    assert _hash("Python Developer") == _hash("python developer")


def test_hash_differs_by_company_and_location():
    assert job_id_hash("Backend Engineer", "Acme", "Remote") != job_id_hash("Backend Engineer", "Acme", "Onsite")
    assert job_id_hash("Backend Engineer", "Acme", "Remote") != job_id_hash("Backend Engineer", "Other Co", "Remote")
