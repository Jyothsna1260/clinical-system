import type { Criterion, NormalizedRule } from "../types";

const OP_TEXT: Record<string, string> = {
  gt: ">",
  gte: "≥",
  lt: "<",
  lte: "≤",
  eq: "=",
};

function val(v: NormalizedRule["value"]): string {
  if (v === null || v === undefined) return "?";
  if (Array.isArray(v)) return v.join(" / ");
  return String(v);
}

/** Human-readable one-line summary of a normalized rule. */
export function ruleSummary(rule: NormalizedRule | null | undefined): string {
  if (!rule) return "Not machine-normalized (free text only)";
  const unit = rule.unit ? ` ${rule.unit}` : "";
  const attr = rule.attribute;
  switch (rule.operator) {
    case "gt":
    case "gte":
    case "lt":
    case "lte":
    case "eq":
      return `${attr} ${OP_TEXT[rule.operator]} ${val(rule.value)}${unit}`;
    case "between":
      return `${attr} between ${val(rule.value)} and ${rule.value_max ?? "?"}${unit}${rule.inclusive === false ? " (exclusive)" : ""}`;
    case "present":
      return `${attr} present: ${val(rule.value)}`;
    case "absent":
      return `${attr} absent: ${val(rule.value)}`;
    case "within_days":
      return `${attr} within ${val(rule.value)} days`;
    default:
      return `${attr} ${String(rule.operator)} ${val(rule.value)}${unit}`;
  }
}

/** Summary of a criterion's full rule, including the second clause of a compound criterion. */
export function criterionRuleSummary(c: Pick<Criterion, "normalized_rule" | "secondary_rule" | "rule_combinator">): string {
  const first = ruleSummary(c.normalized_rule);
  return c.secondary_rule && c.rule_combinator ? `${first} ${c.rule_combinator} ${ruleSummary(c.secondary_rule)}` : first;
}
