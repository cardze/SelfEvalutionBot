"""REVIEW after BUILD (add-runner-review-step): which reviewers run, and reading their verdicts.

The reviewers are the factory's own agents (`.claude/agents/review-*.md`). Each writes
`.auto/review/review-<name>.md` whose first line is `VERDICT: PASS` or `VERDICT: CHANGES`. Those
files are agent-written, so they are read like output.json: no symlinks, size-capped, and only the
first line decides the verdict.
"""

import re
from pathlib import Path

ALWAYS = ("code", "security")
MESSAGES = ("ux", "ui")  # only when the diff touches what the admin sees in Telegram
ORDER = ALWAYS + MESSAGES
REVIEW_DIR = ".auto/review"
MAX_REVIEW_BYTES = 64_000
MAX_FINDINGS = 3000
TOUCHES_MESSAGES = re.compile(
    r"reply_text|reply_markdown|reply_html|send_message|edit_message_text|edit_message_reply_markup"
    r"|InlineKeyboard|ReplyKeyboard|parse_mode"
)
VERDICT = re.compile(r"^VERDICT:\s*(PASS|CHANGES)\b")
SHOWN = {"PASS": "✅", "FIXED": "🔧 fixed", "CHANGES": "⚠️ changes not fixed", "MISSING": "❓ no verdict"}


def reviewers_for(added_lines: list[str]) -> list[str]:
    """code and security always; ux and ui when an added line sends or edits a bot message or keyboard."""
    if any(TOUCHES_MESSAGES.search(line) for line in added_lines):
        return list(ORDER)
    return list(ALWAYS)


def agent_names(reviewers: list[str]) -> str:
    return ", ".join(f"`review-{r}`" for r in reviewers)


def clear(path: Path) -> None:
    folder = path / REVIEW_DIR
    if folder.is_symlink() or folder.is_file():
        folder.unlink()
    elif folder.is_dir():
        for f in folder.iterdir():
            if f.is_symlink() or f.is_file():
                f.unlink()


def _read(path: Path, name: str):
    target = path / REVIEW_DIR / f"review-{name}.md"
    try:
        if (path / ".auto").is_symlink() or (path / REVIEW_DIR).is_symlink() or target.is_symlink():
            return None
        if not target.is_file() or target.stat().st_size > MAX_REVIEW_BYTES:
            return None
        return target.read_text(errors="replace")
    except OSError:
        return None


def read_verdicts(path: Path, reviewers: list[str], fixed: bool) -> dict:
    """{name: {"verdict", "findings"}} for every reviewer in ORDER.

    verdict is PASS, CHANGES, FIXED (CHANGES and the fix round committed something), MISSING (no
    readable verdict) or SKIPPED (not run for this diff).
    """
    verdicts = {}
    for name in ORDER:
        if name not in reviewers:
            verdicts[name] = {"verdict": "SKIPPED", "findings": ""}
            continue
        text = _read(path, name)
        m = VERDICT.match(text.lstrip()) if text else None
        verdict = m.group(1) if m else "MISSING"
        if verdict == "CHANGES" and fixed:
            verdict = "FIXED"
        verdicts[name] = {"verdict": verdict, "findings": (text or "").strip()[:MAX_FINDINGS]}
    return verdicts


def summary_line(verdicts: dict) -> str:
    """One line for the 🔀 merge request, e.g. 'Review: code ✅ · security 🔧 fixed'."""
    if not verdicts:
        return "Review: not run"
    ran = [f"{name} {SHOWN.get(v['verdict'], v['verdict'])}" for name, v in verdicts.items()
           if v["verdict"] != "SKIPPED"]
    skipped = [name for name, v in verdicts.items() if v["verdict"] == "SKIPPED"]
    line = "Review: " + " · ".join(ran)
    if skipped:
        line += f" ({', '.join(skipped)} not run: no bot messages or keyboards changed)"
    return line
