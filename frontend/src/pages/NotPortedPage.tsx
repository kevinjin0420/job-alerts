import { PageHeader } from "../components/AppLayout";

/** Placeholder for the pages still served by the old dashboard. Removed as each one lands. */
export function NotPortedPage({ title }: { title: string }) {
  return (
    <>
      <PageHeader title={title} />
      <div className="border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 px-4 py-6 text-sm text-neutral-500 dark:text-neutral-500">
        Not ported yet - still served by the old dashboard.
      </div>
    </>
  );
}
