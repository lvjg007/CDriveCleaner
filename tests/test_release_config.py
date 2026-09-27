from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _names(path: Path) -> set[str]:
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            names.add(line.split(">=", 1)[0].split("==", 1)[0].strip().lower())
    return names


def test_runtime_and_development_dependencies_are_separated():
    runtime = _names(ROOT / "requirements.txt")
    development = _names(ROOT / "requirements-dev.txt")

    assert "customtkinter" in runtime
    assert "pytest" not in runtime
    assert "pyinstaller" not in runtime
    assert {"pytest", "pyinstaller"}.issubset(development)
