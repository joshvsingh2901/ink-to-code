"use client";

import type {
  ObjectClass,
  ObjectOperatorParameter,
} from "@/lib/testExecution";

export type EditableScenarioObject = {
  id: string;
  name: string;
  class_id: string;
  constructor_id: string;
  arguments: string[];
};

export type EditableObjectStep = {
  id: string;
  step_type:
    | "method"
    | "observer"
    | "operator"
    | "copy_construct"
    | "copy_assign"
    | "self_assign"
    | "move_construct"
    | "move_assign";
  target_object_id: string;
  method_id: string;
  operator_id: string;
  arguments: string[];
  operands: string[];
  result_object_id: string;
  result_name: string;
  special_member_id: string;
  source_object_id: string;
  expected_return: string;
  check_stdout: boolean;
  expected_stdout: string;
};

export type EditableObjectScenario = {
  id: string;
  name: string;
  objects: EditableScenarioObject[];
  steps: EditableObjectStep[];
};

type Props = {
  classes: ObjectClass[];
  scenarios: EditableObjectScenario[];
  disabled: boolean;
  onChange: (scenarios: EditableObjectScenario[]) => void;
};

function newObject(classes: ObjectClass[], index: number): EditableScenarioObject {
  const objectClass = classes.length === 1 ? classes[0] : null;
  const constructor =
    objectClass?.constructors.length === 1 ? objectClass.constructors[0] : null;
  return {
    id: `object-${crypto.randomUUID()}`,
    name: index === 0 ? "object" : `object${index + 1}`,
    class_id: objectClass?.id ?? "",
    constructor_id: constructor?.id ?? "",
    arguments: constructor?.parameters.map(() => "") ?? [],
  };
}

function newStep(targetId: string): EditableObjectStep {
  return {
    id: `step-${crypto.randomUUID()}`,
    step_type: "method",
    target_object_id: targetId,
    method_id: "",
    operator_id: "",
    arguments: [],
    operands: [],
    result_object_id: "",
    result_name: "",
    special_member_id: "",
    source_object_id: "",
    expected_return: "",
    check_stdout: false,
    expected_stdout: "",
  };
}

