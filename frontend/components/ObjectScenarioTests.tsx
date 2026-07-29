"use client";

import type {
  FunctionParameter,
  FunctionTypeMetadata,
  ObjectClass,
  ObjectMethod,
} from "@/lib/testExecution";

export type EditableObjectStep = {
  id: string;
  method_id: string;
  arguments: string[];
  expected_return: string;
  check_stdout: boolean;
  expected_stdout: string;
};

export type EditableObjectScenario = {
  id: string;
  name: string;
  class_id: string;
  constructor_id: string;
  constructor_arguments: string[];
  steps: EditableObjectStep[];
};

type Props = {
  classes: ObjectClass[];
  scenarios: EditableObjectScenario[];
  disabled: boolean;
  onChange: (scenarios: EditableObjectScenario[]) => void;
};

function placeholder(metadata: FunctionTypeMetadata) {
  if (metadata.vector_depth === 2) return "[[1, 2], [3, 4]]";
  if (metadata.kind === "vector" || metadata.kind === "array") {
    return metadata.element_type === "std::string"
      ? '["hello", "world"]'
      : "[1, 2, 3]";
  }
}

function ValueField({
  id,
  parameter,
  value,
  onChange,
}: {
  id: string;
  parameter: FunctionParameter;
  value: string;
  onChange: (value: string) => void;
}) {
  const classes =
    "mt-1 w-full min-w-0 rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200";
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="block text-xs font-medium text-slate-700">
        <span className="block">{parameter.name}</span>
        <span className="block text-[11px] font-normal text-slate-500">
          {parameter.type_metadata.display_type}
        </span>
      </label>
      {parameter.type_metadata.vector_depth === 2 ? (
        <textarea
          id={id}
          rows={3}
          maxLength={1_000}
          value={value}
          placeholder={placeholder(parameter.type_metadata)}
          onChange={(event) => onChange(event.target.value)}
          className={`${classes} resize-y leading-5`}
        />
      ) : (
        <input
          id={id}
          maxLength={1_000}
          value={value}
          placeholder={placeholder(parameter.type_metadata)}
          onChange={(event) => onChange(event.target.value)}
          className={classes}
        />
      )}
    </div>
  );
}

function ReturnField({
  id,
  method,
  value,
  onChange,
}: {
  id: string;
  method: ObjectMethod;
  value: string;
  onChange: (value: string) => void;
}) {
  const classes =
    "mt-1 w-full rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs text-slate-800 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200";
  return (
    <div className="mt-3">
      <label htmlFor={id} className="block text-xs font-medium text-slate-600">
        Expected return — {method.return_type_metadata.display_type}
      </label>
      {method.return_type_metadata.vector_depth === 2 ? (
        <textarea
          id={id}
          rows={3}
          maxLength={1_000}
          value={value}
          placeholder={placeholder(method.return_type_metadata)}
          onChange={(event) => onChange(event.target.value)}
          className={`${classes} resize-y leading-5`}
        />
      ) : (
        <input
          id={id}
          maxLength={1_000}
          value={value}
          placeholder={placeholder(method.return_type_metadata)}
          onChange={(event) => onChange(event.target.value)}
          className={classes}
        />
      )}
    </div>
  );
}

