import ast
import asyncio
import logging
import operator
import os
import random
from urllib.parse import quote
from uuid import UUID
from telegram import (
    BotCommand,
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.error import BadRequest, NetworkError, TelegramError
from telegram.helpers import escape_markdown
from telegram.ext import (
    Application,
    ApplicationHandlerStop,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from storage import ClarificationError, FeedbackService
from clarify import (
    REPLY_PROMPT_TEXT,
    SOMETHING_ELSE_INDEX,
    approval_keyboard,
    deliver_question,
    format_preview,
    get_admin_user_id,
    record_answer,
)
import reminders
import signals_events
from reminders import ReminderLimitExceededError, ReminderParseError, ReminderService
from dotenv import load_dotenv
load_dotenv()
import db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)
# httpx logs every request URL at INFO, and Telegram URLs contain the bot token.
logging.getLogger("httpx").setLevel(logging.WARNING)

# Initialize storage service
feedback_service = FeedbackService()

# Waits before the 2nd and 3rd attempt of a reply that failed with a transient network error.
_REPLY_DELAYS = (1, 3)
# Telegram connect/read timeouts in seconds (python-telegram-bot's default is 5).
_TELEGRAM_TIMEOUT = 10


def _retryable(exc: TelegramError) -> bool:
    # BadRequest subclasses NetworkError in python-telegram-bot, but retrying it cannot help.
    return isinstance(exc, NetworkError) and not isinstance(exc, BadRequest)


async def _sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


async def _reply(message, text: str, **kwargs) -> bool:
    """Reply, retrying transient network errors. Returns False instead of raising a TelegramError."""
    for attempt in range(len(_REPLY_DELAYS) + 1):
        try:
            await message.reply_text(text, **kwargs)
            return True
        except TelegramError as exc:
            if not _retryable(exc) or attempt == len(_REPLY_DELAYS):
                logger.warning("Reply not delivered after %d attempt(s): %s: %s",
                               attempt + 1, type(exc).__name__, exc)
                chat_id = getattr(message, "chat_id", None)
                signals_events.record("reply_failed", exc, user=chat_id,
                                      location=signals_events.caller_facts())
                return False
            await _sleep(_REPLY_DELAYS[attempt])
    return False

STEP_BUG, STEP_SUGGESTION = range(2)

_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNOPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}

DEFAULT_MEALS = (
    "牛肉麵",
    "滷肉飯",
    "火鍋",
    "壽司",
    "義大利麵",
    "漢堡",
    "咖哩飯",
    "炒飯",
    "沙拉",
    "拉麵",
)

DEFAULT_DRINKS = (
    "珍珠奶茶",
    "冬瓜茶",
    "美式咖啡",
    "檸檬紅茶",
    "可樂",
    "豆漿",
    "綠茶",
    "柳橙汁",
)

DELUXE_PREFIXES = (
    "皇家",
    "至尊",
    "黃金",
    "帝王",
    "米其林級",
)

DELUXE_SUFFIXES = (
    "豪華套餐",
    "饗宴",
    "尊爵組合",
    "限定套餐",
)

UBER_EATS_SEARCH_URL = "https://www.ubereats.com/tw/search?q="
FOODPANDA_SEARCH_URL = "https://www.foodpanda.com.tw/search?q="


def build_meal_combo(rng=random):
    """Pick a meal and drink and build a deluxe combo name.

    ``rng`` is any object exposing ``choice(seq)``; returns
    ``(meal, drink, deluxe_name)``.
    """
    meal = rng.choice(DEFAULT_MEALS)
    drink = rng.choice(DEFAULT_DRINKS)
    prefix = rng.choice(DELUXE_PREFIXES)
    suffix = rng.choice(DELUXE_SUFFIXES)
    return meal, drink, f"{prefix}{meal}佐{drink}{suffix}"


def build_order_links(meal):
    """Build delivery-platform search links for ``meal``.

    Pure helper with no network access; returns a list of ``(label, url)``
    tuples, Uber Eats first, then foodpanda.
    """
    query = quote(meal, safe="")
    return [
        ("Uber Eats", UBER_EATS_SEARCH_URL + query),
        ("foodpanda", FOODPANDA_SEARCH_URL + query),
    ]


