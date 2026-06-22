from pathlib import Path

from digest.profile import profile_is_current


def test_shipped_profile_matches_corpus():
    project = Path(__file__).resolve().parent.parent
    assert profile_is_current(
        project / "profile" / "style_profile.json",
        project / "CHINT_Russia_новостные_дайджесты_2025-2026.docx",
    )

