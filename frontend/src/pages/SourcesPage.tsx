import { useState } from "react";

import { useAddCompany, useAdminCompanies, useRemoveCompany, useSourceHealth } from "../api/hooks";
import type { Company, NewCompanyRequest } from "../api/types";
import { PageHeader } from "../components/AppLayout";
import { RefreshButton } from "../components/RangeSelect";
import { TableSkeleton } from "../components/Skeleton";
import { formatLocalDate } from "../lib/formatDate";
import { companyHealthRows, jobTypesLabel, latestTimestamp, sourceLabel, successRate } from "../lib/sourceConfigFields";

const EMPTY_COMPANY: NewCompanyRequest = {
  company_name: "",
  source_kind: "greenhouse",
  board_token: "",
  board_name: "",
  intern_url: "",
  newgrad_url: "",
  fulltime_url: "",
};

const SOURCE_KINDS = [
  { value: "greenhouse", label: "greenhouse" },
  { value: "ashby", label: "ashby" },
  { value: "zyte", label: "zyte" },
  { value: "renderer", label: "renderer" },
];

const INPUT_CLASS =
  "rounded-none border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-neutral-500";

type FormMode = "closed" | "add" | "edit";

function CompanyFormModal({
  mode,
  company,
  onChange,
  onSubmit,
  onClose,
  isPending,
  status,
}: {
  mode: "add" | "edit";
  company: NewCompanyRequest;
  onChange: (patch: Partial<NewCompanyRequest>) => void;
  onSubmit: () => void;
  onClose: () => void;
  isPending: boolean;
  status: string;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      role="dialog"
      aria-modal="true"
      aria-label={mode === "edit" ? `Edit ${company.company_name}` : "Add a company"}
      onClick={(event) => event.target === event.currentTarget && onClose()}
    >
      <div className="w-full max-w-2xl rounded-none border border-neutral-300 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-sm font-semibold">{mode === "edit" ? `Editing ${company.company_name}` : "Add a company"}</h3>
          <button
            type="button"
            onClick={onClose}
            className="text-xs px-2 py-1 rounded-none border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-900"
          >
            Close
          </button>
        </div>

        <div className="grid sm:grid-cols-2 gap-3 mb-3">
          <input
            type="text"
            placeholder="Company name"
            value={company.company_name}
            onChange={(event) => onChange({ company_name: event.target.value })}
            disabled={mode === "edit"}
            className={`${INPUT_CLASS} disabled:opacity-60`}
          />
          <select
            value={company.source_kind}
            onChange={(event) => onChange({ source_kind: event.target.value })}
            className={INPUT_CLASS}
          >
            {SOURCE_KINDS.map((kind) => (
              <option key={kind.value} value={kind.value}>
                {kind.label}
              </option>
            ))}
          </select>
        </div>

        {company.source_kind === "greenhouse" && (
          <input
            type="text"
            placeholder="Greenhouse board token"
            value={company.board_token}
            onChange={(event) => onChange({ board_token: event.target.value })}
            className={`w-full mb-3 ${INPUT_CLASS}`}
          />
        )}
        {company.source_kind === "ashby" && (
          <input
            type="text"
            placeholder="Ashby board name (from jobs.ashbyhq.com/<board-name>)"
            value={company.board_name}
            onChange={(event) => onChange({ board_name: event.target.value })}
            className={`w-full mb-3 ${INPUT_CLASS}`}
          />
        )}

        <div className="grid sm:grid-cols-3 gap-3 mb-3">
          <input
            type="text"
            placeholder="Intern listings URL"
            value={company.intern_url}
            onChange={(event) => onChange({ intern_url: event.target.value })}
            className={INPUT_CLASS}
          />
          <input
            type="text"
            placeholder="New grad listings URL"
            value={company.newgrad_url}
            onChange={(event) => onChange({ newgrad_url: event.target.value })}
            className={INPUT_CLASS}
          />
          <input
            type="text"
            placeholder="Full-time listings URL"
            value={company.fulltime_url}
            onChange={(event) => onChange({ fulltime_url: event.target.value })}
            className={INPUT_CLASS}
          />
        </div>
        <p className="text-xs text-neutral-500 dark:text-neutral-500 mb-4">
          If the source can't filter by role (e.g. greenhouse/ashby/community), use the same URL for all three.
        </p>

        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={onSubmit}
            disabled={isPending}
            className="rounded-none bg-neutral-900 hover:opacity-50 disabled:opacity-40 dark:bg-neutral-100 text-white dark:text-neutral-900 text-sm font-medium px-3 py-1.5"
          >
            {mode === "edit" ? "Save" : "Add"}
          </button>
          <p className="text-sm text-neutral-500 dark:text-neutral-500">{status}</p>
        </div>
      </div>
    </div>
  );
}

export function SourcesPage() {
  const companies = useAdminCompanies();
  const health = useSourceHealth();
  const addCompany = useAddCompany();
  const removeCompany = useRemoveCompany();

  const [formMode, setFormMode] = useState<FormMode>("closed");
  const [formCompany, setFormCompany] = useState<NewCompanyRequest>(EMPTY_COMPANY);

  const healthSources = health.data?.sources ?? [];

  const openAddForm = () => {
    addCompany.reset();
    setFormCompany(EMPTY_COMPANY);
    setFormMode("add");
  };

  const openEditForm = (company: Company) => {
    addCompany.reset();
    setFormCompany({
      company_name: company.company_name,
      source_kind: company.source_kind,
      board_token: company.board_token ?? "",
      board_name: company.board_name ?? "",
      intern_url: company.intern_url ?? "",
      newgrad_url: company.newgrad_url ?? "",
      fulltime_url: company.fulltime_url ?? "",
    });
    setFormMode("edit");
  };

  const closeForm = () => {
    setFormMode("closed");
    setFormCompany(EMPTY_COMPANY);
  };

  const submit = () => {
    const name = formCompany.company_name.trim();
    if (!name) {
      return;
    }
    addCompany.mutate({ ...formCompany, company_name: name }, { onSuccess: closeForm });
  };

  const update = (patch: Partial<NewCompanyRequest>) => setFormCompany((current) => ({ ...current, ...patch }));

  const formStatus = addCompany.isPending
    ? formMode === "edit"
      ? "Saving..."
      : "Adding..."
    : addCompany.isError
      ? formMode === "edit"
        ? "Failed to save changes"
        : "Failed to add company"
      : "";

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
                    onClick={() => openEditForm(company)}
                    className="text-xs px-2 py-1 mr-2 rounded-none border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-900"
                  >
                    Edit
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
        <button
          type="button"
          onClick={openAddForm}
          className="rounded-none bg-neutral-900 hover:opacity-50 dark:bg-neutral-100 text-white dark:text-neutral-900 text-sm font-medium px-3 py-1.5"
        >
          Add company
        </button>
        <RefreshButton
          onClick={() => {
            void companies.refetch();
            void health.refetch();
          }}
        />
      </PageHeader>

      <div className="flex-1 min-h-0 border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 overflow-y-auto overflow-x-auto">
        {renderTable()}
      </div>

      {formMode !== "closed" && (
        <CompanyFormModal
          mode={formMode}
          company={formCompany}
          onChange={update}
          onSubmit={submit}
          onClose={closeForm}
          isPending={addCompany.isPending}
          status={formStatus}
        />
      )}
    </div>
  );
}
