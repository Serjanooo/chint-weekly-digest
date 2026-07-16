from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import urllib.parse
from datetime import date
from pathlib import Path

from .models import Article

WORD_CHARS = "0-9a-zа-яё"


def _term_matches(text: str, term: str) -> bool:
    normalized = text.lower().replace("ё", "е")
    needle = term.lower().replace("ё", "е").strip()
    if not needle:
        return False
    if needle.endswith("*"):
        base = needle[:-1]
        return bool(base) and re.search(rf"(?<![{WORD_CHARS}]){re.escape(base)}", normalized) is not None
    if re.fullmatch(rf"[{WORD_CHARS}\-]+", needle):
        return re.search(rf"(?<![{WORD_CHARS}]){re.escape(needle)}(?![{WORD_CHARS}])", normalized) is not None
    return needle in normalized


def _find_terms(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if _term_matches(text, term)]


def _validate_editorial_policy(result: dict, articles_by_id: dict[str, Article], policy: dict) -> None:
    blocked_prefixes = {"blocked_organization", "politics", "incident"}
    for story in result.get("stories", []):
        article = articles_by_id[story["candidate_id"]]
        blocked_flags = [flag for flag in article.policy_flags if flag.split(":", 1)[0] in blocked_prefixes]
        if blocked_flags:
            raise RuntimeError(
                f"В выпуск попала новость, запрещённая редакционной политикой: {', '.join(blocked_flags)}."
            )

    generated_text = "\n".join(
        [*(result.get("title_options") or []), *[story.get("text", "") for story in result.get("stories", [])]]
    )
    checks = {
        "запрещённые организации": policy.get("blocked_organization_terms", []),
        "политические маркеры": policy.get("political_terms", []),
        "аварийные и криминальные маркеры": policy.get("incident_terms", []),
        "названия сторонних компаний": policy.get("other_company_terms", []),
    }
    for label, terms in checks.items():
        matches = _find_terms(generated_text, terms)
        if matches:
            raise RuntimeError(f"Codex упомянул {label}: {', '.join(matches)}.")


def _codex_executable() -> str:
    configured = os.environ.get("CODEX_BIN")
    if configured:
        return configured

    found = shutil.which("codex")
    if found:
        return found

    if os.name == "nt":
        search_roots = [
            os.environ.get("APPDATA"),
            os.environ.get("LOCALAPPDATA"),
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
        ]
        candidates = []
        for root in search_roots:
            if not root:
                continue
            candidates.extend(
                [
                    Path(root) / "npm" / "codex.cmd",
                    Path(root) / "npm" / "codex.exe",
                    Path(root) / "Codex" / "codex.exe",
                    Path(root) / "Programs" / "Codex" / "codex.exe",
                ]
            )
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)

    app_bundle = Path("/Applications/Codex.app/Contents/Resources/codex")
    if app_bundle.exists():
        return str(app_bundle)

    raise RuntimeError(
        "Codex CLI не найден. Установите Codex CLI, войдите в аккаунт и проверьте, "
        "что команда codex доступна в PATH. Можно также указать путь через переменную CODEX_BIN."
    )


def _codex_command() -> list[str]:
    executable = _codex_executable()
    if os.name == "nt" and Path(executable).suffix.lower() in {".bat", ".cmd"}:
        return [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", executable]
    return [executable]


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
            *_codex_command(), "exec", "--ephemeral", "--skip-git-repo-check", "-s", "read-only",
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
    owned_chint_ids = {article.id for article in articles if article.is_chint_owned}
    if not chint_ids and owned_chint_ids and not owned_chint_ids.intersection(chosen_ids):
        raise RuntimeError("Codex пропустил найденный собственный инфоповод CHINT Russia.")
    policy = json.loads((project / "config" / "sources.json").read_text(encoding="utf-8")).get("editorial_policy", {})
    _validate_editorial_policy(result, by_id, policy)
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
    result["chint_owned_included"] = bool(owned_chint_ids.intersection(chosen_ids))
    result["chint_russia_note"] = "" if chint_ids else (
        f"За период {start.strftime('%d.%m.%Y')}–{end.strftime('%d.%m.%Y')} "
        "публичных новостей о CHINT в России не найдено."
    )
    return result
