from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_browser_verification_has_no_vacuous_escape_hatches():
    for rel in ("scripts/acceptance.py", "scripts/verify_tooltips.py", "tests/test_chat_g6.py"):
        text = (ROOT / rel).read_text()
        assert "or True" not in text, rel


def test_acceptance_evidence_covers_rich_tooltips_and_map_canvas():
    text = (ROOT / "scripts/acceptance.py").read_text()
    assert '@check("rich_tooltips_browser"' in text
    assert "canvas.maplibregl-canvas" in text
    for prefix in ("12.1", "12.3", "12.4", "12.5", "12.6"):
        assert any(line.startswith(f'    ("{prefix}", r".", [') and "rich_tooltips_browser" in line for line in text.splitlines()), prefix