def _eval_expr(node):
    if isinstance(node, ast.Expression):
        return _eval_expr(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_eval_expr(node.left), _eval_expr(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNOPS:
        return _UNOPS[type(node.op)](_eval_expr(node.operand))
    raise ValueError("unsupported expression")


async def setup_bot_commands(application: Application) -> None:
    try:
        await application.bot.set_my_commands(
            [
                BotCommand("start", "Start here and type / for command suggestions"),
                BotCommand("feedback", "Share feedback with the bot"),
                BotCommand("calc", "Evaluate an arithmetic expression, e.g. /calc 2 + 3"),
                BotCommand("meal", "Pick a meal + drink combo for today"),
                BotCommand("remind", "Schedule a reminder or repeating notice"),
                BotCommand("reminders", "List or cancel your reminders"),
                BotCommand("cancel", "Cancel the current feedback flow"),
                BotCommand("help", "Show the command list and tips"),
            ]
        )
    except Exception as exc:
        logger.warning(
            "Telegram command registration failed; continuing without custom commands: %s",
            exc,
        )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Welcome to SelfEvaluationBot! 🤖\n"
        "Use /feedback to share your feedback and help us improve.\n"
        "Type / to see available commands and suggestions in Telegram."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Available commands:\n"
        "/start - Start here and see the welcome message\n"
        "/help - Show this help menu\n"
        "/feedback - Start the feedback form\n"
        "/calc - Evaluate an arithmetic expression (e.g. /calc 2 + 3)\n"
        "/meal - Pick a meal + drink combo for today, with Uber Eats and foodpanda order links\n"
        "/remind - Schedule a reminder or repeating notice (e.g. /remind in 10m Take the bread out)\n"
        "/reminders - List your reminders, or /reminders cancel <id>\n"
        "/cancel - Cancel the current feedback flow\n\n"
        "Reminder times use Asia/Taipei (UTC+8). Minimum repeat interval is "
        + str(reminders.MIN_INTERVAL_SECONDS) + " seconds, maximum is "
        + str(reminders.MAX_OFFSET_SECONDS // 86400) + " days. Each user may have "
        "at most " + str(reminders.MAX_ACTIVE_REMINDERS) + " active reminders.\n"
        "Tip: type / in Telegram to see the built-in command suggestions."
    )


async def calc(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(
            "Usage: /calc <expression>\nExample: /calc 2 + 3"
        )
        return
    expr = " ".join(context.args)
    try:
        tree = ast.parse(expr, mode="eval")
        result = _eval_expr(tree)
        text = str(int(result) if isinstance(result, float) and result.is_integer() else result)
        await update.message.reply_text(text)
    except ZeroDivisionError:
        await update.message.reply_text("Error: division by zero")
    except Exception:
        await update.message.reply_text("Invalid expression. Example: /calc 2 + 3")


async def meal_picker(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    meal, drink, deluxe_name = build_meal_combo()
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton(label, url=url) for label, url in build_order_links(meal)]]
    )
    await update.message.reply_text(
        f"✨ {deluxe_name}\n🍽 餐點：{meal}\n🥤 飲料：{drink}",
        reply_markup=keyboard,
    )


async def remind(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.message.reply_text(reminders.USAGE)
        return

    args = context.args
    when_parts = []
    idx = 0
    keyword = args[0].lower()
    if keyword in ("in", "at", "every") and len(args) >= 2:
        when_parts = [args[0], args[1]]
        idx = 2
    else:
        await update.message.reply_text(reminders.USAGE)
        return

    message_text = " ".join(args[idx:]).strip()
    if not message_text:
        await update.message.reply_text(reminders.USAGE)
        return

    when = " ".join(when_parts)
    try:
        next_fire_at, is_recurring, interval_seconds = reminders.parse_when(when)
    except ReminderParseError as exc:
        await update.message.reply_text(str(exc))
        return

    user = update.effective_user
    chat_id = update.effective_chat.id
    try:
        row = await asyncio.to_thread(
            ReminderService.create_reminder,
            user.id,
            chat_id,
            message_text,
            next_fire_at,
            is_recurring,
            interval_seconds,
        )
    except ReminderLimitExceededError as exc:
        await update.message.reply_text(str(exc))
        return
    if row is None:
        await update.message.reply_text("Sorry, I could not save that reminder. Please try again.")
        return

    when_text = reminders.format_datetime_taipei(next_fire_at)
    if is_recurring:
        await update.message.reply_text(
            "Repeating notice scheduled every " + str(interval_seconds)
            + "s. First occurrence: " + when_text + ". (id " + str(row["id"]) + ")"
        )
    else:
        await update.message.reply_text(
            "Reminder scheduled for " + when_text + ". (id " + str(row["id"]) + ")"
        )


async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    args = context.args or []

    if args and args[0].lower() == "cancel":
        if len(args) < 2:
            await update.message.reply_text("Usage: /reminders cancel <id>")
            return
        try:
            reminder_id = UUID(args[1])
        except ValueError:
            await update.message.reply_text("That does not look like a valid reminder id.")
            return
        cancelled = await asyncio.to_thread(ReminderService.cancel, user.id, reminder_id)
        if cancelled:
            await update.message.reply_text("Reminder cancelled.")
        else:
            await update.message.reply_text(
                "No active reminder with that id belongs to you."
            )
        return

    rows = await asyncio.to_thread(ReminderService.list_active, user.id)
    if not rows:
        await update.message.reply_text("You have no active reminders.")
        return

    lines = [reminders.format_reminder_line(row) for row in rows]
    await update.message.reply_text(
        "Your active reminders:\n" + "\n".join(lines)
    )


async def feedback_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    # Record event in database (run in thread to avoid blocking)
    await asyncio.to_thread(feedback_service.record_event, user.id, "started")
    
    await _reply(
        update.message,
        "📝 *Feedback Form* \\(Step 1 of 2\\)\n\n"
        "What bug or current feature didn't meet your expectation?\n\n"
        "Hint: You can type /cancel anytime to stop this flow\\.",
        parse_mode="MarkdownV2",
    )
    return STEP_BUG


async def feedback_bug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["bug"] = update.message.text
    # The step follows what is saved: move on even if the Step 2 prompt could not be delivered.
    await _reply(
        update.message,
        "📝 *Feedback Form* \\(Step 2 of 2\\)\n\n"
        "How do you suggest fixing the bug or what new feature would you like?",
        parse_mode="MarkdownV2",
    )
    return STEP_SUGGESTION


async def feedback_suggestion(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    bug = context.user_data.get("bug", "")
    suggestion = update.message.text

    logger.info(
        "Feedback received from user id=%s: bug_length=%d suggestion_length=%d",
        user.id,
        len(bug),
        len(suggestion),
    )

    # Store submission and record event in database (run in thread to avoid blocking)
    submission_id = await asyncio.to_thread(
        feedback_service.store_submission, user.id, bug, suggestion
    )
    await asyncio.to_thread(
        feedback_service.record_event, user.id, "submitted", submission_id
    )

    # Stored: the form ends whether or not the thank-you gets through.
    await _reply(
        update.message,
        "✅ *Thank you for your feedback\\!*\n\n"
        f"*Issue reported:*\n{escape_markdown(bug, version=2)}\n\n"
        f"*Your suggestion:*\n{escape_markdown(suggestion, version=2)}\n\n"
        "We appreciate your input and will use it to improve the bot\\. 🙏",
        parse_mode="MarkdownV2",
    )
    context.user_data.clear()
    return ConversationHandler.END


async def feedback_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    # Record event in database (run in thread to avoid blocking)
    await asyncio.to_thread(feedback_service.record_event, user.id, "cancelled")
    
    await _reply(update.message, "Feedback cancelled. Feel free to use /feedback anytime.")
    context.user_data.clear()
    return ConversationHandler.END


def _parse_callback(data: str):
    """Split 'prefix:<uuid>:<arg>' callback data; return (UUID, arg) or None if malformed."""
    parts = (data or "").split(":")
    if len(parts) != 3:
        return None
    try:
        return UUID(parts[1]), parts[2]
    except ValueError:
        return None


async def clarification_approval(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin taps ✅ Send / ❌ Discard on a clarification preview."""
    query = update.callback_query
    try:
        admin_id = get_admin_user_id()
    except RuntimeError as exc:
        logger.warning("Ignoring clarification approval: %s", exc)
        await query.answer()
        return
    parsed = _parse_callback(query.data)
    if query.from_user.id != admin_id or parsed is None:
        await query.answer()
        return
    clarification_id, action = parsed

    clarification = await asyncio.to_thread(FeedbackService.get_clarification, clarification_id)
    if clarification is None:
        await query.answer("Clarification not found.")
        return
    if clarification["status"] != "pending_approval":
        await query.answer(f"Already {clarification['status']}.")
        return

    preview = format_preview(clarification)
    if action == "y":
        try:
            await deliver_question(context.bot, clarification)
        except ClarificationError:
            await query.answer("Already handled.")
            return
        except Exception as exc:
            logger.error("Failed to deliver clarification %s: %s", clarification_id, exc)
            await query.answer("Send failed.")
            await query.edit_message_text(
                f"{preview}\n\n⚠️ Send failed: {exc}\nTap ✅ to retry or ❌ to discard.",
                reply_markup=approval_keyboard(clarification_id),
            )
            return
        await query.answer("Sent.")
        await query.edit_message_text(f"{preview}\n\n✅ Sent")
    elif action == "n":
        if await asyncio.to_thread(FeedbackService.mark_discarded, clarification_id):
            await query.answer("Discarded.")
            await query.edit_message_text(f"{preview}\n\n❌ Discarded")
        else:
            await query.answer("Already handled.")
    else:
        await query.answer()


async def clarification_answer(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Submitter taps an option or "Something else" on a clarification question."""
    query = update.callback_query
    parsed = _parse_callback(query.data)
    if parsed is None:
        await query.answer()
        return
    clarification_id, choice = parsed

    clarification = await asyncio.to_thread(FeedbackService.get_clarification, clarification_id)
    if clarification is None or query.from_user.id != clarification["user_id"]:
        await query.answer()
        return
    if clarification["status"] == "answered":
        await query.answer("Already answered, thanks!")
        return
    if clarification["status"] != "sent":
        await query.answer("This question is no longer open.")
        return

    if choice == SOMETHING_ELSE_INDEX:
        await query.answer()
        prompt = await context.bot.send_message(
            chat_id=clarification["user_id"],
            text=REPLY_PROMPT_TEXT,
            reply_markup=ForceReply(input_field_placeholder="Your answer"),
        )
        await asyncio.to_thread(
            FeedbackService.set_message_id,
            clarification_id,
            "reply_prompt_message_id",
            prompt.message_id,
        )
        return

    options = clarification["options"]
    if not choice.isdigit() or int(choice) >= len(options):
        await query.answer()
        return
    reply = await record_answer(clarification, options[int(choice)], "option")
    await query.answer()
    await query.edit_message_text(f"{clarification['question']}\n\n{reply}")


async def clarification_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Capture a free-text answer sent as a reply to a stored ForceReply prompt.

    Runs in handler group -1, before the /feedback conversation. Stops propagation
    only when the message matched a clarification prompt.
    """
    message = update.message
    if message is None or message.reply_to_message is None:
        return
    clarification = await asyncio.to_thread(
        FeedbackService.find_clarification_by_reply_prompt,
        update.effective_user.id,
        message.reply_to_message.message_id,
    )
    if clarification is None:
        return
    reply = await record_answer(clarification, message.text, "free_text")
    await _reply(message, reply)  # never raises, so the answer cannot fall through to /feedback
    raise ApplicationHandlerStop


RUN_DECISIONS = {"m": "merge", "r": "reject", "b": "build"}
RUN_NOTE_PROMPT_TEXT = "Reply to this message with the changes you want."


async def runner_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin taps ✅ Merge / ❌ Reject / 💬 Request changes on an autonomous-runner message."""
    query = update.callback_query
    try:
        admin_id = get_admin_user_id()
    except RuntimeError as exc:
        logger.warning("Ignoring runner decision: %s", exc)
        await query.answer()
        return
    parsed = _parse_callback(query.data)
    if query.from_user.id != admin_id or parsed is None:
        await query.answer()
        return
    run_id, action = parsed

    if action in RUN_DECISIONS:
        applied = await asyncio.to_thread(
            FeedbackService.set_auto_run_decision, run_id, RUN_DECISIONS[action]
        )
        await query.answer(
            ("The build starts within an hour." if action == "b" else "Queued; the runner acts within an hour.")
            if applied else "This run is not awaiting a decision."
        )
        if applied:
            await query.edit_message_reply_markup(reply_markup=None)
    elif action == "c":
        run = await asyncio.to_thread(FeedbackService.get_auto_run, run_id)
        if run is None or run["stage"] not in ("awaiting_decision", "failed"):
            await query.answer("This run is not awaiting a decision.")
            return
        await query.answer()
        prompt = await context.bot.send_message(
            chat_id=admin_id,
            text=RUN_NOTE_PROMPT_TEXT,
            reply_markup=ForceReply(input_field_placeholder="What should change?"),
        )
        await asyncio.to_thread(
            FeedbackService.update_auto_run, run_id, note_prompt_message_id=prompt.message_id
        )
    else:
        await query.answer()


async def signal_decision(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin taps 📋 Plan a fix / 🙈 Dismiss on a runner 💡 suggestion."""
    query = update.callback_query
    await query.answer()  # first: a late answer fails with "Query is too old"
    try:
        admin_id = get_admin_user_id()
    except RuntimeError as exc:
        logger.warning("Ignoring signal decision: %s", exc)
        return
    parsed = _parse_callback(query.data)
    if query.from_user.id != admin_id or parsed is None:
        return
    signal_id, action = parsed
    if action == "p":
        submission_id = await asyncio.to_thread(FeedbackService.accept_signal, signal_id, admin_id)
        outcome = "📋 Queued as feedback. You'll get the plan and its impact before anything is built." \
            if submission_id else "Already handled."
    elif action == "d":
        dismissed = await asyncio.to_thread(FeedbackService.dismiss_signal, signal_id)
        outcome = "🙈 Dismissed for 7 days." if dismissed else "Already handled."
    else:
        return
    try:
        await query.edit_message_text(f"{query.message.text}\n\n{outcome}", reply_markup=None)
    except TelegramError as exc:
        logger.warning("Could not update the suggestion message: %s", exc)


async def runner_note_reply(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Capture the admin's "request changes" note sent as a reply to the runner's ForceReply prompt.

    Runs in handler group -2 (before clarification replies in -1 and /feedback in 0).
    Stops propagation only when the message matched a runner note prompt.
    """
    message = update.message
    if message is None or message.reply_to_message is None:
        return
    try:
        admin_id = get_admin_user_id()
    except RuntimeError:
        return
    if update.effective_user.id != admin_id:
        return
    run = await asyncio.to_thread(
        FeedbackService.find_auto_run_by_note_prompt, message.reply_to_message.message_id
    )
    if run is None:
        return
    applied = await asyncio.to_thread(
        FeedbackService.set_auto_run_decision, run["id"], "changes", message.text
    )
    await _reply(
        message,
        "Noted. The runner will rebuild with your changes within an hour."
        if applied
        else "This run is no longer awaiting a decision.",
    )
    raise ApplicationHandlerStop


def start_background(application: Application) -> None:
    """Start the reminder delivery loop on the running event loop (see design D1).

    Shared by `main()` (via post_init) and the gateway plugin (see README)."""
    asyncio.create_task(reminders.delivery_loop(application.bot))


async def _post_init(application: Application) -> None:
    start_background(application)


async def _on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log handler and polling errors. `update` is None for polling errors."""
    err = context.error
    if isinstance(err, TelegramError) and _retryable(err):
        logger.warning("Telegram network error: %s: %s", type(err).__name__, err)
    else:
        logger.error("Unhandled error", exc_info=err)
        user = getattr(getattr(update, "effective_user", None), "id", None)
        signals_events.record("unhandled", err, user=user)


def build_application(token: str) -> Application:
    application = (
        Application.builder()
        .token(token)
        .connect_timeout(_TELEGRAM_TIMEOUT)
        .read_timeout(_TELEGRAM_TIMEOUT)
        .post_init(_post_init)
        .build()
    )
    application.add_error_handler(_on_error)
    return application


def register_handlers(application: Application) -> None:
    """Add every bot handler to `application` (shared by bot.py and the gateway plugin)."""
    # Clarification replies must be checked before the /feedback conversation sees the text.
    application.add_handler(
        MessageHandler(filters.TEXT & filters.REPLY & ~filters.COMMAND, clarification_reply),
        group=-1,
    )
    # Runner "request changes" notes are checked first; unmatched replies fall through.
    application.add_handler(
        MessageHandler(filters.TEXT & filters.REPLY & ~filters.COMMAND, runner_note_reply),
        group=-2,
    )
    application.add_handler(CallbackQueryHandler(runner_decision, pattern=r"^run:"))
    application.add_handler(CallbackQueryHandler(signal_decision, pattern=r"^sig:"))
    application.add_handler(CallbackQueryHandler(clarification_approval, pattern=r"^apv:"))
    application.add_handler(CallbackQueryHandler(clarification_answer, pattern=r"^clr:"))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("calc", calc))
    application.add_handler(CommandHandler("meal", meal_picker))
    application.add_handler(CommandHandler("remind", remind))
    application.add_handler(CommandHandler("reminders", reminders_command))

    feedback_handler = ConversationHandler(
        entry_points=[CommandHandler("feedback", feedback_start)],
        states={
            STEP_BUG: [MessageHandler(filters.TEXT & ~filters.COMMAND, feedback_bug)],
            STEP_SUGGESTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, feedback_suggestion)
            ],
        },
        fallbacks=[CommandHandler("cancel", feedback_cancel)],
    )
    application.add_handler(feedback_handler)


def main() -> None:
    # Initialize database before setting up bot
    try:
        db.init_database()
    except Exception as e:
        logger.error(str(e))
        raise

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set.")

    application = build_application(token)

    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        if not loop.is_running():
            loop.run_until_complete(setup_bot_commands(application))
    except Exception as exc:
        logger.warning(
            "Skipping custom Telegram command registration: %s",
            exc,
        )

    register_handlers(application)
    application.run_polling()


if __name__ == "__main__":
    main()
