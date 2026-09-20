import logging
import os
from telegram import Update
from telegram.helpers import escape_markdown
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

STEP_BUG, STEP_SUGGESTION = range(2)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Welcome to SelfEvaluationBot! 🤖\n"
        "Use /feedback to share your feedback and help us improve."
    )


async def feedback_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text(
        "📝 *Feedback Form* (Step 1 of 2)\n\n"
        "What bug or current feature didn't meet your expectation?",
        parse_mode="Markdown",
    )
    return STEP_BUG


async def feedback_bug(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["bug"] = update.message.text
    await update.message.reply_text(
        "📝 *Feedback Form* (Step 2 of 2)\n\n"
        "How do you suggest fixing the bug or what new feature would you like?",
        parse_mode="Markdown",
    )
    return STEP_SUGGESTION


async def feedback_suggestion(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> int:
    user = update.effective_user
    bug = context.user_data.get("bug", "")
    suggestion = update.message.text

    logger.info(
        "Feedback from %s (id=%s): bug=%r suggestion=%r",
        user.username or user.first_name,
        user.id,
        bug,
        suggestion,
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
    await update.message.reply_text("Feedback cancelled. Feel free to use /feedback anytime.")
    context.user_data.clear()
    return ConversationHandler.END


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set.")

    application = Application.builder().token(token).build()

    application.add_handler(CommandHandler("start", start))

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
