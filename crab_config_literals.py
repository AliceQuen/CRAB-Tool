#!/usr/bin/env python3
"""Parse and emit declarative CRAB configuration files without executing them."""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from pprint import pformat
from typing import Any


_MISSING = object()


@dataclass
class ParsedCrabConfig:
    """Literal CRAB config represented as section-ordered field assignments."""

    section_order: list[str] = field(default_factory=list)
    assignments: dict[str, dict[str, Any]] = field(default_factory=dict)

    def ensure_section(self, section: str) -> None:
        if section not in self.section_order:
            self.section_order.append(section)
        self.assignments.setdefault(section, {})

    def set_field(self, section: str, field_name: str, value: Any) -> None:
        self.ensure_section(section)
        self.assignments[section][field_name] = value

    def get_field(
        self, section: str, field_name: str, default: Any = _MISSING
    ) -> Any:
        if section in self.assignments and field_name in self.assignments[section]:
            return self.assignments[section][field_name]
        if default is _MISSING:
            raise KeyError(f"Missing config.{section}.{field_name}")
        return default

    def clone(self) -> "ParsedCrabConfig":
        clone = ParsedCrabConfig(section_order=list(self.section_order))
        for section, fields in self.assignments.items():
            clone.assignments[section] = dict(fields)
        return clone


def render_template(template: str, replacements: dict[str, str]) -> str:
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(key, str(value))
    return rendered


def _is_docstring_expr(node: ast.stmt) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    )


def _is_config_initializer(node: ast.stmt) -> bool:
    if not isinstance(node, ast.Assign) or len(node.targets) != 1:
        return False
    target = node.targets[0]
    if not isinstance(target, ast.Name) or target.id != "config":
        return False
    call = node.value
    if not isinstance(call, ast.Call) or call.args or call.keywords:
        return False
    return isinstance(call.func, ast.Name) and call.func.id in {"Configuration", "config"}


def _section_name_from_call(node: ast.stmt) -> str | None:
    if not isinstance(node, ast.Expr):
        return None
    call = node.value
    if not isinstance(call, ast.Call) or len(call.args) != 1 or call.keywords:
        return None
    if not (
        isinstance(call.func, ast.Attribute)
        and isinstance(call.func.value, ast.Name)
        and call.func.value.id == "config"
        and call.func.attr == "section_"
    ):
        return None
    arg = call.args[0]
    if not isinstance(arg, ast.Constant) or not isinstance(arg.value, str):
        raise ValueError("config.section_() must take a string literal.")
    return str(arg.value)


def _assignment_target(node: ast.stmt) -> tuple[str, str] | None:
    if not isinstance(node, ast.Assign) or len(node.targets) != 1:
        return None
    target = node.targets[0]
    if not (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Attribute)
        and isinstance(target.value.value, ast.Name)
        and target.value.value.id == "config"
    ):
        return None
    return str(target.value.attr), str(target.attr)


def _unsupported_syntax_error(source_name: str, node: ast.AST) -> ValueError:
    line = getattr(node, "lineno", "?")
    return ValueError(
        "Unsupported CRAB config syntax in "
        f"{source_name}:{line}. Only imports, config initialization, "
        "config.section_(...), and direct literal assignments to "
        "config.<Section>.<field> are supported."
    )


def parse_literal_crab_config(
    source_text: str, *, source_name: str = "<string>"
) -> ParsedCrabConfig:
    tree = ast.parse(source_text, filename=source_name)
    parsed = ParsedCrabConfig()

    for node in tree.body:
        if _is_docstring_expr(node) or isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if _is_config_initializer(node):
            continue

        section_name = _section_name_from_call(node)
        if section_name is not None:
            parsed.ensure_section(section_name)
            continue

        target = _assignment_target(node)
        if target is not None:
            section, field_name = target
            try:
                value = ast.literal_eval(node.value)
            except Exception as exc:
                line = getattr(node, "lineno", "?")
                raise ValueError(
                    "Unsupported non-literal value in "
                    f"{source_name}:{line} for config.{section}.{field_name}: {exc}"
                ) from exc
            parsed.set_field(section, field_name, value)
            continue

        raise _unsupported_syntax_error(source_name, node)

    return parsed


def parse_literal_crab_config_file(cfg_path: Path) -> ParsedCrabConfig:
    return parse_literal_crab_config(cfg_path.read_text(), source_name=str(cfg_path))


def load_cfg_metadata_via_literals(cfg_path: Path) -> dict[str, Any]:
    parsed = parse_literal_crab_config_file(cfg_path)
    request_name = parsed.get_field("General", "requestName")
    units_per_job = parsed.get_field("Data", "unitsPerJob")
    return {
        "request_name": str(request_name),
        "units_per_job": int(units_per_job),
        "publication_enabled": bool(parsed.get_field("Data", "publication", False)),
        "output_dataset_tag": parsed.get_field("Data", "outputDatasetTag", None),
        "lumi_mask": parsed.get_field("Data", "lumiMask", None),
        "parsed_config": parsed,
    }


def merge_literal_assignments(
    base: ParsedCrabConfig, overrides: ParsedCrabConfig
) -> ParsedCrabConfig:
    merged = base.clone()
    for section in overrides.section_order:
        merged.ensure_section(section)
        for field_name, value in overrides.assignments.get(section, {}).items():
            merged.set_field(section, field_name, value)
    return merged


def _format_python_literal(value: Any) -> str:
    formatted = pformat(value, width=88, sort_dicts=False)
    if "\n" not in formatted:
        return formatted
    lines = formatted.splitlines()
    return lines[0] + "\n" + "\n".join("    " + line for line in lines[1:])


def emit_wmcore_crab_config(parsed: ParsedCrabConfig) -> str:
    lines = [
        "from WMCore.Configuration import Configuration",
        "",
        "config = Configuration()",
        "",
    ]
    for section in parsed.section_order:
        lines.append(f'config.section_("{section}")')
        for field_name, value in parsed.assignments.get(section, {}).items():
            lines.append(
                f"config.{section}.{field_name} = {_format_python_literal(value)}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
