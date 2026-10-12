import type { KeyboardEvent } from "react";
import { useTheme, type ThemePreference } from "../theme/ThemeContext";
import { MonitorIcon, MoonIcon, SunIcon } from "./Icons";

const OPTIONS: { value: ThemePreference; label: string; Icon: typeof SunIcon }[] = [
  { value: "light", label: "Light", Icon: SunIcon },
  { value: "dark", label: "Dark", Icon: MoonIcon },
  { value: "system", label: "System", Icon: MonitorIcon },
];

/** Segmented Light / Dark / System switch with a sliding indicator. */
export function ThemeToggle({ showLabels = false }: { showLabels?: boolean }) {
  const { preference, setPreference } = useTheme();
  const index = OPTIONS.findIndex((o) => o.value === preference);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
    e.preventDefault();
    const next = OPTIONS[(index + (e.key === "ArrowRight" ? 1 : OPTIONS.length - 1)) % OPTIONS.length];
    if (!next) return;
    setPreference(next.value);
    e.currentTarget.querySelector<HTMLButtonElement>(`[data-value="${next.value}"]`)?.focus();
  };

  return (
    <div
      role="radiogroup"
      aria-label="Color theme"
      onKeyDown={onKeyDown}
      className="relative inline-grid grid-cols-3 rounded-full border border-slate-200 bg-slate-100/80 p-0.5"
    >
      <span
        aria-hidden="true"
        className="absolute bottom-0.5 top-0.5 rounded-full bg-surface shadow-card transition-transform duration-300 ease-out"
        style={{ width: `calc((100% - 4px) / 3)`, left: 2, transform: `translateX(${index * 100}%)` }}
      />
      {OPTIONS.map(({ value, label, Icon }) => {
        const active = value === preference;
        return (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={active}
            aria-label={`${label} theme`}
            title={`${label} theme`}
            data-value={value}
            tabIndex={active ? 0 : -1}
            onClick={() => setPreference(value)}
            className={`relative z-10 flex items-center justify-center gap-1.5 rounded-full px-2.5 py-1.5 text-xs font-medium transition-colors ${
              active ? "text-slate-900" : "text-slate-500 hover:text-slate-800"
            }`}
          >
            <Icon className="text-sm" />
            {showLabels ? <span>{label}</span> : null}
          </button>
        );
      })}
    </div>
  );
}
