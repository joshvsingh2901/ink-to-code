import re
from dataclasses import dataclass, replace
from typing import Literal

SUPPORTED_SCALAR_TYPES = {
    "int",
    "long",
    "long long",
    "float",
    "double",
    "bool",
    "char",
}
SUPPORTED_VECTOR_ELEMENT_TYPES = {
    "int", "long", "long long", "double", "bool"
}
STRING_TYPE = "std::string"
SUPPORTED_TEMPLATE_TYPE_ARGUMENTS = (
    "int",
    "long",
    "long long",
    "float",
    "double",
    "bool",
    "char",
    STRING_TYPE,
)


@dataclass(frozen=True)
class TemplateParameter:
    name: str
    kind: Literal["type", "non_type"]
    non_type_type: str | None = None
    default_argument: str | None = None


@dataclass(frozen=True)
class TemplateArgument:
    parameter_name: str
    kind: Literal["type", "non_type"]
    value: str
    used_default: bool = False


@dataclass(frozen=True)
class ExplicitFunctionSpecialization:
    primary_template_name: str
    effective_template_arguments: tuple[str, ...]
    return_type: str
    parameter_types: tuple[str, ...]
    source_line: int


@dataclass(frozen=True)
class ValueType:
    kind: Literal["scalar", "vector", "array", "void"]
    display_type: str
    scalar_type: str | None = None
    element_type: str | None = None
    vector_depth: Literal[1, 2] | None = None
    passing: Literal[
        "value",
        "const_reference",
        "mutable_reference",
        "scalar_pointer",
        "array_pointer",
    ] = "value"
    size_parameter_name: str | None = None

    @property
    def canonical_type(self) -> str:
        if self.kind == "void":
            return "void"
        if self.kind == "array":
            return f"{self.element_type}[]"
        if self.kind == "scalar":
            base = self.scalar_type or self.display_type
            if self.passing == "scalar_pointer":
                return f"{base}*"
            if self.passing == "mutable_reference":
                return f"{base}&"
            return (
                f"const {base}&"
                if self.passing == "const_reference"
                else base
            )
        base = f"std::vector<{self.element_type}>"
        if self.vector_depth == 2:
            base = f"std::vector<{base}>"
        if self.passing == "mutable_reference":
            return f"{base}&"
        return (
            f"const {base}&"
            if self.passing == "const_reference"
            else base
        )


@dataclass(frozen=True)
class FunctionParameter:
    name: str
    value_type: ValueType

    @property
    def type(self) -> str:
        return self.value_type.display_type


@dataclass(frozen=True)
class FunctionSignature:
    name: str
    return_value_type: ValueType
    parameters: tuple[FunctionParameter, ...]
    template_kind: Literal[
        "none", "function_template", "explicit_specialization"
    ] = "none"
    template_parameters: tuple[TemplateParameter, ...] = ()
    raw_parameter_types: tuple[str, ...] = ()
    raw_return_type: str | None = None
    explicit_specializations: tuple[ExplicitFunctionSpecialization, ...] = ()
    effective_template_arguments: tuple[TemplateArgument, ...] = ()
    template_argument_mode: Literal["deduced", "explicit"] | None = None
    invocation_name: str | None = None
    source_line: int | None = None

    @property
    def return_type(self) -> str:
        return self.return_value_type.display_type

    @property
    def id(self) -> str:
        if self.template_kind == "function_template":
            template_parameters = ",".join(
                f"{parameter.kind}:{parameter.name}"
                for parameter in self.template_parameters
            )
            parameter_types = ",".join(self.raw_parameter_types)
            return (
                f"template:{self.name}<{template_parameters}>"
                f"({parameter_types})->{self.raw_return_type}"
            )
        parameter_types = ",".join(
            parameter.value_type.canonical_type for parameter in self.parameters
        )
        return (
            f"{self.name}({parameter_types})->"
            f"{self.return_value_type.canonical_type}"
        )

    @property
    def display(self) -> str:
        parameters = ", ".join(
            f"{parameter.type} {parameter.name}" for parameter in self.parameters
        )
        template = (
            "<"
            + ", ".join(
                parameter.name for parameter in self.template_parameters
            )
            + ">"
            if self.template_parameters
            else ""
        )
        return f"{self.name}{template}({parameters})"

    @property
    def concrete_instantiation(self) -> str | None:
        if not self.effective_template_arguments:
            return None
        values = ", ".join(
            argument.value for argument in self.effective_template_arguments
        )
        return f"{self.name}<{values}>"

    @property
    def specialization_selected(self) -> bool:
        effective = tuple(
            argument.value for argument in self.effective_template_arguments
        )
        return any(
            specialization.effective_template_arguments == effective
            for specialization in self.explicit_specializations
        )


@dataclass(frozen=True)
class FunctionAnalysis:
    mode: Literal["program", "function", "unsupported"]
    functions: tuple[FunctionSignature, ...] = ()
    message: str | None = None


