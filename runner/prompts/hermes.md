

## Running on Hermes Agent
This run uses Hermes Agent, not Claude Code. Translate the instructions above as follows:
- **Your role.** You are the `openspec-leader`: its instructions are the preloaded skill
  `seb-agent-openspec-leader`. The other preloaded skills are the planner, evaluator and coder roles
  (`seb-agent-planner`, `seb-agent-evaluator`, `seb-agent-coder`) and the OpenSpec workflow skills
  (`seb-openspec-*`, `seb-planner-fetch-feedback`). Where the instructions name a skill without the
  `seb-` prefix, use the prefixed one.
- **Delegation.** To "call" or "delegate to" a role, use `delegate_task`. Put the role's complete
  instructions (from its `seb-agent-<role>` skill) and the handoff contract in the task context;
  subagents do not see your skills.
- **Tools.** `terminal` runs shell commands, `read_file` / `write_file` / `patch` / `search_files`
  work on files. Everything runs inside a sandbox container whose working directory `/workspace` is
  this repository; nothing outside it exists for you.
- **Python.** The repository's `.venv` belongs to another machine; do not use it. Before running
  Python or tests, create the sandbox environment once: `{{VENV_SETUP}}`. Then use `{{PYTHON}}`
  and `{{PIP}}`.
- **No database.** Database tests skip here; that is expected.
