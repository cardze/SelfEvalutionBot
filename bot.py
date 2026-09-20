import asyncio
import logging
import os
import asyncio
from telegram import Update, BotCommand
from telegram.helpers import escape_markdown
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)
from storage import FeedbackService
import db

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# Initialize storage service
feedback_service = FeedbackService()

STEP_BUG, STEP_SUGGESTION = range(2)


async def setup_bot_commands(application: Application) -> None:
    await application.bot.set_my_commands(
        [
            BotCommand("start", "Show the welcome message and available commands"),
            BotCommand("feedback", "Start the two-step feedback form"),
            BotCommand("cancel", "Cancel the current feedback flow"),
            BotCommand("help", "Show usage hints and command tips"),
        ]
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Welcome to SelfEvaluationBot! 🤖\n"
        "Use /feedback to share your feedback and help us improve.\n"
        "Hint: Telegram will suggest /start, /feedback, /cancel, and /help when you type /."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Available commands:\n"
        "/start - Show the welcome message\n"
        "/feedback - Start the feedback form\n"
        "/cancel - Cancel the current feedback flow\n\n"
        "Tip: type / in Telegram to see command suggestions."
    )


async def feedback_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = update.effective_user
    # Record event in database (run in thread to avoid blocking)
    await asyncio.to_thread(feedback_service.record_event, user.id, "started")
    
    await update.message.reply_text(
        "📝 *Feedback Form* \\(Step 1 of 2\\)\n\n"
        "What bug or current feature didn't meet your expectation?\n\n"
        "Hint: You can type /cancel anytime to stop this flow.",
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
    asyncio.run(setup_bot_commands(application))

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))

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
