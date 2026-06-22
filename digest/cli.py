from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from .codex_runner import generate
from .collector import collect, load_config
from .document import build_docx
from .profile import learn_profile, profile_is_current


PROJECT = Path(__file__).resolve().parent.parent
CORPUS = PROJECT / "CHINT_Russia_новостные_дайджесты_2025-2026.docx"
PROFILE = PROJECT / "profile" / "style_profile.json"


def _date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Дата должна быть в формате YYYY-MM-DD") from exc


def _period(args) -> tuple[date, date]:
    if bool(args.start) != bool(args.end):
        raise SystemExit("Укажите одновременно --from и --to.")
    end = args.end or (date.today() - timedelta(days=1))
    start = args.start or (end - timedelta(days=6))
    if start > end:
        raise SystemExit("Дата --from не может быть позже --to.")
    return start, end


def _save_candidates(articles, warnings, start, end) -> Path:
    path = PROJECT / "work" / f"candidates_{start}_{end}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"period": {"from": str(start), "to": str(end)}, "warnings": warnings, "articles": [a.to_dict() for a in articles]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _add_period(parser):
    parser.add_argument("--from", dest="start", type=_date, help="Первая дата периода, YYYY-MM-DD")
    parser.add_argument("--to", dest="end", type=_date, help="Последняя дата периода, YYYY-MM-DD")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="chint-digest", description="Еженедельный дайджест CHINT Russia на базе Codex")
    commands = parser.add_subparsers(dest="command", required=True)
    weekly = commands.add_parser("weekly", help="Собрать новости, вызвать Codex и создать DOCX")
    _add_period(weekly)
    collect_parser = commands.add_parser("collect", help="Только собрать кандидатов")
    _add_period(collect_parser)
    profile_parser = commands.add_parser("init-profile", help="Одноразово обучить профиль на исходном DOCX")
    profile_parser.add_argument("--force", action="store_true")
    render = commands.add_parser("render", help="Повторно собрать DOCX из готового JSON")
    render.add_argument("json_file", type=Path)
    args = parser.parse_args(argv)

    if args.command == "init-profile":
        path = learn_profile(PROJECT, CORPUS, args.force)
        print(f"Профиль готов: {path}")
        return 0
    if args.command == "render":
        data = json.loads(args.json_file.read_text(encoding="utf-8"))
        start, end = date.fromisoformat(data["period"]["from"]), date.fromisoformat(data["period"]["to"])
        output = PROJECT / "outputs" / f"CHINT_digest_{start}_{end}.docx"
        build_docx(data, output, start, end)
        print(f"Word: {output}")
        return 0

    start, end = _period(args)
    config = load_config(PROJECT / "config" / "sources.json")
    print(f"Собираю новости за {start}–{end}…", flush=True)
    articles, warnings = collect(config, start, end)
    candidates_path = _save_candidates(articles, warnings, start, end)
    print(f"Уникальных кандидатов: {len(articles)}. Карточки: {candidates_path}", flush=True)
    for warning in warnings:
        print(f"Предупреждение: {warning}", file=sys.stderr)
    if args.command == "collect":
        return 0
    if not profile_is_current(PROFILE, CORPUS):
        print("Корпус изменился: один раз обновляю профиль стиля через Codex…", flush=True)
        learn_profile(PROJECT, CORPUS)
    print("Codex отбирает 8 сюжетов и пишет выпуск…", flush=True)
    result = generate(PROJECT, articles, start, end)
    result["period"] = {"from": start.isoformat(), "to": end.isoformat()}
    output_json = PROJECT / "outputs" / f"digest_{start}_{end}.json"
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    output_docx = PROJECT / "outputs" / f"CHINT_digest_{start}_{end}.docx"
    build_docx(result, output_docx, start, end)
    print(f"JSON: {output_json}\nWord: {output_docx}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

