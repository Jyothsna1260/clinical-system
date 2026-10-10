// Timestamps without an offset are treated as UTC.
const NAIVE_DATETIME = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/;
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "—";
  const d = new Date(NAIVE_DATETIME.test(value) ? `${value}Z` : value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const dateOnly = DATE_ONLY.test(value);
  const d = new Date(NAIVE_DATETIME.test(value) ? `${value}Z` : value);
  if (Number.isNaN(d.getTime())) return value;
  // A calendar date has no time zone: format it as written instead of shifting it to local time.
  return d.toLocaleDateString(undefined, { dateStyle: "medium", ...(dateOnly ? { timeZone: "UTC" } : {}) });
}

export function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${Math.round(value * 100)}%`;
}

export function humanize(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(formatValue).join(", ");
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
