"""Run SelfEvaluationBot inside a Hermes Agent gateway (change move-bot-into-hermes, design B2).

Loaded by the thin Hermes plugin in hermes_plugin/seb/ (installed into the `seb` Hermes profile by
hermes_profile/setup.sh). It wires the bot's own python-telegram-bot handlers into the gateway's Telegram
application ahead of Hermes's handlers, starts the reminder loop, adds the bot commands to the
Telegram menu, and gives the owner's agent read-only tools over the bot's data.
"""

import asyncio
import json
import logging
import os
import random

logger = logging.getLogger("seb.hermes")

TOOLSET = "seb"
TELEGRAM_ONLY = "This command works in the SelfEvaluationBot Telegram chat."
# Local surfaces the owner drives directly (bound as HERMES_SESSION_SOURCE with no platform).
OWNER_SURFACES = frozenset({"cli", "tui", "desktop"})

_background_started = False
_db_ready = False


# ---------- Telegram ----------


def wire_telegram(application, adapter=None) -> None:
    """Factory for ctx.register_platform_handler("telegram", …): runs at every gateway connect."""
    global _db_ready
    import bot
    import db

    if not _db_ready:
        try:
            db.init_database()
            _db_ready = True
        except Exception:
            logger.exception("SelfEvaluationBot database initialization failed; handlers still wired")
    bot.register_handlers(application)
    start_background_once(application)


def start_background_once(application) -> None:
    """Start the reminder loop once per process (a reconnect rebuilds the app and re-runs wiring)."""
    global _background_started
    if _background_started:
        return
    import bot

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        logger.error("No running event loop when wiring Telegram; reminder delivery not started")
        return
    bot.start_background(application)
    _background_started = True


# ---------- slash commands (menu entries; Telegram is answered by the PTB handlers first) ----------


def command_calc(raw_args: str) -> str:
    from bot import _eval_expr
    import ast

    expr = (raw_args or "").strip()
    if not expr:
        return "Usage: /calc <expression>\nExample: /calc 2 + 3"
    try:
        result = _eval_expr(ast.parse(expr, mode="eval"))
    except ZeroDivisionError:
        return "Error: division by zero"
    except Exception:
        return "Invalid expression. Example: /calc 2 + 3"
    return str(int(result) if isinstance(result, float) and result.is_integer() else result)


def command_meal(raw_args: str) -> str:
    from bot import DEFAULT_MEALS

    return random.choice(DEFAULT_MEALS)


def command_telegram_only(raw_args: str) -> str:
    return TELEGRAM_ONLY


COMMANDS = (
    ("feedback", command_telegram_only, "Share feedback with the bot"),
    ("calc", command_calc, "Evaluate an arithmetic expression, e.g. /calc 2 + 3"),
    ("meal", command_meal, "Randomly pick what to eat today"),
    ("remind", command_telegram_only, "Schedule a reminder or repeating notice"),
    ("reminders", command_telegram_only, "List or cancel your reminders"),
    ("cancel", command_telegram_only, "Cancel the current feedback flow"),
)


# ---------- owner-only agent tools ----------


def _session(name: str) -> str:
    from gateway.session_context import get_session_env

    return get_session_env(name, "")


def owner_check() -> str:
    """'' when the caller is the owner, else the reason. Fails closed on any doubt."""
    try:
        platform = _session("HERMES_SESSION_PLATFORM")
        source = _session("HERMES_SESSION_SOURCE")
        user_id = _session("HERMES_SESSION_USER_ID")
    except Exception:
        return "cannot determine who is asking"
    if not platform and source in OWNER_SURFACES:
        return ""
    admin = os.environ.get("ADMIN_USER_ID", "").strip()
    if not admin:
        return "ADMIN_USER_ID is not configured"
    if not user_id:
        return "cannot determine who is asking"
    if user_id.strip() != admin:
        return "only the bot's owner can use this tool"
    return ""


def tool_feedback_queue(args: dict, **kwargs) -> str:
    reason = owner_check()
    if reason:
        return json.dumps({"error": reason})
    try:
        from storage import FeedbackService

        limit = max(1, min(int(args.get("limit") or 10), 50))
        queue = FeedbackService.get_actionable_feedback()
        queue["actionable"] = queue["actionable"][:limit]
        return json.dumps(queue, default=str, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": f"could not read feedback: {exc}"})


def tool_runner_status(args: dict, **kwargs) -> str:
    reason = owner_check()
    if reason:
        return json.dumps({"error": reason})
    try:
        from storage import FeedbackService

        run = FeedbackService.get_inflight_auto_run()
        return json.dumps({"inflight": run}, default=str, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({"error": f"could not read runner state: {exc}"})


FEEDBACK_QUEUE_SCHEMA = {
    "name": "seb_feedback_queue",
    "description": (
        "Owner only. List SelfEvaluationBot feedback that is waiting to be planned (oldest first), "
        "with clarification answers. Read-only."
    ),
    "parameters": {
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": "Max items (1-50, default 10)"}},
    },
}

RUNNER_STATUS_SCHEMA = {
    "name": "seb_runner_status",
    "description": (
        "Owner only. Show the SelfEvaluationBot feedback runner's in-flight run (stage, change name, "
        "last error), or null when idle. Read-only."
    ),
    "parameters": {"type": "object", "properties": {}},
}


# ---------- plugin entry point ----------


def register(ctx) -> None:
    ctx.register_platform_handler("telegram", wire_telegram)
    for name, handler, description in COMMANDS:
        ctx.register_command(name, handler, description=description)
    ctx.register_tool(name="seb_feedback_queue", toolset=TOOLSET, schema=FEEDBACK_QUEUE_SCHEMA,
                      handler=tool_feedback_queue)
    ctx.register_tool(name="seb_runner_status", toolset=TOOLSET, schema=RUNNER_STATUS_SCHEMA,
                      handler=tool_runner_status)
