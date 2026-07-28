import re
from dataclasses import dataclass
from typing import Literal

SUPPORTED_TYPES = {"int", "long", "long long", "double", "bool"}


@dataclass(frozen=True)
class FunctionParameter:
    name: str
    type: str


@dataclass(frozen=True)
class FunctionSignature:
    name: str
    return_type: str
    parameters: tuple[FunctionParameter, ...]

    @property
    def id(self) -> str:
        parameter_types = ",".join(
            parameter.type for parameter in self.parameters
        )
        return f"{self.name}({parameter_types})->{self.return_type}"

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
    r"(?P<return_type>[A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*)"
    r"\s+(?P<name>[A-Za-z_]\w*)\s*"
    r"\((?P<parameters>[^()]*)\)\s*(?:noexcept\s*)?\{",
)
_SUPPORTED_PARAMETER = re.compile(
    r"(?P<type>long\s+long|long|int|double|bool)"
    r"\s+(?P<name>[A-Za-z_]\w*)",
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


def _parse_parameters(parameters: str) -> tuple[FunctionParameter, ...] | None:
    if not parameters.strip():
        return ()

    parsed: list[FunctionParameter] = []
    for raw_parameter in parameters.split(","):
        parameter = " ".join(raw_parameter.split())
        if (
            not parameter
            or "=" in parameter
            or "..." in parameter
            or any(token in parameter for token in ("*", "&", "[", "]"))
        ):
            return None
        match = _SUPPORTED_PARAMETER.fullmatch(parameter)
        if not match:
            return None
        parsed.append(
            FunctionParameter(
                name=match.group("name"),
                type=" ".join(match.group("type").split()),
            )
        )
    return tuple(parsed)


def _parse_candidate(
    candidate: re.Match[str],
    masked_source: str,
) -> FunctionSignature | None:
    prefix = masked_source[: candidate.start()]
    if re.search(r"template\s*<[^>]*>\s*$", prefix):
        return None

    return_type = " ".join(candidate.group("return_type").split())
    if return_type not in SUPPORTED_TYPES:
        return None
    parameters = _parse_parameters(candidate.group("parameters"))
    if parameters is None:
        return None
    return FunctionSignature(
        name=candidate.group("name"),
        return_type=return_type,
        parameters=parameters,
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

    functions = tuple(
        function
        for candidate in candidates
        if (function := _parse_candidate(candidate, masked)) is not None
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
            message=(
                f"Overloaded function name(s) are not supported yet: {names}."
            ),
        )
    if not functions:
        message = "No supported top-level function could be identified."
        if len(candidates) == 1:
            candidate = candidates[0]
            unsupported_signature = (
                f"{' '.join(candidate.group('return_type').split())} "
                f"{candidate.group('name')}"
                f"({' '.join(candidate.group('parameters').split())})"
            )
            suffix = (
                " Void returns are unsupported."
                if candidate.group("return_type").strip() == "void"
                else ""
            )
            message = (
                f"This function signature is not supported yet: "
                f"{unsupported_signature}.{suffix}"
            )
        return FunctionAnalysis(
            mode="unsupported",
            message=message,
        )

    return FunctionAnalysis(
        mode="function",
        functions=functions,
    )