_FUNCTION_DEFINITION = re.compile(
    r"(?P<return_type>"
    r"(?:const\s+)?(?:std::)?vector\s*<[^{}();]+>\s*(?:const\s*)?[&*]?"
    r"|(?:const\s+)?(?:std::)?string\s*(?:const\s*)?[&*]?"
    r"|(?:const\s+)?(?:long\s+long|long|int|float|double|bool|char)\s*"
    r"(?:const\s*)?&&?"
    r"|(?:long\s+long|long|int|float|double|bool|char)\s*\*+"
    r"|[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*"
    r")\s+(?P<name>[A-Za-z_]\w*)\s*"
    r"\((?P<parameters>[^()]*)\)\s*(?:noexcept\s*)?\{",
)
_PARAMETER_DECLARATION = re.compile(
    r"(?P<type>.+?)\s+(?P<name>[A-Za-z_]\w*)"
)
_REFERENCE_PARAMETER = re.compile(
    r"(?P<type>"
    r"(?:const\s+)?(?:long\s+long|long|int|double|bool)\s*(?:const\s*)?&&?"
    r"|(?:const\s+)?(?:std::)?string\s*(?:const\s*)?&&?"
    r")\s*(?P<name>[A-Za-z_]\w*)"
)
_SCALAR_REFERENCE_TYPE = re.compile(
    r"(?P<prefix_const>const\s+)?"
    r"(?P<base>long\s+long|long|int|double|bool)\s*"
    r"(?P<suffix_const>const\s*)?(?P<modifier>&&?)"
)
_SCALAR_POINTER_TYPE = re.compile(
    r"(?P<prefix_const>const\s+)?"
    r"(?P<base>long\s+long|long|int|double|bool)\s*"
    r"(?P<suffix_const>const\s*)?(?P<modifier>\*+)"
)
_ARRAY_PARAMETER = re.compile(
    r"(?P<element>long\s+long|long|int|double|bool|char)\s*"
    r"(?:"
    r"(?P<pointers>\*+)\s*(?P<pointer_name>[A-Za-z_]\w*)"
    r"|(?P<array_name>[A-Za-z_]\w*)\s*"
    r"(?P<brackets>(?:\[\s*\])+)"
    r")"
)
_SIZE_PARAMETER_NAMES = {"size", "count", "length", "n", "len"}
_INTEGRAL_TYPES = {"int", "long", "long long"}
_VECTOR_TYPE = re.compile(
    r"(?P<prefix_const>const\s+)?"
    r"(?P<qualified>std::)?vector\s*<\s*(?P<element>.+)\s*>\s*"
    r"(?P<suffix_const>const\s*)?(?P<modifier>[&*])?"
)
_VECTOR_ELEMENT_TYPE = re.compile(
    r"(?P<qualified>std::)?vector\s*<\s*(?P<element>.+)\s*>"
)
_STRING_TYPE = re.compile(
    r"(?P<prefix_const>const\s+)?"
    r"(?P<qualified>std::)?string\s*"
    r"(?P<suffix_const>const\s*)?(?P<modifier>[&*])?"
)


def _mask_non_code(source: str) -> str:
    characters = list(source)
    index = 0
    state = "code"

    while index < len(characters):
        current = characters[index]
        following = characters[index + 1] if index + 1 < len(characters) else ""

        if state == "code":
            if current == "/" and following == "/":
                characters[index] = characters[index + 1] = " "
                state = "line_comment"
                index += 2
                continue
            if current == "/" and following == "*":
                characters[index] = characters[index + 1] = " "
                state = "block_comment"
                index += 2
                continue
            if current == '"':
                characters[index] = " "
                state = "string"
            elif current == "'":
                characters[index] = " "
                state = "character"
        elif state == "line_comment":
            if current == "\n":
                state = "code"
            else:
                characters[index] = " "
        elif state == "block_comment":
            if current == "*" and following == "/":
                characters[index] = characters[index + 1] = " "
                state = "code"
                index += 2
                continue
            if current != "\n":
                characters[index] = " "
        elif state in {"string", "character"}:
            delimiter = '"' if state == "string" else "'"
            if current == "\\" and following:
                characters[index] = " "
                if following != "\n":
                    characters[index + 1] = " "
                index += 2
                continue
            if current == delimiter:
                characters[index] = " "
                state = "code"
            elif current != "\n":
                characters[index] = " "
        index += 1

    return "".join(characters)


def _brace_depths(source: str) -> list[int]:
    depths = [0] * (len(source) + 1)
    depth = 0
    for index, character in enumerate(source):
        depths[index] = depth
        if character == "{":
            depth += 1
        elif character == "}":
            depth = max(depth - 1, 0)
    depths[len(source)] = depth
    return depths


