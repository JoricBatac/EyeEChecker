// Client-side twin of backend/app/core/expr.py, used to show/require exam fields as the clinician types.
import type { Expr, FormField } from "./types";

type Facts = Record<string, unknown>;

export function evaluate(expr: Expr, facts: Facts): boolean {
  if ("all" in expr) return expr.all.every((e) => evaluate(e, facts));
  if ("any" in expr) return expr.any.some((e) => evaluate(e, facts));
  if ("not" in expr) return !evaluate(expr.not, facts);
  const actual = facts[expr.fact];
  if (expr.op === "exists") return actual !== undefined && actual !== null;
  if (expr.op === "missing") return actual === undefined || actual === null;
  if (actual === undefined || actual === null) return false;
  const v = expr.value as never;
  switch (expr.op) {
    case "eq":
      return actual === v;
    case "ne":
      return actual !== v;
    case "in":
      return (v as unknown[]).includes(actual);
    case "not_in":
      return !(v as unknown[]).includes(actual);
    case "lt":
      return (actual as number) < v;
    case "lte":
      return (actual as number) <= v;
    case "gt":
      return (actual as number) > v;
    case "gte":
      return (actual as number) >= v;
    case "contains":
      return Array.isArray(actual) && actual.includes(v);
    case "contains_any":
      return Array.isArray(actual) && (v as unknown[]).some((x) => actual.includes(x));
    default:
      return false;
  }
}

export function examFacts(answers: Record<string, unknown>): Facts {
  return Object.fromEntries(Object.entries(answers).map(([k, v]) => [`exam.${k}`, v]));
}

export function isVisible(field: FormField, answers: Record<string, unknown>): boolean {
  return !field.show_if || evaluate(field.show_if, examFacts(answers));
}

export function isRequired(field: FormField, answers: Record<string, unknown>): boolean {
  return field.required || (!!field.required_if && evaluate(field.required_if, examFacts(answers)));
}

export function t(text: Record<string, string> | null | undefined, locale: string): string {
  if (!text) return "";
  return text[locale] ?? text.en ?? Object.values(text)[0] ?? "";
}
