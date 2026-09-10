// Backend accepts only lowercase "true"/"false"; non-boolean values pass through unchanged.
export function normalizeBooleanLiteral(value: string): string {
  const lowered = value.trim().toLowerCase();
  return lowered === "true" || lowered === "false" ? lowered : value;
}