def _parse_value_type(
    raw_type: str,
    *,
    allow_reference: bool,
    unqualified_vector_allowed: bool,
) -> tuple[ValueType | None, str | None]:
    normalized = " ".join(raw_type.split())
    if normalized.endswith("&&"):
        return (
            None,
            "Rvalue reference parameters are unsupported."
            if allow_reference
            else "Reference return values are unsupported.",
        )
    if "*&" in normalized or "* &" in normalized:
        return None, "References to pointers are unsupported."
    scalar_pointer = _SCALAR_POINTER_TYPE.fullmatch(normalized)
    if scalar_pointer is not None:
        if not allow_reference:
            return None, "Pointer return values are unsupported."
        if scalar_pointer.group("modifier") != "*":
            return None, "Pointer-to-pointer parameters are unsupported."
        if (
            scalar_pointer.group("prefix_const")
            or scalar_pointer.group("suffix_const")
        ):
            return None, "Const scalar pointer parameters are unsupported."
        scalar_type = " ".join(scalar_pointer.group("base").split())
        return (
            ValueType(
                kind="scalar",
                display_type=f"{scalar_type}*",
                scalar_type=scalar_type,
                passing="scalar_pointer",
            ),
            None,
        )
    scalar_reference = _SCALAR_REFERENCE_TYPE.fullmatch(normalized)
    if scalar_reference is not None:
        if not allow_reference:
            return None, "Scalar reference return values are unsupported."
        if scalar_reference.group("modifier") == "&&":
            return None, "Rvalue reference parameters are unsupported."
        scalar_type = " ".join(scalar_reference.group("base").split())
        is_const = bool(
            scalar_reference.group("prefix_const")
            or scalar_reference.group("suffix_const")
        )
        passing: Literal["const_reference", "mutable_reference"] = (
            "const_reference" if is_const else "mutable_reference"
        )
        return (
            ValueType(
                kind="scalar",
                display_type=(
                    f"const {scalar_type}&"
                    if is_const
                    else f"{scalar_type}&"
                ),
                scalar_type=scalar_type,
                passing=passing,
            ),
            None,
        )
    if normalized in SUPPORTED_SCALAR_TYPES:
        return (
            ValueType(
                kind="scalar",
                display_type=normalized,
                scalar_type=normalized,
            ),
            None,
        )

    string_match = _STRING_TYPE.fullmatch(normalized)
    if string_match is not None:
        if (
            string_match.group("qualified") is None
            and not unqualified_vector_allowed
        ):
            return (
                None,
                "Unqualified string types require `using namespace std;`.",
            )
        modifier = string_match.group("modifier")
        is_const = bool(
            string_match.group("prefix_const")
            or string_match.group("suffix_const")
        )
        if modifier == "*":
            if not allow_reference:
                return None, "Pointer return values are unsupported."
            if is_const:
                return None, "Const scalar pointer parameters are unsupported."
            return (
                ValueType(
                    kind="scalar",
                    display_type=f"{STRING_TYPE}*",
                    scalar_type=STRING_TYPE,
                    passing="scalar_pointer",
                ),
                None,
            )
        if modifier == "&":
            if not allow_reference:
                return None, "String return values must be returned by value."
            passing: Literal[
                "value",
                "const_reference",
                "mutable_reference",
            ] = (
                "const_reference"
                if is_const
                else "mutable_reference"
            )
        else:
            if is_const and not allow_reference:
                return None, "String return values must be returned by value."
            passing = "value"
        display_type = (
            f"const {STRING_TYPE}&"
            if passing == "const_reference"
            else f"{STRING_TYPE}&"
            if passing == "mutable_reference"
            else STRING_TYPE
        )
        return (
            ValueType(
                kind="scalar",
                display_type=display_type,
                scalar_type=STRING_TYPE,
                passing=passing,
            ),
            None,
        )

    vector_match = _VECTOR_TYPE.fullmatch(normalized)
    if vector_match is None:
        if "vector" in normalized:
            return None, f"Unsupported vector type: {normalized}."
        return None, f"Unsupported type: {normalized}."

    if vector_match.group("qualified") is None and not unqualified_vector_allowed:
        return (
            None,
            "Unqualified vector types require `using namespace std;`.",
        )
    raw_element_type = " ".join(vector_match.group("element").split())
    nested_match = _VECTOR_ELEMENT_TYPE.fullmatch(raw_element_type)
    vector_depth: Literal[1, 2] = 1
    if nested_match is not None:
        if (
            nested_match.group("qualified") is None
            and not unqualified_vector_allowed
        ):
            return (
                None,
                "Unqualified vector types require `using namespace std;`.",
            )
        vector_depth = 2
        raw_element_type = " ".join(
            nested_match.group("element").split()
        )
        if "vector" in raw_element_type:
            return (
                None,
                "Vector nesting deeper than two levels is unsupported.",
            )
    if raw_element_type in SUPPORTED_VECTOR_ELEMENT_TYPES:
        element_type = raw_element_type
    elif raw_element_type in {"string", STRING_TYPE}:
        if (
            raw_element_type == "string"
            and not unqualified_vector_allowed
        ):
            return (
                None,
                "Unqualified string types require `using namespace std;`.",
            )
        element_type = STRING_TYPE
    else:
        return (
            None,
            f"Unsupported vector element type: {raw_element_type}.",
        )
    modifier = vector_match.group("modifier")
    is_const = bool(
        vector_match.group("prefix_const")
        or vector_match.group("suffix_const")
    )
    if modifier == "*":
        return None, "Vector pointer parameters and returns are unsupported."
    if modifier == "&":
        if not allow_reference:
            return None, "Vector return values must be returned by value."
        passing: Literal[
            "value",
            "const_reference",
            "mutable_reference",
        ] = (
            "const_reference"
            if is_const
            else "mutable_reference"
        )
    else:
        if is_const and not allow_reference:
            return None, "Vector return values must be returned by value."
        passing = "value"

    base = f"std::vector<{element_type}>"
    if vector_depth == 2:
        base = f"std::vector<{base}>"
    display_type = (
        f"const {base}&"
        if passing == "const_reference"
        else f"{base}&"
        if passing == "mutable_reference"
        else base
    )
    return (
        ValueType(
            kind="vector",
            display_type=display_type,
            element_type=element_type,
            vector_depth=vector_depth,
            passing=passing,
        ),
        None,
    )


