import re
from dataclasses import dataclass, replace
from typing import Literal

from app.services.function_analysis import (
    FunctionParameter,
    TemplateArgument,
    TemplateParameter,
    ValueType,
    _brace_depths,
    _mask_non_code,
    _parse_parameters,
    _parse_value_type,
    _parse_template_parameters,
    _replace_template_names,
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
    is_virtual: bool = False
    is_pure_virtual: bool = False
    is_override: bool = False
    is_final: bool = False
    overrides_method_id: str | None = None
    override_mismatch_reason: str | None = None


@dataclass(frozen=True)
class OperatorParameter:
    name: str
    display_type: str
    value_type: ValueType | None = None
    object_class_id: str | None = None
    is_stream: bool = False


@dataclass(frozen=True)
class ObjectOperator:
    id: str
    symbol: str
    display: str
    kind: Literal["member", "standalone"]
    declaring_class_id: str | None
    parameters: tuple[OperatorParameter, ...]
    return_display_type: str
    return_value_type: ValueType | None
    return_object_class_id: str | None
    return_kind: Literal[
        "value", "object_value", "mutation_reference", "stream_reference"
    ]
    is_const: bool


@dataclass(frozen=True)
class ObjectSpecialMember:
    id: str
    kind: Literal[
        "copy_constructor",
        "copy_assignment",
        "move_constructor",
        "move_assignment",
        "destructor",
    ]
    display: str
    is_defaulted: bool = False


@dataclass(frozen=True)
class ObjectClass:
    id: str
    name: str
    kind: Literal["class", "struct"]
    constructors: tuple[ObjectConstructor, ...]
    methods: tuple[ObjectMethod, ...]
    operators: tuple[ObjectOperator, ...] = ()
    special_members: tuple[ObjectSpecialMember, ...] = ()
    base_class_id: str | None = None
    inheritance_access: str | None = None
    inheritance_supported: bool = True
    is_abstract: bool = False
    has_virtual_destructor: bool = False
    derived_class_ids: tuple[str, ...] = ()
    inheritance_depth: int = 0
    template_kind: Literal["none", "class_template"] = "none"
    template_parameters: tuple[TemplateParameter, ...] = ()
    effective_template_arguments: tuple[TemplateArgument, ...] = ()
    concrete_type: str | None = None
    template_body: str | None = None


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
_OPERATOR_PREFIX = re.compile(
    r"(?P<return_type>.+?)\s+operator\s*"
    r"(?P<symbol><=>|<<|\+=|-=|\*=|==|!=|<=|>=|\+|-|\*|/|<|>|\[\]|\(\))$"
)
_SUPPORTED_OPERATORS = {
    "+", "-", "*", "/", "+=", "-=", "*=", "==", "!=", "<", "<=", ">",
    ">=", "[]", "()", "<<",
}
_PURE_VIRTUAL_METHOD = re.compile(
    r"(?:^|[;:])\s*"
    r"(?P<prefix>virtual\s+[^;{}()]+?\s+[A-Za-z_]\w*)\s*"
    r"\((?P<parameters>[^()]*)\)\s*"
    r"(?P<suffix>(?:const\s*)?(?:override\s*)?(?:final\s*)?)"
    r"=\s*0\s*;"
)
_PUBLIC_INHERITANCE = re.compile(
    r"^\s*:\s*(?P<access>public|protected|private)\s+"
    r"(?P<base>[A-Za-z_]\w*)\s*$"
)


def _operator_parameter(
    source: str,
    class_names: set[str],
    *,
    unqualified_types_allowed: bool,
) -> OperatorParameter | None:
    normalized = " ".join(source.strip().split())
    match = re.fullmatch(
        r"(?P<type>.+?)(?P<name>[A-Za-z_]\w*)", normalized
    )
    if match is None:
        return None
    raw_type = match.group("type").strip()
    name = match.group("name")
    compact = re.sub(r"\s+", "", raw_type)
    if compact in {"std::ostream&", "ostream&"}:
        return OperatorParameter(
            name=name,
            display_type=raw_type,
            is_stream=True,
        )
    base = compact.replace("const", "").replace("&", "")
    if "*" not in compact and base in class_names:
        return OperatorParameter(
            name=name,
            display_type=raw_type,
            object_class_id=base,
        )
    parsed, _ = _parse_parameters(
        f"{raw_type} {name}",
        unqualified_vector_allowed=unqualified_types_allowed,
    )
    if parsed is None or len(parsed) != 1:
        return None
    return OperatorParameter(
        name=name,
        display_type=raw_type,
        value_type=parsed[0].value_type,
    )


def _operator_return(
    source: str,
    class_names: set[str],
    *,
    unqualified_types_allowed: bool,
) -> tuple[
    str,
    ValueType | None,
    str | None,
    Literal[
        "value", "object_value", "mutation_reference", "stream_reference"
    ],
] | None:
    raw = " ".join(source.strip().split())
    compact = re.sub(r"\s+", "", raw)
    if compact in {"std::ostream&", "ostream&"}:
        return raw, None, None, "stream_reference"
    base = compact.replace("const", "").replace("&", "")
    if "*" in compact:
        return None
    if base in class_names:
        return (
            raw,
            None,
            base,
            "mutation_reference" if "&" in compact else "object_value",
        )
    value_type, _ = _parse_value_type(
        raw,
        allow_reference=True,
        unqualified_vector_allowed=unqualified_types_allowed,
    )
    if value_type is None:
        return None
    return raw, value_type, None, "value"


def _operator_shape_supported(
    symbol: str,
    kind: Literal["member", "standalone"],
    parameters: tuple[OperatorParameter, ...],
    return_kind: str,
) -> bool:
    if symbol in {"+=", "-=", "*="}:
        return (
            kind == "member"
            and len(parameters) == 1
            and return_kind == "mutation_reference"
        )
    if return_kind == "mutation_reference":
        return False
    if symbol == "<<":
        return (
            kind == "standalone"
            and len(parameters) == 2
            and parameters[0].is_stream
            and parameters[1].object_class_id is not None
            and return_kind == "stream_reference"
        )
    if return_kind == "stream_reference":
        return False
    if symbol == "[]":
        return (
            kind == "member"
            and len(parameters) == 1
            and parameters[0].value_type is not None
            and parameters[0].value_type.scalar_type
            in {"int", "long", "long long"}
        )
    if symbol == "()":
        return kind == "member"
    return len(parameters) == (1 if kind == "member" else 2)
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


def _split_parameters(source: str) -> list[str]:
    if not source.strip():
        return []
    parts: list[str] = []
    start = 0
    angle = square = parenthesis = 0
    for index, character in enumerate(source):
        if character == "<":
            angle += 1
        elif character == ">":
            angle = max(0, angle - 1)
        elif character == "[":
            square += 1
        elif character == "]":
            square = max(0, square - 1)
        elif character == "(":
            parenthesis += 1
        elif character == ")":
            parenthesis = max(0, parenthesis - 1)
        elif character == "," and not (angle or square or parenthesis):
            parts.append(source[start:index].strip())
            start = index + 1
    parts.append(source[start:].strip())
    return parts


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


def _special_member(
    class_name: str,
    prefix: str,
    parameters_source: str,
    suffix: str,
) -> ObjectSpecialMember | None:
    compact_parameters = re.sub(r"\s+", "", parameters_source)
    normalized_prefix = re.sub(r"\s+", "", prefix)
    is_defaulted = bool(re.search(r"=\s*default\b", suffix))
    if re.search(r"=\s*delete\b", suffix):
        return None
    kind: Literal[
        "copy_constructor",
        "copy_assignment",
        "move_constructor",
        "move_assignment",
        "destructor",
    ] | None = None
    display = ""
    if normalized_prefix == class_name:
        if re.fullmatch(
            rf"const{re.escape(class_name)}&(?:[A-Za-z_]\w*)?",
            compact_parameters,
        ):
            kind = "copy_constructor"
            display = f"{class_name}::{class_name}(const {class_name}&)"
        elif re.fullmatch(
            rf"{re.escape(class_name)}&&(?:[A-Za-z_]\w*)?",
            compact_parameters,
        ):
            kind = "move_constructor"
            display = f"{class_name}::{class_name}({class_name}&&)"
    elif normalized_prefix in {
        f"{class_name}&operator=",
        f"{class_name}const&operator=",
    }:
        if re.fullmatch(
            rf"const{re.escape(class_name)}&(?:[A-Za-z_]\w*)?",
            compact_parameters,
        ):
            kind = "copy_assignment"
            display = (
                f"{class_name}& {class_name}::operator=(const {class_name}&)"
            )
        elif re.fullmatch(
            rf"{re.escape(class_name)}&&(?:[A-Za-z_]\w*)?",
            compact_parameters,
        ):
            kind = "move_assignment"
            display = f"{class_name}& {class_name}::operator=({class_name}&&)"
    elif normalized_prefix == f"~{class_name}" and not compact_parameters:
        kind = "destructor"
        display = f"{class_name}::~{class_name}()"
    if kind is None:
        return None
    return ObjectSpecialMember(
        id=f"{kind}:{display.replace(' ', '')}",
        kind=kind,
        display=display + (" = default" if is_defaulted else ""),
        is_defaulted=is_defaulted,
    )


def _analyze_class_members(
    class_name: str,
    kind: Literal["class", "struct"],
    body: str,
    *,
    unqualified_types_allowed: bool,
    class_names: set[str],
) -> tuple[
    tuple[ObjectConstructor, ...],
    tuple[ObjectMethod, ...],
    tuple[ObjectOperator, ...],
    tuple[ObjectSpecialMember, ...],
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
    operators: list[ObjectOperator] = []
    special_members: list[ObjectSpecialMember] = []
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
        if body[segment_start:position].rstrip().endswith("operator"):
            position = close_parenthesis + 1
            continue
        definition = _find_definition_brace(body, close_parenthesis)
        prefix = " ".join(body[segment_start:position].split())
        access = _member_access_at(labels, position, default_access)
        tail_end = body.find(";", close_parenthesis)
        definition_start = definition[0] if definition else len(body)
        suffix_end = min(
            tail_end if tail_end >= 0 else len(body),
            definition_start,
        )
        declaration_suffix = body[close_parenthesis + 1:suffix_end]
        special_member = _special_member(
            class_name,
            prefix,
            body[position + 1:close_parenthesis],
            declaration_suffix,
        )
        if special_member is not None:
            if (
                access == "public"
                and (
                    definition is not None
                    or special_member.is_defaulted
                    or special_member.kind == "destructor"
                )
            ):
                special_members.append(special_member)
            if definition is not None:
                position = definition[1] + 1
                segment_start = position
            else:
                position = close_parenthesis + 1
            continue
        if definition is None:
            position = close_parenthesis + 1
            continue
        body_start, body_end = definition
        suffix = " ".join(body[close_parenthesis + 1:body_start].split())
        parameters_source = body[position + 1:close_parenthesis]
        position = body_end + 1
        segment_start = position

        is_friend = prefix.startswith("friend ")
        operator_prefix = prefix.removeprefix("friend ").strip()
        operator_match = _OPERATOR_PREFIX.fullmatch(operator_prefix)
        if operator_match is not None:
            symbol = operator_match.group("symbol")
            if symbol not in _SUPPORTED_OPERATORS:
                continue
            if not is_friend and access != "public":
                continue
            raw_parameters = _split_parameters(parameters_source)
            operator_parameters = tuple(
                parameter
                for raw_parameter in raw_parameters
                if (
                    parameter := _operator_parameter(
                        raw_parameter,
                        class_names,
                        unqualified_types_allowed=unqualified_types_allowed,
                    )
                )
                is not None
            )
            if len(operator_parameters) != len(raw_parameters):
                continue
            returned = _operator_return(
                operator_match.group("return_type"),
                class_names,
                unqualified_types_allowed=unqualified_types_allowed,
            )
            if returned is None:
                continue
            return_display, return_value, return_object, return_kind = returned
            kind: Literal["member", "standalone"] = (
                "standalone" if is_friend else "member"
            )
            if not _operator_shape_supported(
                symbol, kind, operator_parameters, return_kind
            ):
                continue
            is_const = bool(re.search(r"\bconst\b", suffix)) and not is_friend
            canonical_parameters = ",".join(
                parameter.display_type.replace(" ", "")
                for parameter in operator_parameters
            )
            const_suffix = " const" if is_const else ""
            operator_id = (
                f"{kind}:{class_name}::operator{symbol}"
                f"({canonical_parameters}){const_suffix}->{return_display.replace(' ', '')}"
            )
            operators.append(
                ObjectOperator(
                    id=operator_id,
                    symbol=symbol,
                    display=(
                        f"operator{symbol}({canonical_parameters})"
                        f"{const_suffix} -> {return_display}"
                    ),
                    kind=kind,
                    declaring_class_id=None if is_friend else class_name,
                    parameters=operator_parameters,
                    return_display_type=return_display,
                    return_value_type=return_value,
                    return_object_class_id=return_object,
                    return_kind=return_kind,
                    is_const=is_const,
                )
            )
            continue
        if (
            access != "public"
            or "static" in prefix.split()
            or prefix.startswith("~")
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

        is_virtual = prefix.startswith("virtual ")
        method_prefix = prefix.removeprefix("virtual ").strip()
        method_match = _METHOD_PREFIX.fullmatch(method_prefix)
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
                is_virtual=is_virtual,
                is_override=bool(re.search(r"\boverride\b", suffix)),
                is_final=bool(re.search(r"\bfinal\b", suffix)),
            )
        )

    for match in _PURE_VIRTUAL_METHOD.finditer(body):
        if depths[match.start()] != 0:
            continue
        if _member_access_at(labels, match.start(), default_access) != "public":
            continue
        prefix = " ".join(match.group("prefix").split())
        method_prefix = prefix.removeprefix("virtual ").strip()
        method_match = _METHOD_PREFIX.fullmatch(method_prefix)
        if method_match is None:
            continue
        parameters, _ = _parse_parameters(
            match.group("parameters"),
            unqualified_vector_allowed=unqualified_types_allowed,
        )
        if parameters is None:
            continue
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
        is_const = bool(re.search(r"\bconst\b", match.group("suffix")))
        canonical_parameters = _canonical_parameters(parameters)
        const_suffix = " const" if is_const else ""
        method_id = (
            f"{class_name}::{method_match.group('name')}"
            f"({canonical_parameters}){const_suffix}"
            f"->{return_type.canonical_type}"
        )
        if any(item.id == method_id for item in methods):
            continue
        methods.append(
            ObjectMethod(
                id=method_id,
                name=method_match.group("name"),
                display=(
                    f"{method_match.group('name')}({canonical_parameters})"
                    f"{const_suffix} -> {return_type.display_type}"
                ),
                parameters=parameters,
                return_value_type=return_type,
                is_const=is_const,
                is_virtual=True,
                is_pure_virtual=True,
                is_override=bool(
                    re.search(r"\boverride\b", match.group("suffix"))
                ),
                is_final=bool(
                    re.search(r"\bfinal\b", match.group("suffix"))
                ),
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
    ambiguous_operator_const_overloads = {
        (
            operator.symbol,
            tuple(parameter.display_type for parameter in operator.parameters),
        )
        for operator in operators
        if operator.kind == "member"
        and any(
            candidate.kind == "member"
            and candidate.symbol == operator.symbol
            and tuple(
                parameter.display_type for parameter in candidate.parameters
            )
            == tuple(
                parameter.display_type for parameter in operator.parameters
            )
            and candidate.is_const != operator.is_const
            for candidate in operators
        )
    }
    operators = [
        operator
        for operator in operators
        if (
            operator.symbol,
            tuple(parameter.display_type for parameter in operator.parameters),
        )
        not in ambiguous_operator_const_overloads
    ]
    duplicate_special_ids = {
        member.id
        for member in special_members
        if sum(
            candidate.id == member.id for candidate in special_members
        )
        > 1
    }
    special_members = [
        member
        for member in special_members
        if member.id not in duplicate_special_ids
    ]
    return (
        tuple(constructors),
        tuple(methods),
        tuple(operators),
        tuple(special_members),
    )


def _analyze_standalone_operators(
    source: str,
    class_names: set[str],
    *,
    unqualified_types_allowed: bool,
) -> tuple[ObjectOperator, ...]:
    depths = _brace_depths(source)
    operators: list[ObjectOperator] = []
    segment_start = 0
    position = 0
    while position < len(source):
        if depths[position] != 0:
            position += 1
            continue
        if source[position] in ";}":
            segment_start = position + 1
            position += 1
            continue
        if source[position] != "(":
            position += 1
            continue
        close_parenthesis = _matching_delimiter(source, position, "(", ")")
        if close_parenthesis is None:
            break
        definition = _find_definition_brace(source, close_parenthesis)
        if definition is None:
            position = close_parenthesis + 1
            continue
        _, body_end = definition
        prefix = " ".join(source[segment_start:position].split())
        operator_match = _OPERATOR_PREFIX.fullmatch(prefix)
        parameters_source = source[position + 1:close_parenthesis]
        position = body_end + 1
        segment_start = position
        if operator_match is None:
            continue
        symbol = operator_match.group("symbol")
        raw_parameters = _split_parameters(parameters_source)
        parameters = tuple(
            parameter
            for raw_parameter in raw_parameters
            if (
                parameter := _operator_parameter(
                    raw_parameter,
                    class_names,
                    unqualified_types_allowed=unqualified_types_allowed,
                )
            )
            is not None
        )
        if len(parameters) != len(raw_parameters):
            continue
        returned = _operator_return(
            operator_match.group("return_type"),
            class_names,
            unqualified_types_allowed=unqualified_types_allowed,
        )
        if returned is None:
            continue
        participating = next(
            (
                parameter.object_class_id
                for parameter in parameters
                if parameter.object_class_id is not None
            ),
            None,
        )
        if participating is None:
            continue
        return_display, return_value, return_object, return_kind = returned
        if not _operator_shape_supported(
            symbol, "standalone", parameters, return_kind
        ):
            continue
        canonical = ",".join(
            parameter.display_type.replace(" ", "") for parameter in parameters
        )
        operators.append(
            ObjectOperator(
                id=(
                    f"standalone:{participating}::operator{symbol}"
                    f"({canonical})->{return_display.replace(' ', '')}"
                ),
                symbol=symbol,
                display=f"operator{symbol}({canonical}) -> {return_display}",
                kind="standalone",
                declaring_class_id=None,
                parameters=parameters,
                return_display_type=return_display,
                return_value_type=return_value,
                return_object_class_id=return_object,
                return_kind=return_kind,
                is_const=False,
            )
        )
    return tuple(operators)


def analyze_object_scenarios(source: str) -> ObjectAnalysis:
    masked = _mask_non_code(source)
    depths = _brace_depths(masked)
    unqualified_types_allowed = bool(
        re.search(r"\busing\s+namespace\s+std\s*;", masked)
    )
    class_names = {
        match.group("name")
        for match in _CLASS_START.finditer(masked)
        if depths[match.start()] == 0
    }
    classes: list[ObjectClass] = []
    rejected_inheritance = False
    rejected_template = False

    for match in _CLASS_START.finditer(masked):
        if depths[match.start()] != 0:
            continue
        template_match = re.search(
            r"template\s*<(?P<parameters>[^<>]*)>\s*$",
            masked[: match.start()],
        )
        template_parameters: tuple[TemplateParameter, ...] = ()
        template_arguments: tuple[TemplateArgument, ...] = ()
        template_kind: Literal["none", "class_template"] = "none"
        if template_match:
            if (
                "..." in template_match.group("parameters")
                or "<" in match.group("header")
                or "requires" in masked[
                    template_match.start():match.start()
                ]
            ):
                rejected_template = True
                continue
            parsed_template, _ = _parse_template_parameters(
                template_match.group("parameters")
            )
            if parsed_template is None:
                rejected_template = True
                continue
            template_parameters = parsed_template
            template_kind = "class_template"
            template_arguments = tuple(
                TemplateArgument(
                    parameter_name=parameter.name,
                    kind=parameter.kind,
                    value=(
                        parameter.default_argument
                        if parameter.default_argument is not None
                        else "int"
                        if parameter.kind == "type"
                        else "1"
                    ),
                    used_default=parameter.default_argument is not None,
                )
                for parameter in template_parameters
            )
        base_class_id = None
        inheritance_access = None
        inheritance_supported = True
        if ":" in match.group("header"):
            inheritance = _PUBLIC_INHERITANCE.fullmatch(
                match.group("header")
            )
            if (
                inheritance is None
                or "," in match.group("header")
                or "virtual" in match.group("header").split()
            ):
                rejected_inheritance = True
                inheritance_supported = False
            else:
                base_class_id = inheritance.group("base")
                inheritance_access = inheritance.group("access")
                if inheritance_access != "public":
                    rejected_inheritance = True
                    inheritance_supported = False
        body_end = _matching_delimiter(masked, match.end() - 1, "{", "}")
        if body_end is None:
            continue
        kind = match.group("kind")
        name = match.group("name")
        raw_body = masked[match.end():body_end]
        member_body = (
            _replace_template_names(
                raw_body,
                {
                    argument.parameter_name: argument.value
                    for argument in template_arguments
                },
            )
            if template_kind == "class_template"
            else raw_body
        )
        constructors, methods, operators, special_members = (
            _analyze_class_members(
            name,
            kind,
            member_body,
            unqualified_types_allowed=unqualified_types_allowed,
            class_names=class_names,
            )
        )
        is_abstract = any(method.is_pure_virtual for method in methods)
        if not constructors and not is_abstract:
            constructors = (
                ObjectConstructor(
                    id=f"{name}::{name}()",
                    display=f"{name}()",
                    parameters=(),
                ),
            )
        if constructors or is_abstract:
            classes.append(
                ObjectClass(
                    id=name,
                    name=name,
                    kind=kind,
                    constructors=constructors,
                    methods=methods,
                    operators=operators,
                    special_members=special_members,
                    base_class_id=base_class_id,
                    inheritance_access=inheritance_access,
                    inheritance_supported=inheritance_supported,
                    is_abstract=is_abstract,
                    has_virtual_destructor=bool(
                        re.search(
                            rf"\bvirtual\s+~{re.escape(name)}\s*\(",
                            masked[match.end():body_end],
                        )
                    ),
                    template_kind=template_kind,
                    template_parameters=template_parameters,
                    effective_template_arguments=template_arguments,
                    concrete_type=(
                        f"{name}<"
                        + ", ".join(
                            argument.value for argument in template_arguments
                        )
                        + ">"
                        if template_arguments
                        else None
                    ),
                    template_body=(
                        raw_body if template_kind == "class_template" else None
                    ),
                )
            )

    by_id = {item.id: item for item in classes}
    resolved: list[ObjectClass] = []
    for object_class in classes:
        base = (
            by_id.get(object_class.base_class_id)
            if object_class.base_class_id
            else None
        )
        missing_base = (
            object_class.base_class_id is not None and base is None
        )
        if missing_base:
            rejected_inheritance = True
        methods = []
        for method in object_class.methods:
            matching = next(
                (
                    candidate
                    for candidate in (base.methods if base else ())
                    if candidate.name == method.name
                    and _canonical_parameters(candidate.parameters)
                    == _canonical_parameters(method.parameters)
                    and candidate.is_const == method.is_const
                ),
                None,
            )
            same_name = next(
                (
                    candidate
                    for candidate in (base.methods if base else ())
                    if candidate.name == method.name
                    and candidate.is_virtual
                ),
                None,
            )
            mismatch_reason = None
            if same_name and matching is None:
                if same_name.is_const != method.is_const:
                    mismatch_reason = "const qualification"
                elif len(same_name.parameters) != len(method.parameters):
                    mismatch_reason = "parameter count"
                elif _canonical_parameters(
                    same_name.parameters
                ) != _canonical_parameters(method.parameters):
                    mismatch_reason = "parameter types"
                elif (
                    same_name.return_value_type.canonical_type
                    != method.return_value_type.canonical_type
                ):
                    mismatch_reason = "return type"
            methods.append(
                replace(
                    method,
                    is_virtual=method.is_virtual
                    or bool(matching and matching.is_virtual),
                    overrides_method_id=(
                        matching.id
                        if matching and matching.is_virtual
                        else None
                    ),
                    override_mismatch_reason=mismatch_reason,
                )
            )
        inherited_pure = {
            (method.name, _canonical_parameters(method.parameters), method.is_const)
            for method in (base.methods if base else ())
            if method.is_pure_virtual
        }
        implemented = {
            (method.name, _canonical_parameters(method.parameters), method.is_const)
            for method in methods
            if not method.is_pure_virtual
        }
        unresolved_pure = inherited_pure - implemented
        depth = (base.inheritance_depth + 1) if base else 0
        resolved.append(
            replace(
                object_class,
                methods=tuple(methods),
                is_abstract=object_class.is_abstract or bool(unresolved_pure),
                inheritance_depth=depth,
                inheritance_supported=(
                    object_class.inheritance_supported and not missing_base
                ),
            )
        )
    classes = [
        replace(
            item,
            derived_class_ids=tuple(
                candidate.id
                for candidate in resolved
                if candidate.base_class_id == item.id
            ),
        )
        for item in resolved
    ]

    message = (
        "Inheritance is unsupported in object scenarios."
        if rejected_inheritance
        else "This advanced class-template form is unsupported."
        if rejected_template
        else None
    )
    standalone = _analyze_standalone_operators(
        masked,
        class_names,
        unqualified_types_allowed=unqualified_types_allowed,
    )
    if standalone:
        classes = [
            replace(
                object_class,
                operators=object_class.operators
                + tuple(
                    operator
                    for operator in standalone
                    if any(
                        parameter.object_class_id == object_class.id
                        for parameter in operator.parameters
                    )
                ),
            )
            for object_class in classes
        ]
    candidate_classes = classes
    classes = [
        object_class
        for object_class in classes
        if object_class.inheritance_supported
        and (
            object_class.methods
            or object_class.operators
            or object_class.base_class_id
            or object_class.derived_class_ids
        )
    ]
    if not classes:
        lifecycle_only = next(
            (
                object_class
                for object_class in candidate_classes
                if object_class.inheritance_supported
                and not (
                    object_class.methods
                    or object_class.operators
                    or object_class.base_class_id
                    or object_class.derived_class_ids
                )
                and object_class.special_members
            ),
            None,
        )
        message = (
            "Inheritance is unsupported in object scenarios."
            if rejected_inheritance
            else "This advanced class-template form is unsupported."
            if rejected_template
            else (
                f"'{lifecycle_only.name}' defines lifecycle operations "
                "(constructor, destructor, copy/move) but has no supported "
                "public instance method to exercise through an object "
                "scenario. Add a public observer or instance method to "
                "make it directly testable."
                if lifecycle_only is not None
                else (
                    "No class or struct with a usable public constructor "
                    "and public instance method was found."
                )
            )
        )
    return ObjectAnalysis(classes=tuple(classes), message=message)


def instantiate_object_template(
    object_class: ObjectClass,
    supplied_arguments: tuple[TemplateArgument, ...],
    *,
    unqualified_types_allowed: bool,
) -> ObjectClass:
    if object_class.template_kind != "class_template":
        if supplied_arguments:
            raise ValueError(
                "Template arguments cannot be used with a non-template class."
            )
        return object_class
    supplied = {
        argument.parameter_name: argument for argument in supplied_arguments
    }
    if len(supplied) != len(supplied_arguments):
        raise ValueError("Template argument names must be unique.")
    resolved: list[TemplateArgument] = []
    replacements: dict[str, str] = {}
    supported_types = {
        "int", "long", "long long", "float", "double", "bool", "char",
        "std::string",
    }
    for parameter in object_class.template_parameters:
        argument = supplied.get(parameter.name)
        value = (
            argument.value
            if argument is not None and not argument.used_default
            else parameter.default_argument
        )
        used_default = (
            argument.used_default if argument is not None else True
        )
        if value is None:
            raise ValueError(
                f"Template argument {parameter.name} is required."
            )
        normalized = " ".join(value.strip().split())
        if parameter.kind == "type":
            if normalized == "string":
                normalized = "std::string"
            if normalized not in supported_types:
                raise ValueError(
                    f"Template type argument {parameter.name} is unsupported."
                )
        elif parameter.non_type_type in {"int", "long", "long long"}:
            if not re.fullmatch(r"[+-]?\d+", normalized):
                raise ValueError(
                    f"Template argument {parameter.name} must be an integer literal."
                )
        elif parameter.non_type_type == "bool":
            if normalized not in {"true", "false"}:
                raise ValueError(
                    f"Template argument {parameter.name} must be true or false."
                )
        elif parameter.non_type_type == "char":
            if not re.fullmatch(r"'(?:[^'\\\\]|\\\\[nrt0'\\\\])'", normalized):
                raise ValueError(
                    f"Template argument {parameter.name} must be a character literal."
                )
        replacements[parameter.name] = normalized
        resolved.append(
            TemplateArgument(
                parameter_name=parameter.name,
                kind=parameter.kind,
                value=normalized,
                used_default=used_default,
            )
        )
    body = _replace_template_names(
        object_class.template_body or "", replacements
    )
    constructors, methods, operators, special_members = _analyze_class_members(
        object_class.name,
        object_class.kind,
        body,
        unqualified_types_allowed=unqualified_types_allowed,
        class_names={object_class.name},
    )
    if not constructors:
        constructors = (
            ObjectConstructor(
                id=f"{object_class.name}::{object_class.name}()",
                display=f"{object_class.name}()",
                parameters=(),
            ),
        )
    concrete = (
        f"{object_class.name}<"
        + ", ".join(argument.value for argument in resolved)
        + ">"
    )
    return replace(
        object_class,
        name=concrete,
        constructors=constructors,
        methods=methods,
        operators=operators,
        special_members=special_members,
        effective_template_arguments=tuple(resolved),
        concrete_type=concrete,
    )
