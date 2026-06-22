from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from pathlib import Path

from docx import Document


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def extract_corpus(path: Path) -> str:
    document = Document(path)
    return "\n".join(paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip())


def profile_is_current(profile_path: Path, corpus_path: Path) -> bool:
    if not profile_path.exists():
        return False
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    return profile.get("corpus_sha256") == sha256(corpus_path)


def learn_profile(project: Path, corpus_path: Path, force: bool = False) -> Path:
    profile_path = project / "profile" / "style_profile.json"
    if not force and profile_is_current(profile_path, corpus_path):
        return profile_path
    prompt_template = (project / "prompts" / "learn_style.md").read_text(encoding="utf-8")
    prompt = prompt_template.replace("{{CORPUS_SHA256}}", sha256(corpus_path)).replace("{{CORPUS}}", extract_corpus(corpus_path))
    with tempfile.TemporaryDirectory(prefix="chint-profile-") as temp:
        output = Path(temp) / "profile.json"
        command = [
            "codex", "exec", "--ephemeral", "--skip-git-repo-check", "-s", "read-only",
            "-C", str(project), "--output-schema", str(project / "schemas" / "style_profile.schema.json"),
            "-o", str(output), "-",
        ]
        subprocess.run(command, input=prompt, text=True, check=True)
        parsed = json.loads(output.read_text(encoding="utf-8"))
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    profile_path.write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return profile_path