function ValueField({
  id,
  label,
  type,
  value,
  placeholder,
  helperText,
  onChange,
}: {
  id: string;
  label: string;
  type: string;
  value: string;
  placeholder?: string;
  helperText?: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="min-w-0">
      <label htmlFor={id} className="block text-xs font-medium text-slate-700">
        <span className="block">{label}</span>
        <span className="block text-[11px] font-normal text-slate-500">
          {type}
        </span>
      </label>
      <input
        id={id}
        value={value}
        maxLength={1_000}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1 w-full min-w-0 rounded-md border border-slate-300 px-2 py-1.5 font-mono text-xs text-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-200"
      />
      {helperText && (
        <p className="mt-1 text-[11px] leading-4 text-slate-500">
          {helperText}
        </p>
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
  function updateScenario(
    scenarioId: string,
    change: (scenario: EditableObjectScenario) => EditableObjectScenario,
  ) {
    onChange(
      scenarios.map((scenario) =>
        scenario.id === scenarioId ? change(scenario) : scenario,
      ),
    );
  }

  return (
    <div className="mt-3 space-y-3">
      {scenarios.map((scenario, scenarioIndex) => {
        return (
          <fieldset
            key={scenario.id}
            disabled={disabled}
            className="rounded-md border border-slate-200 p-3"
          >
            <legend className="sr-only">Scenario {scenarioIndex + 1}</legend>
            <div className="flex items-center gap-2">
              <input
                aria-label="Scenario name"
                value={scenario.name}
                maxLength={100}
                onChange={(event) =>
                  updateScenario(scenario.id, (current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
                className="min-w-0 flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-sm font-medium text-slate-800 focus:outline-none focus:ring-2 focus:ring-slate-200"
              />
              <button
                type="button"
                onClick={() =>
                  onChange(scenarios.filter((item) => item.id !== scenario.id))
                }
                className="rounded px-2 py-1 text-xs text-slate-500 hover:bg-rose-50 hover:text-rose-700 focus-visible:outline-2 focus-visible:outline-slate-900"
              >
                Remove
              </button>
            </div>

            <div className="mt-4 flex items-center justify-between gap-2">
              <p className="text-xs font-semibold text-slate-700">Objects</p>
              <button
                type="button"
                disabled={scenario.objects.length >= 5}
                onClick={() =>
                  updateScenario(scenario.id, (current) => ({
                    ...current,
                    objects: [
                      ...current.objects,
                      newObject(classes, current.objects.length),
                    ],
                  }))
                }
                className="rounded-md border border-slate-300 px-2 py-1 text-[11px] font-semibold text-slate-700 focus-visible:outline-2 focus-visible:outline-slate-900 disabled:opacity-40"
              >
                Add object
              </button>
            </div>
            <div className="mt-2 space-y-2">
              {scenario.objects.map((object, objectIndex) => {
                const objectClass = classes.find(
                  (item) => item.id === object.class_id,
                );
                const constructor = objectClass?.constructors.find(
                  (item) => item.id === object.constructor_id,
                );
                const replaceObject = (
                  change: (item: EditableScenarioObject) => EditableScenarioObject,
                ) =>
                  updateScenario(scenario.id, (current) => ({
                    ...current,
                    objects: current.objects.map((item) =>
                      item.id === object.id ? change(item) : item,
                    ),
                    steps: current.steps.filter(
                      (step) =>
                        step.target_object_id !== object.id &&
                        step.source_object_id !== object.id &&
                        !step.operands.includes(object.id),
                    ),
                  }));
                return (
                  <div
                    key={object.id}
                    className="rounded-md border border-slate-200 p-2.5"
                  >
                    <div className="flex items-center gap-2">
                      <input
                        aria-label={`Object ${objectIndex + 1} name`}
                        value={object.name}
                        maxLength={100}
                        onChange={(event) =>
                          replaceObject((current) => ({
                            ...current,
                            name: event.target.value,
                          }))
                        }
                        className="min-w-0 flex-1 rounded-md border border-slate-300 px-2 py-1.5 text-xs font-medium focus:outline-none focus:ring-2 focus:ring-slate-200"
                      />
                      {scenario.objects.length > 1 && (
                        <button
                          type="button"
                          onClick={() =>
                            updateScenario(scenario.id, (current) => ({
                              ...current,
                              objects: current.objects.filter(
                                (item) => item.id !== object.id,
                              ),
                              steps: current.steps.filter(
                                (step) =>
                                  step.target_object_id !== object.id &&
                                  step.source_object_id !== object.id &&
                                  !step.operands.includes(object.id),
                              ),
                            }))
                          }
                          className="text-[11px] text-slate-500 hover:text-rose-700"
                        >
                          Remove
                        </button>
                      )}
                    </div>
                    <div className="mt-2 grid gap-2">
                      <select
                        aria-label={`${object.name} class`}
                        value={object.class_id}
                        onChange={(event) => {
                          const nextClass = classes.find(
                            (item) => item.id === event.target.value,
                          );
                          const nextConstructor =
                            nextClass?.constructors.length === 1
                              ? nextClass.constructors[0]
                              : null;
                          replaceObject((current) => ({
                            ...current,
                            class_id: nextClass?.id ?? "",
                            constructor_id: nextConstructor?.id ?? "",
                            arguments:
                              nextConstructor?.parameters.map(() => "") ?? [],
                          }));
                        }}
                        className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-slate-200"
                      >
                        <option value="">Choose a class</option>
                        {classes.map((item) => (
                          <option key={item.id} value={item.id}>
                            {item.name}
                          </option>
                        ))}
                      </select>
                      {objectClass && (
                        <select
                          aria-label={`${object.name} constructor`}
                          value={object.constructor_id}
                          onChange={(event) => {
                            const next = objectClass.constructors.find(
                              (item) => item.id === event.target.value,
                            );
                            replaceObject((current) => ({
                              ...current,
                              constructor_id: next?.id ?? "",
                              arguments: next?.parameters.map(() => "") ?? [],
                            }));
                          }}
                          className="w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-slate-200"
                        >
                          <option value="">Choose a constructor</option>
                          {objectClass.constructors.map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.display}
                            </option>
                          ))}
                        </select>
                      )}
                      {constructor?.parameters.map((parameter, index) => (
                        <ValueField
                          key={`${object.id}-${index}`}
                          id={`${object.id}-${index}`}
                          label={parameter.name}
                          type={parameter.type_metadata.display_type}
                          value={object.arguments[index] ?? ""}
                          onChange={(value) =>
                            replaceObject((current) => ({
                              ...current,
                              arguments: current.arguments.map(
                                (argument, argumentIndex) =>
                                  argumentIndex === index ? value : argument,
                              ),
                            }))
                          }
                        />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>

            <div className="mt-4 flex items-center justify-between gap-2">
              <p className="text-xs font-semibold text-slate-700">
                Scenario steps
              </p>
              <button
                type="button"
                disabled={!scenario.objects.length || scenario.steps.length >= 20}
                onClick={() =>
                  updateScenario(scenario.id, (current) => ({
                    ...current,
                    steps: [
                      ...current.steps,
                      newStep(current.objects[0]?.id ?? ""),
                    ],
                  }))
                }
                className="rounded-md border border-slate-300 px-2 py-1 text-[11px] font-semibold text-slate-700 focus-visible:outline-2 focus-visible:outline-slate-900 disabled:opacity-40"
              >
                Add step
              </button>
            </div>
            <div className="mt-2 space-y-2">
              {scenario.steps.map((step, stepIndex) => {
                const priorObjects = [...scenario.objects];
                const movedFrom = new Set<string>();
                for (const priorStep of scenario.steps.slice(0, stepIndex)) {
                  const source = priorObjects.find(
                    (item) => item.id === priorStep.source_object_id,
                  );
                  if (
                    priorStep.result_object_id &&
                    priorStep.result_name
                  ) {
                    const operatorClass = classes
                      .flatMap((item) => item.operators)
                      .find((item) => item.id === priorStep.operator_id)
                      ?.return_object_class_id;
                    priorObjects.push({
                      id: priorStep.result_object_id,
                      name: priorStep.result_name,
                      class_id: operatorClass ?? source?.class_id ?? "",
                      constructor_id: "",
                      arguments: [],
                    });
                  }
                  if (
                    priorStep.step_type === "move_construct" ||
                    priorStep.step_type === "move_assign"
                  ) {
                    movedFrom.add(priorStep.source_object_id);
                  }
                  if (
                    priorStep.step_type === "copy_assign" ||
                    priorStep.step_type === "move_assign"
                  ) {
                    movedFrom.delete(priorStep.target_object_id);
                  }
                }
                const target = priorObjects.find(
                  (item) => item.id === step.target_object_id,
                );
                const targetClass = classes.find(
                  (item) => item.id === target?.class_id,
                );
                const operator = classes
                  .flatMap((item) => item.operators)
                  .find((item) => item.id === step.operator_id);
                const method = targetClass?.methods.find(
                  (item) => item.id === step.method_id,
                );
                const operatorParameters =
                  operator?.parameters.filter(
                    (item) => item.operand_kind !== "stream",
                  ) ?? [];
                const specialMember = targetClass?.special_members.find(
                  (item) => item.id === step.special_member_id,
                );
                const replaceStep = (
                  change: (item: EditableObjectStep) => EditableObjectStep,
                ) =>
                  updateScenario(scenario.id, (current) => ({
                    ...current,
                    steps: current.steps.map((item) =>
                      item.id === step.id ? change(item) : item,
                    ),
                  }));
                return (
                  <div
                    key={step.id}
                    className="rounded-md border border-slate-200 p-2.5"
                  >
                    <div className="flex items-center justify-between">
                      <p className="text-xs font-semibold">Step {stepIndex + 1}</p>
                      <div className="flex gap-1">
                        <button
                          type="button"
                          disabled={stepIndex === 0}
                          aria-label={`Move step ${stepIndex + 1} up`}
                          onClick={() =>
                            updateScenario(scenario.id, (current) => {
                              const steps = [...current.steps];
                              [steps[stepIndex - 1], steps[stepIndex]] = [
                                steps[stepIndex],
                                steps[stepIndex - 1],
                              ];
                              return { ...current, steps };
                            })
                          }
                        >
                          ↑
                        </button>
                        <button
                          type="button"
                          disabled={stepIndex === scenario.steps.length - 1}
                          aria-label={`Move step ${stepIndex + 1} down`}
                          onClick={() =>
                            updateScenario(scenario.id, (current) => {
                              const steps = [...current.steps];
                              [steps[stepIndex], steps[stepIndex + 1]] = [
                                steps[stepIndex + 1],
                                steps[stepIndex],
                              ];
                              return { ...current, steps };
                            })
                          }
                        >
                          ↓
                        </button>
                        <button
                          type="button"
                          onClick={() =>
                            updateScenario(scenario.id, (current) => ({
                              ...current,
                              steps: current.steps.filter(
                                (item) =>
                                  item.id !== step.id &&
                                  item.target_object_id !==
                                    step.result_object_id &&
                                  item.source_object_id !==
                                    step.result_object_id &&
                                  !item.operands.includes(
                                    step.result_object_id,
                                  ),
                              ),
                            }))
                          }
                          className="text-[11px] text-slate-500 hover:text-rose-700"
                        >
                          Remove
                        </button>
                      </div>
                    </div>
                    <select
                      aria-label={`Step ${stepIndex + 1} type`}
                      value={step.step_type}
                      onChange={(event) => {
                        const nextType = event.target.value as
                            | "method"
                            | "observer"
                            | "operator"
                            | "copy_construct"
                            | "copy_assign"
                            | "self_assign"
                            | "move_construct"
                            | "move_assign";
                        replaceStep((current) => {
                          if (current.step_type === nextType) return current;
                          if (
                            ["method", "observer"].includes(
                              current.step_type,
                            ) &&
                            ["method", "observer"].includes(nextType)
                          ) {
                            const selectedMethod =
                              targetClass?.methods.find(
                                (item) => item.id === current.method_id,
                              );
                            const observerCanUseMethod =
                              nextType !== "observer" ||
                              selectedMethod?.return_type_metadata.kind !==
                                "void";
                            return {
                              ...newStep(current.target_object_id),
                              id: current.id,
                              step_type: nextType,
                              method_id: observerCanUseMethod
                                ? current.method_id
                                : "",
                              arguments: observerCanUseMethod
                                ? current.arguments
                                : [],
                              expected_return:
                                observerCanUseMethod &&
                                selectedMethod?.return_type_metadata.kind !==
                                  "void"
                                  ? current.expected_return
                                  : "",
                              check_stdout: observerCanUseMethod
                                ? current.check_stdout
                                : false,
                              expected_stdout:
                                observerCanUseMethod &&
                                current.check_stdout
                                  ? current.expected_stdout
                                  : "",
                            };
                          }
                          return {
                            ...newStep(current.target_object_id),
                            id: current.id,
                            step_type: nextType,
                            source_object_id: [
                              "copy_construct",
                              "move_construct",
                              "self_assign",
                            ].includes(nextType)
                              ? current.target_object_id
                              : "",
                          };
                        });
                      }}
                      className="mt-2 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs"
                    >
                      <option value="method">Method call</option>
                      <option value="observer">Observer method call</option>
                      <option value="operator">Operator call</option>
                      {targetClass?.special_members.some(
                        (item) => item.kind === "copy_constructor",
                      ) && (
                        <option value="copy_construct">Copy construct</option>
                      )}
                      {targetClass?.special_members.some(
                        (item) => item.kind === "copy_assignment",
                      ) && (
                        <>
                          <option value="copy_assign">Copy assign</option>
                          <option value="self_assign">Self assign</option>
                        </>
                      )}
                      {targetClass?.special_members.some(
                        (item) => item.kind === "move_constructor",
                      ) && (
                        <option value="move_construct">Move construct</option>
                      )}
                      {targetClass?.special_members.some(
                        (item) => item.kind === "move_assignment",
                      ) && (
                        <option value="move_assign">Move assign</option>
                      )}
                    </select>
                    <select
                      aria-label={`Step ${stepIndex + 1} target object`}
                      value={step.target_object_id}
                      onChange={(event) =>
                        replaceStep((current) => ({
                          ...newStep(event.target.value),
                          id: current.id,
                          step_type: current.step_type,
                          source_object_id: [
                            "copy_construct",
                            "move_construct",
                            "self_assign",
                          ].includes(current.step_type)
                            ? event.target.value
                            : "",
                        }))
                      }
                      className="mt-2 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs"
                    >
                      <option value="">Choose an object</option>
                      {priorObjects.map((item) => (
                        <option
                          key={item.id}
                          value={item.id}
                          disabled={
                            movedFrom.has(item.id) &&
                            !["copy_assign", "move_assign"].includes(
                              step.step_type,
                            )
                          }
                        >
                          {item.name}
                          {movedFrom.has(item.id) ? " — moved from" : ""}
                        </option>
                      ))}
                    </select>
                    {["method", "observer"].includes(step.step_type) ? (
                      <>
                        <select
                          aria-label={`Step ${stepIndex + 1} method`}
                          value={step.method_id}
                          onChange={(event) => {
                            const next = targetClass?.methods.find(
                              (item) => item.id === event.target.value,
                            );
                            replaceStep((current) => ({
                              ...current,
                              method_id: next?.id ?? "",
                              arguments: next?.parameters.map(() => "") ?? [],
                              expected_return:
                                next?.return_type_metadata.kind === "void"
                                  ? ""
                                  : next?.id === current.method_id
                                    ? current.expected_return
                                    : "",
                            }));
                          }}
                          className="mt-2 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs"
                        >
                          <option value="">Choose a method</option>
                          {targetClass?.methods
                            .filter(
                              (item) =>
                                step.step_type !== "observer" ||
                                item.return_type_metadata.kind !== "void",
                            )
                            .map((item) => (
                            <option key={item.id} value={item.id}>
                              {item.display}
                            </option>
                            ))}
                        </select>
                        {method?.parameters.map((parameter, index) => (
                          <ValueField
                            key={`${step.id}-argument-${index}`}
                            id={`${step.id}-argument-${index}`}
                            label={parameter.name}
                            type={parameter.type_metadata.display_type}
                            value={step.arguments[index] ?? ""}
                            onChange={(value) =>
                              replaceStep((current) => ({
                                ...current,
                                arguments: current.arguments.map(
                                  (item, itemIndex) =>
                                    itemIndex === index ? value : item,
                                ),
                              }))
                            }
                          />
                        ))}
                      </>
                    ) : step.step_type === "operator" ? (
                      <>
                        <select
                          aria-label={`Step ${stepIndex + 1} operator`}
                          value={step.operator_id}
                          onChange={(event) => {
                            const next = classes
                              .flatMap((item) => item.operators)
                              .find((item) => item.id === event.target.value);
                            replaceStep((current) => ({
                              ...current,
                              operator_id: next?.id ?? "",
                              operands:
                                next?.parameters
                                  .filter(
                                    (item) => item.operand_kind !== "stream",
                                  )
                                  .map(() => "") ?? [],
                              expected_return: "",
                              check_stdout: next?.symbol === "<<",
                              expected_stdout: "",
                              result_object_id:
                                next?.return_kind === "object_value"
                                  ? `result-${crypto.randomUUID()}`
                                  : "",
                              result_name: "",
                            }));
                          }}
                          className="mt-2 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs"
                        >
                          <option value="">Choose an operator</option>
                          {classes
                            .flatMap((item) => item.operators)
                            .filter(
                              (item, index, all) =>
                                all.findIndex(
                                  (candidate) => candidate.id === item.id,
                                ) === index &&
                                (item.kind === "standalone" ||
                                  item.declaring_class_id === target?.class_id),
                            )
                            .map((item) => (
                              <option key={item.id} value={item.id}>
                                {item.display}
                              </option>
                            ))}
                        </select>
                        {operatorParameters.map((parameter, index) => (
                          <OperandField
                            key={`${step.id}-operand-${index}`}
                            id={`${step.id}-operand-${index}`}
                            parameter={parameter}
                            value={step.operands[index] ?? ""}
                            objects={priorObjects}
                            onChange={(value) =>
                              replaceStep((current) => ({
                                ...current,
                                operands: current.operands.map(
                                  (item, itemIndex) =>
                                    itemIndex === index ? value : item,
                                ),
                              }))
                            }
                          />
                        ))}
                        {operator?.return_kind === "object_value" && (
                          <ValueField
                            id={`${step.id}-result-name`}
                            label="Returned object name"
                            type={operator.return_type}
                            value={step.result_name}
                            placeholder="e.g. result"
                            helperText="Use this name to reference the returned object in later steps."
                            onChange={(value) =>
                              replaceStep((current) => ({
                                ...current,
                                result_name: value,
                              }))
                            }
                          />
                        )}
                      </>
                    ) : (
                      <SpecialMemberFields
                        step={step}
                        member={specialMember}
                        targetClass={targetClass}
                        objects={priorObjects}
                        movedFrom={movedFrom}
                        onChange={replaceStep}
                      />
                    )}
                    {((method &&
                      method.return_type_metadata.kind !== "void") ||
                      operator?.return_kind === "value") && (
                      <ValueField
                        id={`${step.id}-expected-return`}
                        label="Expected value"
                        type={
                          method?.return_type_metadata.display_type ??
                          operator?.return_type ??
                          ""
                        }
                        value={step.expected_return}
                        onChange={(value) =>
                          replaceStep((current) => ({
                            ...current,
                            expected_return: value,
                          }))
                        }
                      />
                    )}
                    <label className="mt-2 flex items-center gap-2 text-xs text-slate-600">
                      <input
                        type="checkbox"
                        checked={step.check_stdout}
                        disabled={operator?.symbol === "<<"}
                        onChange={(event) =>
                          replaceStep((current) => ({
                            ...current,
                            check_stdout: event.target.checked,
                            expected_stdout: event.target.checked
                              ? current.expected_stdout
                              : "",
                          }))
                        }
                      />
                      Check method output
                    </label>
                    {step.check_stdout && (
                      <textarea
                        aria-label="Expected output"
                        value={step.expected_stdout}
                        rows={2}
                        onChange={(event) =>
                          replaceStep((current) => ({
                            ...current,
                            expected_stdout: event.target.value,
                          }))
                        }
                        className="mt-1 w-full rounded-md border border-slate-300 p-2 font-mono text-xs"
                      />
                    )}
                  </div>
                );
              })}
            </div>
          </fieldset>
        );
      })}
      <button
        type="button"
        disabled={disabled || scenarios.length >= 10}
        onClick={() =>
          onChange([
            ...scenarios,
            {
              id: `scenario-${crypto.randomUUID()}`,
              name: `Scenario ${scenarios.length + 1}`,
              objects: [newObject(classes, 0)],
              steps: [],
            },
          ])
        }
        className="w-full rounded-md border border-dashed border-slate-300 px-3 py-2 text-xs font-semibold text-slate-600"
      >
        Add scenario
      </button>
    </div>
  );
}

function SpecialMemberFields({
  step,
  member,
  targetClass,
  objects,
  movedFrom,
  onChange,
}: {
  step: EditableObjectStep;
  member:
    | NonNullable<ObjectClass["special_members"]>[number]
    | undefined;
  targetClass: ObjectClass | undefined;
  objects: EditableScenarioObject[];
  movedFrom: Set<string>;
  onChange: (
    change: (item: EditableObjectStep) => EditableObjectStep,
  ) => void;
}) {
  const expectedKind = ({
    copy_construct: "copy_constructor",
    copy_assign: "copy_assignment",
    self_assign: "copy_assignment",
    move_construct: "move_constructor",
    move_assign: "move_assignment",
  } as Record<string, string>)[step.step_type];
  const createsObject = ["copy_construct", "move_construct"].includes(
    step.step_type,
  );
  const needsSource = ["copy_assign", "move_assign"].includes(step.step_type);
  return (
    <div className="mt-2 space-y-2">
      {needsSource && (
        <label className="block text-xs text-slate-700">
          Source
          <select
            value={step.source_object_id}
            onChange={(event) =>
              onChange((current) => ({
                ...current,
                source_object_id: event.target.value,
              }))
            }
            className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs"
          >
            <option value="">Choose a source object</option>
            {objects
              .filter(
                (item) =>
                  item.class_id === targetClass?.id &&
                  !movedFrom.has(item.id),
              )
              .map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
          </select>
        </label>
      )}
      <label className="block text-xs text-slate-700">
        Selected operation
        <select
          value={step.special_member_id}
          onChange={(event) =>
            onChange((current) => ({
              ...current,
              special_member_id: event.target.value,
              result_object_id:
                createsObject && !current.result_object_id
                  ? `result-${crypto.randomUUID()}`
                  : current.result_object_id,
            }))
          }
          className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs"
        >
          <option value="">Choose an operation</option>
          {targetClass?.special_members
            .filter((item) => item.kind === expectedKind)
            .map((item) => (
              <option key={item.id} value={item.id}>
                {item.display}
              </option>
            ))}
        </select>
      </label>
      {createsObject && (
        <>
          <ValueField
            id={`${step.id}-special-result`}
            label={
              step.step_type === "copy_construct"
                ? "Copied object name"
                : "Moved object name"
            }
            type={targetClass?.name ?? ""}
            value={step.result_name}
            placeholder={
              step.step_type === "copy_construct" ? "e.g. copied" : "e.g. moved"
            }
            onChange={(value) =>
              onChange((current) => ({
                ...current,
                result_name: value,
                result_object_id:
                  current.result_object_id || `result-${crypto.randomUUID()}`,
              }))
            }
          />
          {step.step_type === "copy_construct" && (
            <p className="text-[11px] leading-4 text-slate-500">
              Add a mutating method call on one object, then add observer calls
              for both objects to verify independence.
            </p>
          )}
        </>
      )}
      {member?.is_defaulted && (
        <p className="text-[11px] text-slate-500">
          This special member is explicitly defaulted.
        </p>
      )}
    </div>
  );
}

function OperandField({
  id,
  parameter,
  value,
  objects,
  onChange,
}: {
  id: string;
  parameter: ObjectOperatorParameter;
  value: string;
  objects: EditableScenarioObject[];
  onChange: (value: string) => void;
}) {
  if (parameter.operand_kind === "object") {
    return (
      <label className="mt-2 block text-xs text-slate-700">
        {parameter.name} <span className="text-slate-500">{parameter.type}</span>
        <select
          value={value}
          onChange={(event) => onChange(event.target.value)}
          className="mt-1 w-full rounded-md border border-slate-300 bg-white px-2 py-1.5 text-xs"
        >
          <option value="">Choose an object</option>
          {objects
            .filter((item) => item.class_id === parameter.object_class_id)
            .map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
        </select>
      </label>
    );
  }
  return (
    <ValueField
      id={id}
      label={parameter.name}
      type={parameter.type}
      value={value}
      onChange={onChange}
    />
  );
}
