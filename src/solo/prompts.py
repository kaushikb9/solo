from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


def load(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text()


def render(name: str, **vars: object) -> str:
    return load(name).format(**vars)
