from datetime import datetime, timezone

import pytest

from digest.codex_runner import _codex_command, _codex_executable, _find_terms, _validate_editorial_policy
from digest.models import Article


def _article(policy_flags=None):
    return Article(
        "1",
        "Новость",
        "https://example.com/a",
        "Источник",
        datetime.now(timezone.utc),
        "",
        policy_flags=policy_flags or [],
    )


def test_selected_blocked_candidate_is_rejected():
    result = {
        "stories": [{"candidate_id": "1", "text": "Нейтральная новость про энергетику."}],
    }
    with pytest.raises(RuntimeError, match="редакционной политикой"):
        _validate_editorial_policy(
            result,
            {"1": _article(["blocked_organization:Meta"])},
            {"blocked_organization_terms": ["Meta"], "political_terms": [], "other_company_terms": []},
        )


def test_generated_company_name_is_rejected():
    result = {
        "stories": [{"candidate_id": "1", "text": "Компания Sitronics разработала решение для ЦОД."}],
    }
    with pytest.raises(RuntimeError, match="сторонних компаний"):
        _validate_editorial_policy(
            result,
            {"1": _article()},
            {"blocked_organization_terms": [], "political_terms": [], "other_company_terms": ["Sitronics"]},
        )


def test_industrial_batch_is_not_treated_as_political_party():
    terms = ["Госдум*", "политическая партия", "политические партии"]
    text = "Это уже не демонстрация прототипа, а партия техники для реального маршрута."
    assert _find_terms(text, terms) == []


def test_political_inflections_are_still_detected():
    terms = ["Госдум*", "политическая партия", "политические партии"]
    assert _find_terms("Проект закона принят Госдумой.", terms) == ["Госдум*"]
    assert _find_terms("Политическая партия выдвинула кандидата.", terms) == ["политическая партия"]


def test_codex_executable_can_be_overridden(monkeypatch):
    monkeypatch.setenv("CODEX_BIN", r"C:\Tools\codex.cmd")
    assert _codex_executable() == r"C:\Tools\codex.cmd"


def test_codex_executable_uses_path(monkeypatch):
    monkeypatch.delenv("CODEX_BIN", raising=False)
    monkeypatch.setattr("digest.codex_runner.shutil.which", lambda command: "/usr/local/bin/codex")
    assert _codex_executable() == "/usr/local/bin/codex"


def test_codex_cmd_uses_windows_command_processor(monkeypatch):
    monkeypatch.setattr("digest.codex_runner.os.name", "nt")
    monkeypatch.setenv("COMSPEC", r"C:\Windows\System32\cmd.exe")
    monkeypatch.setenv("CODEX_BIN", r"C:\Users\serjano\AppData\Roaming\npm\codex.cmd")
    assert _codex_command() == [
        r"C:\Windows\System32\cmd.exe",
        "/d",
        "/c",
        r"C:\Users\serjano\AppData\Roaming\npm\codex.cmd",
    ]
