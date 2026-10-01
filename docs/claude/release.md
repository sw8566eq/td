# Release binary

## Release binary

`.github/workflows/release.yml` builds a standalone Linux binary with PyInstaller and publishes it
to a GitHub Release whenever a `v*` tag is pushed -- `requirements.txt` includes `pyinstaller`
alongside `pygame`/`pytest` for exactly this, so `pip install -r requirements.txt` is still the one
setup command that covers running, testing, *and* packaging the game. Linux only, deliberately --
this project has never had a Windows/macOS build, and nothing about the packaging step below has
been verified on either.

It's `--onedir`, never `--onefile`, and that's load-bearing rather than a style preference:
`--onefile` re-extracts every bundled file into a *fresh* temp directory on every single launch and
deletes it again on exit. `progression/progress.py`/`progression/achievements.py`/`persistence/player_settings.py`/`persistence/save_state.py` (see
"Small on-disk JSON state files" above) all resolve their JSON file's path relative to their own
module's `__file__` -- under `--onefile` that's a different, vanishing directory every run, so none
of progress/achievements/settings/a saved run would actually survive being closed and reopened,
even though every one of those features works perfectly when run from source. `--onedir` keeps that
directory stable (it's just the unpacked folder sitting next to the executable), so persistence
works exactly like an ordinary `python main.py` run. This was verified empirically, not assumed --
building a throwaway diagnostic executable and comparing `__file__` across two separate launches is
what caught it, since it isn't the kind of bug a single smoke-test launch would ever surface.

`presentation/assets.py`'s `DEFAULT_ASSET_ROOT` exists for the same category of reason: it used to be a bare
`asset_root="assets"` default, resolved against the process's current working directory -- fine for
`python main.py` run from the repo root (the only way this project was ever launched before a
packaged build existed), but a packaged binary double-clicked from a file manager or run via a PATH
symlink has no such guarantee about its own cwd. `DEFAULT_ASSET_ROOT` is computed once, relative to
`presentation/assets.py`'s own `__file__`, the same fix in the same spirit as the JSON state files above -- and
under PyInstaller's `--onedir`, that resolves to the bundled `assets/` folder sitting right next to
the module itself regardless of launch directory, which is also why the release build step passes
`--add-data "assets:assets"` to put it there in the first place.

The workflow runs the exact same 3-step gate `tests.yml` runs on every push/PR (`ruff check .`, the
strict-mode `mypy` module list, `pytest -v --cov=. --cov-report=term-missing --cov-fail-under=98`)
before building, not just a bare `pytest -q` -- a tag push used to skip straight to the test suite
with no lint/type/coverage-floor check of its own, so a release build's only quality gate was
whatever `tests.yml` happened to already run on that commit, never structurally guaranteed (nothing
stops tagging an arbitrary/local commit that skipped it). This makes the mypy module list a 4th
copy across the repo (`pyproject.toml`'s override list, this file's Commands block, `tests.yml`,
and now `release.yml`) -- the same manual-sync tradeoff already accepted above, not a new one. Once
the gate passes, the workflow tars up `dist/td` (a directory, not a single file -- `--onedir`'s
whole point) and attaches it to the release via `gh release create`, using the pushed tag itself as
both the release name and the archive's version suffix.
