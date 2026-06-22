from __future__ import annotations

import json
import subprocess
import tempfile
import urllib.parse
from datetime import date
from pathlib import Path

from .models import Article


def generate(project: Path, articles: list[Article], start: date, end: date) -> dict:
    if len(articles) < 8:
        raise RuntimeError(f"Собрано только {len(articles)} уникальных релевантных новостей; нужно минимум 8.")
    profile = json.loads((project / "profile" / "style_profile.json").read_text(encoding="utf-8"))
    template = (project / "prompts" / "generate_digest.md").read_text(encoding="utf-8")
    payload = {
        "period": {"from": start.isoformat(), "to": end.isoformat()},
        "style_profile": profile,
        "candidates": [article.to_dict() for article in articles],
    }
    prompt = template.replace("{{INPUT_JSON}}", json.dumps(payload, ensure_ascii=False, indent=2))
    with tempfile.TemporaryDirectory(prefix="chint-digest-") as temp:
        output = Path(temp) / "digest.json"
        command = [
            "codex", "exec", "--ephemeral", "--skip-git-repo-check", "-s", "read-only",
            "-C", str(project), "--output-schema", str(project / "schemas" / "digest.schema.json"),
            "-o", str(output), "-",
        ]
        subprocess.run(command, input=prompt, text=True, check=True)
        result = json.loads(output.read_text(encoding="utf-8"))
    if len(result.get("stories", [])) != 8 or len(result.get("title_options", [])) != 10:
        raise RuntimeError("Codex вернул неполный выпуск: ожидалось 8 новостей и 10 заголовков.")
    by_id = {article.id: article for article in articles}
    chosen_ids = [story.get("candidate_id") for story in result["stories"]]
    if len(set(chosen_ids)) != 8 or any(candidate_id not in by_id for candidate_id in chosen_ids):
        raise RuntimeError("Codex вернул повторяющийся или неизвестный candidate_id.")
    if not any(story.get("story_role") == "entertaining" for story in result["stories"]):
        raise RuntimeError("Codex не включил обязательную развлекательную технологическую новость.")
    chint_ids = {article.id for article in articles if article.is_chint_russia}
    if chint_ids and not chint_ids.intersection(chosen_ids):
        raise RuntimeError("Codex пропустил найденную новость о CHINT в России.")
    # Metadata is authoritative and must never depend on model transcription.
    for story in result["stories"]:
        link_text = story.get("link_text", "").strip()
        if not link_text or story["text"].count(link_text) != 1:
            raise RuntimeError(f"Некорректная глагольная ссылка в новости {story['candidate_id']}.")
        article = by_id[story["candidate_id"]]
        if (urllib.parse.urlparse(article.url).hostname or "").endswith("google.com"):
            raise RuntimeError("В финальный выпуск попала ссылка Google вместо прямой ссылки на СМИ.")
        story["source"] = article.source
        story["url"] = article.url
        story["published_date"] = article.published_at.date().isoformat()
    result["chint_russia_included"] = bool(chint_ids)
    result["chint_russia_note"] = "" if chint_ids else (
        f"За период {start.strftime('%d.%m.%Y')}–{end.strftime('%d.%m.%Y')} "
        "публичных новостей о CHINT в России не найдено."
    )
    return result
