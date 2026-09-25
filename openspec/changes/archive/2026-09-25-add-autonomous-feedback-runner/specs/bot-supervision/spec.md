## ADDED Requirements

### Requirement: Bot runs under launchd
The system SHALL provide a launchd user-agent definition that runs `bot.py` from the main checkout with `KeepAlive` and `RunAtLoad`. Standard output and standard error SHALL go to log files under `~/.seb-runner/logs/`.

#### Scenario: Bot crashes
- **WHEN** the bot process exits unexpectedly
- **THEN** launchd starts it again without manual action

#### Scenario: Login after reboot
- **WHEN** the admin logs in after a reboot
- **THEN** the bot is started automatically

#### Scenario: Logs available
- **WHEN** the bot writes log output
- **THEN** it appears in `~/.seb-runner/logs/bot.out.log` or `bot.err.log`

### Requirement: Programmatic restart
The runner SHALL be able to restart the bot with `launchctl kickstart -k gui/<uid>/com.seb.bot`, so newly merged code and schema changes take effect.

#### Scenario: Restart after merge
- **WHEN** the runner completes a merge
- **THEN** it restarts the bot, and the new process runs the merged code

### Requirement: Install and uninstall helpers
`runner/setup.sh install-agents` SHALL render the bot and runner plist templates with absolute paths and load them with `launchctl bootstrap`. `runner/setup.sh uninstall-agents` SHALL unload and remove them.

#### Scenario: Install
- **WHEN** the admin runs `runner/setup.sh install-agents`
- **THEN** both agents are loaded and `launchctl print gui/<uid>/com.seb.bot` shows the bot running

#### Scenario: Uninstall
- **WHEN** the admin runs `runner/setup.sh uninstall-agents`
- **THEN** neither agent remains loaded and the plist files are removed from `~/Library/LaunchAgents/`
