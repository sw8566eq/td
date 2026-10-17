"""Guards for the agent docs (AGENTS.md + docs/agents/), so their organization can't silently rot.

- every doc under docs/agents/ is indexed in AGENTS.md, and every indexed doc exists;
- every quoted cross-reference to a doc section names a heading that really exists there;
- the strict mypy module list is identical in its four hand-kept copies.
"""

import pathlib
import re
import tomllib

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs" / "agents"
AGENTS_MD = REPO_ROOT / "AGENTS.md"

# `[run-map.md](run-map.md) "Node types"` inside docs/agents/ ...
DOC_LINK_REF = re.compile(r'\[([\w-]+\.md)\]\(\1\)(?:\'s)? "([^"]+)"')
# ... and `docs/agents/run-map.md "Node types"` (or AGENTS.md's `[x.md](docs/agents/x.md) "..."`)
# from code comments and AGENTS.md.
PATH_REF = re.compile(r'docs/agents/([\w-]+\.md)\)?(?:\'s)? "([^"]+)"')
SOURCE_GLOBS = ("*.py", "*.toml", "*.yml", "*.md")
SKIPPED_DIRS = {".venv", ".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".claude"}


def _normalize(text):
    """Collapse a quoted section name that wrapped across comment/docstring lines."""
    text = re.sub(r"\n\s*#\s*", " ", text)
    return " ".join(text.split())


def _headings(doc_name):
    lines = (DOCS_DIR / doc_name).read_text().splitlines()
    return [_normalize(line.lstrip("#")) for line in lines if line.startswith("#")]


def _resolves(doc_name, section):
    # A reference may shorten a long heading to its leading words ("Two currencies").
    wanted = _normalize(section)
    return any(heading == wanted or heading.startswith(wanted) for heading in _headings(doc_name))


def _source_files():
    for pattern in SOURCE_GLOBS:
        for path in REPO_ROOT.rglob(pattern):
            if not SKIPPED_DIRS.intersection(path.relative_to(REPO_ROOT).parts):
                yield path


def test_every_agent_doc_is_indexed_in_agents_md():
    agents_md = AGENTS_MD.read_text()
    indexed = set(re.findall(r"\(docs/agents/([\w-]+\.md)\)", agents_md))
    on_disk = {path.name for path in DOCS_DIR.glob("*.md")}
    assert on_disk - indexed == set(), "docs missing from AGENTS.md's index"
    assert indexed - on_disk == set(), "AGENTS.md links docs that don't exist"


def test_claude_md_imports_agents_md():
    assert "@AGENTS.md" in (REPO_ROOT / "CLAUDE.md").read_text()


def test_doc_section_cross_references_resolve():
    broken = []
    for doc in DOCS_DIR.glob("*.md"):
        for target, section in DOC_LINK_REF.findall(doc.read_text()):
            if not (DOCS_DIR / target).exists() or not _resolves(target, section):
                broken.append(f"{doc.name}: {target} {section!r}")
    for path in _source_files():
        if path == pathlib.Path(__file__):
            continue
        for target, section in PATH_REF.findall(path.read_text(errors="ignore")):
            if not (DOCS_DIR / target).exists() or not _resolves(target, section):
                broken.append(f"{path.relative_to(REPO_ROOT)}: {target} {section!r}")
    assert broken == []


def _mypy_command_modules(text):
    match = re.search(r"^\s*(?:- run: )?mypy ((?:\S+\.py ?)+)", text, re.MULTILINE)
    assert match, "no mypy command found"
    return sorted(match.group(1).split())


def test_strict_mypy_module_list_matches_in_all_four_places():
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    (override,) = pyproject["tool"]["mypy"]["overrides"]
    from_pyproject = sorted(module.replace(".", "/") + ".py" for module in override["module"])
    workflows = REPO_ROOT / ".github" / "workflows"
    assert _mypy_command_modules(AGENTS_MD.read_text()) == from_pyproject
    assert _mypy_command_modules((workflows / "tests.yml").read_text()) == from_pyproject
    assert _mypy_command_modules((workflows / "release.yml").read_text()) == from_pyproject
