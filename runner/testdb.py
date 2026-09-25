"""Post-approval full test run against a throwaway database (design D10).

The agent's sandbox has no database (the sandbox blocks Postgres, and a private Postgres cannot start
there), so database tests skip during the sandboxed verification. After the admin taps ✅ the code is
approved — the bot is about to run it with full access anyway — so the runner runs the COMPLETE suite
on exactly the approved commit before merging:

- the approved ref is exported with the main checkout's git (never the agent's workspace or .venv)
- a fresh venv is built from the approved requirements
- a throwaway database feedback_bot_verify_<id> is created, used, and dropped
- the environment carries only the throwaway DB settings (no bot token)
"""

import io
import os
import shutil
import subprocess
import tarfile
from contextlib import closing
from pathlib import Path

import psycopg

from db import get_db_config
from runner import refs
from runner.config import Config
from runner.verify import SUMMARY, Verification
from runner.workspace import short_id


def scratch_db_name(submission_id) -> str:
    return f"feedback_bot_verify_{short_id(submission_id)}"


def _admin_connection():
    """Connection to the maintenance DB using the bot's own (trusted) credentials."""
    cfg = get_db_config()
    conn = psycopg.connect(host=cfg["host"], port=cfg["port"], dbname="postgres",
                           user=cfg["user"], password=cfg["password"], autocommit=True)
    return conn


def create_scratch(name: str) -> None:
    drop_scratch(name)
    with closing(_admin_connection()) as conn:
        conn.execute(f'CREATE DATABASE "{name}"')


def drop_scratch(name: str) -> None:
    if not name.startswith("feedback_bot_verify_"):
        raise ValueError(f"Refusing to drop {name}")
    with closing(_admin_connection()) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def export_ref(config: Config, ref: str, dest: Path) -> None:
    shutil.rmtree(dest, ignore_errors=True)
    dest.mkdir(parents=True)
    data = refs.git_main(config, "archive", "--format=tar", ref, binary=True)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        tar.extractall(dest, filter="data")


def run_full_suite(config: Config, ref: str, submission_id) -> Verification:
    workdir = config.runner_home / "verify" / short_id(submission_id)
    name = scratch_db_name(submission_id)
    try:
        export_ref(config, ref, workdir / "src")
        venv = workdir / "venv"
        subprocess.run([str(config.bot_python), "-m", "venv", str(venv)], check=True, capture_output=True)
        subprocess.run([str(venv / "bin/pip"), "install", "--quiet", "--disable-pip-version-check",
                        "-r", str(workdir / "src/requirements.txt"), "pytest"],
                       check=True, capture_output=True, text=True)
        create_scratch(name)
        cfg = get_db_config()
        env = {
            # /opt/homebrew/bin: psycopg locates libpq via pg_config on PATH
            "PATH": f"{venv / 'bin'}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
            "HOME": os.environ.get("HOME", ""),
            "LANG": "en_US.UTF-8",
            "POSTGRES_HOST": str(cfg["host"]), "POSTGRES_PORT": str(cfg["port"]),
            "POSTGRES_USER": str(cfg["user"]), "POSTGRES_PASSWORD": str(cfg["password"]),
            "POSTGRES_DB": name,
        }
        proc = subprocess.run([str(venv / "bin/python"), "-m", "pytest", "-q", "tests"],
                              cwd=workdir / "src", env=env, capture_output=True, text=True,
                              timeout=config.build.timeout_s)
        return full_suite_verdict(proc.returncode, proc.stdout + proc.stderr)
    except subprocess.CalledProcessError as e:
        return Verification(False, f"could not prepare the test environment: {(e.stderr or '')[-500:]}")
    except subprocess.TimeoutExpired:
        return Verification(False, "full test suite timed out")
    finally:
        try:
            drop_scratch(name)
        except Exception:
            pass
        shutil.rmtree(workdir, ignore_errors=True)


def full_suite_verdict(returncode: int, output: str) -> Verification:
    matches = list(SUMMARY.finditer(output))
    if not matches:
        return Verification(False, "no pytest summary line: " + output.strip()[-300:])
    body = matches[-1].group("body")
    if returncode != 0 or "failed" in body or "error" in body or "passed" not in body:
        return Verification(False, body)
    if "skipped" in body:
        # With a database available nothing should skip; a skip means DB tests did not really run.
        return Verification(False, f"{body} — tests were skipped although a database was provided")
    return Verification(True, body)
