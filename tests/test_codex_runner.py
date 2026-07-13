from datetime import datetime, timezone

import pytest

from digest.codex_runner import _find_terms, _validate_editorial_policy
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
        "title_options": [f"Заголовок {index}" for index in range(10)],
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
        "title_options": [f"Заголовок {index}" for index in range(10)],
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
