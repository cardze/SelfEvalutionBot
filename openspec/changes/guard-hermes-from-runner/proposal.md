# Guard Hermes from runner-built changes

## Problem
Since `move-bot-into-hermes`, the bot runs inside the `seb` Hermes gateway and the runner ticks from
Hermes cron. A feedback-driven change that the admin approves is merged into the main checkout and then:

- runs on the host: the merge step executes the merged `hermes_profile/setup.sh sync`, and the next
  tick executes the merged `runner/`;
- runs inside the gateway: `hermes_bot.py`, `hermes_plugin/seb/` and the bot code are loaded into the
  Hermes process on restart;
- changes Hermes's own environment: `requirements.txt` becomes the plugin's `python_dependencies`,
  which `hermes pm install` resolves together with Hermes core.

The admin reviews every diff, but one approval of an agent-written change could break Hermes core, its
config or other profiles. The admin asked to restrict that.

## Goals
- Runner-built changes can only change the bot itself, never the Hermes integration, the runner, or
  the dependencies Hermes installs.
- The merge step runs no merged script and makes no change under `~/.hermes`; the only Hermes command
  it runs is restarting its own profile's gateway.
- The agent sandbox cannot read `~/.hermes` (it holds the `seb` profile's bot token and provider keys).
- Every guard is enforced in runner code and covered by tests.

## Non-goals
- Isolating bot code from the gateway process at runtime. Bot code runs as the same user inside the
  gateway; the guard is a pre-merge policy, not a runtime sandbox.
- Restricting changes people make by hand or through pull requests.

## Success criteria
- A PLAN or BUILD that touches a protected path, or adds code that mentions Hermes, fails with a
  message saying the change needs a person; a merge of such a commit is refused.
- In Hermes mode a merge never runs `hermes_profile/setup.sh` or `hermes pm install`.
- The self-test and rendered settings deny reading `~/.hermes`.
