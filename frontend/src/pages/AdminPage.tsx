import { useEffect, useState } from "react";

import {
  useAdminSettings,
  useAdminUsers,
  useInviteUser,
  useRemoveUser,
  useSaveClassifierModel,
  useTriggerScan,
} from "../api/hooks";
import { PageHeader } from "../components/AppLayout";
import { RefreshButton } from "../components/RangeSelect";
import { TableSkeleton } from "../components/Skeleton";

const CARD_CLASS = "max-w-md border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-3";
const LABEL_CLASS = "block text-xs font-medium uppercase tracking-wide text-neutral-500 dark:text-neutral-500 mb-2";
const INPUT_CLASS =
  "flex-1 rounded-none border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-neutral-500";
const PRIMARY_BUTTON_CLASS =
  "rounded-none bg-neutral-900 hover:opacity-50 disabled:opacity-40 dark:bg-neutral-100 text-white dark:text-neutral-900 text-sm font-medium px-3 py-1.5";
const STATUS_CLASS = "mt-2 text-sm text-neutral-500 dark:text-neutral-500";

function UsersTable() {
  const users = useAdminUsers();
  const removeUser = useRemoveUser();

  if (users.isPending) {
    return <TableSkeleton rows={5} columns={5} />;
  }
  if (users.isError) {
    return <div className="px-4 py-6 text-sm text-red-600 dark:text-red-400">Failed to load users</div>;
  }
  if (users.data.users.length === 0) {
    return <div className="px-4 py-6 text-sm text-neutral-500 dark:text-neutral-500">No users yet</div>;
  }

  return (
    <table className="w-full table-fixed border-collapse text-sm">
      <thead>
        <tr className="sticky top-0 bg-white dark:bg-neutral-900 border-b border-neutral-200 dark:border-neutral-800 text-left text-xs uppercase tracking-wide text-neutral-500 dark:text-neutral-500">
          <th className="px-3 py-2 font-medium w-4/12">Email</th>
          <th className="px-3 py-2 font-medium w-1/12">Role</th>
          <th className="px-3 py-2 font-medium w-3/12">ntfy topic</th>
          <th className="px-3 py-2 font-medium w-2/12">Notifications</th>
          <th className="px-3 py-2 font-medium w-2/12" />
        </tr>
      </thead>
      <tbody>
        {users.data.users.map((user) => {
          const notificationsEnabled = user.active !== false;
          return (
            <tr key={user.user_id} className="border-b border-neutral-100 dark:border-neutral-900 last:border-0">
              <td className="px-3 py-2 break-words font-mono">{user.user_id}</td>
              <td className="px-3 py-2">{user.is_admin ? "Admin" : "User"}</td>
              <td className="px-3 py-2 break-words font-mono">{user.ntfy_topic || "-"}</td>
              <td
                className={`px-3 py-2 ${notificationsEnabled ? "text-green-700 dark:text-green-400" : "text-red-600 dark:text-red-400"}`}
              >
                {notificationsEnabled ? "Enabled" : "Disabled"}
              </td>
              <td className="px-3 py-2 text-right">
                {!user.is_admin && (
                  <button
                    type="button"
                    onClick={() => removeUser.mutate(user.user_id)}
                    disabled={removeUser.isPending}
                    className="text-xs px-2 py-1 rounded-none border border-red-200 dark:border-red-900 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950 disabled:opacity-40"
                  >
                    Remove
                  </button>
                )}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function AdminPage() {
  const users = useAdminUsers();
  const inviteUser = useInviteUser();
  const settings = useAdminSettings();
  const saveModel = useSaveClassifierModel();
  const triggerScan = useTriggerScan();

  const [inviteEmail, setInviteEmail] = useState("");
  const [classifierModel, setClassifierModel] = useState("");

  const loadedModel = settings.data?.classifier_model;
  useEffect(() => {
    if (loadedModel !== undefined) {
      setClassifierModel(loadedModel);
    }
  }, [loadedModel]);

  const invite = () => {
    const email = inviteEmail.trim();
    if (!email) {
      return;
    }
    inviteUser.mutate(email, { onSuccess: () => setInviteEmail("") });
  };

  const inviteStatus = inviteUser.isPending
    ? "Inviting..."
    : inviteUser.isError
      ? "Failed to invite user"
      : inviteUser.isSuccess
        ? `Invited ${inviteUser.variables}`
        : "";

  const modelStatus = saveModel.isPending
    ? "Saving..."
    : saveModel.isError
      ? saveModel.error.message
      : saveModel.isSuccess
        ? "Saved"
        : "";

  const scanStatus = triggerScan.isPending
    ? "Triggering..."
    : triggerScan.isError
      ? "Failed to trigger scan"
      : triggerScan.isSuccess
        ? "Scan triggered - check Logs in a few seconds"
        : "";

  return (
    <>
      <PageHeader title="Users">
        <RefreshButton onClick={() => void users.refetch()} />
      </PageHeader>

      <div className={`${CARD_CLASS} mb-6`}>
        <label className={LABEL_CLASS}>Invite a user</label>
        <div className="flex gap-3">
          <input
            type="email"
            placeholder="friend@example.com"
            value={inviteEmail}
            onChange={(event) => setInviteEmail(event.target.value)}
            className={INPUT_CLASS}
          />
          <button type="button" onClick={invite} disabled={inviteUser.isPending} className={PRIMARY_BUTTON_CLASS}>
            Invite
          </button>
        </div>
        <p className={STATUS_CLASS}>{inviteStatus}</p>
      </div>

      <div className="border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 mb-10 max-h-[calc(100vh-160px)] overflow-y-auto overflow-x-hidden">
        <UsersTable />
      </div>

      <h2 className="text-xs font-semibold tracking-widest uppercase text-neutral-500 dark:text-neutral-500 mb-6">
        Global settings
      </h2>

      <div className={CARD_CLASS}>
        <label className={LABEL_CLASS}>Classifier model</label>
        <div className="flex gap-3">
          <input
            type="text"
            placeholder="qwen/qwen3.6-flash"
            value={classifierModel}
            onChange={(event) => setClassifierModel(event.target.value)}
            className={`${INPUT_CLASS} font-mono`}
          />
          <button
            type="button"
            onClick={() => classifierModel.trim() && saveModel.mutate(classifierModel.trim())}
            disabled={saveModel.isPending}
            className={PRIMARY_BUTTON_CLASS}
          >
            Save
          </button>
        </div>
        <p className={STATUS_CLASS}>{modelStatus}</p>
      </div>

      <div className={`${CARD_CLASS} mt-6`}>
        <label className={LABEL_CLASS}>Scan</label>
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => triggerScan.mutate()}
            disabled={triggerScan.isPending}
            className={PRIMARY_BUTTON_CLASS}
          >
            Run scan now
          </button>
          <p className="text-sm text-neutral-500 dark:text-neutral-500">{scanStatus}</p>
        </div>
      </div>

      <div className={`${CARD_CLASS} mt-6`}>
        <label className={LABEL_CLASS}>Billing</label>
        <div className="flex flex-col gap-2 text-sm">
          <a href="https://app.zyte.com/o/1001025" target="_blank" rel="noopener" className="hover:underline">
            Zyte dashboard &rarr;
          </a>
          <a href="https://openrouter.ai/settings/profile" target="_blank" rel="noopener" className="hover:underline">
            OpenRouter dashboard &rarr;
          </a>
        </div>
      </div>
    </>
  );
}
