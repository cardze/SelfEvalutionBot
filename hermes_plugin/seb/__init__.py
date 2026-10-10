"""Hermes plugin shim for SelfEvaluationBot (change move-bot-into-hermes, design B2).

hermes_profile/setup.sh copies this directory into $HERMES_HOME/plugins/seb/. It only locates the main
checkout and hands over to <MAIN>/hermes_bot.py, so merged changes take effect on the next gateway
restart without reinstalling the plugin.
"""

import os
import sys
from pathlib import Path


def find_main() -> Path:
    configured = os.environ.get("SEB_MAIN", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parent.parent.parent  # <MAIN>/hermes_plugin/seb/__init__.py


def register(ctx):
    main = find_main()
    if not (main / "hermes_bot.py").is_file():
        raise RuntimeError(f"SelfEvaluationBot checkout not found at {main}; set SEB_MAIN in the profile .env")
    if str(main) not in sys.path:
        sys.path.append(str(main))
    try:
        from dotenv import load_dotenv

        load_dotenv(main / ".env", override=False)  # profile .env values win
    except ImportError:
        pass
    import hermes_bot

    hermes_bot.register(ctx)
