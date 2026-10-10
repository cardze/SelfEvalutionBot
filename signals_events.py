"""Structured problem events for the runner's suggestions (add-runner-signals, design D2).

The bot appends one JSON object per line to the file named by SEB_SIGNALS_FILE. Every field is
computed from the exception object and code locations — never from message or log text — so
nothing a user typed can shape an event. With SEB_SIGNALS_FILE unset (any test run) nothing is
written. Writing never raises.
"""

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parent

# Suggestion text of the admin submission created by 📋 Plan a fix (fixed wording + fingerprint).
SUGGESTION_TEXT = ("Find the cause and fix it so this no longer happens. "
                   "(Suggested by the runner, signal {fingerprint}.)")

# key -> (exception class, exact message, plain-language explanation shown to the admin)
KNOWN_CAUSES = {
    "reply_target_gone": (
        "telegram.error.BadRequest", "Message to be replied not found",
        "the user's message was gone before the bot replied",
    ),
    "query_too_old": (
        "telegram.error.BadRequest",
        "Query is too old and response timeout expired or query id is invalid",
        "the button was answered too late (e.g. during a bot restart)",
    ),
    "bot_blocked": (
        "telegram.error.Forbidden", "Forbidden: bot was blocked by the user",
        "the user has blocked the bot",
    ),
    "timed_out": ("telegram.error.TimedOut", "Timed out", "Telegram did not answer in time"),
}


def exception_class(exc: BaseException) -> str:
    cls = type(exc)
    if cls.__module__ == "builtins":
        return cls.__qualname__
    return f"{cls.__module__}.{cls.__qualname__}"


def known_cause(exc: BaseException) -> Optional[str]:
    name, message = exception_class(exc), str(exc)
    for key, (cls, text, _) in KNOWN_CAUSES.items():
        if name == cls and message == text:
            return key
    return None


def _repo_location(filename: str) -> Optional[str]:
    """The path relative to the repository, or None for frames outside it, in packages or tests."""
    path = Path(filename)
    if not path.is_absolute():  # e.g. "<stdin>", "<string>": never resolve against the cwd
        return None
    try:
        rel = path.resolve().relative_to(REPO_ROOT)
    except (OSError, ValueError):
        return None
    if not (REPO_ROOT / rel).is_file():
        return None
    parts = rel.parts
    if not parts or parts[0] == "tests" or "site-packages" in parts:
        return None
    return rel.as_posix()


def exception_facts(exc: BaseException) -> dict:
    """Class plus the deepest in-repository frame of the exception's own traceback."""
    facts = {"exc": exception_class(exc)}
    for frame in reversed(traceback.extract_tb(exc.__traceback__)):
        path = _repo_location(frame.filename)
        if path:
            facts.update(file=path, func=frame.name, line=frame.lineno)
            break
    return facts


def caller_facts(depth: int = 2) -> dict:
    """The in-repository function that called the caller of this function."""
    frame = sys._getframe(depth)
    path = _repo_location(frame.f_code.co_filename)
    if not path:
        return {}
    return {"file": path, "func": frame.f_code.co_name, "line": frame.f_lineno}


def record(kind: str, exc: BaseException, user: Optional[int] = None, location: Optional[dict] = None) -> None:
    """Append one event. Does nothing without SEB_SIGNALS_FILE; never raises."""
    target = os.environ.get("SEB_SIGNALS_FILE")
    if not target:
        return
    try:
        event = {"v": 1, "ts": datetime.now(timezone.utc).isoformat(), "kind": kind}
        event.update(exception_facts(exc))
        if location is not None:  # e.g. the handler that called _reply, not _reply itself
            for key in ("file", "func", "line"):
                event.pop(key, None)
            event.update(location)
        if isinstance(user, int) and not isinstance(user, bool):
            event["user"] = user
        cause = known_cause(exc)
        if cause:
            event["known_cause"] = cause
        with open(target, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=True) + "\n")
    except Exception:  # best effort: a problem report must never become a problem
        pass
