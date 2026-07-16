from datetime import date
from zipfile import ZipFile

from digest.document import build_docx


def test_story_link_is_embedded_in_verb(tmp_path):
    data = {
        "stories": [
            {
                "candidate_id": str(index),
                "text": f"Компания разработала технологию номер {index}. Она помогает энергетикам.",
                "link_text": "разработала",
                "story_role": "entertaining" if index == 7 else "core",
                "source": "Источник",
                "url": f"https://example.com/{index}",
                "published_date": "2026-06-21",
            }
            for index in range(10)
        ],
    }
    output = tmp_path / "digest.docx"
    build_docx(data, output, date(2026, 6, 15), date(2026, 6, 21))
    with ZipFile(output) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert xml.count("<w:hyperlink") == 10
    assert xml.count(">разработала<") == 10
    assert "Источник:" not in xml
    assert "10 вариантов заголовка" not in xml
    assert "Основной вариант заголовка" not in xml


def test_missing_chint_note_is_added(tmp_path):
    data = {
        "stories": [
            {
                "candidate_id": str(index),
                "text": f"Компания разработала технологию номер {index} для энергетики.",
                "link_text": "разработала",
                "story_role": "entertaining" if index == 7 else "core",
                "source": "Источник",
                "url": f"https://example.com/{index}",
                "published_date": "2026-06-21",
            }
            for index in range(10)
        ],
        "chint_russia_note": "Новостей о CHINT в России не найдено.",
    }
    output = tmp_path / "digest.docx"
    build_docx(data, output, date(2026, 6, 15), date(2026, 6, 21))
    with ZipFile(output) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    assert "Редакционная пометка:" in xml
    assert "Новостей о CHINT в России не найдено." in xml
