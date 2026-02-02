"""CLI entrypoint detection (if __name__ == "__main__" blocks)."""

import libcst as cst
from libcst.metadata import MetadataWrapper, PositionProvider

from bubble.enums import EntrypointKind, Framework
from bubble.integrations.base import Entrypoint


class CLIEntrypointVisitor(cst.CSTVisitor):
    """Detects CLI entrypoints (if __name__ == '__main__': blocks)."""

    METADATA_DEPENDENCIES = (PositionProvider,)

    IGNORED_FUNCTIONS = {
        "print",
        "exit",
        "quit",
        "help",
        "input",
        "len",
        "str",
        "int",
        "float",
        "bool",
        "list",
        "dict",
        "set",
        "tuple",
        "open",
        "close",
        "read",
        "write",
        "format",
        "repr",
        "type",
        "isinstance",
        "hasattr",
        "getattr",
        "setattr",
    }

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.entrypoints: list[Entrypoint] = []

    def visit_If(self, node: cst.If) -> bool:
        if not self._is_main_guard(node.test):
            return True

        pos = self.get_metadata(PositionProvider, node)
        called_functions = self._extract_called_functions(node.body)

        if called_functions:
            for func_name in called_functions:
                self.entrypoints.append(
                    Entrypoint(
                        file=self.file_path,
                        function=func_name,
                        line=pos.start.line,
                        kind=EntrypointKind.CLI_SCRIPT,
                        metadata={
                            "guard_line": str(pos.start.line),
                            "framework": Framework.CLI,
                        },
                    )
                )
        else:
            self.entrypoints.append(
                Entrypoint(
                    file=self.file_path,
                    function="<main_block>",
                    line=pos.start.line,
                    kind=EntrypointKind.CLI_SCRIPT,
                    metadata={
                        "guard_line": str(pos.start.line),
                        "framework": Framework.CLI,
                        "inline": "True",
                    },
                )
            )

        return False

    def _is_main_guard(self, test: cst.BaseExpression) -> bool:
        if not isinstance(test, cst.Comparison):
            return False

        if not isinstance(test.left, cst.Name):
            return False
        if test.left.value != "__name__":
            return False

        if len(test.comparisons) != 1:
            return False

        comp = test.comparisons[0]
        if not isinstance(comp.operator, cst.Equal):
            return False

        if isinstance(comp.comparator, cst.SimpleString):
            value = comp.comparator.evaluated_value
            return value == "__main__"

        return False

    def _extract_called_functions(self, body: cst.BaseSuite) -> list[str]:
        functions: list[str] = []
        seen: set[str] = set()

        if isinstance(body, cst.IndentedBlock):
            for stmt in body.body:
                if isinstance(stmt, cst.SimpleStatementLine):
                    for item in stmt.body:
                        if isinstance(item, cst.Expr) and isinstance(item.value, cst.Call):
                            func_name = self._get_call_name(item.value)
                            if (
                                func_name
                                and func_name not in self.IGNORED_FUNCTIONS
                                and func_name not in seen
                            ):
                                functions.append(func_name)
                                seen.add(func_name)

        return functions

    def _get_call_name(self, call: cst.Call) -> str:
        if isinstance(call.func, cst.Name):
            return call.func.value
        elif isinstance(call.func, cst.Attribute):
            return call.func.attr.value
        return ""


def detect_cli_entrypoints(source: str, file_path: str) -> list[Entrypoint]:
    """Detect CLI entrypoints in a Python source file."""
    try:
        module = cst.parse_module(source)
    except Exception:
        return []

    wrapper = MetadataWrapper(module)
    visitor = CLIEntrypointVisitor(file_path)

    try:
        wrapper.visit(visitor)
        return visitor.entrypoints
    except Exception:
        return []
