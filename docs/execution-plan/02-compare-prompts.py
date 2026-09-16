"""Compare model-facing prompt text between two juena-chatbot revisions.

The cutover is allowed to change deployment documentation and Python imports,
so a whole-file ``*.md`` or ``*.py`` diff is too broad. This verifier checks
the authored Markdown below ``src/juena/agents`` and the docstrings of functions
decorated with LangChain's ``@tool``. It reports names only: prompt text is not
copied into the planning repository's output or history.

Run from the juena-chatbot repository:

    uv run python ../Vitess-AI-Agent/docs/execution-plan/02-compare-prompts.py \
        ee9248d HEAD
"""

from __future__ import annotations

import argparse
import ast
import subprocess
from collections.abc import Iterable


def _git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def _paths(revision: str) -> set[str]:
    return set(_git("ls-tree", "-r", "--name-only", revision).splitlines())


def _source(revision: str, path: str) -> str:
    return _git("show", f"{revision}:{path}")


def _decorator_name(decorator: ast.expr) -> str | None:
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


class _ToolDocstrings(ast.NodeVisitor):
    def __init__(self) -> None:
        self.scope: list[str] = []
        self.values: dict[str, str | None] = {}

    def _visit_definition(
        self,
        node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        name = ".".join([*self.scope, node.name])
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and any(
            _decorator_name(decorator) == "tool" for decorator in node.decorator_list
        ):
            self.values[name] = ast.get_docstring(node, clean=False)
        self.scope.append(node.name)
        self.generic_visit(node)
        self.scope.pop()

    visit_ClassDef = _visit_definition
    visit_FunctionDef = _visit_definition
    visit_AsyncFunctionDef = _visit_definition


def _tool_docstrings(source: str) -> dict[str, str | None]:
    visitor = _ToolDocstrings()
    visitor.visit(ast.parse(source))
    return visitor.values


def _changed_markdown(before: str, after: str, paths: Iterable[str]) -> list[str]:
    return [
        path
        for path in sorted(paths)
        if _source(before, path) != _source(after, path)
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("before", help="pre-cutover git revision")
    parser.add_argument("after", nargs="?", default="HEAD")
    args = parser.parse_args()

    before_paths = _paths(args.before)
    after_paths = _paths(args.after)
    all_paths = before_paths | after_paths

    prompt_paths = {
        path
        for path in all_paths
        if path.startswith("src/juena/agents/") and path.endswith(".md")
    }
    missing_prompts = sorted(
        path for path in prompt_paths if path not in before_paths or path not in after_paths
    )
    shared_prompts = prompt_paths & before_paths & after_paths
    changed_prompts = _changed_markdown(args.before, args.after, shared_prompts)

    python_paths = {
        path
        for path in all_paths
        if path.startswith("src/juena/") and path.endswith(".py")
    }
    changed_tools: list[str] = []
    missing = object()
    for path in sorted(python_paths):
        before_docs = (
            _tool_docstrings(_source(args.before, path)) if path in before_paths else {}
        )
        after_docs = (
            _tool_docstrings(_source(args.after, path)) if path in after_paths else {}
        )
        for name in sorted(before_docs.keys() | after_docs.keys()):
            if before_docs.get(name, missing) != after_docs.get(name, missing):
                changed_tools.append(f"{path}:{name}")

    changed = [*missing_prompts, *changed_prompts, *changed_tools]
    if changed:
        print("model-facing prompt text changed:")
        for name in changed:
            print(f"  {name}")
        return 1

    print(
        f"prompt text unchanged: {len(shared_prompts)} Markdown files, "
        f"{sum(len(_tool_docstrings(_source(args.after, path))) for path in python_paths if path in after_paths)} @tool docstrings"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
