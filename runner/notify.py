"""Telegram messages from the runner to the admin (plain text; message ids stored on the run)."""

import asyncio
import os

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from clarify import get_admin_user_id
from storage import FeedbackService

MAX_TEXT = 3900  # Telegram's limit is 4096; leave room for headers


def decision_keyboard(run_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Merge", callback_data=f"run:{run_id}:m"),
            InlineKeyboardButton("❌ Reject", callback_data=f"run:{run_id}:r"),
            InlineKeyboardButton("💬 Changes", callback_data=f"run:{run_id}:c"),
        ]]
    )


def failure_keyboard(run_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("❌ Reject", callback_data=f"run:{run_id}:r"),
            InlineKeyboardButton("💬 Retry with note", callback_data=f"run:{run_id}:c"),
        ]]
    )


def _clip(text: str) -> str:
    return text if len(text) <= MAX_TEXT else text[: MAX_TEXT - 20] + "\n…(truncated)"


def send(text: str, reply_markup=None) -> int:
    """Send a plain-text message to the admin and return its message id."""

    async def _go():
        bot = Bot(os.environ["TELEGRAM_BOT_TOKEN"])
        async with bot:
            message = await bot.send_message(
                chat_id=get_admin_user_id(), text=_clip(text), reply_markup=reply_markup
            )
            return message.message_id

    return asyncio.run(_go())


def feedback_line(submission: dict) -> str:
    line = f"Feedback: \"{submission['bug_text']}\" / \"{submission['suggestion_text']}\""
    if submission.get("clarification_answer"):
        line += f"\nClarified: \"{submission['clarification_answer']}\""
    return line


def planned(run: dict, submission: dict, summary: str) -> int:
    return send(
        f"📋 Planning {run['change_name']}\n{feedback_line(submission)}\n\n{summary}\n\n"
        "Building now. You'll get a merge request when it's ready."
    )


def merge_request(run: dict, submission: dict, summary: str, diffstat: str,
                  tests: str, new_deps: list[str], review_cmd: str) -> int:
    deps = "\n".join(f"📦 New dependency: {d}" for d in new_deps) or "No new dependencies"
    message_id = send(
        f"🔀 Ready to merge: {run['change_name']}\n{feedback_line(submission)}\n\n{summary}\n\n"
        f"Changes:\n{diffstat}\n\nTests: {tests}\n{deps}\n\nReview locally:\n{review_cmd}",
        reply_markup=decision_keyboard(run["id"]),
    )
    FeedbackService.update_auto_run(run["id"], merge_request_message_id=message_id)
    return message_id


def failure(run: dict, error: str, actionable: bool = True) -> int:
    name = run.get("change_name") or str(run["id"])[:8]
    return send(
        f"⚠️ Runner problem on {name}\n\n{error}",
        reply_markup=failure_keyboard(run["id"]) if actionable else None,
    )


def warning(text: str) -> int:
    return send(f"⚠️ Runner: {text}")


def merged(run: dict) -> int:
    return send(f"✅ Merged {run['change_name']}. The bot has been restarted with the new code.")


def rejected(run: dict) -> int:
    return send(f"❌ Rejected {run.get('change_name') or 'change'}. Recorded as won't do.")