def _parse_parameters(
    parameters: str,
    *,
    unqualified_vector_allowed: bool,
) -> tuple[tuple[FunctionParameter, ...] | None, str | None]:
    if not parameters.strip():
        return (), None

    parsed: list[FunctionParameter] = []
    for raw_parameter in parameters.split(","):
        parameter = " ".join(raw_parameter.split())
        if not parameter or "=" in parameter or "..." in parameter:
            return None, "Default and variadic parameters are unsupported."
        if "(&" in parameter and "[" in parameter:
            return None, "References to arrays are unsupported."
        array_match = _ARRAY_PARAMETER.fullmatch(parameter)
        if array_match is not None:
            element_type = " ".join(array_match.group("element").split())
            if element_type == "char":
                return None, "Character arrays and pointers are unsupported."
            pointers = array_match.group("pointers")
            brackets = array_match.group("brackets")
            if pointers and pointers != "*":
                return None, "Pointer-to-pointer parameters are unsupported."
            if brackets and brackets.count("[") != 1:
                return None, "Multidimensional arrays are unsupported."
            parameter_name = (
                array_match.group("pointer_name")
                or array_match.group("array_name")
            )
            value_type = (
                ValueType(
                    kind="scalar",
                    display_type=f"{element_type}*",
                    scalar_type=element_type,
                    passing="scalar_pointer",
                )
                if pointers
                else ValueType(
                        kind="array",
                        display_type=f"{element_type}[]",
                        element_type=element_type,
                        passing="array_pointer",
                )
            )
            parsed.append(
                FunctionParameter(
                    name=parameter_name,
                    value_type=value_type,
                )
            )
            continue
        match = (
            _REFERENCE_PARAMETER.fullmatch(parameter)
            or _PARAMETER_DECLARATION.fullmatch(parameter)
        )
        if match is None:
            return None, f"This parameter is not supported: {parameter}."
        value_type, error = _parse_value_type(
            match.group("type"),
            allow_reference=True,
            unqualified_vector_allowed=unqualified_vector_allowed,
        )
        if value_type is None:
            return None, error
        parsed.append(
            FunctionParameter(
                name=match.group("name"),
                value_type=value_type,
            )
        )

    linked = list(parsed)
    for index, parameter in enumerate(parsed):
        is_array_declaration = parameter.value_type.kind == "array"
        is_numeric_pointer = (
            parameter.value_type.passing == "scalar_pointer"
            and parameter.value_type.scalar_type in SUPPORTED_SCALAR_TYPES
        )
        if not is_array_declaration and not is_numeric_pointer:
            continue
        next_array_index = next(
            (
                candidate_index
                for candidate_index in range(index + 1, len(parsed))
                if (
                    parsed[candidate_index].value_type.kind == "array"
                    or parsed[candidate_index].value_type.passing
                    == "scalar_pointer"
                )
            ),
            len(parsed),
        )
        candidates = [
            candidate
            for candidate in parsed[index + 1 : next_array_index]
            if candidate.name.lower() in _SIZE_PARAMETER_NAMES
            and candidate.value_type.kind == "scalar"
            and candidate.value_type.scalar_type in _INTEGRAL_TYPES
        ]
        if not candidates:
            if is_numeric_pointer:
                continue
            return (
                None,
                f"Array parameter {parameter.name} requires a later integral "
                "size parameter named size, count, length, n, or len.",
            )
        if len(candidates) > 1:
            return (
                None,
                f"Array parameter {parameter.name} has an ambiguous size "
                "parameter.",
            )
        size_parameter = candidates[0]
        linked[index] = replace(
            parameter,
            value_type=ValueType(
                kind="array",
                display_type=f"{parameter.value_type.scalar_type}[]"
                if is_numeric_pointer
                else parameter.value_type.display_type,
                element_type=(
                    parameter.value_type.scalar_type
                    if is_numeric_pointer
                    else parameter.value_type.element_type
                ),
                passing="array_pointer",
                size_parameter_name=size_parameter.name,
            ),
        )
    return tuple(linked), None


