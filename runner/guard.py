"""What a runner-built change may touch (guard-hermes-from-runner, design G1–G3).

The bot runs inside the `seb` Hermes gateway and the runner ticks from Hermes cron, so an approved
change could otherwise reach Hermes itself. Runner-built changes are limited to the bot; the Hermes
integration, the runner and (in Hermes mode) the dependencies Hermes installs need a person.
"""

from runner import refs
from runner.config import Config

ALWAYS_PREFIXES = ("hermes_profile/", "hermes_plugin/")
ALWAYS_FILES = frozenset({"hermes_bot.py"})
HERMES_MODE_PREFIXES = ("runner/",)
HERMES_MODE_FILES = frozenset({"requirements.txt"})
EXEMPT_PREFIXES = ("openspec/",)  # proposals may discuss Hermes; they never run
MAX_REPORTED = 5

NEEDS_A_PERSON = ("Runner-built changes may not touch the Hermes integration, the runner or the "
                  "dependencies Hermes installs; this one needs a person")


def protected_paths(paths, bot_service: str) -> list[str]:
    """The paths a runner-built change may not touch, compared case-insensitively (macOS checkout)."""
    hermes_mode = bot_service == "hermes"
    found = []
    for path in paths:
        low = path.lower()
        if low.startswith(EXEMPT_PREFIXES):
            continue
        if (low.startswith(ALWAYS_PREFIXES) or low in ALWAYS_FILES or "hermes" in low
                or (hermes_mode and (low.startswith(HERMES_MODE_PREFIXES) or low in HERMES_MODE_FILES))):
            found.append(path)
    return found


def hermes_mentions(added) -> list[str]:
    """`path: line` for added lines that mention Hermes (design G2)."""
    return [f"{path}: {text.strip()[:120]}" for path, text in added if "hermes" in text.lower()]


def violations(config: Config, ref: str) -> list[str]:
    """Reasons the commit at `ref` may not be merged by the runner; empty when it may."""
    reasons = []
    paths = protected_paths(refs.changed_paths(config, ref), config.bot_service)
    if paths:
        reasons.append("protected paths changed: " + ", ".join(paths[:MAX_REPORTED])
                       + (f" (+{len(paths) - MAX_REPORTED} more)" if len(paths) > MAX_REPORTED else ""))
    mentions = hermes_mentions(refs.added_lines(config, ref))
    if mentions:
        reasons.append("added code mentions Hermes: " + "; ".join(mentions[:MAX_REPORTED])
                       + (f" (+{len(mentions) - MAX_REPORTED} more)" if len(mentions) > MAX_REPORTED else ""))
    return reasons


def describe(reasons: list[str]) -> str:
    return NEEDS_A_PERSON + ".\n" + "\n".join(f"- {r}" for r in reasons)


def prompt_rule(config: Config) -> str:
    """The rule as the PLAN and BUILD prompts state it, so agents don't spend a run on it."""
    paths = "`hermes_profile/`, `hermes_plugin/`, `hermes_bot.py` or any file with `hermes` in its path"
    if config.bot_service == "hermes":
        paths += ", `runner/` or `requirements.txt` (the bot runs inside Hermes, so no new dependencies)"
    return (f"Never change {paths}, and never add code that mentions Hermes (outside `openspec/` and "
            "Markdown). The runner refuses such a change and the run fails. If the feedback cannot be done "
            "without them, plan only what can be, and say in the summary what needs a person.")
