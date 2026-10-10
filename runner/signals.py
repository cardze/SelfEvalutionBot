"""Runner signals: turn the bot's structured problem events into 💡 suggestions (add-runner-signals).

Trusted runner code, no model. Reads only the bot's events file (never its text log), re-validates
every event against `main` (design D3), records them with an exact cursor (D4), and renders
suggestions from fixed text and validated fields only (D9, D10).
"""

import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from runner import notify, refs
from runner.config import Config
from signals_events import KNOWN_CAUSES
from storage import FeedbackService

log = logging.getLogger("runner")

KINDS = ("unhandled", "reply_failed", "reminder_failed")
MAX_READ = 5 * 1024 * 1024
MAX_SUGGESTIONS_PER_DAY = 3
SNOOZE = timedelta(days=7)
WINDOW = timedelta(hours=24)
REPEAT_THRESHOLD = 3  # reply_failed / reminder_failed within WINDOW; unhandled needs 1
FUTURE_SLACK = timedelta(minutes=5)
DISPLAY_TZ = ZoneInfo("Asia/Taipei")

EXC_RE = re.compile(r"^[A-Za-z_][\w.]{0,100}$")
FILE_RE = re.compile(r"^[\w./-]{1,200}$")
FUNC_RE = re.compile(r"^\w{1,100}$")

BUTTON_LABELS = {
    "run": "the buttons on runner messages",
    "apv": "the clarification buttons",
    "clr": "the clarification buttons",
    "sig": "the 💡 suggestion buttons",
}


# ---------- reading (D4) ----------


def read_new_lines(path: Path, cursor: Optional[dict]) -> Optional[tuple[list[bytes], int, int, int]]:
    """
    Complete lines appended since the cursor. Returns (lines, inode, new_offset, skipped) or None if
    there is no file. With no cursor, starts at the end (nothing is replayed).
    """
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    if cursor is None:
        return [], st.st_ino, st.st_size, 0
    offset = cursor["byte_offset"]
    if cursor["inode"] != st.st_ino or st.st_size < offset:  # rotated or truncated
        offset = 0
    with open(path, "rb") as f:
        f.seek(offset)
        chunk = f.read(MAX_READ)
    end = chunk.rfind(b"\n")
    if end == -1:
        if len(chunk) == MAX_READ:  # one absurdly long line: skip it rather than stall forever
            return [], st.st_ino, offset + len(chunk), 1
        return [], st.st_ino, offset, 0  # partial line: wait for the rest
    complete = chunk[: end + 1]
    return complete.split(b"\n")[:-1], st.st_ino, offset + len(complete), 0


# ---------- validation (D3) ----------


class MainCode:
    """Cached, read-only view of files on `main` in the main checkout."""

    def __init__(self, config: Config):
        self.config = config
        self._tracked: dict[str, bool] = {}
        self._source: dict[str, str] = {}

    def is_tracked(self, path: str) -> bool:
        if path not in self._tracked:
            out = refs.git_main(self.config, "ls-tree", "--name-only", "main", "--", path, check=False)
            self._tracked[path] = out.strip() == path
        return self._tracked[path]

    def source(self, path: str) -> str:
        if path not in self._source:
            self._source[path] = (refs.git_main(self.config, "show", f"main:{path}", check=False)
                                  if self.is_tracked(path) else "")
        return self._source[path]

    def defines(self, path: str, func: str) -> bool:
        pattern = rf"^\s*(?:async\s+)?def {re.escape(func)}\s*\("
        return re.search(pattern, self.source(path), re.MULTILINE) is not None


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate(raw: bytes, code: MainCode, now: datetime) -> Optional[dict]:
    """A validated event with its fingerprint, or None if anything is off."""
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("v") != 1 or data.get("kind") not in KINDS:
        return None
    try:
        ts = datetime.fromisoformat(data["ts"])
    except (KeyError, TypeError, ValueError):
        return None
    if ts.tzinfo is None or ts > now + FUTURE_SLACK:
        return None
    exc = data.get("exc")
    if not isinstance(exc, str) or not EXC_RE.match(exc):
        return None
    file, func, line = data.get("file"), data.get("func"), data.get("line")
    if (file is None) != (func is None):
        return None
    if file is not None:
        if not (isinstance(file, str) and FILE_RE.match(file) and isinstance(func, str)
                and FUNC_RE.match(func)):
            return None
        parts = file.split("/")
        if ".." in parts or parts[0] == "tests" or "site-packages" in parts:
            return None
        if not code.is_tracked(file) or not code.defines(file, func):
            return None
    if line is not None and not (_is_int(line) and line > 0):
        return None
    user = data.get("user")
    if user is not None and not (_is_int(user) and user >= 0):
        return None
    cause = data.get("known_cause")
    if cause is not None and cause not in KNOWN_CAUSES:
        return None
    kind = data["kind"]
    if kind == "unhandled":
        fingerprint = f"unhandled:{exc}:{file}:{func}"
    elif kind == "reply_failed":
        fingerprint = f"reply_failed:{exc}:{func}"
    else:
        fingerprint = f"reminder_failed:{exc}"
    return {"fingerprint": fingerprint, "kind": kind, "exc": exc, "file": file, "func": func,
            "line": line, "user": user, "known_cause": cause, "ts": ts}


# ---------- impact (D9) ----------


def _balanced(text: str, start: int) -> str:
    """The text from `start` (an opening parenthesis) to its matching closing one."""
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "(":
            depth += 1
        elif text[i] == ")":
            depth -= 1
            if depth == 0:
                return text[start: i + 1]
    return text[start:]


