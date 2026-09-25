import ast
import asyncio
import logging
import operator
import os
from uuid import UUID
from telegram import Update, BotCommand, ForceReply
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
from dotenv import load_dotenv
load_dotenv()
import db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Initialize storage service
feedback_service = FeedbackService()

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
        "/cancel - Cancel the current feedback flow\n\n"
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


async def feedback_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    # Record event in database (run in thread to avoid blocking)
    await asyncio.to_thread(feedback_service.record_event, user.id, "started")
    
    await update.message.reply_text(
        "📝 *Feedback Form* \\(Step 1 of 2\\)\n\n"
        "What bug or current feature didn't meet your expectation?\n\n"
        "Hint: You can type /cancel anytime to stop this flow\\.",
        parse_mode="MarkdownV2",
    )
    return STEP_BUG


async def feedback_bug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["bug"] = update.message.text
    await update.message.reply_text(
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

    await update.message.reply_text(
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
    
    await update.message.reply_text("Feedback cancelled. Feel free to use /feedback anytime.")
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
    await message.reply_text(reply)
    raise ApplicationHandlerStop


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

    application = Application.builder().token(token).build()

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

    # Clarification replies must be checked before the /feedback conversation sees the text.
    application.add_handler(
        MessageHandler(filters.TEXT & filters.REPLY & ~filters.COMMAND, clarification_reply),
        group=-1,
    )
    application.add_handler(CallbackQueryHandler(clarification_approval, pattern=r"^apv:"))
    application.add_handler(CallbackQueryHandler(clarification_answer, pattern=r"^clr:"))
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("calc", calc))

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

    application.run_polling()


if __name__ == "__main__":
    main()
