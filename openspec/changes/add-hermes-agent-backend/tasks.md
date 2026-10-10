## 1. Configuration (`runner/config.py`)

- [x] 1.1 Add `agent_backend`, `hermes_bin`, `hermes_home`, `hermes_model`, `hermes_provider`, `hermes_selftest_model` to `Config`, parsed from `config.env`; reject unknown backends
- [x] 1.2 Add `secret_files(config)` / backend-aware secret loading: Claude token for `claude`, nothing for `hermes` (credentials stay in the profile)

## 2. Hermes adapter (`runner/hermes.py`)

- [x] 2.1 `command(config, limits, toolsets, skills, model)` building the `hermes chat` command line (H3)
- [x] 2.2 `build_env(config)` with `HERMES_HOME`, PATH, locale; no runner or bot secrets
- [x] 2.3 `parse_stream(raw) -> StreamSummary` for Hermes JSONL, unwrapping terminal JSON output and exit codes
- [x] 2.4 `parse_result(raw) -> AgentResult` with auth-failure detection (H8)
- [x] 2.5 `render_profile(config)` from `runner/hermes/config.template.yaml` and `check_profile(config)` pre-flight (H5, H7)
- [x] 2.6 `secret_markers(config)` from the profile `.env`
- [x] 2.7 Prompt values per backend (`VENV_SETUP`, `PYTHON`, `PIP`) and the `runner/prompts/hermes.md` appendix

## 3. Dispatch and stages

- [x] 3.1 `agent.run()` and new `agent.probe()` dispatch on the backend (H2)
- [x] 3.2 `selftest` and `verify` use `agent.probe()`; Hermes tool names and verification command (H6, H7)
- [x] 3.3 `runner.Session` loads the right secrets/snapshot per backend; `auth_problem` text per backend
- [x] 3.4 `snapshot.export_hermes_skills(config)` (H4)
- [x] 3.5 `runner/prompts/build.md` uses `{{VENV_SETUP}}`, `{{PYTHON}}`, `{{PIP}}`

## 4. Sandbox assets and setup

- [x] 4.1 `runner/hermes/config.template.yaml`, `runner/hermes/Dockerfile`, `runner/hermes/squid.conf`
- [x] 4.2 `runner/setup.sh`: `hermes-profile`, `hermes-sandbox`, `use-backend <claude|hermes>`; `selftest` works for both backends
- [x] 4.3 README: Hermes backend section (setup, dashboard, rollback, cost note)

## 5. Tests (no Hermes, Docker or database needed)

- [x] 5.1 Config: default backend, hermes keys, unknown backend error
- [x] 5.2 Command line and environment: flags, toolsets, skills, model/provider, no secrets in env
- [x] 5.3 JSONL parsing: tool_use/tool_result, terminal JSON unwrap, blocked call without result, final result ok/error, auth markers
- [x] 5.4 Self-test verdicts on Hermes samples: blocked passes, leak of a profile secret fails, success fails
- [x] 5.5 Verification verdicts on Hermes samples: pass, failures, model lies, output tail
- [x] 5.6 Profile render + pre-flight: template passes; `backend: local`, extra volume, forwarded env, missing network each fail
- [x] 5.7 Skills export: agents and skills land under `skills/seb-runner/` with rewritten names; old export removed
- [x] 5.8 Prompt rendering per backend leaves no placeholders
- [x] 5.9 Full existing suite still passes
