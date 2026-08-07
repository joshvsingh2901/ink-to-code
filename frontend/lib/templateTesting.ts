import type {
  FunctionDescriptor,
  TemplateParameter,
} from "./testExecution";

export type EditableTemplateArgumentValue = {
  value: string;
  useDefault: boolean;
};

export const TEMPLATE_TYPE_OPTIONS = [
  "int",
  "long",
  "long long",
  "float",
  "double",
  "bool",
  "char",
  "std::string",
  "std::vector<int>",
  "std::deque<int>",
  "std::list<int>",
  "std::set<int>",
  "std::map<std::string, int>",
] as const;

export function initialTemplateArgumentValues(
  parameters: TemplateParameter[],
): Record<string, EditableTemplateArgumentValue> {
  return Object.fromEntries(
    parameters.map((parameter) => [
      parameter.name,
      {
        value: parameter.default_argument ?? "",
        useDefault: parameter.default_argument !== null,
      },
    ]),
  );
}

export function templateArgumentsPayload(
  parameters: TemplateParameter[],
  values: Record<string, EditableTemplateArgumentValue>,
) {
  return parameters.map((parameter) => ({
    parameter_name: parameter.name,
    kind: parameter.kind,
    value: values[parameter.name]?.value ?? "",
    use_default: values[parameter.name]?.useDefault ?? false,
  }));
}

function inferredLiteralType(value: string): string | null {
  const normalized = value.trim();
  if (/^[+-]?\d+$/.test(normalized)) return "int";
  if (/^[+-]?(?:\d+\.\d*|\d*\.\d+)(?:e[+-]?\d+)?$/i.test(normalized)) {
    return "double";
  }
  if (normalized === "true" || normalized === "false") return "bool";
  return null;
}

export function templateInstantiationPreview(
  selectedFunction: FunctionDescriptor,
  mode: "deduced" | "explicit",
  values: Record<string, EditableTemplateArgumentValue>,
  callArguments: string[],
): string {
  const argumentsInOrder = selectedFunction.template_parameters.map(
    (parameter) => {
      const configured = values[parameter.name];
      if (mode === "explicit") {
        return configured?.useDefault
          ? parameter.default_argument ?? "?"
          : configured?.value || "?";
      }
      const parameterIndex = selectedFunction.parameters.findIndex(
        (candidate) =>
          candidate.type_metadata.scalar_type === parameter.name,
      );
      return parameterIndex >= 0
        ? inferredLiteralType(callArguments[parameterIndex] ?? "") ?? "?"
        : parameter.default_argument ?? "?";
    },
  );
  return `${selectedFunction.name}<${argumentsInOrder.join(", ")}>`;
}

export function templateSelectionLabel(result: {
  specialization_kind?: "primary" | "explicit_specialization" | null;
  specialization_selected?: boolean;
}): string | null {
  if (
    result.specialization_kind === "explicit_specialization" &&
    result.specialization_selected
  ) {
    return "Explicit specialization selected";
  }
  if (result.specialization_kind === "primary") {
    return "Primary template selected";
  }
  return null;
}
