import { describe, expect, it } from "vitest";
import { formatValue, humanize } from "../format";
import { findExcerpt } from "../highlight";
import { emptyForm, formToProfile, parseProfileJson, profileToForm } from "../patientForm";
import { criterionRuleSummary, ruleSummary } from "../rules";

describe("rules", () => {
  it("summarises single and compound rules", () => {
    expect(ruleSummary({ attribute: "egfr", operator: "gte", value: 30, unit: "mL/min/1.73m2" })).toBe(
      "egfr ≥ 30 mL/min/1.73m2",
    );
    expect(
      criterionRuleSummary({
        normalized_rule: { attribute: "creatinine", operator: "gt", value: 1.5, unit: "mg/dL" },
        secondary_rule: { attribute: "crcl", operator: "lt", value: 40, unit: "mL/min" },
        rule_combinator: "or",
      }),
    ).toBe("creatinine > 1.5 mg/dL or crcl < 40 mL/min");
    expect(criterionRuleSummary({ normalized_rule: null })).toBe("Not machine-normalized (free text only)");
  });
});

describe("findExcerpt", () => {
  it("finds an excerpt across PDF line breaks and case differences", () => {
    const page = "Inclusion criteria:\n1. eGFR must not\nbe below 30 mL/min";
    const m = findExcerpt(page, "eGFR must not be below 30");
    expect(m).not.toBeNull();
    expect(page.slice(m!.start, m!.end).replace(/\s+/g, " ")).toBe("eGFR must not be below 30");
  });

  it("returns null when the excerpt is absent", () => {
    expect(findExcerpt("Exclusion criteria", "pregnancy")).toBeNull();
  });
});

describe("patient form", () => {
  it("round-trips a profile through the form", () => {
    const profile = {
      as_of: "2026-10-01",
      demographics: { age: 69, sex: "male" as const },
      labs: [{ name: "eGFR", value: 28, unit: "mL/min/1.73m2", observed_at: "2026-09-25" }],
      diagnoses: [{ name: "Type 2 diabetes mellitus" }],
      medications: [],
      history: [],
    };
    const built = formToProfile(profileToForm("Patient A", profile));
    expect(built.errors).toEqual([]);
    expect(built.profile?.labs?.[0]).toEqual(profile.labs[0]);
    expect(built.profile?.demographics?.age).toBe(69);
  });

  it("reports invalid values instead of guessing", () => {
    const form = { ...emptyForm(), age: "abc" };
    const built = formToProfile(form);
    expect(built.profile).toBeNull();
    expect(built.errors.join(" ")).toMatch(/Age must be a number/);
  });

  it("imports JSON with a label wrapper and lists unknown fields", () => {
    const parsed = parseProfileJson(JSON.stringify({ label: "P", profile: { demographics: { age: 50 }, extra: 1 } }));
    expect(parsed.label).toBe("P");
    expect(parsed.ignored).toContain("extra");
  });

  it("rejects malformed JSON with a readable error", () => {
    expect(() => parseProfileJson("{not json")).toThrow(/Invalid JSON/);
  });
});

describe("format", () => {
  it("formats values for display", () => {
    expect(formatValue(null)).toBe("—");
    expect(formatValue([1, "a"])).toBe("1, a");
    expect(formatValue({ a: 1 })).toBe('{"a":1}');
    expect(humanize("MORE_INFORMATION_REQUIRED")).toMatch(/more information required/i);
  });
});
