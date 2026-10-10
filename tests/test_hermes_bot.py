"""Tests for running the bot inside a Hermes gateway (change move-bot-into-hermes).

No Hermes, Telegram, network or database: the gateway's Application and plugin context are faked.
"""

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
from telegram.ext import CallbackQueryHandler, CommandHandler, ConversationHandler, MessageHandler

import bot
import hermes_bot
from runner import runner as rr
from runner.config import load_config

REPO = Path(__file__).resolve().parent.parent


class FakeApplication:
    def __init__(self):
        self.handlers = []  # (handler, group)
        self.bot = object()

    def add_handler(self, handler, group=0):
        self.handlers.append((handler, group))


class FakeCtx:
    def __init__(self):
        self.platform_handlers = []
        self.commands = {}
        self.tools = {}

    def register_platform_handler(self, platform, factory):
        self.platform_handlers.append((platform, factory))

    def register_command(self, name, handler, description=""):
        self.commands[name] = (handler, description)

    def register_tool(self, name, toolset, schema, handler, **kwargs):
        self.tools[name] = (toolset, schema, handler)


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(hermes_bot, "_background_started", False)
    monkeypatch.setattr(hermes_bot, "_db_ready", False)


# ---------- 6.1 shared handlers ----------


def _describe(handler):
    if isinstance(handler, CommandHandler):
        return ("command", tuple(sorted(handler.commands)))
    if isinstance(handler, CallbackQueryHandler):
        return ("callback", handler.pattern.pattern)
    if isinstance(handler, ConversationHandler):
        return ("conversation", tuple(sorted(handler.entry_points[0].commands)))
    if isinstance(handler, MessageHandler):
        return ("message", handler.callback.__name__)
    return ("other", type(handler).__name__)


def test_register_handlers_matches_bot_main():
    app = FakeApplication()
    bot.register_handlers(app)
    got = [(_describe(h), g) for h, g in app.handlers]
    assert got == [
        (("message", "clarification_reply"), -1),
        (("message", "runner_note_reply"), -2),
        (("callback", "^run:"), 0),
        (("callback", "^apv:"), 0),
        (("callback", "^clr:"), 0),
        (("command", ("start",)), 0),
        (("command", ("help",)), 0),
        (("command", ("calc",)), 0),
        (("command", ("meal",)), 0),
        (("command", ("remind",)), 0),
        (("command", ("reminders",)), 0),
        (("conversation", ("feedback",)), 0),
    ]


# ---------- 6.2 plugin registration ----------


def _load_shim():
    spec = importlib.util.spec_from_file_location("seb_plugin_shim", REPO / "hermes_plugin/seb/__init__.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_plugin_registers_factory_commands_and_tools(monkeypatch):
    monkeypatch.setenv("SEB_MAIN", str(REPO))
    ctx = FakeCtx()
    _load_shim().register(ctx)
    assert ctx.platform_handlers == [("telegram", hermes_bot.wire_telegram)]
    assert set(ctx.commands) == {"feedback", "calc", "meal", "remind", "reminders", "cancel"}
    assert set(ctx.tools) == {"seb_feedback_queue", "seb_runner_status"}
    for name, (toolset, schema, handler) in ctx.tools.items():
        assert toolset == "seb" and schema["name"] == name and callable(handler)


def test_plugin_refuses_missing_checkout(monkeypatch, tmp_path):
    monkeypatch.setenv("SEB_MAIN", str(tmp_path))
    with pytest.raises(RuntimeError, match="SEB_MAIN"):
        _load_shim().register(FakeCtx())


def test_plugin_yaml_declares_tools():
    text = (REPO / "hermes_plugin/seb/plugin.yaml").read_text()
    assert "seb_feedback_queue" in text and "seb_runner_status" in text
    assert "python-telegram-bot" not in text  # Hermes pins its own PTB


def test_menu_commands():
    assert hermes_bot.command_calc("2 + 3") == "5"
    assert hermes_bot.command_calc("1/0") == "Error: division by zero"
    assert hermes_bot.command_calc("").startswith("Usage:")
    assert hermes_bot.command_meal("") in bot.DEFAULT_MEALS
    assert hermes_bot.command_telegram_only("") == hermes_bot.TELEGRAM_ONLY


# ---------- 6.3 Telegram factory ----------


def test_wire_telegram_inits_registers_and_starts_once(monkeypatch):
    import db

    calls = []
    monkeypatch.setattr(db, "init_database", lambda: calls.append("init"))
    monkeypatch.setattr(bot, "start_background", lambda app: calls.append("background"))

    async def connect_twice():
        for _ in range(2):
            app = FakeApplication()
            hermes_bot.wire_telegram(app, adapter=None)
            assert len(app.handlers) == 12
    asyncio.run(connect_twice())
    assert calls == ["init", "background"]


def test_wire_telegram_survives_db_failure(monkeypatch, caplog):
    import db

    def boom():
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "init_database", boom)
    monkeypatch.setattr(bot, "start_background", lambda app: None)

    async def connect():
        app = FakeApplication()
        hermes_bot.wire_telegram(app)
        return app
    app = asyncio.run(connect())
    assert len(app.handlers) == 12
    assert "database initialization failed" in caplog.text


