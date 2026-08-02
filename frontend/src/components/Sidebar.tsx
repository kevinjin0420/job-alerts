import { NavLink } from "react-router-dom";

import { useCurrentUser } from "../api/hooks";
import { ThemeToggle } from "./ThemeToggle";

const BASE_LINK_CLASS = "px-3 py-2.5 rounded-none";
const INACTIVE_CLASS = "text-neutral-600 hover:bg-neutral-100 dark:text-neutral-400 dark:hover:bg-neutral-900";
const ACTIVE_CLASS = "font-medium bg-neutral-900 text-white dark:bg-neutral-100 dark:text-neutral-900";

const USER_LINKS = [
  { to: "/listings", label: "Listings" },
  { to: "/metrics", label: "Metrics" },
  { to: "/config", label: "Config" },
  { to: "/profile", label: "Profile" },
];

const ADMIN_LINKS = [
  { to: "/logs", label: "Logs" },
  { to: "/llm-logs", label: "LLM Logs" },
  { to: "/sources", label: "Sources" },
  { to: "/admin", label: "Admin" },
  { to: "/activity", label: "Activity" },
];

function SidebarLink({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) => `${BASE_LINK_CLASS} ${isActive ? ACTIVE_CLASS : INACTIVE_CLASS}`}
    >
      {label}
    </NavLink>
  );
}

/** onClose only in the mobile drawer; the docked sidebar has nothing to close. */
export function Sidebar({ className = "", onClose }: { className?: string; onClose?: () => void }) {
  const { data: currentUser } = useCurrentUser();

  return (
    <aside
      className={`w-52 shrink-0 border-r border-neutral-200 dark:border-neutral-800 p-3 bg-neutral-50 dark:bg-neutral-950 ${className}`}
    >
      <div className="flex items-center justify-between mb-8">
        <div className="text-xs font-semibold tracking-widest uppercase">job alerts</div>
        <div className="flex items-center gap-2">
          <a
            href="https://github.com/kevinjin0420/job-alerts"
            target="_blank"
            rel="noopener"
            className="text-neutral-500 dark:text-neutral-500 hover:opacity-50"
            aria-label="View source"
          >
            <svg className="w-4 h-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
              <path d="M12 .5C5.73.5.5 5.73.5 12c0 5.09 3.29 9.4 7.86 10.93.57.1.78-.25.78-.55 0-.27-.01-1.15-.02-2.09-3.2.7-3.88-1.36-3.88-1.36-.53-1.34-1.29-1.7-1.29-1.7-1.05-.72.08-.71.08-.71 1.17.08 1.78 1.2 1.78 1.2 1.03 1.77 2.71 1.26 3.38.96.1-.75.4-1.26.73-1.55-2.56-.29-5.25-1.28-5.25-5.7 0-1.26.45-2.29 1.19-3.09-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11.1 11.1 0 0 1 5.79 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.24 2.76.12 3.05.74.8 1.19 1.83 1.19 3.09 0 4.43-2.7 5.4-5.27 5.69.42.36.78 1.08.78 2.17 0 1.57-.01 2.83-.01 3.22 0 .3.2.66.79.55A11.5 11.5 0 0 0 23.5 12c0-6.27-5.23-11.5-11.5-11.5z" />
            </svg>
          </a>
          <ThemeToggle />
          {onClose && (
            <button
              type="button"
              onClick={onClose}
              aria-label="Close navigation"
              className="-mr-1 p-1 text-neutral-500 dark:text-neutral-500 hover:opacity-50"
            >
              <svg className="w-4 h-4" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
                <path d="M6.28 5.22a.75.75 0 00-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 101.06 1.06L10 11.06l3.72 3.72a.75.75 0 101.06-1.06L11.06 10l3.72-3.72a.75.75 0 00-1.06-1.06L10 8.94 6.28 5.22z" />
              </svg>
            </button>
          )}
        </div>
      </div>
      <nav className="flex flex-col gap-1 text-sm">
        {USER_LINKS.map((link) => (
          <SidebarLink key={link.to} {...link} />
        ))}
        {currentUser?.is_admin && (
          <>
            <hr className="my-2 border-neutral-200 dark:border-neutral-800" />
            {ADMIN_LINKS.map((link) => (
              <SidebarLink key={link.to} {...link} />
            ))}
          </>
        )}
      </nav>
    </aside>
  );
}
