import re
from dataclasses import dataclass
from typing import Literal

from app.services.function_analysis import (
    FunctionParameter,
    ValueType,
    _brace_depths,
    _mask_non_code,
    _parse_parameters,
    _parse_value_type,
)


@dataclass(frozen=True)
class ObjectConstructor:
    id: str
    display: str
    parameters: tuple[FunctionParameter, ...]


@dataclass(frozen=True)
class ObjectMethod:
    id: str
    name: str
    display: str
    parameters: tuple[FunctionParameter, ...]
    return_value_type: ValueType
    is_const: bool


@dataclass(frozen=True)
class ObjectClass:
    id: str
    name: str
    kind: Literal["class", "struct"]
    constructors: tuple[ObjectConstructor, ...]
    methods: tuple[ObjectMethod, ...]


@dataclass(frozen=True)
class ObjectAnalysis:
    classes: tuple[ObjectClass, ...] = ()
    message: str | None = None


_CLASS_START = re.compile(
    r"\b(?P<kind>class|struct)\s+(?P<name>[A-Za-z_]\w*)"
    r"(?P<header>[^;{}]*)\{"
)
_ACCESS_LABEL = re.compile(r"(public|private|protected)\s*:")
_METHOD_PREFIX = re.compile(
    r"(?P<return_type>.+?)\s+(?P<name>[A-Za-z_]\w*)$"
)
def _matching_delimiter(
    source: str,
    start: int,
    opening: str,
    closing: str,
) -> int | None:
    depth = 0
    for index in range(start, len(source)):
        if source[index] == opening:
            depth += 1
        elif source[index] == closing:
            depth -= 1
            if depth == 0:
                return index
    return None


def _canonical_parameters(parameters: tuple[FunctionParameter, ...]) -> str:
    return ",".join(
        parameter.value_type.canonical_type for parameter in parameters
    )


def _find_definition_brace(
    body: str,
    close_parenthesis: int,
) -> tuple[int, int] | None:
    position = close_parenthesis + 1
    while position < len(body):
        if body.startswith("= delete", position):
            return None
        character = body[position]
        if character == ";":
            return None
        if character == "{":
            close_brace = _matching_delimiter(body, position, "{", "}")
            if close_brace is None:
                return None
            following = close_brace + 1
            while following < len(body) and body[following].isspace():
                following += 1
            if following < len(body) and body[following] in {",", "{"}:
                position = following + (body[following] == ",")
                continue
            return position, close_brace
        position += 1
    return None


def _member_access_at(
    labels: list[tuple[int, str]],
    position: int,
    default_access: str,
) -> str:
    access = default_access
    for label_position, label in labels:
        if label_position >= position:
            break
        access = label
    return access


