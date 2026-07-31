import type { ReactNode } from "react";
import { Outlet } from "react-router-dom";

import { Sidebar } from "./Sidebar";

/** h-screen + overflow-hidden makes <main> the single scroll container, so pages
 * that fill the viewport (Activity, Sources) can use flex-1/min-h-0 and pages
 * that just grow (Metrics) still scroll. */
export function AppLayout() {
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 p-6 flex flex-col min-h-0 overflow-y-auto">
        <Outlet />
      </main>
    </div>
  );
}

export function PageHeader({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex items-center justify-between mb-6 shrink-0">
      <h2 className="text-xs font-semibold tracking-widest uppercase text-neutral-500 dark:text-neutral-500">
        {title}
      </h2>
      <div className="flex items-center gap-3">{children}</div>
    </div>
  );
}