def _scalar_pointer_uses_unsupported_arithmetic(
    candidate: re.Match[str],
    masked_source: str,
    parameter_name: str,
) -> bool:
    body_start = candidate.end()
    depth = 1
    body_end = body_start
    while body_end < len(masked_source) and depth:
        if masked_source[body_end] == "{":
            depth += 1
        elif masked_source[body_end] == "}":
            depth -= 1
        body_end += 1
    body = masked_source[body_start:body_end]
    name = re.escape(parameter_name)
    direct_name = rf"(?<![\w*]){name}\b"
    return any(
        re.search(pattern, body)
        for pattern in (
            rf"{direct_name}\s*\[",
            rf"{direct_name}\s*(?:\+\+|--|\+=|-=)",
            rf"(?:\+\+|--)\s*{direct_name}",
            rf"{direct_name}\s*[+-]\s*(?=\w|\d|\()",
        )
    )


def _split_template_items(source: str) -> tuple[str, ...]:
    items: list[str] = []
    start = 0
    depth = 0
    for index, character in enumerate(source):
        if character in "<([{":
            depth += 1
        elif character in ">)]}":
            depth -= 1
        elif character == "," and depth == 0:
            items.append(source[start:index].strip())
            start = index + 1
    items.append(source[start:].strip())
    return tuple(item for item in items if item)


def _parse_template_parameters(
    source: str,
) -> tuple[tuple[TemplateParameter, ...] | None, str | None]:
    if "..." in source:
        return None, "Variadic templates are unsupported."
    parameters: list[TemplateParameter] = []
    for item in _split_template_items(source):
        declaration, separator, default = item.partition("=")
        declaration = " ".join(declaration.split())
        default = " ".join(default.split()) if separator else None
        type_match = re.fullmatch(
            r"(?:typename|class)\s+([A-Za-z_]\w*)", declaration
        )
        if type_match:
            parameters.append(
                TemplateParameter(
                    name=type_match.group(1),
                    kind="type",
                    default_argument=default,
                )
            )
            continue
        non_type_match = re.fullmatch(
            r"(int|long|long\s+long|bool|char)\s+([A-Za-z_]\w*)",
            declaration,
        )
        if non_type_match:
            parameters.append(
                TemplateParameter(
                    name=non_type_match.group(2),
                    kind="non_type",
                    non_type_type=" ".join(non_type_match.group(1).split()),
                    default_argument=default,
                )
            )
            continue
        return None, f"Unsupported template parameter: {declaration}."
    if not parameters:
        return None, "Empty template parameter lists are specializations."
    names = [parameter.name for parameter in parameters]
    if len(names) != len(set(names)):
        return None, "Template parameter names must be unique."
    return tuple(parameters), None


def _template_value_type(
    source: str,
    template_parameters: tuple[TemplateParameter, ...],
    *,
    allow_reference: bool,
) -> ValueType | None:
    normalized = " ".join(source.strip().split())
    for parameter in template_parameters:
        if parameter.kind != "type":
            continue
        escaped = re.escape(parameter.name)
        match = re.fullmatch(
            rf"(?P<prefix>const\s+)?{escaped}\s*"
            rf"(?P<suffix>const\s*)?(?P<modifier>[&*])?",
            normalized,
        )
        if not match:
            continue
        modifier = match.group("modifier")
        is_const = bool(match.group("prefix") or match.group("suffix"))
        if modifier == "*" or (modifier == "&" and not allow_reference):
            return None
        passing = (
            "const_reference"
            if modifier == "&" and is_const
            else "mutable_reference"
            if modifier == "&"
            else "value"
        )
        return ValueType(
            kind="scalar",
            display_type=normalized,
            scalar_type=parameter.name,
            passing=passing,
        )
    if normalized == "auto" and not allow_reference:
        return ValueType(
            kind="scalar",
            display_type="auto",
            scalar_type="auto",
        )
    return None