export function ObjectScenarioTests({
  classes,
  scenarios,
  disabled,
  onChange,
}: Props) {
  function update(
    scenarioId: string,
    change: (scenario: EditableObjectScenario) => EditableObjectScenario,
  ) {
    onChange(
      scenarios.map((scenario) =>
        scenario.id === scenarioId ? change(scenario) : scenario,
      ),
    );
  }

  function addScenario() {
    const objectClass = classes.length === 1 ? classes[0] : null;
    const constructor =
      objectClass?.constructors.length === 1
        ? objectClass.constructors[0]
        : null;
    onChange([
      ...scenarios,
      {
        id: `scenario-${crypto.randomUUID()}`,
        name: `Scenario ${scenarios.length + 1}`,
        class_id: objectClass?.id ?? "",
        constructor_id: constructor?.id ?? "",
        constructor_arguments: constructor?.parameters.map(() => "") ?? [],
        steps: [],
      },
    ]);
  }

  return (
    <div className="mt-3 space-y-3">
      {scenarios.map((scenario, scenarioIndex) => {
        const objectClass = classes.find(
          (candidate) => candidate.id === scenario.class_id,
        );
        const constructor = objectClass?.constructors.find(
          (candidate) => candidate.id === scenario.constructor_id,
        );
        return (
          <fieldset
            key={scenario.id}
            disabled={disabled}
            className="rounded-md border border-slate-200 p-3"
          >
            <legend className="sr-only">Scenario {scenarioIndex + 1}</legend>
            <div className="flex items-center gap-2">
              <label htmlFor={`${scenario.id}-name`} className="sr-only">
                Scenario name
              </label>
              <input
                id={`${scenario.id}-name`}
                value={scenario.name}
                maxLength={100}
                onChange={(event) =>
                  update(scenario.id, (current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
                className="min-w-0 flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm font-medium text-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-200"
              />
              <button
                type="button"
                onClick={() =>
                  onChange(
                    scenarios.filter((candidate) => candidate.id !== scenario.id),
                  )
                }
                className="rounded-md px-2 py-1.5 text-xs text-slate-500 hover:bg-rose-50 hover:text-rose-700 focus-visible:outline-2 focus-visible:outline-slate-900"
              >
                Remove
              </button>
            </div>
            <label
              htmlFor={`${scenario.id}-class`}
              className="mt-3 block text-xs font-medium text-slate-600"
            >
              Class
            </label>
            <select
              id={`${scenario.id}-class`}
              value={scenario.class_id}
              onChange={(event) => {
                const nextClass = classes.find(
                  (candidate) => candidate.id === event.target.value,
                );
                const nextConstructor =
                  nextClass?.constructors.length === 1
                    ? nextClass.constructors[0]
                    : null;
                update(scenario.id, (current) => ({
                  ...current,
                  class_id: nextClass?.id ?? "",
                  constructor_id: nextConstructor?.id ?? "",
                  constructor_arguments:
                    nextConstructor?.parameters.map(() => "") ?? [],
                  steps: [],
                }));
              }}
              className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2.5 py-2 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-200"
            >
              <option value="">Choose a class</option>
              {classes.map((candidate) => (
                <option key={candidate.id} value={candidate.id}>
                  {candidate.name}
                </option>
              ))}
            </select>
            {objectClass && (
              <>
                <label
                  htmlFor={`${scenario.id}-constructor`}
                  className="mt-3 block text-xs font-medium text-slate-600"
                >
                  Constructor
                </label>
                <select
                  id={`${scenario.id}-constructor`}
                  value={scenario.constructor_id}
                  onChange={(event) => {
                    const nextConstructor = objectClass.constructors.find(
                      (candidate) => candidate.id === event.target.value,
                    );
                    update(scenario.id, (current) => ({
                      ...current,
                      constructor_id: nextConstructor?.id ?? "",
                      constructor_arguments:
                        nextConstructor?.parameters.map(() => "") ?? [],
                    }));
                  }}
                  className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2.5 py-2 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-200"
                >
                  <option value="">Choose a constructor</option>
                  {objectClass.constructors.map((candidate) => (
                    <option key={candidate.id} value={candidate.id}>
                      {candidate.display}
                    </option>
                  ))}
                </select>
              </>
            )}
            {constructor && (
              <>
                <p className="mt-3 text-xs font-medium text-slate-600">
                  Constructor arguments
                </p>
                <div className="mt-1.5 space-y-2">
                  {constructor.parameters.map((parameter, index) => (
                    <ValueField
                      key={`${scenario.id}-constructor-${index}`}
                      id={`${scenario.id}-constructor-${index}`}
                      parameter={parameter}
                      value={scenario.constructor_arguments[index] ?? ""}
                      onChange={(value) =>
                        update(scenario.id, (current) => ({
                          ...current,
                          constructor_arguments:
                            current.constructor_arguments.map(
                              (argument, argumentIndex) =>
                                argumentIndex === index ? value : argument,
                            ),
                        }))
                      }
                    />
                  ))}
                  {constructor.parameters.length === 0 && (
                    <p className="text-xs text-slate-500">
                      This constructor takes no arguments.
                    </p>
                  )}
                </div>
                <div className="mt-4 flex items-center justify-between gap-2">
                  <p className="text-xs font-medium text-slate-700">
                    Scenario steps
                  </p>
                  <button
                    type="button"
                    disabled={scenario.steps.length >= 20}
                    onClick={() => {
                      const method =
                        objectClass!.methods.length === 1
                          ? objectClass!.methods[0]
                          : null;
                      update(scenario.id, (current) => ({
                        ...current,
                        steps: [
                          ...current.steps,
                          {
                            id: `step-${crypto.randomUUID()}`,
                            method_id: method?.id ?? "",
                            arguments: method?.parameters.map(() => "") ?? [],
                            expected_return: "",
                            check_stdout: false,
                            expected_stdout: "",
                          },
                        ],
                      }));
                    }}
                    className="rounded-md border border-slate-300 px-2 py-1 text-[11px] font-semibold text-slate-700 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-slate-900 disabled:opacity-50"
                  >
                    Add method call
                  </button>
                </div>
                <div className="mt-2 space-y-2">
                  {scenario.steps.map((step, stepIndex) => {
                    const method = objectClass!.methods.find(
                      (candidate) => candidate.id === step.method_id,
                    );
                    const replaceStep = (
                      change: (current: EditableObjectStep) => EditableObjectStep,
                    ) =>
                      update(scenario.id, (current) => ({
                        ...current,
                        steps: current.steps.map((candidate) =>
                          candidate.id === step.id
                            ? change(candidate)
                            : candidate,
                        ),
                      }));
                    return (
                      <div
                        key={step.id}
                        className="rounded-md border border-slate-200 p-2.5"
                      >
                        <div className="flex items-center justify-between gap-2">
                          <p className="text-xs font-semibold text-slate-700">
                            Step {stepIndex + 1}
                          </p>
                          <div className="flex gap-1">
                            {(["up", "down"] as const).map((direction) => {
                              const disabledMove =
                                direction === "up"
                                  ? stepIndex === 0
                                  : stepIndex === scenario.steps.length - 1;
                              return (
                                <button
                                  key={direction}
                                  type="button"
                                  disabled={disabledMove}
                                  title={`Move step ${direction}`}
                                  aria-label={`Move step ${stepIndex + 1} ${direction}`}
                                  onClick={() =>
                                    update(scenario.id, (current) => {
                                      const steps = [...current.steps];
                                      const otherIndex =
                                        direction === "up"
                                          ? stepIndex - 1
                                          : stepIndex + 1;
                                      [steps[stepIndex], steps[otherIndex]] = [
                                        steps[otherIndex],
                                        steps[stepIndex],
                                      ];
                                      return { ...current, steps };
                                    })
                                  }
                                  className="rounded px-1.5 py-1 text-slate-500 hover:bg-slate-100 focus-visible:outline-2 focus-visible:outline-slate-900 disabled:opacity-30"
                                >
                                  {direction === "up" ? "↑" : "↓"}
                                </button>
                              );
                            })}
                            <button
                              type="button"
                              onClick={() =>
                                update(scenario.id, (current) => ({
                                  ...current,
                                  steps: current.steps.filter(
                                    (candidate) => candidate.id !== step.id,
                                  ),
                                }))
                              }
                              className="rounded px-1.5 py-1 text-[11px] text-slate-500 hover:bg-rose-50 hover:text-rose-700 focus-visible:outline-2 focus-visible:outline-slate-900"
                            >
                              Remove
                            </button>
                          </div>
                        </div>
                        <label
                          htmlFor={`${step.id}-method`}
                          className="mt-2 block text-[11px] font-medium text-slate-600"
                        >
                          Method
                        </label>
                        <select
                          id={`${step.id}-method`}
                          value={step.method_id}
                          onChange={(event) => {
                            const nextMethod = objectClass!.methods.find(
                              (candidate) => candidate.id === event.target.value,
                            );
                            replaceStep((current) => ({
                              ...current,
                              method_id: nextMethod?.id ?? "",
                              arguments:
                                nextMethod?.parameters.map(() => "") ?? [],
                              expected_return: "",
                              check_stdout: false,
                              expected_stdout: "",
                            }));
                          }}
                          className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-200"
                        >
                          <option value="">Choose a method</option>
                          {objectClass!.methods.map((candidate) => (
                            <option key={candidate.id} value={candidate.id}>
                              {candidate.display}
                            </option>
                          ))}
                        </select>
                        {method && (
                          <>
                            <div className="mt-3 space-y-2">
                              {method.parameters.map((parameter, index) => (
                                <ValueField
                                  key={`${step.id}-argument-${index}`}
                                  id={`${step.id}-argument-${index}`}
                                  parameter={parameter}
                                  value={step.arguments[index] ?? ""}
                                  onChange={(value) =>
                                    replaceStep((current) => ({
                                      ...current,
                                      arguments: current.arguments.map(
                                        (argument, argumentIndex) =>
                                          argumentIndex === index
                                            ? value
                                            : argument,
                                      ),
                                    }))
                                  }
                                />
                              ))}
                            </div>
                            {method.return_type_metadata.kind !== "void" && (
                              <ReturnField
                                id={`${step.id}-expected-return`}
                                method={method}
                                value={step.expected_return}
                                onChange={(value) =>
                                  replaceStep((current) => ({
                                    ...current,
                                    expected_return: value,
                                  }))
                                }
                              />
                            )}
                            <label className="mt-3 flex items-center gap-2 text-xs font-medium text-slate-600">
                              <input
                                type="checkbox"
                                checked={step.check_stdout}
                                onChange={(event) =>
                                  replaceStep((current) => ({
                                    ...current,
                                    check_stdout: event.target.checked,
                                    expected_stdout: event.target.checked
                                      ? current.expected_stdout
                                      : "",
                                  }))
                                }
                                className="size-3.5 rounded border-slate-300 text-slate-800 focus:ring-slate-300"
                              />
                              Check method output
                            </label>
                            {step.check_stdout && (
                              <>
                                <label
                                  htmlFor={`${step.id}-expected-output`}
                                  className="mt-2 block text-xs font-medium text-slate-600"
                                >
                                  Expected output
                                </label>
                                <textarea
                                  id={`${step.id}-expected-output`}
                                  rows={2}
                                  maxLength={64 * 1024}
                                  value={step.expected_stdout}
                                  onChange={(event) =>
                                    replaceStep((current) => ({
                                      ...current,
                                      expected_stdout: event.target.value,
                                    }))
                                  }
                                  className="mt-1 w-full resize-y rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs leading-5 text-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-200"
                                />
                              </>
                            )}
                          </>
                        )}
                      </div>
                    );
                  })}
                  {scenario.steps.length === 0 && (
                    <p className="text-xs leading-5 text-slate-500">
                      Add at least one method call.
                    </p>
                  )}
                </div>
              </>
            )}
          </fieldset>
        );
      })}
      <button
        type="button"
        disabled={disabled || scenarios.length >= 10}
        onClick={addScenario}
        className="w-full rounded-md border border-dashed border-slate-300 px-3 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-slate-900 disabled:opacity-50"
      >
        Add scenario
      </button>
    </div>
  );
}