def _analyze_class_members(
    class_name: str,
    kind: Literal["class", "struct"],
    body: str,
    *,
    unqualified_types_allowed: bool,
) -> tuple[
    tuple[ObjectConstructor, ...],
    tuple[ObjectMethod, ...],
]:
    depths = _brace_depths(body)
    labels = [
        (match.start(), match.group(1))
        for match in _ACCESS_LABEL.finditer(body)
        if depths[match.start()] == 0
    ]
    default_access = "public" if kind == "struct" else "private"
    constructors: list[ObjectConstructor] = []
    methods: list[ObjectMethod] = []
    segment_start = 0
    position = 0

    while position < len(body):
        if depths[position] != 0:
            position += 1
            continue
        access_match = _ACCESS_LABEL.match(body, position)
        if access_match is not None:
            segment_start = access_match.end()
            position = access_match.end()
            continue
        if body[position] in ";}":
            segment_start = position + 1
            position += 1
            continue
        if body[position] != "(":
            position += 1
            continue

        close_parenthesis = _matching_delimiter(body, position, "(", ")")
        if close_parenthesis is None:
            break
        definition = _find_definition_brace(body, close_parenthesis)
        if definition is None:
            position = close_parenthesis + 1
            continue
        body_start, body_end = definition
        prefix = " ".join(body[segment_start:position].split())
        suffix = " ".join(body[close_parenthesis + 1:body_start].split())
        parameters_source = body[position + 1:close_parenthesis]
        access = _member_access_at(labels, position, default_access)
        position = body_end + 1
        segment_start = position

        if (
            access != "public"
            or "static" in prefix.split()
            or "operator" in prefix
            or prefix.startswith("~")
            or "virtual" in prefix.split()
        ):
            continue
        parameters, _ = _parse_parameters(
            parameters_source,
            unqualified_vector_allowed=unqualified_types_allowed,
        )
        if parameters is None:
            continue
        canonical_parameters = _canonical_parameters(parameters)

        constructor_prefix = prefix.removeprefix("explicit ").strip()
        if constructor_prefix == class_name:
            constructor_id = (
                f"{class_name}::{class_name}({canonical_parameters})"
            )
            constructors.append(
                ObjectConstructor(
                    id=constructor_id,
                    display=f"{class_name}({canonical_parameters})",
                    parameters=parameters,
                )
            )
            continue

        method_match = _METHOD_PREFIX.fullmatch(prefix)
        if method_match is None:
            continue
        method_name = method_match.group("name")
        return_type, _ = _parse_value_type(
            method_match.group("return_type"),
            allow_reference=False,
            unqualified_vector_allowed=unqualified_types_allowed,
        )
        if return_type is None:
            if method_match.group("return_type").strip() == "void":
                return_type = ValueType(kind="void", display_type="void")
            else:
                continue
        is_const = bool(re.search(r"\bconst\b", suffix))
        const_suffix = " const" if is_const else ""
        method_id = (
            f"{class_name}::{method_name}({canonical_parameters})"
            f"{const_suffix}->{return_type.canonical_type}"
        )
        methods.append(
            ObjectMethod(
                id=method_id,
                name=method_name,
                display=(
                    f"{method_name}({canonical_parameters})"
                    f"{const_suffix} -> {return_type.display_type}"
                ),
                parameters=parameters,
                return_value_type=return_type,
                is_const=is_const,
            )
        )

    ambiguous_const_overloads = {
        (method.name, _canonical_parameters(method.parameters))
        for method in methods
        if any(
            candidate.name == method.name
            and candidate.parameters == method.parameters
            and candidate.is_const != method.is_const
            for candidate in methods
        )
    }
    methods = [
        method
        for method in methods
        if (
            method.name,
            _canonical_parameters(method.parameters),
        )
        not in ambiguous_const_overloads
    ]
    return tuple(constructors), tuple(methods)


def analyze_object_scenarios(source: str) -> ObjectAnalysis:
    masked = _mask_non_code(source)
    depths = _brace_depths(masked)
    unqualified_types_allowed = bool(
        re.search(r"\busing\s+namespace\s+std\s*;", masked)
    )
    classes: list[ObjectClass] = []
    rejected_inheritance = False

    for match in _CLASS_START.finditer(masked):
        if depths[match.start()] != 0:
            continue
        if ":" in match.group("header"):
            rejected_inheritance = True
            continue
        body_end = _matching_delimiter(masked, match.end() - 1, "{", "}")
        if body_end is None:
            continue
        kind = match.group("kind")
        name = match.group("name")
        constructors, methods = _analyze_class_members(
            name,
            kind,
            masked[match.end():body_end],
            unqualified_types_allowed=unqualified_types_allowed,
        )
        if constructors and methods:
            classes.append(
                ObjectClass(
                    id=name,
                    name=name,
                    kind=kind,
                    constructors=constructors,
                    methods=methods,
                )
            )

    message = None
    if not classes:
        message = (
            "Inheritance is unsupported in object scenarios."
            if rejected_inheritance
            else (
                "No class or struct with a usable public constructor "
                "and public instance method was found."
            )
        )
    return ObjectAnalysis(classes=tuple(classes), message=message)
