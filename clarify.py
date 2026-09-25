"""Clarification questions: draft validation, admin preview, delivery, and answer recording.

Shared by bot.py (callback/reply handlers) and ask.py (planner CLI).
All user-facing text is sent as plain text: questions are LLM-written and must not
be interpreted as Markdown.
"""

import asyncio
import logging
import os

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from storage import ClarificationError, FeedbackService

logger = logging.getLogger(__name__)

MIN_OPTIONS = 2
MAX_OPTIONS = 4
MAX_OPTION_LEN = 30
MAX_QUESTION_LEN = 500

SOMETHING_ELSE_LABEL = "✏️ Something else"
SOMETHING_ELSE_INDEX = "x"
REPLY_PROMPT_TEXT = "Reply to this message with your answer."


class DraftError(ValueError):
    """Raised when a clarification draft fails validation."""


def validate_draft(question: str, options: list[str]) -> tuple[str, list[str]]:
    """Return the stripped question and options, or raise DraftError."""
    question = (question or "").strip()
    options = [(o or "").strip() for o in options]

    if not question:
        raise DraftError("Question must not be empty.")
    if len(question) > MAX_QUESTION_LEN:
        raise DraftError(f"Question must be at most {MAX_QUESTION_LEN} characters.")
    if not MIN_OPTIONS <= len(options) <= MAX_OPTIONS:
        raise DraftError(f"Provide {MIN_OPTIONS}-{MAX_OPTIONS} options (got {len(options)}).")
    for option in options:
        if not option:
            raise DraftError("Options must not be empty.")
        if len(option) > MAX_OPTION_LEN:
            raise DraftError(f"Option too long (max {MAX_OPTION_LEN} characters): {option!r}")
    if len(set(options)) != len(options):
        raise DraftError("Options must not contain duplicates.")
    return question, options


def get_admin_user_id() -> int:
    value = os.environ.get("ADMIN_USER_ID")
    if not value:
        raise RuntimeError("ADMIN_USER_ID environment variable is not set.")
    try:
        return int(value)
    except ValueError as e:
        raise RuntimeError(f"ADMIN_USER_ID must be a Telegram user id, got {value!r}.") from e


def approval_keyboard(clarification_id) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("✅ Send", callback_data=f"apv:{clarification_id}:y"),
            InlineKeyboardButton("❌ Discard", callback_data=f"apv:{clarification_id}:n"),
        ]]
    )


def question_keyboard(clarification_id, options: list[str]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(option, callback_data=f"clr:{clarification_id}:{i}")]
        for i, option in enumerate(options)
    ]
    rows.append(
        [InlineKeyboardButton(
            SOMETHING_ELSE_LABEL,
            callback_data=f"clr:{clarification_id}:{SOMETHING_ELSE_INDEX}",
        )]
    )
    return InlineKeyboardMarkup(rows)


def format_preview(clarification: dict) -> str:
    options = "\n".join(f"  • {o}" for o in clarification["options"])
    return (
        "🔍 Clarification draft\n"
        f"To: user {clarification['user_id']}\n"
        f"Feedback: {clarification['bug_text']}\n"
        f"Suggestion: {clarification['suggestion_text']}\n"
        "──────────\n"
        f"Q: {clarification['question']}\n"
        f"{options}"
    )


async def send_admin_preview(bot, clarification: dict) -> None:
    """Send the approval preview to the admin and remember its message id."""
    message = await bot.send_message(
        chat_id=get_admin_user_id(),
        text=format_preview(clarification),
        reply_markup=approval_keyboard(clarification["id"]),
    )
    await asyncio.to_thread(
        FeedbackService.set_message_id, clarification["id"], "admin_message_id", message.message_id
    )


async def deliver_question(bot, clarification: dict) -> None:
    """
    Send the question to the submitter.

    Marks the clarification 'sent' first; if Telegram rejects the send, reverts to
    'pending_approval' and re-raises. Records 'clarification_requested' only on success.

    Raises:
        ClarificationError: the clarification is no longer pending approval
    """
    clarification_id = clarification["id"]
    if not await asyncio.to_thread(FeedbackService.mark_sent, clarification_id):
        raise ClarificationError("Clarification is no longer pending approval.")
    try:
        message = await bot.send_message(
            chat_id=clarification["user_id"],
            text=clarification["question"],
            reply_markup=question_keyboard(clarification_id, clarification["options"]),
        )
    except Exception:
        await asyncio.to_thread(FeedbackService.revert_to_pending, clarification_id)
        raise
    await asyncio.to_thread(
        FeedbackService.set_message_id, clarification_id, "question_message_id", message.message_id
    )
    await asyncio.to_thread(
        FeedbackService.record_event,
        clarification["user_id"],
        "clarification_requested",
        clarification["feedback_submission_id"],
    )
    logger.info(f"✓ Clarification delivered: clarification_id={clarification_id}")


async def record_answer(clarification: dict, answer_text: str, answer_source: str) -> str:
    """Store the first answer for a clarification and return the text to show the user."""
    if not await asyncio.to_thread(
        FeedbackService.mark_answered, clarification["id"], answer_text, answer_source
    ):
        return "Already answered, thanks!"
    await asyncio.to_thread(
        FeedbackService.record_event,
        clarification["user_id"],
        "clarified",
        clarification["feedback_submission_id"],
    )
    logger.info(
        f"✓ Clarification answered: clarification_id={clarification['id']}, source={answer_source}"
    )
    if await asyncio.to_thread(FeedbackService.is_resolved, clarification["feedback_submission_id"]):
        return "Thanks! This was already addressed."
    return f"Thanks! Noted: {answer_text}"
