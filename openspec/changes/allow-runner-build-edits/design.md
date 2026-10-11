# Design: allow runner BUILD edits

- **E1 acceptEdits.** `runner/settings.template.json` sets `permissions.defaultMode: "acceptEdits"`.
  Claude Code then auto-approves file edits inside the working directories (the run's workspace, its
  cwd, and the `--add-dir` snapshot) and still refuses edits elsewhere in headless mode.
- **E2 Edit deny rules.** Deny rules beat acceptEdits, so `Edit(//…/**)` rules (they cover Write and
  MultiEdit too) block the main checkout, the snapshot folder (`{{SNAPSHOT}}`, so the agent cannot
  rewrite the agents and skills it runs with), `~/.seb-runner`, `~/.hermes`, `~/.claude`, `~/.ssh`,
  `~/.aws` and `~/.config`. `render_settings` checks Edit rules are absolute `//` paths like Read rules.
- **E3 Self-test.** For the Claude backend the self-test adds "write-tool outside workspace": the Write
  tool must not create `~/.seb-runner/canary-edit`. The Hermes backend is unchanged (its tool calls run
  in a Docker container).

Affected: `runner/settings.template.json`, `runner/templates.py`, `runner/selftest.py`, tests.