def _parse_template_candidate(
    candidate: re.Match[str],
    template_match: re.Match[str],
    *,
    unqualified_vector_allowed: bool,
) -> tuple[FunctionSignature | None, str | None]:
    template_parameters, error = _parse_template_parameters(
        template_match.group("parameters")
    )
    if template_parameters is None:
        return None, error
    raw_parameters = _split_template_items(candidate.group("parameters"))
    parsed_parameters: list[FunctionParameter] = []
    raw_parameter_types: list[str] = []
    for parameter_index, raw_parameter in enumerate(raw_parameters):
        match = _PARAMETER_DECLARATION.fullmatch(
            " ".join(raw_parameter.split())
        )
        raw_type = " ".join(
            (
                match.group("type")
                if match is not None
                else raw_parameter
            ).split()
        )
        parameter_name = (
            match.group("name")
            if match is not None
            else f"argument{parameter_index + 1}"
        )
        value_type = _template_value_type(
            raw_type, template_parameters, allow_reference=True
        )
        if value_type is None:
            value_type, error = _parse_value_type(
                raw_type,
                allow_reference=True,
                unqualified_vector_allowed=unqualified_vector_allowed,
            )
        if value_type is None:
            return None, error
        parsed_parameters.append(
            FunctionParameter(name=parameter_name, value_type=value_type)
        )
        raw_parameter_types.append(raw_type)
    raw_return = " ".join(candidate.group("return_type").split())
    return_type = _template_value_type(
        raw_return, template_parameters, allow_reference=False
    )
    if return_type is None:
        return_type, error = _parse_value_type(
            raw_return,
            allow_reference=False,
            unqualified_vector_allowed=unqualified_vector_allowed,
        )
    if return_type is None:
        if raw_return == "void":
            return_type = ValueType(kind="void", display_type="void")
        else:
            return None, error
    type_names = {
        parameter.name
        for parameter in template_parameters
        if parameter.kind == "type"
    }
    deducible = {
        parameter.value_type.scalar_type
        for parameter in parsed_parameters
        if parameter.value_type.scalar_type in type_names
    }
    required_non_deducible = [
        parameter
        for parameter in template_parameters
        if parameter.default_argument is None
        and (
            parameter.kind == "non_type"
            or parameter.name not in deducible
        )
    ]
    return (
        FunctionSignature(
            name=candidate.group("name"),
            return_value_type=return_type,
            parameters=tuple(parsed_parameters),
            template_kind="function_template",
            template_parameters=template_parameters,
            raw_parameter_types=tuple(raw_parameter_types),
            raw_return_type=raw_return,
            template_argument_mode=(
                None if required_non_deducible else "deduced"
            ),
            source_line=candidate.string.count(
                "\n", 0, template_match.start()
            )
            + 1,
        ),
        None,
    )


def _parse_candidate(
    candidate: re.Match[str],
    masked_source: str,
    *,
    unqualified_vector_allowed: bool,
) -> tuple[FunctionSignature | None, str | None]:
    prefix = masked_source[: candidate.start()]
    template_match = re.search(
        r"template\s*<(?P<parameters>[^<>]*)>\s*$", prefix
    )
    if template_match:
        if "..." in template_match.group("parameters"):
            return None, "Variadic templates are unsupported."
        if any(
            marker in template_match.group("parameters")
            for marker in ("template", "requires")
        ):
            return None, "This advanced template form is unsupported."
        return _parse_template_candidate(
            candidate,
            template_match,
            unqualified_vector_allowed=unqualified_vector_allowed,
        )

    return_value_type, error = _parse_value_type(
        candidate.group("return_type"),
        allow_reference=False,
        unqualified_vector_allowed=unqualified_vector_allowed,
    )
    if return_value_type is None:
        if candidate.group("return_type").strip() == "void":
            return_value_type = ValueType(
                kind="void",
                display_type="void",
            )
        else:
            if "*" in candidate.group("return_type"):
                return None, "Pointer return values are unsupported."
            return None, error
    parameters, error = _parse_parameters(
        candidate.group("parameters"),
        unqualified_vector_allowed=unqualified_vector_allowed,
    )
    if parameters is None:
        return None, error
    for parameter in parameters:
        if (
            parameter.value_type.passing == "scalar_pointer"
            and _scalar_pointer_uses_unsupported_arithmetic(
                candidate,
                masked_source,
                parameter.name,
            )
        ):
            return (
                None,
                f"Scalar pointer arithmetic is unsupported for "
                f"{parameter.name}.",
            )
    return (
        FunctionSignature(
            name=candidate.group("name"),
            return_value_type=return_value_type,
            parameters=parameters,
            source_line=candidate.string.count("\n", 0, candidate.start()) + 1,
        ),
        None,
    )


