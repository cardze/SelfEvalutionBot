"""Planner CLI for feedback clarifications.

    python ask.py next
    python ask.py draft <submission_id> --question "…" --option "…" --option "…" [--yes]
    python ask.py resend-preview <submission_id>

Exits non-zero on any failure. Nothing is sent to Telegram unless the database write succeeded.
"""

import argparse
import asyncio
import json
import os
import sys
from uuid import UUID

from dotenv import load_dotenv

load_dotenv()

from telegram import Bot

from clarify import DraftError, deliver_question, send_admin_preview, validate_draft
from storage import ClarificationError, FeedbackService


def _bot() -> Bot:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable is not set.")
    return Bot(token)


async def _send(coro_factory) -> None:
    bot = _bot()
    async with bot:
        await coro_factory(bot)


def cmd_next(args) -> int:
    print(json.dumps(FeedbackService.get_actionable_feedback(), default=str, ensure_ascii=False, indent=2))
    return 0


def cmd_draft(args) -> int:
    question, options = validate_draft(args.question, args.option or [])
    clarification = FeedbackService.create_clarification(args.submission_id, question, options)
    if args.yes:
        asyncio.run(_send(lambda bot: deliver_question(bot, clarification)))
        print(f"Sent clarification {clarification['id']} to user {clarification['user_id']}.")
    else:
        asyncio.run(_send(lambda bot: send_admin_preview(bot, clarification)))
        print(f"Drafted clarification {clarification['id']}; preview sent to admin for approval.")
    return 0


def cmd_resend_preview(args) -> int:
    clarification = FeedbackService.get_clarification_by_submission(args.submission_id)
    if clarification is None:
        raise ClarificationError(f"No clarification for submission {args.submission_id}")
    if clarification["status"] != "pending_approval":
        raise ClarificationError(
            f"Clarification is '{clarification['status']}', not 'pending_approval'"
        )
    asyncio.run(_send(lambda bot: send_admin_preview(bot, clarification)))
    print(f"Preview re-sent for clarification {clarification['id']}.")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Feedback clarification CLI for the planner.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_next = sub.add_parser("next", help="Print the actionable feedback queue as JSON")
    p_next.set_defaults(func=cmd_next)

    p_draft = sub.add_parser("draft", help="Draft the one clarifying question for a submission")
    p_draft.add_argument("submission_id", type=UUID)
    p_draft.add_argument("--question", required=True)
    p_draft.add_argument("--option", action="append", help="Answer option (repeat 2-4 times)")
    p_draft.add_argument("--yes", action="store_true", help="Skip admin approval and send directly")
    p_draft.set_defaults(func=cmd_draft)

    p_resend = sub.add_parser("resend-preview", help="Re-send the admin preview for a pending draft")
    p_resend.add_argument("submission_id", type=UUID)
    p_resend.set_defaults(func=cmd_resend_preview)

    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (DraftError, ClarificationError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"Error: {type(e).__name__}: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
