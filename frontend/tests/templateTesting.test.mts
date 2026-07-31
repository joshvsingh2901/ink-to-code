import assert from "node:assert/strict";
import test from "node:test";

import {
  initialTemplateArgumentValues,
  templateArgumentsPayload,
  templateInstantiationPreview,
  templateSelectionLabel,
} from "../lib/templateTesting.ts";

const parameters = [
  {
    name: "T",
    kind: "type" as const,
    non_type_type: null,
    default_argument: null,
    deducible: true,
  },
  {
    name: "N",
    kind: "non_type" as const,
    non_type_type: "int",
    default_argument: "5",
    deducible: false,
  },
];

const descriptor = {
  id: "template:configured",
  name: "configured",
  return_type: "int",
  return_type_metadata: {
    kind: "scalar" as const,
    display_type: "int",
    scalar_type: "int",
    element_type: null,
    vector_depth: null,
    passing: "value" as const,
    size_parameter_name: null,
  },
  parameters: [
    {
      name: "value",
      type: "T",
      type_metadata: {
        kind: "scalar" as const,
        display_type: "T",
        scalar_type: "T",
        element_type: null,
        vector_depth: null,
        passing: "value" as const,
        size_parameter_name: null,
      },
    },
  ],
  display: "configured<T, N>(T value)",
  template_kind: "function_template" as const,
  template_parameters: parameters,
  template_argument_mode: null,
  effective_template_arguments: [],
  concrete_instantiation: null,
  specialization_selected: false,
  explicit_specializations: [],
  source_line: 1,
};

test("template defaults are represented explicitly", () => {
  const values = initialTemplateArgumentValues(parameters);
  assert.deepEqual(values, {
    T: { value: "", useDefault: false },
    N: { value: "5", useDefault: true },
  });
});

test("explicit template payload preserves declaration order", () => {
  const payload = templateArgumentsPayload(parameters, {
    T: { value: "double", useDefault: false },
    N: { value: "5", useDefault: true },
  });
  assert.deepEqual(
    payload.map((argument) => argument.parameter_name),
    ["T", "N"],
  );
  assert.equal(payload[1].use_default, true);
});

test("deduction preview infers a direct scalar argument", () => {
  assert.equal(
    templateInstantiationPreview(
      descriptor,
      "deduced",
      initialTemplateArgumentValues(parameters),
      ["3"],
    ),
    "configured<int, 5>",
  );
});

test("explicit preview uses validated selections and defaults", () => {
  assert.equal(
    templateInstantiationPreview(
      descriptor,
      "explicit",
      {
        T: { value: "double", useDefault: false },
        N: { value: "5", useDefault: true },
      },
      [],
    ),
    "configured<double, 5>",
  );
});

test("switching modes does not mutate stored explicit values", () => {
  const values = {
    T: { value: "double", useDefault: false },
    N: { value: "7", useDefault: false },
  };
  templateInstantiationPreview(descriptor, "deduced", values, ["2"]);
  assert.deepEqual(values, {
    T: { value: "double", useDefault: false },
    N: { value: "7", useDefault: false },
  });
});

test("specialization summary follows structured metadata", () => {
  assert.equal(
    templateSelectionLabel({
      specialization_kind: "explicit_specialization",
      specialization_selected: true,
    }),
    "Explicit specialization selected",
  );
  assert.equal(
    templateSelectionLabel({
      specialization_kind: "primary",
      specialization_selected: false,
    }),
    "Primary template selected",
  );
});

test("specialization summary never infers selection from output", () => {
  assert.equal(
    templateSelectionLabel({
      specialization_kind: null,
      specialization_selected: false,
    }),
    null,
  );
});
