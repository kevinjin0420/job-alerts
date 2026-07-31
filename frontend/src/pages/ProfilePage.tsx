import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  useCurrentUser,
  useDeleteAccount,
  useGenerateApiKey,
  useProfile,
  useRemoveResume,
  useSaveConfig,
  useSaveNtfyTopic,
  useSaveResumeUrl,
  useSetSubscription,
  useTestNotification,
  useUploadResume,
  useUserConfig,
} from "../api/hooks";
import { useAuth } from "../auth/AuthContext";
import { PageHeader } from "../components/AppLayout";

const CARD_CLASS = "border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-3";
const LABEL_CLASS = "block text-xs font-medium uppercase tracking-wide text-neutral-500 dark:text-neutral-500 mb-2";
const INPUT_CLASS =
  "flex-1 min-w-[12rem] rounded-none border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-1 focus:ring-neutral-500";
const PRIMARY_BUTTON_CLASS =
  "rounded-none bg-neutral-900 hover:opacity-50 disabled:opacity-40 dark:bg-neutral-100 text-white dark:text-neutral-900 text-sm font-medium px-3 py-1.5";
const SECONDARY_BUTTON_CLASS =
  "rounded-none border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-900 disabled:opacity-40 text-sm font-medium px-3 py-1.5";

function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result;
      const base64 = typeof result === "string" ? result.split(",").pop() : undefined;
      if (base64 === undefined) {
        reject(new Error("could not read file"));
        return;
      }
      resolve(base64);
    };
    reader.onerror = () => reject(new Error("could not read file"));
    reader.readAsDataURL(file);
  });
}

type ResumeTab = "upload" | "url";

function ResumeCard() {
  const profile = useProfile();
  const uploadResume = useUploadResume();
  const saveResumeUrl = useSaveResumeUrl();
  const removeResume = useRemoveResume();

  const [tab, setTab] = useState<ResumeTab>("upload");
  const [resumeUrl, setResumeUrl] = useState("");
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [localError, setLocalError] = useState<string | null>(null);

  const loadedProfile = profile.data;
  useEffect(() => {
    if (!loadedProfile) {
      return;
    }
    if (loadedProfile.resume_url) {
      setTab("url");
      setResumeUrl(loadedProfile.resume_url);
    } else {
      setResumeUrl("");
      if (loadedProfile.resume_filename) {
        setTab("upload");
      }
    }
  }, [loadedProfile]);

  const upload = async () => {
    setLocalError(null);
    const file = fileInputRef.current?.files?.[0];
    if (!file) {
      setLocalError("Choose a PDF first");
      return;
    }
    try {
      const contentBase64 = await readFileAsBase64(file);
      uploadResume.mutate(
        { filename: file.name, content_base64: contentBase64 },
        {
          onSuccess: () => {
            if (fileInputRef.current) {
              fileInputRef.current.value = "";
            }
          },
        },
      );
    } catch {
      setLocalError("Upload failed");
    }
  };

  const statusText = (): string => {
    if (localError) {
      return localError;
    }
    if (uploadResume.isPending) {
      return "Uploading…";
    }
    if (saveResumeUrl.isPending) {
      return "Checking URL…";
    }
    if (uploadResume.isError) {
      return uploadResume.error.message;
    }
    if (saveResumeUrl.isError) {
      return saveResumeUrl.error.message;
    }
    if (profile.isPending) {
      return "Loading…";
    }
    if (profile.isError) {
      return "Failed to load resume status";
    }
    const data = profile.data;
    if (!data?.resume_filename) {
      return "No resume set yet";
    }
    if (data.resume_url) {
      return data.resume_fetch_error
        ? `${data.resume_url} - fetch failed: ${data.resume_fetch_error}`
        : data.resume_url;
    }
    const uploadedAt = data.resume_uploaded_at
      ? new Date(data.resume_uploaded_at * 1000).toLocaleString()
      : "unknown time";
    return `${data.resume_filename} - uploaded ${uploadedAt}`;
  };

  const tabClass = (isActive: boolean) =>
    `px-3 py-1.5 text-sm font-medium border-b-2 ${
      isActive
        ? "border-neutral-900 dark:border-neutral-100 text-neutral-900 dark:text-neutral-100"
        : "border-transparent text-neutral-500 dark:text-neutral-500"
    }`;

  const hasResume = Boolean(profile.data?.resume_filename);
  const resumeText = profile.data?.resume_text;

  return (
    <div className={CARD_CLASS}>
      <label className={LABEL_CLASS}>Resume</label>
      <p className="text-sm text-neutral-500 dark:text-neutral-500 mb-3">
        Adds a 0-100 fit score on Listings; doesn't affect notifications. Only one source is active at a time.
      </p>
      <div className="text-sm text-neutral-500 dark:text-neutral-500 mb-3">{statusText()}</div>

      <div className="flex gap-1 mb-3 border-b border-neutral-200 dark:border-neutral-800">
        <button type="button" onClick={() => setTab("upload")} className={tabClass(tab === "upload")}>
          Upload
        </button>
        <button type="button" onClick={() => setTab("url")} className={tabClass(tab === "url")}>
          From URL
        </button>
      </div>

      {tab === "upload" ? (
        <div>
          <input
            ref={fileInputRef}
            type="file"
            accept="application/pdf"
            className="w-full mb-3 text-sm file:mr-3 file:rounded-none file:border-0 file:bg-neutral-900 file:text-white dark:file:bg-neutral-100 dark:file:text-neutral-900 file:text-sm file:font-medium file:px-3 file:py-1.5"
          />
          <button
            type="button"
            onClick={() => void upload()}
            disabled={uploadResume.isPending}
            className={PRIMARY_BUTTON_CLASS}
          >
            Upload
          </button>
        </div>
      ) : (
        <div>
          <div className="flex flex-wrap gap-3 mb-2">
            <input
              type="url"
              placeholder="https://example.com/resume.pdf"
              value={resumeUrl}
              onChange={(event) => setResumeUrl(event.target.value)}
              className={INPUT_CLASS}
            />
            <button
              type="button"
              onClick={() => {
                setLocalError(null);
                const url = resumeUrl.trim();
                if (!url) {
                  setLocalError("Enter a URL first");
                  return;
                }
                saveResumeUrl.mutate(url);
              }}
              disabled={saveResumeUrl.isPending}
              className={PRIMARY_BUTTON_CLASS}
            >
              Save
            </button>
          </div>
          <p className="text-xs text-neutral-500 dark:text-neutral-500">
            Fetched live each time - no re-sync needed.
          </p>
        </div>
      )}

      {hasResume && (
        <button
          type="button"
          onClick={() => removeResume.mutate()}
          disabled={removeResume.isPending}
          className="mt-3 text-xs px-3 py-1.5 rounded-none border border-red-200 dark:border-red-900 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950 disabled:opacity-40"
        >
          Remove resume
        </button>
      )}

      {hasResume && resumeText && (
        <details className="mt-3">
          <summary className="text-sm text-neutral-500 dark:text-neutral-500 cursor-pointer">
            View extracted text
          </summary>
          <pre className="mt-2 max-h-64 overflow-y-auto whitespace-pre-wrap rounded-none border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-xs">
            {resumeText}
          </pre>
        </details>
      )}
    </div>
  );
}

