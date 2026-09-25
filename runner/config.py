"""Runner configuration: paths, limits and secret locations.

Non-secret settings come from ~/.seb-runner/config.env (all optional; defaults below).
Secrets are read from the main checkout's .env and ~/.seb-runner/oauth_token — only by the
trusted runner, never passed to agents.
"""

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

RUNNER_HOME = Path.home() / ".seb-runner"
SNAPSHOT_HOME = Path.home() / ".seb-snapshot"  # must stay outside RUNNER_HOME (sandbox denies it)
TOKEN_PREFIX = "sk-ant-oat01-"


def parse_env_file(path: Path) -> dict:
    """Parse KEY=VALUE lines (comments, blank lines, optional quotes, optional 'export')."""
    values = {}
    if not path.exists():
        return values
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):]
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass(frozen=True)
class StageLimits:
    timeout_s: int
    budget_usd: float
    max_turns: int


@dataclass(frozen=True)
class Config:
    main: Path
    workspace_root: Path
    bot_python: Path
    runner_home: Path = RUNNER_HOME
    snapshot_home: Path = SNAPSHOT_HOME
    throttle_hours: float = 5.0
    max_build_attempts: int = 2
    plan: StageLimits = field(default_factory=lambda: StageLimits(1200, 2.0, 60))
    build: StageLimits = field(default_factory=lambda: StageLimits(3600, 8.0, 200))
    selftest: StageLimits = field(default_factory=lambda: StageLimits(300, 0.3, 15))
    selftest_model: str = "haiku"

    @property
    def logs_dir(self) -> Path:
        return self.runner_home / "logs"

    @property
    def token_file(self) -> Path:
        return self.runner_home / "oauth_token"

    @property
    def settings_file(self) -> Path:
        return self.runner_home / "runner-settings.json"

    @property
    def last_run_file(self) -> Path:
        return self.runner_home / "last_run"


def load_config(env_file: Path = RUNNER_HOME / "config.env") -> Config:
    values = parse_env_file(env_file)
    main = Path(values.get("MAIN", Path(__file__).resolve().parent.parent)).expanduser()
    workspace_root = Path(values.get("WORKSPACE_ROOT", main.parent)).expanduser()
    bot_python = Path(values.get("BOT_PYTHON", sys.executable)).expanduser()

    def limits(prefix: str, default: StageLimits) -> StageLimits:
        return StageLimits(
            int(values.get(f"{prefix}_TIMEOUT_S", default.timeout_s)),
            float(values.get(f"{prefix}_BUDGET_USD", default.budget_usd)),
            int(values.get(f"{prefix}_MAX_TURNS", default.max_turns)),
        )

    base = Config(main=main, workspace_root=workspace_root, bot_python=bot_python)
    return Config(
        main=main,
        workspace_root=workspace_root,
        bot_python=bot_python,
        throttle_hours=float(values.get("THROTTLE_HOURS", base.throttle_hours)),
        max_build_attempts=int(values.get("MAX_BUILD_ATTEMPTS", base.max_build_attempts)),
        plan=limits("PLAN", base.plan),
        build=limits("BUILD", base.build),
        selftest=limits("SELFTEST", base.selftest),
        selftest_model=values.get("SELFTEST_MODEL", base.selftest_model),
    )


def load_main_secrets(config: Config) -> None:
    """Load the main checkout's .env into this (trusted) process's environment."""
    for key, value in parse_env_file(config.main / ".env").items():
        os.environ.setdefault(key, value)


def read_token(config: Config) -> str:
    token = config.token_file.read_text().strip() if config.token_file.exists() else ""
    if not token.startswith(TOKEN_PREFIX):
        raise RuntimeError(
            f"No valid OAuth token at {config.token_file}. Run: runner/setup.sh store-token"
        )
    return token
