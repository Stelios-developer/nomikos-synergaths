"""Working-tree architecture/publication checks; read-only, no cloud operations.

Static import checks are conventions, not a complete TS/Python dependency proof.
"""
import ast
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from check_git_index import TOKEN_PATTERNS, configured_secrets, forbidden_path


def cycles(graph):
    visited, active, problems = set(), set(), []

    def visit(node):
        if node in active:
            problems.append(f"Frontend import cycle: {node}")
            return
        if node in visited:
            return
        active.add(node)
        for child in graph.get(node, ()):
            visit(child)
        active.remove(node)
        visited.add(node)

    for node in graph:
        visit(node)
    return problems


def resolve_import(path, specifier, published):
    relative = (ROOT / path).parent / specifier
    for candidate in (relative, *(Path(str(relative) + ext) for ext in (".ts", ".tsx", ".js", ".mjs")), relative / "index.ts", relative / "index.tsx"):
        try:
            target = candidate.resolve().relative_to(ROOT).as_posix()
        except ValueError:
            continue
        if target in published:
            return target
    return None


def inspect_sources(sources):
    problems, graph = [], {}
    published = set(sources)
    for path, source in sources.items():
        if path.endswith(".py"):
            try:
                tree = ast.parse(source, filename=path)
            except SyntaxError:
                problems.append(f"Invalid Python syntax: {path}")
                continue
            if path.startswith(("backend/services/", "backend/db/")):
                for node in ast.walk(tree):
                    modules = ([node.module or ""] if isinstance(node, ast.ImportFrom)
                               else [item.name for item in node.names] if isinstance(node, ast.Import) else [])
                    if any(module == "main" or module.startswith("routers") for module in modules):
                        problems.append(f"Domain/storage imports HTTP composition: {path}")
        if path.startswith("frontend/src/") and path.endswith((".ts", ".tsx")):
            graph[path] = []
            for imported in re.findall(r"\b(?:from\s+|import\s*)['\"]([^'\"]+)['\"]", source):
                if imported.startswith(("node:", "../../scripts", "../../../scripts")):
                    problems.append(f"Browser imports operator tooling: {path}")
                if not imported.startswith("."):
                    continue
                target = resolve_import(path, imported.split("?")[0], published)
                if target is None:
                    problems.append(f"Unresolved local import: {path}: {imported}")
                elif target.endswith((".ts", ".tsx")):
                    graph[path].append(target)
                    if path.startswith("frontend/src/api/") and "/components/" in target:
                        problems.append(f"Transport imports UI: {path}")
    return problems + cycles(graph)


def main():
    paths = subprocess.check_output(["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0")
    paths = sorted({path for path in paths if path and (ROOT / path).is_file()})
    problems, sources = [], {}
    secrets = configured_secrets()
    for path in paths:
        file = ROOT / path
        if file.is_symlink() or forbidden_path(path):
            problems.append(f"Private/generated path or symlink in publication candidates: {path}")
            continue
        data = file.read_bytes()
        for name, value in secrets:
            if value in data:
                problems.append(f"Configured secret {name} in publication candidate: {path} (value withheld)")
        if b"\0" in data:
            continue
        for label, pattern in TOKEN_PATTERNS.items():
            if re.search(pattern, data):
                problems.append(f"Recognizable {label}: {path} (value withheld)")
        try:
            sources[path] = data.decode("utf-8-sig")
        except UnicodeDecodeError:
            problems.append(f"Source is not UTF-8: {path}")
    problems += inspect_sources(sources)
    for path, source in sources.items():
        if not path.endswith(".md"):
            continue
        # Ignore fenced examples. Link targets refer to published files, not local runtime output.
        source = re.sub(r"```.*?```", "", source, flags=re.S)
        for first, second in re.findall(r"\[[^\]\n]*\]\((?:<([^>]+)>|([^\s)]+))\)", source):
            target = (first or second).split("#")[0]
            if not target or re.match(r"(?:https?://|mailto:|[A-Za-z]:|/)", target):
                continue
            if resolve_import(path, target, set(paths)) is None:
                problems.append(f"Broken/unpublished local documentation link: {path}: {target}")
    for problem in sorted(set(problems)):
        print("BLOCK:", problem)
    print(f"Checked {len(paths)} candidate files; {len(set(problems))} source/publication issues.")
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