def analyze_test_mode(source: str) -> FunctionAnalysis:
    masked = _mask_non_code(source)
    depths = _brace_depths(masked)
    candidates = [
        match
        for match in _FUNCTION_DEFINITION.finditer(masked)
        if depths[match.start()] == 0
    ]

    if any(match.group("name") == "main" for match in candidates):
        return FunctionAnalysis(mode="program")

    unqualified_vector_allowed = bool(
        re.search(r"\busing\s+namespace\s+std\s*;", masked)
    )
    parsed_candidates = [
        _parse_candidate(
            candidate,
            masked,
            unqualified_vector_allowed=unqualified_vector_allowed,
        )
        for candidate in candidates
    ]
    functions = tuple(
        function for function, _ in parsed_candidates if function is not None
    )
    parsed_specializations: list[ExplicitFunctionSpecialization] = []
    specialization_argument_error = False
    for specialization in re.finditer(
        r"template\s*<\s*>\s*"
        r"(?P<return_type>[^;{}()]+?)\s+"
        r"(?P<name>[A-Za-z_]\w*)\s*"
        r"<(?P<arguments>[^<>]+)>\s*"
        r"\((?P<parameters>[^()]*)\)",
        masked,
    ):
        arguments = _split_template_items(
            specialization.group("arguments")
        )
        parameter_types = tuple(
            " ".join(
                (
                    parameter_match.group("type")
                    if (
                        parameter_match := _PARAMETER_DECLARATION.fullmatch(
                            " ".join(raw_parameter.split())
                        )
                    )
                    else raw_parameter
                ).split()
            )
            for raw_parameter in _split_template_items(
                specialization.group("parameters")
            )
        )
        candidates_for_name = [
            function
            for function in functions
            if function.template_kind == "function_template"
            and function.name == specialization.group("name")
        ]
        matching_primary = next(
            (
                function
                for function in candidates_for_name
                if len(function.template_parameters) == len(arguments)
                and tuple(
                    _replace_template_names(
                        raw_type,
                        {
                            parameter.name: argument
                            for parameter, argument in zip(
                                function.template_parameters,
                                arguments,
                                strict=True,
                            )
                        },
                    )
                    for raw_type in function.raw_parameter_types
                )
                == parameter_types
            ),
            None,
        )
        if matching_primary is None:
            if candidates_for_name and not any(
                len(function.template_parameters) == len(arguments)
                for function in candidates_for_name
            ):
                specialization_argument_error = True
            continue
        parsed_specializations.append(
            ExplicitFunctionSpecialization(
                primary_template_name=matching_primary.name,
                effective_template_arguments=arguments,
                return_type=" ".join(
                    specialization.group("return_type").split()
                ),
                parameter_types=parameter_types,
                source_line=masked.count(
                    "\n", 0, specialization.start()
                )
                + 1,
            )
        )
        functions = tuple(
            replace(
                function,
                explicit_specializations=(
                    function.explicit_specializations
                    + (parsed_specializations[-1],)
                ),
                template_argument_mode="explicit",
            )
            if function is matching_primary
            else function
            for function in functions
        )
    if specialization_argument_error:
        return FunctionAnalysis(
            mode="unsupported",
            message=(
                "An explicit specialization has the wrong number of "
                "template arguments."
            ),
        )
    duplicate_names = {
        function.name
        for function in functions
        if sum(candidate.name == function.name for candidate in functions) > 1
        and not all(
            candidate.template_kind == "function_template"
            for candidate in functions
            if candidate.name == function.name
        )
    }
    if duplicate_names:
        names = ", ".join(sorted(duplicate_names))
        return FunctionAnalysis(
            mode="unsupported",
            message=f"Overloaded function name(s) are not supported yet: {names}.",
        )
    if not functions:
        errors = [error for _, error in parsed_candidates if error]
        return FunctionAnalysis(
            mode="unsupported",
            message=(
                errors[0]
                if len(candidates) == 1 and errors
                else "No supported top-level function could be identified."
            ),
        )

    return FunctionAnalysis(mode="function", functions=functions)


def _normalize_template_type(value: str) -> str | None:
    normalized = " ".join(value.strip().split())
    if normalized == "string":
        normalized = STRING_TYPE
    return (
        normalized
        if normalized in SUPPORTED_TEMPLATE_TYPE_ARGUMENTS
        else None
    )


def _infer_literal_type(value: str) -> str | None:
    normalized = value.strip()
    if normalized in {"true", "false"}:
        return "bool"
    if re.fullmatch(r"[+-]?\d+", normalized):
        return "int"
    if re.fullmatch(
        r"[+-]?(?:\d+\.\d*|\d*\.\d+)(?:[eE][+-]?\d+)?",
        normalized,
    ):
        return "double"
    return None


def _replace_template_names(
    source: str,
    arguments: dict[str, str],
) -> str:
    result = source
    for name, value in arguments.items():
        result = re.sub(rf"\b{re.escape(name)}\b", value, result)
    return result


