"""Language Server Protocol server for Flow exception analysis.

Provides inlay hints and hover information about exception flow through
Python codebases. Uses pygls to handle LSP protocol details over stdio.

Install dependencies:
    pip install bubble-analysis[lsp]

Run:
    bubble-lsp
    python -m bubble.lsp
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

from lsprotocol import types
from pygls.lsp.server import LanguageServer

from bubble.extractor import extract_from_directory
from bubble.integrations.base import Entrypoint
from bubble.models import CallSite, FunctionDef, ProgramModel
from bubble.propagation import (
    ExceptionFlow,
    PropagationResult,
    compute_exception_flow,
    propagate_exceptions,
)

_log_file = Path.home() / ".bubble-lsp.log"
logging.basicConfig(
    handlers=[
        logging.StreamHandler(sys.stderr),
        logging.FileHandler(_log_file, mode="w"),
    ],
    level=logging.INFO,
    format="[bubble-lsp] %(asctime)s %(message)s",
)
logging.getLogger("pygls").setLevel(logging.WARNING)
log = logging.getLogger("bubble-lsp")

RERAISE_PATTERNS = {"e", "ex", "err", "exc", "error", "exception", "Unknown"}


class FlowLanguageServer(LanguageServer):
    """Language server that holds a cached ProgramModel."""

    def __init__(self) -> None:
        super().__init__("bubble-lsp", "v0.1")
        self._model: ProgramModel | None = None
        self._workspace_root: Path | None = None

    def get_model(self) -> ProgramModel | None:
        if self._model is not None:
            return self._model

        if self._workspace_root is None:
            return None

        log.info("building model for %s", self._workspace_root)
        try:
            self._model = extract_from_directory(self._workspace_root)
            func_count = len(self._model.functions)
            raise_count = len(self._model.raise_sites)
            log.info("model built: %d functions, %d raise sites", func_count, raise_count)
        except Exception:
            log.exception("failed to build model")
            return None

        return self._model

    def invalidate_model(self) -> None:
        self._model = None


server = FlowLanguageServer()


def _uri_to_path(uri: str) -> Path:
    parsed = urlparse(uri)
    return Path(unquote(parsed.path))


def _find_function_def_at_line(
    model: ProgramModel, file_path: Path, line: int
) -> FunctionDef | None:
    """Find a function definition whose def line is exactly at the given line."""
    file_str = str(file_path)
    for func in model.functions.values():
        if func.file == file_str and func.line == line:
            return func

    file_funcs = [f for f in model.functions.values() if f.file == file_str]
    if not file_funcs:
        sample_files = list({f.file for f in list(model.functions.values())[:5]})
        log.info(
            "no functions found for file %s; sample model files: %s",
            file_str,
            sample_files,
        )
    return None


def _find_call_sites_at_line(model: ProgramModel, file_path: Path, line: int) -> list[CallSite]:
    """Find all call sites on the given line in the given file."""
    file_str = str(file_path)
    return [cs for cs in model.call_sites if cs.file == file_str and cs.line == line]


def _is_reraise(exc_type: str) -> bool:
    """Check if an exception type looks like a reraise variable name."""
    return exc_type in RERAISE_PATTERNS


def _format_def_hover(flow: ExceptionFlow, function_name: str) -> str | None:
    """Format exception flow for a def-line hover.

    Returns None when there are no meaningful exceptions to display,
    so the editor shows no hover popup.
    """
    filtered_uncaught = {k: v for k, v in flow.uncaught.items() if not _is_reraise(k)}
    filtered_framework = {k: v for k, v in flow.framework_handled.items() if not _is_reraise(k)}
    filtered_caught = {k: v for k, v in flow.caught_locally.items() if not _is_reraise(k)}
    filtered_global = {k: v for k, v in flow.caught_by_global.items() if not _is_reraise(k)}

    if not any([filtered_uncaught, filtered_framework, filtered_caught, filtered_global]):
        return None

    parts: list[str] = []
    parts.append(f"**Exception flow for `{function_name}`**\n")

    if filtered_uncaught:
        parts.append("**Uncaught (will propagate):**")
        for exc_type in sorted(filtered_uncaught):
            parts.append(f"- `{exc_type}`")
        parts.append("")

    if filtered_framework:
        parts.append("**Framework handled:**")
        for exc_type in sorted(filtered_framework):
            parts.append(f"- `{exc_type}`")
        parts.append("")

    if filtered_caught:
        parts.append("**Caught locally:**")
        for exc_type in sorted(filtered_caught):
            parts.append(f"- `{exc_type}`")
        parts.append("")

    if filtered_global:
        parts.append("**Caught by global handler:**")
        for exc_type in sorted(filtered_global):
            parts.append(f"- `{exc_type}`")
        parts.append("")

    return "\n".join(parts)


def _format_call_hover(
    call_sites: list[CallSite],
    propagation: PropagationResult,
    model: ProgramModel,
) -> str | None:
    """Format exception info for call sites on a line.

    For each distinct callee, shows what exceptions it can throw.
    Returns None if no exceptions are found for any callee.
    """
    seen_callees: set[str] = set()
    parts: list[str] = []

    for cs in call_sites:
        callee_key = cs.callee_qualified
        callee_display = cs.callee_name

        if callee_key and callee_key in seen_callees:
            continue

        exceptions: set[str] = set()

        if callee_key:
            seen_callees.add(callee_key)
            exceptions = propagation.propagated_raises.get(callee_key, set())

        if not exceptions:
            candidates = model.name_to_keys.get(cs.callee_name, [])
            for candidate_key in candidates:
                candidate_exceptions = propagation.propagated_raises.get(candidate_key, set())
                exceptions = exceptions | candidate_exceptions

        filtered = {exc for exc in exceptions if not _is_reraise(exc)}
        if not filtered:
            continue

        parts.append(f"**`{callee_display}()` can raise:**")
        for exc_type in sorted(filtered):
            parts.append(f"- `{exc_type}`")
        parts.append("")

    if not parts:
        return None

    return "\n".join(parts)


def _function_key(func: FunctionDef, file_path: Path, workspace_root: Path) -> str:
    """Build the canonical function key from a FunctionDef."""
    try:
        relative_file = str(file_path.relative_to(workspace_root))
    except ValueError:
        relative_file = func.file
    return f"{relative_file}::{func.qualified_name}"


def _get_uncaught_exceptions(
    func: FunctionDef,
    file_path: Path,
    workspace_root: Path,
    model: ProgramModel,
    propagation: PropagationResult,
) -> set[str]:
    """Get filtered uncaught exceptions for a function."""
    function_key = _function_key(func, file_path, workspace_root)
    flow = compute_exception_flow(function_key, model, propagation)
    return {k for k in flow.uncaught if not _is_reraise(k)}


@server.feature(types.INITIALIZE)
def on_initialize(params: types.InitializeParams) -> None:
    """Capture the workspace root on initialization."""
    root_uri = params.root_uri
    if root_uri:
        server._workspace_root = _uri_to_path(root_uri)
        log.info("workspace root: %s", server._workspace_root)


@server.feature(types.TEXT_DOCUMENT_DID_OPEN)
def did_open(ls: FlowLanguageServer, params: types.DidOpenTextDocumentParams) -> None:
    """Publish diagnostics when a file is opened."""
    _publish_file_diagnostics(ls, params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_DID_SAVE)
def did_save(ls: FlowLanguageServer, params: types.DidSaveTextDocumentParams) -> None:
    """Invalidate the model and republish diagnostics on save."""
    log.info("file saved, invalidating model")
    ls.invalidate_model()
    _publish_file_diagnostics(ls, params.text_document.uri)


@server.feature(types.TEXT_DOCUMENT_HOVER)
def hover(ls: FlowLanguageServer, params: types.HoverParams) -> types.Hover | None:
    """Return context-sensitive exception info based on cursor position.

    - On a def/async def line: full exception flow for that function
    - On a function call: exceptions the callee can throw
    - Anywhere else: no hover
    """
    model = ls.get_model()
    if model is None or ls._workspace_root is None:
        log.info("hover: no model or workspace root")
        return None

    file_path = _uri_to_path(params.text_document.uri)
    line = params.position.line + 1
    log.info("hover at %s:%d", file_path, line)

    func = _find_function_def_at_line(model, file_path, line)
    if func is not None:
        try:
            relative_file = str(file_path.relative_to(ls._workspace_root))
        except ValueError:
            relative_file = func.file
        function_key = f"{relative_file}::{func.qualified_name}"
        log.info("hover matched def: %s", function_key)

        try:
            propagation = propagate_exceptions(model, skip_evidence=True)
            flow = compute_exception_flow(function_key, model, propagation)
        except Exception:
            log.exception("exception flow failed for %s", function_key)
            return None

        hover_text = _format_def_hover(flow, func.qualified_name)
        if hover_text is None:
            log.info("hover def: all exceptions filtered, no popup")
            return None

        return types.Hover(
            contents=types.MarkupContent(
                kind=types.MarkupKind.Markdown,
                value=hover_text,
            ),
        )

    call_sites = _find_call_sites_at_line(model, file_path, line)
    if call_sites:
        callees = [cs.callee_name for cs in call_sites]
        log.info("hover matched %d call(s): %s", len(call_sites), callees)

        try:
            propagation = propagate_exceptions(model, skip_evidence=True)
        except Exception:
            log.exception("propagation failed")
            return None

        hover_text = _format_call_hover(call_sites, propagation, model)
        if hover_text is None:
            log.info("hover call: no exceptions found for callees")
            return None

        return types.Hover(
            contents=types.MarkupContent(
                kind=types.MarkupKind.Markdown,
                value=hover_text,
            ),
        )

    log.info("hover: no def or call site at line %d, skipping", line)
    return None


ROUTE_DECORATOR_PATTERNS = {".get(", ".post(", ".put(", ".delete(", ".patch(", ".route(", ".api_view"}
IGNORE_PREFIX = "bubble: ignore"


def _parse_ignore_comment(source_lines: list[str], decorator_line: int, def_line: int) -> set[str] | bool:
    """Parse bubble ignore comments between the decorator and def line (inclusive).

    Returns True for a blanket ignore, a set of exception names for selective
    ignore, or False if no ignore comment is found.

    Supported formats:
        # bubble: ignore
        # bubble: ignore[ValueError, KeyError]
    """
    for i in range(decorator_line, min(def_line, len(source_lines))):
        line = source_lines[i]
        comment_idx = line.find("# ")
        if comment_idx == -1:
            continue
        comment = line[comment_idx + 2:].strip()
        if not comment.startswith(IGNORE_PREFIX):
            continue
        rest = comment[len(IGNORE_PREFIX):].strip()
        if not rest:
            return True
        if rest.startswith("[") and rest.endswith("]"):
            types_str = rest[1:-1]
            return {t.strip() for t in types_str.split(",") if t.strip()}
    return False


def _find_route_decorator_range(
    source_lines: list[str], def_line: int
) -> types.Range | None:
    """Find the route decorator above a function def and return its range.

    Scans backwards from the def line looking for a decorator that matches
    a route pattern (e.g. @router.get, @app.route). Falls back to the
    nearest decorator if no route pattern is found.
    """
    def_idx = def_line - 1
    nearest_decorator_idx: int | None = None

    for i in range(def_idx - 1, max(def_idx - 20, -1), -1):
        stripped = source_lines[i].strip()
        if stripped.startswith("@"):
            if nearest_decorator_idx is None:
                nearest_decorator_idx = i
            lower = stripped.lower()
            if any(p in lower for p in ROUTE_DECORATOR_PATTERNS):
                return _line_range(source_lines, i)
        elif stripped == "":
            break

    if nearest_decorator_idx is not None:
        return _line_range(source_lines, nearest_decorator_idx)
    return None


def _line_range(source_lines: list[str], line_idx: int) -> types.Range:
    """Build a Range covering the non-whitespace content of a line."""
    line = source_lines[line_idx]
    start_char = len(line) - len(line.lstrip())
    return types.Range(
        start=types.Position(line=line_idx, character=start_char),
        end=types.Position(line=line_idx, character=len(line)),
    )


def _publish_file_diagnostics(ls: FlowLanguageServer, uri: str) -> None:
    """Compute and publish exception diagnostics for entrypoints in a file."""
    model = ls.get_model()
    if model is None or ls._workspace_root is None:
        return

    file_path = _uri_to_path(uri)
    try:
        relative_file = str(file_path.relative_to(ls._workspace_root))
    except ValueError:
        return

    file_entrypoints = [ep for ep in model.entrypoints if ep.file == relative_file]
    log.info("diagnostics: %s has %d entrypoints", relative_file, len(file_entrypoints))

    if not file_entrypoints:
        ls.text_document_publish_diagnostics(
            types.PublishDiagnosticsParams(uri=uri, diagnostics=[])
        )
        return

    try:
        doc = ls.workspace.get_text_document(uri)
        source_lines = doc.source.splitlines()
    except Exception:
        log.exception("diagnostics: failed to read document")
        return

    try:
        propagation = propagate_exceptions(model, skip_evidence=True)
    except Exception:
        log.exception("diagnostics: propagation failed")
        return

    diagnostics: list[types.Diagnostic] = []
    for ep in file_entrypoints:
        function_key = f"{ep.file}::{ep.function}"
        if function_key not in model.functions:
            candidates = model.name_to_keys.get(ep.function, [])
            file_candidates = [k for k in candidates if k.startswith(f"{ep.file}::")]
            if file_candidates:
                function_key = file_candidates[0]
            else:
                log.info("diagnostics: no function key for entrypoint %s", function_key)
                continue

        flow = compute_exception_flow(function_key, model, propagation)
        uncaught = {k for k in flow.uncaught if not _is_reraise(k)}
        if not uncaught:
            continue

        decorator_range = _find_route_decorator_range(source_lines, ep.line)
        if decorator_range is None:
            continue

        ignored = _parse_ignore_comment(source_lines, decorator_range.start.line, ep.line)
        if ignored is True:
            continue
        if isinstance(ignored, set):
            uncaught = uncaught - ignored
            if not uncaught:
                continue

        exc_list = ", ".join(sorted(uncaught))
        route = ep.metadata.get("http_path", "")
        if route:
            message = f"{route} — uncaught exceptions: {exc_list}"
        else:
            message = f"Uncaught exceptions: {exc_list}"

        diagnostics.append(
            types.Diagnostic(
                range=decorator_range,
                message=message,
                severity=types.DiagnosticSeverity.Warning,
                source="bubble",
            )
        )

    log.info("diagnostics: publishing %d warnings for %s", len(diagnostics), relative_file)
    ls.text_document_publish_diagnostics(
        types.PublishDiagnosticsParams(uri=uri, diagnostics=diagnostics)
    )


def main() -> None:
    """Start the LSP server over stdio."""
    log.info("bubble-lsp starting (stdio)")
    server.start_io()


if __name__ == "__main__":
    main()
