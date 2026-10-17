# CLAUDE.md

All project guidance lives in `AGENTS.md`, so every coding agent reads the same rules. It is imported
below. Architecture notes are in `docs/agents/`.

@AGENTS.md

## Claude Code specifics

- The local `run-td` skill (`.claude/skills/run-td/`, gitignored) drives a headless `Game()` for
  screenshots and interactive checks. Use it to see a change working in the real game.
