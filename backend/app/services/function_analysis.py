import re
from dataclasses import dataclass, replace
from typing import Literal

SUPPORTED_SCALAR_TYPES = {"int", "long", "long long", "double", "bool"}
STRING_TYPE = "std::string"


@dataclass(frozen=True)
class ValueType:
    kind: Literal["scalar", "vector", "array", "void"]
    display_type: str
    scalar_type: str | None = None
    element_type: str | None = None
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

    @property
    def return_type(self) -> str:
        return self.return_value_type.display_type

    @property
    def id(self) -> str:
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
        return f"{self.name}({parameters})"


@dataclass(frozen=True)
class FunctionAnalysis:
    mode: Literal["program", "function", "unsupported"]
    functions: tuple[FunctionSignature, ...] = ()
    message: str | None = None


_FUNCTION_DEFINITION = re.compile(
    r"(?P<return_type>"
    r"(?:const\s+)?(?:std::)?vector\s*<[^<>]+>\s*(?:const\s*)?[&*]?"
    r"|(?:const\s+)?(?:std::)?string\s*(?:const\s*)?[&*]?"
    r"|(?:const\s+)?(?:long\s+long|long|int|double|bool)\s*"
    r"(?:const\s*)?&&?"
    r"|(?:long\s+long|long|int|double|bool|char)\s*\*+"
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
    r"(?P<qualified>std::)?vector\s*<\s*(?P<element>[^<>]+)\s*>\s*"
    r"(?P<suffix_const>const\s*)?(?P<modifier>[&*])?"
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
    if raw_element_type in SUPPORTED_SCALAR_TYPES:
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


def _parse_candidate(
    candidate: re.Match[str],
    masked_source: str,
    *,
    unqualified_vector_allowed: bool,
) -> tuple[FunctionSignature | None, str | None]:
    prefix = masked_source[: candidate.start()]
    if re.search(r"template\s*<[^>]*>\s*$", prefix):
        return None, "Function templates are unsupported."

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
    duplicate_names = {
        function.name
        for function in functions
        if sum(candidate.name == function.name for candidate in functions) > 1
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
