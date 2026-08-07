from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from app.services.function_analysis import FunctionSignature, analyze_test_mode
from app.services.object_analysis import (
    ObjectClass,
    ObjectConstructor,
    ObjectMethod,
    analyze_object_scenarios,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AiCapabilityResult:
    supported: bool
    target_kind: Literal["function", "object"] | None
    target_id: str | None
    unsupported_reason: str | None
    unsupported_parameters: tuple[tuple[str, str], ...]
    mutation_capable_parameters: tuple[str, ...]
    exception_support: bool
    iterator_groups: tuple[dict, ...]
    template_kind: str
    requires_explicit_template_arguments: bool
    object_constructors: tuple[str, ...]
    object_methods: tuple[str, ...]
    supported_sibling_targets: tuple[str, ...]


def _function_passes_gate(fn: FunctionSignature) -> bool:
    if not fn.return_value_type.supported:
        return False
    return all(p.value_type.supported for p in fn.parameters)


def _constructor_passes_gate(ctor: ObjectConstructor) -> bool:
    return all(p.value_type.supported for p in ctor.parameters)


def _method_passes_gate(method: ObjectMethod) -> bool:
    if not method.return_value_type.supported:
        return False
    return all(p.value_type.supported for p in method.parameters)


def _unsupported_result(
    target_kind: Literal["function", "object"],
    target_id: str,
    reason: str,
    template_kind: str = "none",
    sibling_targets: tuple[str, ...] = (),
    unsupported_params: tuple[tuple[str, str], ...] = (),
) -> AiCapabilityResult:
    return AiCapabilityResult(
        supported=False,
        target_kind=target_kind,
        target_id=target_id,
        unsupported_reason=reason,
        unsupported_parameters=unsupported_params,
        mutation_capable_parameters=(),
        exception_support=False,
        iterator_groups=(),
        template_kind=template_kind,
        requires_explicit_template_arguments=False,
        object_constructors=(),
        object_methods=(),
        supported_sibling_targets=sibling_targets,
    )


def _assess_function(code: str, target_id: str) -> AiCapabilityResult:
    analysis = analyze_test_mode(code)

    if analysis.mode == "program":
        return _unsupported_result(
            "function",
            target_id,
            "This source contains only a main() program; there are no testable functions.",
        )

    target_fn: FunctionSignature | None = None
    for fn in analysis.functions:
        if fn.id == target_id:
            target_fn = fn
            break

    all_supported_siblings = tuple(
        fn.display
        for fn in analysis.functions
        if fn.id != target_id and _function_passes_gate(fn)
    )

    if target_fn is None:
        return _unsupported_result(
            "function",
            target_id,
            "The selected target no longer exists in the current code.",
            sibling_targets=all_supported_siblings,
        )

    unsupported_params: list[tuple[str, str]] = []
    if not target_fn.return_value_type.supported:
        unsupported_params.append(
            (
                "(return)",
                target_fn.return_value_type.unsupported_reason
                or "Unsupported return type.",
            )
        )
    for param in target_fn.parameters:
        if not param.value_type.supported:
            unsupported_params.append(
                (
                    param.name,
                    param.value_type.unsupported_reason
                    or "Unsupported parameter type.",
                )
            )

    if unsupported_params:
        return _unsupported_result(
            "function",
            target_id,
            unsupported_params[0][1],
            template_kind=target_fn.template_kind,
            sibling_targets=all_supported_siblings,
            unsupported_params=tuple(unsupported_params),
        )

    # Collect mutation-capable parameters
    mutation_capable: list[str] = []
    for param in target_fn.parameters:
        vt = param.value_type
        if vt.passing in {"mutable_reference", "scalar_pointer"}:
            mutation_capable.append(param.name)
        elif (
            vt.kind == "iterator"
            and vt.iterator_const is False
            and vt.iterator_role in {"single", "range_begin"}
        ):
            mutation_capable.append(param.name)

    # Build iterator group metadata (keyed on group_index)
    group_map: dict[int, dict] = {}
    for param in target_fn.parameters:
        vt = param.value_type
        if vt.kind == "iterator" and vt.iterator_group_index is not None:
            idx = vt.iterator_group_index
            if idx not in group_map:
                group_map[idx] = {}
            if vt.iterator_role in {"single", "range_begin"}:
                group_map[idx]["role"] = vt.iterator_role
                group_map[idx]["const"] = vt.iterator_const
                group_map[idx]["container"] = vt.iterator_container
                group_map[idx]["head_param"] = param.name
            elif vt.iterator_role == "range_end":
                group_map[idx]["tail_param"] = param.name

    return AiCapabilityResult(
        supported=True,
        target_kind="function",
        target_id=target_id,
        unsupported_reason=None,
        unsupported_parameters=(),
        mutation_capable_parameters=tuple(mutation_capable),
        exception_support=True,
        iterator_groups=tuple(group_map[k] for k in sorted(group_map)),
        template_kind=target_fn.template_kind,
        requires_explicit_template_arguments=(
            target_fn.template_argument_mode == "explicit"
        ),
        object_constructors=(),
        object_methods=(),
        supported_sibling_targets=all_supported_siblings,
    )


def _assess_object(code: str, target_id: str) -> AiCapabilityResult:
    analysis = analyze_object_scenarios(code)

    target_class: ObjectClass | None = None
    for cls in analysis.classes:
        if cls.id == target_id:
            target_class = cls
            break

    sibling_displays = tuple(
        cls.name
        for cls in analysis.classes
        if cls.id != target_id
        and not cls.is_abstract
        and cls.template_kind == "none"
        and any(_constructor_passes_gate(c) for c in cls.constructors)
        and any(_method_passes_gate(m) for m in cls.methods)
    )

    if target_class is None:
        return _unsupported_result(
            "object",
            target_id,
            "The selected target no longer exists in the current code.",
            sibling_targets=sibling_displays,
        )

    if target_class.is_abstract:
        return _unsupported_result(
            "object",
            target_id,
            "Abstract classes cannot be directly constructed for testing.",
            template_kind=target_class.template_kind,
            sibling_targets=sibling_displays,
        )

    if target_class.template_kind != "none":
        return _unsupported_result(
            "object",
            target_id,
            "Class templates are not supported for AI test generation in v1.",
            template_kind=target_class.template_kind,
            sibling_targets=sibling_displays,
        )

    supported_ctor_ids = tuple(
        c.id for c in target_class.constructors if _constructor_passes_gate(c)
    )
    supported_method_ids = tuple(
        m.id for m in target_class.methods if _method_passes_gate(m)
    )

    if not supported_ctor_ids:
        return _unsupported_result(
            "object",
            target_id,
            "This class has no supported constructors for AI test generation.",
            template_kind=target_class.template_kind,
            sibling_targets=sibling_displays,
        )

    if not supported_method_ids:
        return _unsupported_result(
            "object",
            target_id,
            "This class has no supported methods for AI test generation.",
            template_kind=target_class.template_kind,
            sibling_targets=sibling_displays,
        )

    return AiCapabilityResult(
        supported=True,
        target_kind="object",
        target_id=target_id,
        unsupported_reason=None,
        unsupported_parameters=(),
        mutation_capable_parameters=(),
        exception_support=True,
        iterator_groups=(),
        template_kind=target_class.template_kind,
        requires_explicit_template_arguments=False,
        object_constructors=supported_ctor_ids,
        object_methods=supported_method_ids,
        supported_sibling_targets=sibling_displays,
    )


def assess_ai_capability(
    code: str,
    target_kind: Literal["function", "object"],
    target_id: str,
) -> AiCapabilityResult:
    if target_kind == "function":
        return _assess_function(code, target_id)
    return _assess_object(code, target_id)