def handler_map(bot_source: str) -> dict[str, tuple[str, str]]:
    """func -> ("command", "/cmd") or ("button", label), from the bot's handler registrations."""
    features: dict[str, tuple[str, str]] = {}
    for match in re.finditer(r"ConversationHandler\(", bot_source):
        block = _balanced(bot_source, match.end() - 1)
        entry = re.search(r'entry_points=\[\s*CommandHandler\("(\w+)"', block)
        if entry:
            for func in re.findall(r"Handler\([^()]*?,\s*(\w+)\)", block):
                features[func] = ("command", f"/{entry.group(1)}")
    for cmd, func in re.findall(r'CommandHandler\("(\w+)",\s*(\w+)\)', bot_source):
        features[func] = ("command", f"/{cmd}")
    for func, prefix in re.findall(r'CallbackQueryHandler\((\w+),\s*pattern=r"\^(\w+):"\)', bot_source):
        features[func] = ("button", BUTTON_LABELS.get(prefix, "some buttons"))
    return features


def _feature(signal: dict, features: dict) -> tuple[str, str]:
    if signal["file"] == "reminders.py" or signal["kind"] == "reminder_failed":
        return ("reminders", "reminder delivery")
    if signal["func"] and signal["func"] in features:
        return features[signal["func"]]
    return ("internal", f"internal code ({signal['func'] or 'unknown'})")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" if n == 1 else f"{n} {word}s"


def render(signal: dict, features: dict, now: datetime) -> str:
    """The 💡 text: fixed wording plus validated fields only (D10)."""
    ftype, name = _feature(signal, features)
    kind = signal["kind"]
    if kind == "unhandled":
        if ftype == "command":
            headline, impact = f"{name} sometimes fails for users", \
                f"the user sends {name} and probably gets no reply"
        elif ftype == "button":
            headline, impact = f"{name[0].upper()}{name[1:]} sometimes fail", \
                "the tap probably shows no result"
        elif ftype == "reminders":
            headline, impact = "Reminder delivery hit an unhandled error", \
                "a reminder may be delayed or not sent"
        else:
            headline, impact = f"The bot hit an unhandled error in {name}", \
                "unknown — the error happened outside a command or button"
    elif kind == "reply_failed":
        where = name if ftype == "command" else "a bot reply"
        headline, impact = f"Replies in {where} are not getting through", \
            "a reply did not arrive (what the user typed is still saved)"
    else:
        headline, impact = "Reminders are failing to send", "a reminder is delayed until a retry succeeds"

    users = len(signal["users"])
    recent = sum(1 for r in signal["recent"] if datetime.fromisoformat(r) >= now - WINDOW)
    last = signal["last_seen"].astimezone(DISPLAY_TZ).strftime("%Y-%m-%d %H:%M")
    who = " · ".join([
        _plural(users, "user") if users else "users unknown",
        _plural(signal["occurrences"], "time"),
        f"last {last}",
        f"{recent} in the last 24 h" if recent else "none in the last 24 h",
    ])
    lines = [f"💡 {headline}", f"Impact: {impact}", f"Who:    {who}"]
    if signal.get("known_cause") in KNOWN_CAUSES:
        lines.append(f"Cause:  {KNOWN_CAUSES[signal['known_cause']][2]}")
    short_exc = signal["exc"].rsplit(".", 1)[-1]
    if signal["file"]:
        line = f" (line {signal['last_line']})" if signal.get("last_line") else ""
        lines.append(f"Where:  {short_exc} in {signal['file']} → {signal['func']}{line}")
    else:
        lines.append(f"Where:  {short_exc}")
    return "\n".join(lines)


def threshold_met(signal: dict, now: datetime) -> bool:
    if signal["kind"] == "unhandled":
        return signal["occurrences"] >= 1
    recent = sum(1 for r in signal["recent"] if datetime.fromisoformat(r) >= now - WINDOW)
    return recent >= REPEAT_THRESHOLD


# ---------- one scan per tick (D7) ----------


def scan(config: Config, now: datetime) -> dict:
    """Read → record (with cursor) → settle accepted → suggest. Returns counters for the log."""
    stats = {"read": 0, "dropped": 0, "suggested": 0, "reset": 0, "dismissed": 0}
    code = MainCode(config)
    batch = read_new_lines(config.signals_file, FeedbackService.get_signal_cursor())
    if batch is None:
        log.debug("signals: no events file at %s", config.signals_file)
    else:
        lines, inode, offset, skipped = batch
        events = []
        for raw in lines:
            event = validate(raw, code, now)
            if event is None:
                stats["dropped"] += 1
            else:
                events.append(event)
        stats["read"] = len(events)
        stats["dropped"] += skipped
        FeedbackService.record_signal_events(events, inode, offset, now)
    stats["reset"], stats["dismissed"] = FeedbackService.settle_accepted_signals()

    room = MAX_SUGGESTIONS_PER_DAY - FeedbackService.count_signals_suggested_since(now - WINDOW)
    if room > 0:
        features = handler_map(code.source("bot.py"))
        for signal in FeedbackService.signal_candidates(now, SNOOZE):
            if room <= 0:
                break
            if not threshold_met(signal, now):
                continue
            text = render(signal, features, now)
            try:
                message_id = notify.signal(signal["id"], text)
            except Exception as e:  # stays observed/dismissed; retried next tick
                log.warning("signals: could not send suggestion %s: %s", signal["fingerprint"], e)
                continue
            FeedbackService.mark_signal_suggested(signal["id"], text, message_id)
            stats["suggested"] += 1
            room -= 1
    return stats