export function ProfilePage() {
  const currentUser = useCurrentUser();
  const config = useUserConfig();
  const saveConfig = useSaveConfig();
  const saveNtfyTopic = useSaveNtfyTopic();
  const testNotification = useTestNotification();
  const generateApiKey = useGenerateApiKey();
  const setSubscription = useSetSubscription();
  const deleteAccount = useDeleteAccount();
  const { signOut } = useAuth();
  const navigate = useNavigate();

  const [emailTo, setEmailTo] = useState("");
  const [ntfyTopic, setNtfyTopic] = useState("");
  const [ntfyStatus, setNtfyStatus] = useState("");

  const loadedEmails = config.data?.email_to;
  useEffect(() => {
    if (loadedEmails) {
      setEmailTo(loadedEmails.join(", "));
    }
  }, [loadedEmails]);

  const loadedTopic = currentUser.data?.ntfy_topic;
  useEffect(() => {
    if (loadedTopic !== undefined) {
      setNtfyTopic(loadedTopic);
    }
  }, [loadedTopic]);

  const accountActive = currentUser.data?.active !== false;

  const saveEmail = () =>
    saveConfig.mutate({
      email_to: emailTo
        .split(",")
        .map((item) => item.trim())
        .filter(Boolean),
    });

  const emailStatus = saveConfig.isPending
    ? "Saving..."
    : saveConfig.isError
      ? "Failed to save"
      : saveConfig.isSuccess
        ? "Saved"
        : "";

  const saveTopic = () => {
    const topic = ntfyTopic.trim();
    if (!topic) {
      setNtfyStatus("Enter a topic first");
      return;
    }
    setNtfyStatus("Saving...");
    saveNtfyTopic.mutate(topic, {
      onSuccess: () => setNtfyStatus("Saved"),
      onError: (error) => setNtfyStatus(error.message || "Failed to save"),
    });
  };

  const sendTest = () => {
    const topic = ntfyTopic.trim();
    if (!topic) {
      setNtfyStatus("Enter a topic first");
      return;
    }
    setNtfyStatus("Sending test…");
    testNotification.mutate(topic, {
      onSuccess: () => setNtfyStatus("Sent - check your ntfy app"),
      onError: (error) => setNtfyStatus(error.message || "Failed to send"),
    });
  };

  const removeAccount = () => {
    const confirmed = window.confirm(
      "Delete your account? This permanently removes your config, resume, and listing history. This cannot be undone.",
    );
    if (!confirmed) {
      return;
    }
    deleteAccount.mutate(undefined, {
      onSuccess: () => {
        signOut();
        void navigate("/login", { replace: true });
      },
    });
  };

  const dangerStatus = deleteAccount.isPending
    ? "Deleting…"
    : deleteAccount.isError
      ? deleteAccount.error.message
      : setSubscription.isPending
        ? accountActive
          ? "Pausing…"
          : "Resuming…"
        : setSubscription.isError
          ? "Failed to update"
          : setSubscription.isSuccess
            ? accountActive
              ? "Resumed - scans will include you again"
              : "Paused - no scans or notifications until you resume"
            : "";

  return (
    <div className="flex flex-col flex-1">
      <PageHeader title="Profile">
        <span className="text-sm text-neutral-500 dark:text-neutral-500">{emailStatus}</span>
      </PageHeader>

      <div className="grid lg:grid-cols-2 gap-6 items-start">
        <div className="space-y-6">
          <div className={CARD_CLASS}>
            <label className={LABEL_CLASS}>Email recipient</label>
            <div className="flex flex-wrap gap-3">
              <input
                type="text"
                placeholder="you@example.com"
                value={emailTo}
                onChange={(event) => setEmailTo(event.target.value)}
                className={INPUT_CLASS}
              />
              <button type="button" onClick={saveEmail} disabled={saveConfig.isPending} className={PRIMARY_BUTTON_CLASS}>
                Save
              </button>
            </div>
          </div>

          <div className={CARD_CLASS}>
            <label className={LABEL_CLASS}>Notification channel</label>
            <p className="text-sm text-neutral-500 dark:text-neutral-500 mb-3">
              Your{" "}
              <a href="https://ntfy.sh" target="_blank" rel="noopener" className="underline hover:opacity-50">
                ntfy
              </a>{" "}
              topic. See{" "}
              <a
                href="https://github.com/kevinjin0420/job-alerts/blob/main/docs/ntfy-setup.md"
                target="_blank"
                rel="noopener"
                className="underline hover:opacity-50"
              >
                docs/ntfy-setup.md
              </a>{" "}
              for setup instructions.
            </p>
            <div className="flex flex-wrap gap-3">
              <input
                type="text"
                placeholder="job-alerts-xxxxxxxxxxxx"
                value={ntfyTopic}
                onChange={(event) => setNtfyTopic(event.target.value)}
                className={INPUT_CLASS}
              />
              <button type="button" onClick={saveTopic} disabled={saveNtfyTopic.isPending} className={PRIMARY_BUTTON_CLASS}>
                Save
              </button>
              <button
                type="button"
                onClick={sendTest}
                disabled={testNotification.isPending}
                className={SECONDARY_BUTTON_CLASS}
              >
                Send test
              </button>
            </div>
            <p className="mt-2 text-sm text-neutral-500 dark:text-neutral-500">{ntfyStatus}</p>
          </div>

          <div className={CARD_CLASS}>
            <label className={LABEL_CLASS}>Agent API key</label>
            <p className="text-sm text-neutral-500 dark:text-neutral-500 mb-3">
              For your own agent to read/update this config. See{" "}
              <a
                href="https://github.com/kevinjin0420/job-alerts/blob/main/docs/agent-skill.md"
                target="_blank"
                rel="noopener"
                className="underline hover:opacity-50"
              >
                docs/agent-skill.md
              </a>
              . Shown once.
            </p>
            {generateApiKey.data && (
              <div className="mb-3 rounded-none border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm font-mono break-all">
                {generateApiKey.data.api_key}
              </div>
            )}
            <button
              type="button"
              onClick={() => generateApiKey.mutate()}
              disabled={generateApiKey.isPending}
              className={SECONDARY_BUTTON_CLASS}
            >
              Generate new API key
            </button>
          </div>
        </div>

        <div className="space-y-6">
          <ResumeCard />
        </div>
      </div>

      <div className="mt-auto pt-6 grid lg:grid-cols-2 gap-6">
        <div className="border border-red-200 dark:border-red-900 bg-white dark:bg-neutral-900 p-3">
          <label className="block text-xs font-medium uppercase tracking-wide text-red-600 dark:text-red-400 mb-2">
            Danger zone
          </label>

          <div className="flex flex-wrap items-center justify-between gap-4 py-2 border-b border-neutral-100 dark:border-neutral-900">
            <div>
              <p className="text-sm font-medium">Pause notifications</p>
              <p className="text-sm text-neutral-500 dark:text-neutral-500">
                Stops scans and notifications for you without deleting anything. Resume anytime.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setSubscription.mutate(!accountActive)}
              disabled={setSubscription.isPending}
              className={`shrink-0 ${SECONDARY_BUTTON_CLASS}`}
            >
              {accountActive ? "Pause" : "Resume"}
            </button>
          </div>

          <div className="flex flex-wrap items-center justify-between gap-4 py-2">
            <div>
              <p className="text-sm font-medium">Delete account</p>
              <p className="text-sm text-neutral-500 dark:text-neutral-500">
                Permanently deletes your account, config, resume, and listing history. Cannot be undone.
              </p>
            </div>
            <button
              type="button"
              onClick={removeAccount}
              disabled={deleteAccount.isPending}
              className="shrink-0 rounded-none border border-red-200 dark:border-red-900 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950 disabled:opacity-40 text-sm font-medium px-3 py-1.5"
            >
              Delete account
            </button>
          </div>

          <p className="mt-2 text-sm text-neutral-500 dark:text-neutral-500">{dangerStatus}</p>
        </div>
      </div>
    </div>
  );
}
