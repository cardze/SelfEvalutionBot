## ADDED Requirements

### Requirement: Runner-built changes cannot touch the Hermes integration
The runner SHALL refuse a runner-built commit whose diff against `main` changes `hermes_profile/`,
`hermes_plugin/`, `hermes_bot.py` or any path containing `hermes` outside `openspec/`. With
`BOT_SERVICE=hermes` it SHALL also refuse changes to `runner/` and `requirements.txt`. The check SHALL
run after PLAN, after BUILD and again on the exact commit before merging.

#### Scenario: BUILD edits the plugin
- **WHEN** a BUILD commits a change to `hermes_plugin/seb/__init__.py`
- **THEN** the run fails without retry and the admin is told the change needs a person

#### Scenario: Requirements change in Hermes mode
- **WHEN** `BOT_SERVICE=hermes` and a BUILD adds a line to `requirements.txt`
- **THEN** the run fails and nothing reaches Hermes's environment

#### Scenario: Requirements change in launchd mode
- **WHEN** `BOT_SERVICE=launchd` and a BUILD adds a line to `requirements.txt`
- **THEN** the change proceeds to the merge request as before

#### Scenario: Protected commit reaches the merge
- **WHEN** the admin taps ✅ Merge on a commit that touches a protected path
- **THEN** the merge is aborted before the test suite and `main` is unchanged

### Requirement: Added code does not reference Hermes
The runner SHALL refuse a runner-built commit that adds a line containing `hermes`
(case-insensitive) to any file outside `openspec/` and Markdown files.

#### Scenario: Bot code writes into the Hermes home
- **WHEN** a BUILD adds `Path.home() / ".hermes" / "config.yaml"` to `bot.py`
- **THEN** the run fails and names the file and line

### Requirement: Merging runs no Hermes setup
With `BOT_SERVICE=hermes`, merging SHALL NOT run `hermes_profile/setup.sh` or `hermes pm install`.
The only Hermes command it runs SHALL be restarting the `HERMES_PROFILE` gateway, and
`HERMES_PROFILE` SHALL be a plain profile name other than `default`.

#### Scenario: Merge in Hermes mode
- **WHEN** a ✅ Merge succeeds with `BOT_SERVICE=hermes`
- **THEN** the only Hermes command run is `hermes -p seb gateway restart`

#### Scenario: Default profile configured
- **WHEN** `config.env` sets `HERMES_PROFILE=default`
- **THEN** loading the runner config fails with an error naming `HERMES_PROFILE`

### Requirement: The agent cannot read the Hermes home
The runner settings SHALL deny reading `~/.hermes` with permission rules and `filesystem.denyRead`,
and the isolation self-test SHALL check that listing it is blocked.

#### Scenario: Agent lists the Hermes home
- **WHEN** the agent runs `ls -a ~/.hermes`
- **THEN** the command fails and the self-test records the check as passed
