import { useState } from "react";

import { useAddCompany, useAdminCompanies, useRemoveCompany, useSourceHealth } from "../api/hooks";
import type { Company, NewCompanyRequest } from "../api/types";
import { PageHeader } from "../components/AppLayout";
import { RefreshButton } from "../components/RangeSelect";
import { TableSkeleton } from "../components/Skeleton";
import { formatLocalDate } from "../lib/formatDate";
import {
  companyHealthRows,
  jobTypesLabel,
  latestTimestamp,
  sourceConfigFields,
  sourceLabel,
  successRate,
} from "../lib/sourceConfigFields";

const EMPTY_COMPANY: NewCompanyRequest = {
  company_name: "",
  source_kind: "community",
  board_token: "",
  board_name: "",
  intern_url: "",
  newgrad_url: "",
  fulltime_url: "",
};

const SOURCE_KINDS = [
  { value: "community", label: "Community filter only" },
  { value: "greenhouse", label: "Greenhouse-backed" },
  { value: "ashby", label: "Ashby-backed" },
  { value: "zyte", label: "Zyte-backed (paid, anti-bot bypass)" },
];

const INPUT_CLASS =
  "rounded-none border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-neutral-500";

function SourceConfigModal({ company, onClose }: { company: Company; onClose: () => void }) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(event) => event.target === event.currentTarget && onClose()}
    >
      <div className="w-full max-w-lg rounded-none border border-neutral-300 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold">{company.company_name} - Source config</h3>
          <button
            type="button"
            onClick={onClose}
            className="text-xs px-2 py-1 rounded-none border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-900"
          >
            Close
          </button>
        </div>
        <dl className="space-y-3">
          {sourceConfigFields(company).map(([label, value]) => (
            <div key={label}>
              <dt className="text-xs uppercase tracking-wide text-neutral-500 dark:text-neutral-500 mb-1">{label}</dt>
              <dd
                className={`font-mono text-xs break-all ${value ? "" : "text-neutral-400 dark:text-neutral-600"}`}
              >
                {value || "not set"}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}

export function SourcesPage() {
  const companies = useAdminCompanies();
  const health = useSourceHealth();
  const addCompany = useAddCompany();
  const removeCompany = useRemoveCompany();

  const [newCompany, setNewCompany] = useState<NewCompanyRequest>(EMPTY_COMPANY);
  const [modalCompany, setModalCompany] = useState<Company | null>(null);

  const healthSources = health.data?.sources ?? [];

  const submit = () => {
    const name = newCompany.company_name.trim();
    if (!name) {
      return;
    }
    addCompany.mutate({ ...newCompany, company_name: name }, { onSuccess: () => setNewCompany(EMPTY_COMPANY) });
  };

  const addStatus = addCompany.isPending
    ? "Adding..."
    : addCompany.isError
      ? "Failed to add company"
      : addCompany.isSuccess
        ? `Added ${addCompany.variables.company_name}`
        : "";

  const update = (patch: Partial<NewCompanyRequest>) => setNewCompany((current) => ({ ...current, ...patch }));

  const renderTable = () => {
    if (companies.isPending || health.isPending) {
      return <TableSkeleton rows={6} columns={7} />;
    }
    if (companies.isError || health.isError) {
      return <div className="px-4 py-6 text-sm text-red-600 dark:text-red-400">Failed to load companies</div>;
    }
    if (companies.data.companies.length === 0) {
      return <div className="px-4 py-6 text-sm text-neutral-500 dark:text-neutral-500">No companies yet</div>;
    }

    return (
      <table className="w-full min-w-[48rem] table-fixed border-collapse text-sm">
        <thead>
          <tr className="sticky top-0 bg-white dark:bg-neutral-900 border-b border-neutral-200 dark:border-neutral-800 text-left text-xs uppercase tracking-wide text-neutral-500 dark:text-neutral-500">
            <th className="px-3 py-2 font-medium w-2/12">Name</th>
            <th className="px-3 py-2 font-medium w-2/12">Source</th>
            <th className="px-3 py-2 font-medium w-2/12">Job types</th>
            <th className="px-3 py-2 font-medium w-2/12">Last success</th>
            <th className="px-3 py-2 font-medium w-2/12">Last failure</th>
            <th className="px-3 py-2 font-medium w-1/12">Success rate</th>
            <th className="px-3 py-2 font-medium w-2/12" />
          </tr>
        </thead>
        <tbody>
          {companies.data.companies.map((company) => {
            const rows = companyHealthRows(company, healthSources);
            const lastSuccess = latestTimestamp(rows, "last_success_at");
            const lastFailure = latestTimestamp(rows, "last_failure_at");
            const neverRan = rows.length === 0;
            return (
              <tr
                key={company.company_name}
                className="border-b border-neutral-100 dark:border-neutral-900 last:border-0"
              >
                <td className="px-3 py-2 break-words">{company.company_name}</td>
                <td className="px-3 py-2 font-mono text-xs break-all">{sourceLabel(company)}</td>
                <td className="px-3 py-2">{jobTypesLabel(company)}</td>
                <td className="px-3 py-2 font-mono text-xs">
                  {neverRan ? "Never run" : lastSuccess ? formatLocalDate(lastSuccess) : "-"}
                </td>
                <td className="px-3 py-2 font-mono text-xs">
                  {neverRan ? "Never run" : lastFailure ? formatLocalDate(lastFailure) : "-"}
                </td>
                <td className="px-3 py-2">{successRate(rows)}</td>
                <td className="px-3 py-2 text-right">
                  <button
                    type="button"
                    onClick={() => setModalCompany(company)}
                    className="text-xs px-2 py-1 mr-2 rounded-none border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-900"
                  >
                    Config
                  </button>
                  <button
                    type="button"
                    onClick={() => removeCompany.mutate(company.company_name)}
                    disabled={removeCompany.isPending}
                    className="text-xs px-2 py-1 rounded-none border border-red-200 dark:border-red-900 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950 disabled:opacity-40"
                  >
                    Remove
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    );
  };

  return (
    <div className="flex flex-col min-h-0 flex-1">
      <PageHeader title="Companies">
        <RefreshButton
          onClick={() => {
            void companies.refetch();
            void health.refetch();
          }}
        />
      </PageHeader>

      <div className="border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-3 mb-6 shrink-0">
        <label className="block text-xs font-medium uppercase tracking-wide text-neutral-500 dark:text-neutral-500 mb-2">
          Add a company
        </label>
        <div className="grid sm:grid-cols-3 gap-3 mb-3">
          <input
            type="text"
            placeholder="Company name"
            value={newCompany.company_name}
            onChange={(event) => update({ company_name: event.target.value })}
            className={INPUT_CLASS}
          />
          <select
            value={newCompany.source_kind}
            onChange={(event) => update({ source_kind: event.target.value })}
            className={INPUT_CLASS}
          >
            {SOURCE_KINDS.map((kind) => (
              <option key={kind.value} value={kind.value}>
                {kind.label}
              </option>
            ))}
          </select>
          <button
            type="button"
            onClick={submit}
            disabled={addCompany.isPending}
            className="rounded-none bg-neutral-900 hover:opacity-50 disabled:opacity-40 dark:bg-neutral-100 text-white dark:text-neutral-900 text-sm font-medium px-3 py-1.5"
          >
            Add
          </button>
        </div>

        {newCompany.source_kind === "greenhouse" && (
          <input
            type="text"
            placeholder="Greenhouse board token"
            value={newCompany.board_token}
            onChange={(event) => update({ board_token: event.target.value })}
            className={`w-full mb-3 ${INPUT_CLASS}`}
          />
        )}
        {newCompany.source_kind === "ashby" && (
          <input
            type="text"
            placeholder="Ashby board name (from jobs.ashbyhq.com/<board-name>)"
            value={newCompany.board_name}
            onChange={(event) => update({ board_name: event.target.value })}
            className={`w-full mb-3 ${INPUT_CLASS}`}
          />
        )}

        <div className="grid sm:grid-cols-3 gap-3 mb-3">
          <input
            type="text"
            placeholder="Intern listings URL"
            value={newCompany.intern_url}
            onChange={(event) => update({ intern_url: event.target.value })}
            className={INPUT_CLASS}
          />
          <input
            type="text"
            placeholder="New grad listings URL"
            value={newCompany.newgrad_url}
            onChange={(event) => update({ newgrad_url: event.target.value })}
            className={INPUT_CLASS}
          />
          <input
            type="text"
            placeholder="Full-time listings URL"
            value={newCompany.fulltime_url}
            onChange={(event) => update({ fulltime_url: event.target.value })}
            className={INPUT_CLASS}
          />
        </div>
        <p className="text-xs text-neutral-500 dark:text-neutral-500 mb-2">
          If the source can't filter by role (e.g. greenhouse/ashby/community), use the same URL for all three.
        </p>
        <p className="mt-2 text-sm text-neutral-500 dark:text-neutral-500">{addStatus}</p>
      </div>

      <div className="flex-1 min-h-0 border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 overflow-y-auto overflow-x-auto">
        {renderTable()}
      </div>

      {modalCompany && <SourceConfigModal company={modalCompany} onClose={() => setModalCompany(null)} />}
    </div>
  );
}