def instantiate_function_template(
    signature: FunctionSignature,
    supplied_arguments: tuple[TemplateArgument, ...],
    *,
    argument_mode: Literal["deduced", "explicit"],
    call_arguments: tuple[str, ...],
    unqualified_vector_allowed: bool,
) -> FunctionSignature:
    if signature.template_kind != "function_template":
        if supplied_arguments:
            raise ValueError(
                "Template arguments cannot be used with a non-template function."
            )
        return signature
    supplied = {argument.parameter_name: argument for argument in supplied_arguments}
    if len(supplied) != len(supplied_arguments):
        raise ValueError("Template argument names must be unique.")
    unknown = set(supplied) - {
        parameter.name for parameter in signature.template_parameters
    }
    if unknown:
        raise ValueError("The request contains an unknown template argument.")
    effective: list[TemplateArgument] = []
    resolved: dict[str, str] = {}
    for parameter in signature.template_parameters:
        supplied_argument = supplied.get(parameter.name)
        if supplied_argument is not None:
            if supplied_argument.kind != parameter.kind:
                raise ValueError(
                    f"Template argument {parameter.name} has the wrong kind."
                )
            raw_value = supplied_argument.value
            used_default = supplied_argument.used_default
        elif parameter.default_argument is not None:
            raw_value = parameter.default_argument
            used_default = True
        elif argument_mode == "deduced" and parameter.kind == "type":
            candidates = {
                _infer_literal_type(call_arguments[index])
                for index, raw_type in enumerate(signature.raw_parameter_types)
                if re.search(
                    rf"\b{re.escape(parameter.name)}\b", raw_type
                )
            }
            candidates.discard(None)
            if not candidates:
                raise ValueError(
                    f"Template argument deduction failed for {parameter.name}."
                )
            raw_value = next(
                inferred
                for index, raw_type in enumerate(
                    signature.raw_parameter_types
                )
                if re.search(
                    rf"\b{re.escape(parameter.name)}\b", raw_type
                )
                and (
                    inferred := _infer_literal_type(call_arguments[index])
                )
                is not None
            )
            used_default = False
        else:
            raise ValueError(
                f"Template argument {parameter.name} is required."
            )
        if parameter.kind == "type":
            normalized = _normalize_template_type(raw_value)
            if normalized is None:
                raise ValueError(
                    f"Template type argument {parameter.name} is unsupported."
                )
        else:
            normalized = " ".join(raw_value.strip().split())
            if parameter.non_type_type in {"int", "long", "long long"}:
                if not re.fullmatch(r"[+-]?\d+", normalized):
                    raise ValueError(
                        f"Template argument {parameter.name} must be an integer literal."
                    )
                if not -(2**31) <= int(normalized) <= 2**31 - 1:
                    raise ValueError(
                        f"Template argument {parameter.name} is outside the supported range."
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
            else:
                raise ValueError(
                    f"Template argument {parameter.name} uses an unsupported non-type parameter."
                )
        resolved[parameter.name] = normalized
        effective.append(
            TemplateArgument(
                parameter_name=parameter.name,
                kind=parameter.kind,
                value=normalized,
                used_default=used_default,
            )
        )
    parameters: list[FunctionParameter] = []
    for parameter_index, (parameter, raw_type) in enumerate(
        zip(signature.parameters, signature.raw_parameter_types, strict=True)
    ):
        concrete_type = _replace_template_names(raw_type, resolved)
        if argument_mode == "deduced":
            for template_parameter in signature.template_parameters:
                if (
                    template_parameter.kind == "type"
                    and re.fullmatch(
                        rf"(?:const\s+)?{re.escape(template_parameter.name)}"
                        r"\s*(?:const\s*)?[&]?",
                        raw_type,
                    )
                ):
                    inferred = _infer_literal_type(
                        call_arguments[parameter_index]
                    )
                    if inferred is not None:
                        concrete_type = _replace_template_names(
                            raw_type,
                            {template_parameter.name: inferred},
                        )
        value_type, error = _parse_value_type(
            concrete_type,
            allow_reference=True,
            unqualified_vector_allowed=unqualified_vector_allowed,
        )
        if value_type is None:
            raise ValueError(error or f"Unsupported type {concrete_type}.")
        parameters.append(
            FunctionParameter(name=parameter.name, value_type=value_type)
        )
    raw_return = _replace_template_names(
        signature.raw_return_type or signature.return_type, resolved
    )
    if raw_return == "auto":
        concrete_types = [
            parameter.value_type.scalar_type
            for parameter in parameters
            if parameter.value_type.kind == "scalar"
        ]
        raw_return = (
            "double"
            if any(item in {"float", "double"} for item in concrete_types)
            else concrete_types[0]
            if concrete_types
            else "int"
        )
    return_type, error = _parse_value_type(
        raw_return,
        allow_reference=False,
        unqualified_vector_allowed=unqualified_vector_allowed,
    )
    if return_type is None:
        if raw_return == "void":
            return_type = ValueType(kind="void", display_type="void")
        else:
            raise ValueError(error or f"Unsupported return type {raw_return}.")
    concrete = ", ".join(argument.value for argument in effective)
    return replace(
        signature,
        parameters=tuple(parameters),
        return_value_type=return_type,
        effective_template_arguments=tuple(effective),
        template_argument_mode=argument_mode,
        invocation_name=(
            signature.name
            if argument_mode == "deduced"
            else f"{signature.name}<{concrete}>"
        ),
    )
