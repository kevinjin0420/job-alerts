import { useEffect, useState, type ReactNode } from "react";
import { Outlet, useLocation } from "react-router-dom";

import { Sidebar } from "./Sidebar";

/** dvh not vh: 100vh counts the collapsing mobile URL bar. overflow-hidden makes <main> the only scroller. */
export function AppLayout() {
  const [isNavOpen, setIsNavOpen] = useState(false);
  const location = useLocation();

  // Navigating with the drawer open would leave it covering the page you just opened.
  useEffect(() => {
    setIsNavOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!isNavOpen) {
      return;
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsNavOpen(false);
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [isNavOpen]);

  return (
    <div className="flex h-dvh overflow-hidden">
      <Sidebar className="hidden md:block" />

      {isNavOpen && (
        <div className="md:hidden fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label="Navigation">
          <button
            type="button"
            aria-label="Close navigation"
            onClick={() => setIsNavOpen(false)}
            className="absolute inset-0 w-full h-full bg-black/40"
          />
          <Sidebar className="relative z-50 h-full overflow-y-auto" onClose={() => setIsNavOpen(false)} />
        </div>
      )}

      {/* min-w-0: flex items default to min-width:auto, letting wide tables stretch the page. */}
      <div className="flex-1 min-w-0 flex flex-col min-h-0">
        <div className="md:hidden flex items-center gap-3 border-b border-neutral-200 dark:border-neutral-800 px-4 py-3 shrink-0">
          <button
            type="button"
            onClick={() => setIsNavOpen(true)}
            aria-label="Open navigation"
            aria-expanded={isNavOpen}
            className="-ml-2 p-2 text-neutral-600 dark:text-neutral-400 hover:opacity-50"
          >
            <svg className="w-5 h-5" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
              <path
                fillRule="evenodd"
                d="M3 5.5A.75.75 0 013.75 4.75h12.5a.75.75 0 010 1.5H3.75A.75.75 0 013 5.5zm0 4.5a.75.75 0 01.75-.75h12.5a.75.75 0 010 1.5H3.75A.75.75 0 013 10zm0 4.5a.75.75 0 01.75-.75h12.5a.75.75 0 010 1.5H3.75a.75.75 0 01-.75-.75z"
                clipRule="evenodd"
              />
            </svg>
          </button>
          <span className="text-xs font-semibold tracking-widest uppercase">job alerts</span>
        </div>

        <main className="flex-1 min-w-0 p-4 sm:p-6 flex flex-col min-h-0 overflow-y-auto">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 mb-6 shrink-0 min-h-8">
      <h2 className="text-xs font-semibold tracking-widest uppercase text-neutral-500 dark:text-neutral-500">
        {title}
      </h2>
      <div className="flex flex-wrap items-center gap-3">{children}</div>
    </div>
  );
}
