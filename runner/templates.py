"""Render the runner's settings file and launchd plists from templates in runner/.

    python -m runner.templates settings              # → ~/.seb-runner/runner-settings.json
    python -m runner.templates plists <dest_dir>     # → <dest_dir>/com.seb.{bot,runner}.plist
"""

import json
import os
import sys
from pathlib import Path

from runner.config import Config, load_config

TEMPLATE_DIR = Path(__file__).resolve().parent
PLIST_LABELS = ("com.seb.bot", "com.seb.runner")


def agent_path(config: Config) -> str:
    """PATH for launchd jobs, which otherwise start with a minimal environment."""
    home = Path.home()
    entries = [
        str(config.bot_python.parent),
        str(home / ".local/bin"),
        "/opt/homebrew/bin",
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
        "/usr/sbin",
        "/sbin",
    ]
    return ":".join(dict.fromkeys(entries))


def render(text: str, values: dict) -> str:
    for key, value in values.items():
        text = text.replace("{{" + key + "}}", str(value))
    if "{{" in text:
        raise ValueError("Unrendered placeholder left in template")
    return text


def _values(config: Config) -> dict:
    return {
        "MAIN": config.main,
        "HOME": Path.home(),
        "BOT_PYTHON": config.bot_python,
        "PATH": agent_path(config),
    }


def render_settings(config: Config) -> Path:
    text = render((TEMPLATE_DIR / "settings.template.json").read_text(), _values(config))
    settings = json.loads(text)  # must be valid JSON
    for rule in settings["permissions"]["deny"]:
        if rule.startswith("Read(") and not rule.startswith("Read(//"):
            raise ValueError(f"Deny rule is not an absolute // path: {rule}")
    config.runner_home.mkdir(parents=True, exist_ok=True)
    config.settings_file.write_text(json.dumps(settings, indent=2) + "\n")
    return config.settings_file


def render_plists(config: Config, dest_dir: Path) -> list[Path]:
    dest_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for label in PLIST_LABELS:
        text = render((TEMPLATE_DIR / "launchd" / f"{label}.plist.template").read_text(), _values(config))
        path = dest_dir / f"{label}.plist"
        path.write_text(text)
        written.append(path)
    return written


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    config = load_config()
    if argv[:1] == ["settings"]:
        print(render_settings(config))
    elif argv[:1] == ["plists"] and len(argv) == 2:
        for path in render_plists(config, Path(argv[1]).expanduser()):
            print(path)
    else:
        print(__doc__, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
