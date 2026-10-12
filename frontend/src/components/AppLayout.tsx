import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import { CloseIcon, FileIcon, GridIcon, LogoutIcon, MenuIcon, UsersIcon } from "./Icons";
import { ThemeToggle } from "./ThemeToggle";
import { useToast } from "./Toast";
import { ROUTES } from "../lib/routes";

const NAV = [
  { to: ROUTES.dashboard, label: "Dashboard", Icon: GridIcon },
  { to: ROUTES.uploadTrial, label: "Upload protocol", Icon: FileIcon },
  { to: ROUTES.newPatient, label: "New patient", Icon: UsersIcon },
];

function navClass({ isActive }: { isActive: boolean }): string {
  return `flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
    isActive ? "bg-accent-50 text-accent-800" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900"
  }`;
}

export function BrandMark({ size = "md" }: { size?: "md" | "lg" }) {
  const cls = size === "lg" ? "h-11 w-11 rounded-xl text-lg" : "h-8 w-8 rounded-lg text-sm";
  return (
    <span
      aria-hidden="true"
      className={`flex shrink-0 items-center justify-center bg-gradient-to-br from-accent-500 to-violet-600 font-bold text-white shadow-md shadow-accent-600/30 ${cls}`}
    >
      <svg viewBox="0 0 20 20" width="1.1em" height="1.1em" fill="none" stroke="currentColor" strokeWidth={2.4} strokeLinecap="round" strokeLinejoin="round">
        <path d="M5 10.5l3 3 7-7" />
      </svg>
    </span>
  );
}

function initials(name: string): string {
  const parts = name.replace(/@.*/, "").split(/[\s._-]+/).filter(Boolean);
  return ((parts[0]?.[0] ?? "?") + (parts[1]?.[0] ?? "")).toUpperCase();
}

export function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const { notify } = useToast();
  const [open, setOpen] = useState(false);

  useEffect(() => setOpen(false), [location.pathname]);

  const onLogout = () => {
    logout();
    notify("info", "Signed out", "See you next time.");
    navigate(ROUTES.login, { replace: true });
  };

  const displayName = user ? user.full_name || user.email : "";

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2">
        Skip to content
      </a>
      <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-surface/75 backdrop-blur-lg">
        <div className="mx-auto flex h-16 max-w-7xl items-center justify-between gap-4 px-4 sm:px-6">
          <NavLink to={ROUTES.dashboard} className="flex min-w-0 items-center gap-2.5 rounded-lg">
            <BrandMark />
            <span className="min-w-0 leading-tight">
              <span className="block truncate font-semibold tracking-tight text-slate-900">Trial Eligibility</span>
              <span className="block truncate text-[11px] font-medium text-slate-500">Agentic screening support</span>
            </span>
          </NavLink>
          <nav aria-label="Primary" className="hidden items-center gap-1 md:flex">
            {NAV.map(({ to, label, Icon }) => (
              <NavLink key={to} to={to} className={navClass} end>
                <Icon className="text-base" />
                {label}
              </NavLink>
            ))}
          </nav>
          <div className="hidden items-center gap-3 md:flex">
            <ThemeToggle />
            {user ? (
              <span className="flex items-center gap-2" title={user.email}>
                <span
                  aria-hidden="true"
                  className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-emerald-400 to-accent-500 text-xs font-bold text-white"
                >
                  {initials(displayName)}
                </span>
                <span className="hidden max-w-[10rem] truncate text-sm font-medium text-slate-700 lg:block">{displayName}</span>
              </span>
            ) : null}
            <button type="button" onClick={onLogout} className="btn-ghost px-2.5 py-1.5" title="Log out">
              <LogoutIcon className="text-base" />
              <span className="sr-only lg:not-sr-only">Log out</span>
            </button>
          </div>
          <div className="flex items-center gap-2 md:hidden">
            <ThemeToggle />
            <button
              type="button"
              className="btn-ghost p-2"
              aria-expanded={open}
              aria-controls="mobile-nav"
              onClick={() => setOpen((o) => !o)}
            >
              {open ? <CloseIcon className="text-xl" /> : <MenuIcon className="text-xl" />}
              <span className="sr-only">{open ? "Close menu" : "Open menu"}</span>
            </button>
          </div>
        </div>
        {open ? (
          <nav id="mobile-nav" aria-label="Primary mobile" className="animate-fade-in border-t border-slate-200 bg-surface px-4 py-3 md:hidden">
            <div className="flex flex-col gap-1">
              {NAV.map(({ to, label, Icon }) => (
                <NavLink key={to} to={to} className={navClass} end>
                  <Icon className="text-base" />
                  {label}
                </NavLink>
              ))}
              {user ? <p className="px-3 pt-2 text-xs text-slate-600">Signed in as {user.email}</p> : null}
              <button type="button" onClick={onLogout} className="btn-secondary mt-2">
                <LogoutIcon /> Log out
              </button>
            </div>
          </nav>
        ) : null}
      </header>
      <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-6 sm:px-6 lg:py-8">
        <div key={location.pathname} className="animate-fade-up">
          <Outlet />
        </div>
      </main>
      <footer className="border-t border-slate-200 py-5">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-2 px-4 text-xs text-slate-500 sm:px-6">
          <p>Prototype clinical decision support. Supports, but does not replace, qualified clinical review.</p>
          <p>Synthetic data only · No real patient information</p>
        </div>
      </footer>
    </div>
  );
}
