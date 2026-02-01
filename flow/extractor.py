"""Extract structural information from Python source files using libcst."""

import os
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import TYPE_CHECKING

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

if TYPE_CHECKING:
    from flow.cache import FileCache

from flow.detectors import detect_entrypoints, detect_global_handlers
from flow.enums import ResolutionKind
from flow.loader import load_detectors
from flow.models import (
    CallSite,
    CatchSite,
    ClassDef,
    Entrypoint,
    FunctionDef,
    GlobalHandler,
    ImportInfo,
    ProgramModel,
    RaiseSite,
)


class CodeExtractor(cst.CSTVisitor):
    """Extracts structural information from a Python module."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    def __init__(self, file_path: str, relative_path: str | None = None) -> None:
        self.file_path = file_path
        self.relative_path = relative_path or file_path
        self.functions: list[FunctionDef] = []
        self.classes: list[ClassDef] = []
        self.raise_sites: list[RaiseSite] = []
        self.catch_sites: list[CatchSite] = []
        self.call_sites: list[CallSite] = []
        self.imports: list[ImportInfo] = []
        self.import_map: dict[str, str] = {}
        self.return_types: dict[str, str] = {}
        self.detected_frameworks: set[str] = set()

        self._class_stack: list[str] = []
        self._function_stack: list[str] = []
        self._local_types: dict[str, str] = {}
        self._abstract_methods: dict[str, set[str]] = {}
        self._class_bases: dict[str, list[str]] = {}

    def visit_Import(self, node: cst.Import) -> bool:
        for name in node.names if isinstance(node.names, tuple) else []:
            if isinstance(name, cst.ImportAlias):
                module_name = self._get_name_from_expr(name.name)
                alias = (
                    name.asname.name.value
                    if name.asname and isinstance(name.asname.name, cst.Name)
                    else None
                )
                self.imports.append(
                    ImportInfo(
                        file=self.file_path,
                        module=module_name,
                        name=module_name,
                        alias=alias,
                        is_from_import=False,
                    )
                )
                local_name = alias or module_name.split(".")[0]
                self.import_map[local_name] = module_name
                self._detect_framework(module_name)
        return False

    def visit_ImportFrom(self, node: cst.ImportFrom) -> bool:
        if node.module is None:
            return False

        module_name = self._get_name_from_expr(node.module)
        self._detect_framework(module_name)

        if isinstance(node.names, cst.ImportStar):
            self.imports.append(
                ImportInfo(
                    file=self.file_path,
                    module=module_name,
                    name="*",
                    alias=None,
                    is_from_import=True,
                )
            )
        elif isinstance(node.names, tuple):
            for name in node.names:
                if isinstance(name, cst.ImportAlias):
                    imported_name = self._get_name_from_expr(name.name)
                    alias = (
                        name.asname.name.value
                        if name.asname and isinstance(name.asname.name, cst.Name)
                        else None
                    )
                    self.imports.append(
                        ImportInfo(
                            file=self.file_path,
                            module=module_name,
                            name=imported_name,
                            alias=alias,
                            is_from_import=True,
                        )
                    )
                    local_name = alias or imported_name
                    self.import_map[local_name] = f"{module_name}.{imported_name}"
        return False

    def visit_ClassDef(self, node: cst.ClassDef) -> bool:
        class_name = node.name.value

        bases: list[str] = []
        for arg in node.bases:
            base_name = self._get_name_from_expr(arg.value)
            if base_name:
                bases.append(base_name)

        self._class_stack.append(class_name)
        self._abstract_methods[class_name] = set()
        self._class_bases[class_name] = bases

        return True

    def leave_ClassDef(self, node: cst.ClassDef) -> None:
        class_name = self._class_stack.pop()
        pos = self.get_metadata(PositionProvider, node)

        bases = self._class_bases.get(class_name, [])
        abstract_methods = self._abstract_methods.get(class_name, set())

        is_abstract = len(abstract_methods) > 0 or "ABC" in bases or "abc.ABC" in bases

        qualified_name = (
            ".".join(self._class_stack + [class_name]) if self._class_stack else class_name
        )

        self.classes.append(
            ClassDef(
                name=class_name,
                qualified_name=qualified_name,
                file=self.file_path,
                line=pos.start.line,
                bases=bases,
                is_abstract=is_abstract,
                abstract_methods=abstract_methods,
            )
        )

    def visit_FunctionDef(self, node: cst.FunctionDef) -> bool:
        pos = self.get_metadata(PositionProvider, node)
        func_name = node.name.value

        is_method = len(self._class_stack) > 0
        class_name = self._class_stack[-1] if is_method else None

        if is_method:
            qualified_name = ".".join(self._class_stack + [func_name])
        else:
            qualified_name = func_name

        is_async = isinstance(node.asynchronous, cst.Asynchronous)

        return_type: str | None = None
        if node.returns is not None:
            return_type = self._get_name_from_expr(node.returns.annotation)
            if return_type:
                full_qualified = f"{self.relative_path}::{qualified_name}"
                self.return_types[full_qualified] = return_type

        if is_method and class_name:
            is_abstract = self._is_abstract_method(node)
            if is_abstract:
                self._abstract_methods[class_name].add(func_name)

        self.functions.append(
            FunctionDef(
                name=func_name,
                qualified_name=qualified_name,
                file=self.file_path,
                line=pos.start.line,
                is_method=is_method,
                is_async=is_async,
                class_name=class_name,
                return_type=return_type,
            )
        )

        caller_qualified = f"{self.relative_path}::{qualified_name}"
        self._extract_depends_calls(node.params, func_name, caller_qualified, pos.start.line)

        self._function_stack.append(func_name)
        self._local_types.clear()
        return True

    def _is_abstract_method(self, node: cst.FunctionDef) -> bool:
        """Check if a method is abstract."""
        if self._has_abstractmethod_decorator(node):
            return True

        if self._is_raise_not_implemented(node.body):
            return True

        if self._is_pass_or_ellipsis(node.body):
            return True

        return False

    def _has_abstractmethod_decorator(self, node: cst.FunctionDef) -> bool:
        """Check for @abstractmethod or @abc.abstractmethod decorator."""
        for decorator in node.decorators:
            if isinstance(decorator.decorator, cst.Name):
                if decorator.decorator.value == "abstractmethod":
                    return True
            elif isinstance(decorator.decorator, cst.Attribute):
                if decorator.decorator.attr.value == "abstractmethod":
                    return True
        return False

    def _is_raise_not_implemented(self, body: cst.BaseSuite) -> bool:
        """Check if method body ends with 'raise NotImplementedError'.

        Allows a docstring before the raise statement.
        """
        if not isinstance(body, cst.IndentedBlock):
            return False

        stmts = [s for s in body.body if not isinstance(s, cst.EmptyLine)]
        if not stmts:
            return False

        last_stmt = stmts[-1]
        if not isinstance(last_stmt, cst.SimpleStatementLine):
            return False

        if len(last_stmt.body) != 1:
            return False

        inner = last_stmt.body[0]
        if not isinstance(inner, cst.Raise):
            return False

        if inner.exc is None:
            return False

        exc_name = None
        if isinstance(inner.exc, cst.Name):
            exc_name = inner.exc.value
        elif isinstance(inner.exc, cst.Call):
            if isinstance(inner.exc.func, cst.Name):
                exc_name = inner.exc.func.value

        return exc_name == "NotImplementedError"

    def _is_pass_or_ellipsis(self, body: cst.BaseSuite) -> bool:
        """Check if method body is just 'pass' or '...'."""
        if not isinstance(body, cst.IndentedBlock):
            return False

        stmts = [s for s in body.body if not isinstance(s, cst.EmptyLine)]
        if len(stmts) != 1:
            return False

        stmt = stmts[0]
        if not isinstance(stmt, cst.SimpleStatementLine):
            return False

        if len(stmt.body) != 1:
            return False

        inner = stmt.body[0]

        if isinstance(inner, cst.Pass):
            return True

        if isinstance(inner, cst.Expr) and isinstance(inner.value, cst.Ellipsis):
            return True

        return False

    def leave_FunctionDef(self, node: cst.FunctionDef) -> None:
        self._function_stack.pop()
        self._local_types.clear()

    def visit_Raise(self, node: cst.Raise) -> bool:
        pos = self.get_metadata(PositionProvider, node)

        if self._function_stack:
            if self._class_stack:
                qualified_function = ".".join(self._class_stack + [self._function_stack[-1]])
            else:
                qualified_function = self._function_stack[-1]
        else:
            qualified_function = "<module>"

        is_bare_raise = node.exc is None

        exception_type = "Unknown"
        message_expr: str | None = None
        code = ""

        if node.exc is not None:
            code = cst.parse_module("").code_for_node(node)

            if isinstance(node.exc, cst.Call):
                exception_type = self._get_name_from_expr(node.exc.func)
                if node.exc.args:
                    first_arg = node.exc.args[0].value
                    if isinstance(
                        first_arg, cst.SimpleString | cst.FormattedString | cst.ConcatenatedString
                    ):
                        message_expr = cst.parse_module("").code_for_node(first_arg)
            elif isinstance(node.exc, cst.Name):
                exception_type = node.exc.value

        self.raise_sites.append(
            RaiseSite(
                file=self.relative_path,
                line=pos.start.line,
                function=qualified_function,
                exception_type=exception_type,
                is_bare_raise=is_bare_raise,
                code=code.strip(),
                message_expr=message_expr,
            )
        )

        return True

    def visit_Try(self, node: cst.Try) -> bool:
        self.get_metadata(PositionProvider, node)

        if self._function_stack:
            if self._class_stack:
                qualified_function = ".".join(self._class_stack + [self._function_stack[-1]])
            else:
                qualified_function = self._function_stack[-1]
        else:
            qualified_function = "<module>"

        for handler in node.handlers:
            caught_types: list[str] = []
            has_bare_except = False

            if handler.type is None:
                has_bare_except = True
            elif isinstance(handler.type, cst.Tuple):
                for el in handler.type.elements:
                    if isinstance(el.value, cst.Name | cst.Attribute):
                        name = self._get_name_from_expr(el.value)
                        if name:
                            caught_types.append(name)
            else:
                name = self._get_name_from_expr(handler.type)
                if name:
                    caught_types.append(name)

            has_reraise = self._block_has_reraise(handler.body)

            handler_pos = self.get_metadata(PositionProvider, handler)

            self.catch_sites.append(
                CatchSite(
                    file=self.relative_path,
                    line=handler_pos.start.line,
                    function=qualified_function,
                    caught_types=caught_types,
                    has_bare_except=has_bare_except,
                    has_reraise=has_reraise,
                )
            )

        return True

    def visit_Call(self, node: cst.Call) -> bool:
        pos = self.get_metadata(PositionProvider, node)
        current_function = self._function_stack[-1] if self._function_stack else "<module>"

        caller_qualified = self._get_current_qualified_name()

        callee_name: str
        callee_qualified: str | None = None
        resolution_kind: ResolutionKind = ResolutionKind.UNRESOLVED
        is_method_call = False

        if isinstance(node.func, cst.Attribute):
            callee_name = node.func.attr.value
            is_method_call = True
            base_expr = node.func.value

            if isinstance(base_expr, cst.Name):
                base_name = base_expr.value
                if base_name == "self" and self._class_stack:
                    callee_qualified = (
                        f"{self.relative_path}::{'.'.join(self._class_stack)}.{callee_name}"
                    )
                    resolution_kind = ResolutionKind.SELF
                elif base_name in self._local_types:
                    type_name = self._local_types[base_name]
                    if type_name in self.import_map:
                        callee_qualified = f"{self.import_map[type_name]}.{callee_name}"
                        resolution_kind = ResolutionKind.CONSTRUCTOR
                    else:
                        callee_qualified = f"{self.relative_path}::{type_name}.{callee_name}"
                        resolution_kind = ResolutionKind.CONSTRUCTOR
                elif base_name in self.import_map:
                    module_qualified = self.import_map[base_name]
                    callee_qualified = f"{module_qualified}.{callee_name}"
                    resolution_kind = ResolutionKind.MODULE_ATTRIBUTE
                    is_method_call = False

        elif isinstance(node.func, cst.Name):
            callee_name = node.func.value
            if callee_name in self.import_map:
                callee_qualified = self.import_map[callee_name]
                resolution_kind = ResolutionKind.IMPORT
        else:
            return True

        self.call_sites.append(
            CallSite(
                file=self.file_path,
                line=pos.start.line,
                caller_function=current_function,
                callee_name=callee_name,
                is_method_call=is_method_call,
                caller_qualified=caller_qualified,
                callee_qualified=callee_qualified,
                resolution_kind=resolution_kind,
            )
        )

        return True

    def _get_current_qualified_name(self) -> str:
        """Get the fully qualified name of the current context."""
        parts = [self.relative_path]
        if self._class_stack:
            parts.append(".".join(self._class_stack))
        if self._function_stack:
            parts.append(self._function_stack[-1])
        return "::".join(parts) if len(parts) > 1 else parts[0]

    def _extract_depends_calls(
        self,
        params: cst.Parameters,
        caller_function: str,
        caller_qualified: str,
        line: int,
    ) -> None:
        """Extract FastAPI Depends() declarations from function parameters."""
        all_params = list(params.params) + list(params.kwonly_params)

        for param in all_params:
            if param.default is None:
                continue

            dep_info = self._parse_depends(param.default)
            if dep_info:
                self.call_sites.append(
                    CallSite(
                        file=self.file_path,
                        line=line,
                        caller_function=caller_function,
                        callee_name=dep_info["name"],
                        is_method_call=False,
                        caller_qualified=caller_qualified,
                        callee_qualified=dep_info.get("qualified"),
                        resolution_kind=ResolutionKind.FASTAPI_DEPENDS,
                    )
                )

    def _parse_depends(self, node: cst.BaseExpression) -> dict[str, str | None] | None:
        """Parse Depends(func) and return dependency info."""
        if not isinstance(node, cst.Call):
            return None

        func_name = self._get_name_from_expr(node.func)
        if func_name not in ("Depends", "fastapi.Depends"):
            return None

        if not node.args:
            return None

        first_arg = node.args[0].value
        dep_name = self._get_name_from_expr(first_arg)
        if not dep_name:
            return None

        qualified = self.import_map.get(dep_name)

        return {
            "name": dep_name,
            "qualified": qualified,
        }

    def visit_Assign(self, node: cst.Assign) -> bool:
        """Track variable assignments for constructor resolution."""
        if not isinstance(node.value, cst.Call):
            return True

        call = node.value
        if not isinstance(call.func, cst.Name):
            return True

        type_name = call.func.value

        for target in node.targets:
            if isinstance(target.target, cst.Name):
                var_name = target.target.value
                self._local_types[var_name] = type_name

        return True

    def visit_AnnAssign(self, node: cst.AnnAssign) -> bool:
        """Track annotated assignments for type resolution."""
        if node.target is None or not isinstance(node.target, cst.Name):
            return True

        var_name = node.target.value

        if node.annotation and node.annotation.annotation:
            type_name = self._get_name_from_expr(node.annotation.annotation)
            if type_name:
                self._local_types[var_name] = type_name

        if node.value and isinstance(node.value, cst.Call):
            call = node.value
            if isinstance(call.func, cst.Name):
                self._local_types[var_name] = call.func.value

        return True

    def _get_name_from_expr(self, expr: cst.BaseExpression) -> str:
        """Extract a name from an expression (handles Name and Attribute)."""
        if isinstance(expr, cst.Name):
            return expr.value
        elif isinstance(expr, cst.Attribute):
            base = self._get_name_from_expr(expr.value)
            if base:
                return f"{base}.{expr.attr.value}"
            return expr.attr.value
        return ""

    def _detect_framework(self, module_name: str) -> None:
        """Detect frameworks from import module names."""
        module_lower = module_name.lower()
        if "flask" in module_lower:
            self.detected_frameworks.add("flask")
        elif "fastapi" in module_lower or "starlette" in module_lower:
            self.detected_frameworks.add("fastapi")
        elif "django" in module_lower or "rest_framework" in module_lower:
            self.detected_frameworks.add("django")

    def _block_has_reraise(self, body: cst.BaseSuite) -> bool:
        """Check if a block contains a raise statement (re-raise)."""
        if isinstance(body, cst.IndentedBlock):
            for stmt in body.body:
                if isinstance(stmt, cst.SimpleStatementLine):
                    for s in stmt.body:
                        if isinstance(s, cst.Raise):
                            return True
        return False


class FileExtraction:
    """Results from extracting a single file."""

    def __init__(self) -> None:
        self.functions: list[FunctionDef] = []
        self.classes: list[ClassDef] = []
        self.raise_sites: list[RaiseSite] = []
        self.catch_sites: list[CatchSite] = []
        self.call_sites: list[CallSite] = []
        self.imports: list[ImportInfo] = []
        self.entrypoints: list[Entrypoint] = []
        self.global_handlers: list[GlobalHandler] = []
        self.import_map: dict[str, str] = {}
        self.return_types: dict[str, str] = {}
        self.detected_frameworks: set[str] = set()


def extract_from_file(file_path: Path, relative_path: str | None = None) -> FileExtraction:
    """Extract structural information from a single Python file."""
    result = FileExtraction()

    try:
        source = file_path.read_text()
        module = cst.parse_module(source)
    except Exception:
        return result

    wrapper = MetadataWrapper(module)
    extractor = CodeExtractor(str(file_path), relative_path)

    try:
        wrapper.visit(extractor)
    except Exception:
        return result

    result.functions = extractor.functions
    result.classes = extractor.classes
    result.raise_sites = extractor.raise_sites
    result.catch_sites = extractor.catch_sites
    result.call_sites = extractor.call_sites
    result.imports = extractor.imports
    result.import_map = extractor.import_map
    result.return_types = extractor.return_types
    result.detected_frameworks = extractor.detected_frameworks

    try:
        result.entrypoints = detect_entrypoints(source, str(file_path))
    except Exception:
        pass

    try:
        result.global_handlers = detect_global_handlers(source, str(file_path))
    except Exception:
        pass

    return result


def _should_exclude(path_str: str, exclude_dirs: Sequence[str]) -> bool:
    """Check if a path should be excluded based on directory names."""
    parts = path_str.split("/")
    for part in parts:
        if part in exclude_dirs:
            return True
        if part.startswith(".") and part != ".":
            return True
    return False


DRF_HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
DRF_ACTION_METHODS = {"list", "create", "retrieve", "update", "partial_update", "destroy"}
DRF_DISPATCH_METHODS = DRF_HTTP_METHODS | DRF_ACTION_METHODS


def _extract_single_file(
    file_path: Path,
    relative_path: str,
    cache: "FileCache | None",
) -> tuple[str, FileExtraction]:
    """Extract from a single file, using cache if available.

    This function is designed to be called from a ThreadPoolExecutor.
    """
    extraction = None
    if cache:
        extraction = cache.get(file_path)

    if extraction is None:
        extraction = extract_from_file(file_path, relative_path)

    return (relative_path, extraction)


def _inject_drf_dispatch_calls(model: ProgramModel) -> None:
    """Inject synthetic call edges for Django/DRF class-based view dispatch.

    When a DRF view class is detected as an entrypoint, this creates CallSite
    entries from the view class to each HTTP method handler (get, post, etc.)
    that exists on the class.
    """
    drf_view_entrypoints = [
        ep
        for ep in model.entrypoints
        if ep.metadata.get("framework") == "django" and ep.metadata.get("view_type") == "class"
    ]

    for entrypoint in drf_view_entrypoints:
        view_class = entrypoint.function
        view_file = entrypoint.file
        view_line = entrypoint.line

        for _func_key, func_def in model.functions.items():
            if not func_def.is_method:
                continue
            if func_def.class_name != view_class:
                continue
            if func_def.name not in DRF_DISPATCH_METHODS:
                continue

            relative_file = view_file
            if "/" in relative_file or "\\" in relative_file:
                pass
            else:
                for key in model.functions:
                    if view_class in key and func_def.name in key:
                        parts = key.split(":")
                        if parts:
                            relative_file = parts[0]
                        break

            caller_qualified = f"{relative_file}::{view_class}"
            callee_qualified = f"{relative_file}::{view_class}.{func_def.name}"

            model.call_sites.append(
                CallSite(
                    file=view_file,
                    line=view_line,
                    caller_function=view_class,
                    callee_name=func_def.name,
                    is_method_call=True,
                    caller_qualified=caller_qualified,
                    callee_qualified=callee_qualified,
                    resolution_kind=ResolutionKind.IMPLICIT_DISPATCH,
                )
            )


def extract_from_directory(
    directory: Path,
    exclude_dirs: Sequence[str] | None = None,
    use_cache: bool = True,
) -> ProgramModel:
    """Extract structural information from all Python files in a directory."""
    from flow.cache import FileCache

    if exclude_dirs is None:
        exclude_dirs = [
            "__pycache__",
            ".venv",
            "venv",
            "site-packages",
            "node_modules",
            ".git",
            "dist",
            "build",
            "tests",
            "test",
        ]

    model = ProgramModel()

    custom_detectors = load_detectors(directory)

    cache = None
    if use_cache:
        cache = FileCache(directory / ".flow")

    python_files = list(directory.rglob("*.py"))

    work_items: list[tuple[Path, str]] = []
    for file_path in python_files:
        relative_path = file_path.relative_to(directory)
        path_str = str(relative_path)
        if not _should_exclude(path_str, exclude_dirs):
            work_items.append((file_path, path_str))

    extractions: list[tuple[str, FileExtraction]] = []
    cache_misses: list[tuple[Path, str, FileExtraction]] = []

    max_workers = min(32, (os.cpu_count() or 1) + 4)

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_extract_single_file, fp, rp, cache): (fp, rp) for fp, rp in work_items
        }
        for future in as_completed(futures):
            file_path, path_str = futures[future]
            result_path, extraction = future.result()
            extractions.append((result_path, extraction))

            if cache and cache.get(file_path) is None:
                cache_misses.append((file_path, path_str, extraction))

    if cache:
        for file_path, _path_str, extraction in cache_misses:
            cache.put(file_path, extraction)

    for path_str, extraction in extractions:
        for func in extraction.functions:
            key = f"{path_str}:{func.qualified_name}"
            model.functions[key] = func

        for cls in extraction.classes:
            key = f"{path_str}:{cls.qualified_name}"
            model.classes[key] = cls
            model.exception_hierarchy.add_class(cls)

        model.raise_sites.extend(extraction.raise_sites)
        model.catch_sites.extend(extraction.catch_sites)
        model.call_sites.extend(extraction.call_sites)
        model.imports.extend(extraction.imports)
        model.entrypoints.extend(extraction.entrypoints)
        model.global_handlers.extend(extraction.global_handlers)
        model.import_maps[path_str] = extraction.import_map
        model.return_types.update(extraction.return_types)
        model.detected_frameworks.update(extraction.detected_frameworks)

    for file_path, _path_str in work_items:
        if custom_detectors.entrypoint_detectors or custom_detectors.global_handler_detectors:
            try:
                source = file_path.read_text()
                model.entrypoints.extend(
                    custom_detectors.detect_entrypoints(source, str(file_path))
                )
                model.global_handlers.extend(
                    custom_detectors.detect_global_handlers(source, str(file_path))
                )
            except Exception:
                pass

    if cache:
        cache.close()

    _inject_drf_dispatch_calls(model)

    return model
