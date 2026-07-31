export function Spinner({ className = "" }: { className?: string }) {
  return (
    <svg
      className={`animate-spin ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v3a5 5 0 00-5 5H4z" />
    </svg>
  );
}

export function FullPageSpinner() {
  return (
    <div className="min-h-screen flex items-center justify-center text-neutral-400 dark:text-neutral-600">
      <Spinner className="w-6 h-6" />
    </div>
  );
}

export function SkeletonBar({ className = "" }: { className?: string }) {
  return <div className={`skeleton bg-neutral-200 dark:bg-neutral-800 ${className}`} />;
}

export function TableSkeleton({ rows = 8, columns = 8 }: { rows?: number; columns?: number }) {
  return (
    <div className="divide-y divide-neutral-200 dark:divide-neutral-800">
      {Array.from({ length: rows }, (_, rowIndex) => (
        <div key={rowIndex} className="flex gap-3 px-3 py-3">
          {Array.from({ length: columns }, (_, columnIndex) => (
            <SkeletonBar key={columnIndex} className="h-4 flex-1" />
          ))}
        </div>
      ))}
    </div>
  );
}
