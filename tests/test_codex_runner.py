from datetime import datetime, timezone

import pytest

from digest.codex_runner import _validate_editorial_policy
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
