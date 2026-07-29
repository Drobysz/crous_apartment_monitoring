"""Static safety checks for the active Alembic revision graph."""

import ast
from collections import Counter
from pathlib import Path

MAX_REVISION_LENGTH = 32
VERSIONS_DIR = Path(__file__).parents[2] / "alembic" / "versions"


def _assignment(module: ast.Module, name: str, path: Path) -> object:
    values = [
        node.value
        for node in module.body
        if isinstance(node, ast.Assign)
        for target in node.targets
        if isinstance(target, ast.Name) and target.id == name
    ]
    assert len(values) == 1, f"{path}: expected exactly one {name!r} assignment"
    return ast.literal_eval(values[0])


def _attribute_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _attribute_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""


def test_active_migration_graph_is_linear_and_uses_short_identifiers() -> None:
    revisions: dict[str, str | None] = {}

    for path in sorted(VERSIONS_DIR.glob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        revision = _assignment(module, "revision", path)
        down_revision = _assignment(module, "down_revision", path)

        assert isinstance(revision, str), f"{path}: revision must be a string"
        assert revision.isascii() and 0 < len(revision) <= MAX_REVISION_LENGTH, (
            f"{path}: revision {revision!r} must be ASCII and no longer than "
            f"{MAX_REVISION_LENGTH} characters"
        )
        assert down_revision is None or isinstance(down_revision, str), (
            f"{path}: down_revision must be a string or None"
        )
        if isinstance(down_revision, str):
            assert down_revision.isascii() and len(down_revision) <= MAX_REVISION_LENGTH, (
                f"{path}: down_revision {down_revision!r} must be ASCII and no longer "
                f"than {MAX_REVISION_LENGTH} characters"
            )
        assert revision not in revisions, f"duplicate revision ID: {revision!r}"
        revisions[revision] = down_revision

    assert revisions, "no active Alembic revisions found"
    parents = [parent for parent in revisions.values() if parent is not None]
    assert all(parent in revisions for parent in parents), "a down_revision is missing from the active graph"
    assert len([revision for revision, parent in revisions.items() if parent is None]) == 1
    assert all(count == 1 for count in Counter(parents).values()), "migration graph has a branch"

    heads = set(revisions) - set(parents)
    assert len(heads) == 1, f"expected exactly one head, got {sorted(heads)}"

    visited: set[str] = set()
    current = next(iter(heads))
    while current is not None:
        assert current not in visited, f"migration graph contains a cycle at {current!r}"
        visited.add(current)
        current = revisions[current]
    assert visited == set(revisions), "migration graph is disconnected"


def test_active_revisions_are_historical_snapshots() -> None:
    last_changed_at_definitions = 0

    for path in sorted(VERSIONS_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        module = ast.parse(source, filename=str(path))

        for node in ast.walk(module):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("app.db"), (
                    f"{path}: active revisions must not import application database modules"
                )
            if isinstance(node, ast.Import):
                assert all(not alias.name.startswith("app.db") for alias in node.names), (
                    f"{path}: active revisions must not import application database modules"
                )
            if isinstance(node, ast.Call):
                call_name = _attribute_name(node.func)
                assert call_name not in {"Base.metadata.create_all", "Base.metadata.drop_all"}, (
                    f"{path}: active revisions must use explicit Alembic operations"
                )
                if call_name in {"sa.Column", "sqlalchemy.Column"} and node.args:
                    column_name = node.args[0]
                    if isinstance(column_name, ast.Constant) and column_name.value == "last_changed_at":
                        last_changed_at_definitions += 1

    assert last_changed_at_definitions == 1, "searches.last_changed_at must be created exactly once"