def test_background_needs_running_loop(monkeypatch):
    started = []
    monkeypatch.setattr(bot, "start_background", lambda app: started.append(app))
    hermes_bot.start_background_once(FakeApplication())  # no loop running
    assert started == [] and hermes_bot._background_started is False


# ---------- 6.4 owner-only tools ----------


def _as(monkeypatch, platform="", source="", user_id="", admin="42"):
    values = {"HERMES_SESSION_PLATFORM": platform, "HERMES_SESSION_SOURCE": source,
              "HERMES_SESSION_USER_ID": user_id}
    monkeypatch.setattr(hermes_bot, "_session", lambda name: values[name])
    if admin is None:
        monkeypatch.delenv("ADMIN_USER_ID", raising=False)
    else:
        monkeypatch.setenv("ADMIN_USER_ID", admin)


@pytest.mark.parametrize("who, allowed", [
    (dict(platform="telegram", user_id="42"), True),
    (dict(platform="telegram", user_id="7"), False),
    (dict(platform="telegram", user_id=""), False),
    (dict(platform="telegram", user_id="42", admin=None), False),
    (dict(source="cli"), True),
    (dict(source="tui"), True),
    (dict(source="telegram"), False),
    (dict(), False),
    (dict(platform="telegram", source="cli", user_id="7"), False),
])
def test_owner_check(monkeypatch, who, allowed):
    _as(monkeypatch, **who)
    assert (hermes_bot.owner_check() == "") is allowed


def test_owner_check_fails_closed_on_error(monkeypatch):
    def broken(name):
        raise ImportError("no gateway")
    monkeypatch.setattr(hermes_bot, "_session", broken)
    assert hermes_bot.owner_check() != ""


def test_tools_refuse_non_owner_without_touching_db(monkeypatch):
    import storage

    def forbidden(*a, **kw):
        raise AssertionError("database read for a non-owner")
    monkeypatch.setattr(storage.FeedbackService, "get_actionable_feedback", forbidden)
    monkeypatch.setattr(storage.FeedbackService, "get_inflight_auto_run", forbidden)
    _as(monkeypatch, platform="telegram", user_id="7")
    assert "owner" in json.loads(hermes_bot.tool_feedback_queue({}))["error"]
    assert "owner" in json.loads(hermes_bot.tool_runner_status({}))["error"]


def test_feedback_queue_tool_for_owner(monkeypatch):
    import storage

    items = [{"id": i, "text": f"item {i}"} for i in range(30)]
    monkeypatch.setattr(storage.FeedbackService, "get_actionable_feedback",
                        lambda: {"actionable": list(items), "pending_clarification": []})
    monkeypatch.setattr(storage.FeedbackService, "get_inflight_auto_run", lambda: {"stage": "build"})
    _as(monkeypatch, platform="telegram", user_id="42")
    queue = json.loads(hermes_bot.tool_feedback_queue({"limit": 3}))
    assert [i["id"] for i in queue["actionable"]] == [0, 1, 2]
    assert len(json.loads(hermes_bot.tool_feedback_queue({"limit": 999}))["actionable"]) == 30
    assert json.loads(hermes_bot.tool_runner_status({})) == {"inflight": {"stage": "build"}}


# ---------- 6.5 requirements filter and runner config ----------


def test_bot_requirements_drops_only_ptb():
    text = ("python-telegram-bot==20.7\npsycopg[binary]==3.1.12\n# python-telegram-bot is pinned\n"
            "python_telegram_bot[job-queue]>=20\npython-dotenv==1.0.0\ntelegram-text==1\n")
    out = rr.bot_requirements(text).splitlines()
    assert out == ["psycopg[binary]==3.1.12", "# python-telegram-bot is pinned", "python-dotenv==1.0.0",
                   "telegram-text==1"]


def test_load_config_bot_service(tmp_path):
    env = tmp_path / "config.env"
    env.write_text("")
    config = load_config(env)
    assert (config.bot_service, config.hermes_python, config.hermes_profile) == ("launchd", None, "seb")
    env.write_text("BOT_SERVICE=Hermes\nHERMES_PYTHON=~/h/bin/python\nHERMES_PROFILE=other\n")
    config = load_config(env)
    assert config.bot_service == "hermes" and config.hermes_profile == "other"
    assert config.hermes_python == Path("~/h/bin/python").expanduser()
    env.write_text("BOT_SERVICE=hermes\n")
    with pytest.raises(ValueError, match="HERMES_PYTHON"):
        load_config(env)
    env.write_text("BOT_SERVICE=systemd\n")
    with pytest.raises(ValueError, match="BOT_SERVICE"):
        load_config(env)
