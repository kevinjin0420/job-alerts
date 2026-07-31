import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

import {
  useCompleteOnboarding,
  useConfigOptions,
  useCurrentUser,
  useSaveConfig,
  useSaveNtfyTopic,
  useTestNotification,
  useUserConfig,
} from "../api/hooks";
import { SkeletonBar } from "../components/Skeleton";

const DEFAULT_FIT_PROMPT = `1. It is an internship position (not full-time or new-grad).
2. It is a general software engineering role (edit this if you also want data/ML/hardware roles).
3. It is located in the United States (remote-US counts).
4. It is open to Bachelor's degree students.`;

const CARD_CLASS = "border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-3";
const LABEL_CLASS = "block text-xs font-medium uppercase tracking-wide text-neutral-500 dark:text-neutral-500 mb-2";
const INPUT_CLASS =
  "w-full rounded-none border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-neutral-500";

function CheckboxList({
  options,
  selected,
  onToggle,
}: {
  options: string[];
  selected: Set<string>;
  onToggle: (option: string, checked: boolean) => void;
}) {
  return (
    <>
      {options.map((option) => (
        <label
          key={option}
          className="flex items-center gap-2 px-3 py-2 text-sm cursor-pointer hover:bg-neutral-50 dark:hover:bg-neutral-800"
        >
          <input
            type="checkbox"
            className="rounded-none border-neutral-300 dark:border-neutral-700"
            checked={selected.has(option.toLowerCase())}
            onChange={(event) => onToggle(option, event.target.checked)}
          />
          {option}
        </label>
      ))}
    </>
  );
}

export function OnboardingPage() {
  const currentUser = useCurrentUser();
  const config = useUserConfig();
  const options = useConfigOptions();
  const saveConfig = useSaveConfig();
  const saveNtfyTopic = useSaveNtfyTopic();
  const testNotification = useTestNotification();
  const completeOnboarding = useCompleteOnboarding();
  const navigate = useNavigate();

  const [companySearch, setCompanySearch] = useState("");
  const [selectedCompanies, setSelectedCompanies] = useState<Set<string>>(new Set());
  const [selectedJobTypes, setSelectedJobTypes] = useState<Set<string>>(new Set(["intern"]));
  const [fitPrompt, setFitPrompt] = useState(DEFAULT_FIT_PROMPT);
  const [ntfyTopic, setNtfyTopic] = useState("");
  const [ntfyAck, setNtfyAck] = useState(false);
  const [emailTo, setEmailTo] = useState("");
  const [ntfyStatus, setNtfyStatus] = useState("");
  const [error, setError] = useState<string | null>(null);

  const loadedConfig = config.data;
  useEffect(() => {
    if (!loadedConfig) {
      return;
    }
    setFitPrompt(loadedConfig.fit_prompt || DEFAULT_FIT_PROMPT);
    setEmailTo((loadedConfig.email_to ?? []).join(", "));
    setSelectedCompanies(new Set((loadedConfig.companies ?? []).map((name) => name.toLowerCase())));
    setSelectedJobTypes(new Set((loadedConfig.job_types ?? ["intern"]).map((name) => name.toLowerCase())));
  }, [loadedConfig]);

  const loadedTopic = currentUser.data?.ntfy_topic;
  useEffect(() => {
    if (loadedTopic !== undefined) {
      setNtfyTopic(loadedTopic);
    }
  }, [loadedTopic]);

  const visibleCompanies = useMemo(() => {
    const query = companySearch.trim().toLowerCase();
    const all = options.data?.companies ?? [];
    return query ? all.filter((name) => name.toLowerCase().includes(query)) : all;
  }, [options.data, companySearch]);

  const toggle = (setter: typeof setSelectedCompanies) => (option: string, checked: boolean) =>
    setter((current) => {
      const next = new Set(current);
      if (checked) {
        next.add(option.toLowerCase());
      } else {
        next.delete(option.toLowerCase());
      }
      return next;
    });

  const selectedFrom = (all: string[], selected: Set<string>) =>
    all.filter((name) => selected.has(name.toLowerCase()));

  const sendTest = () => {
    const topic = ntfyTopic.trim();
    if (!topic) {
      setNtfyStatus("Enter a topic first");
      return;
    }
    setNtfyStatus("Sending test…");
    testNotification.mutate(topic, {
      onSuccess: () => setNtfyStatus("Sent - check your ntfy app"),
      onError: (caught) => setNtfyStatus(caught.message || "Failed to send"),
    });
  };

  const finish = async () => {
    setError(null);
    const companies = selectedFrom(options.data?.companies ?? [], selectedCompanies);
    const jobTypes = selectedFrom(options.data?.job_types ?? [], selectedJobTypes);
    const trimmedPrompt = fitPrompt.trim();
    const trimmedTopic = ntfyTopic.trim();
    const emails = emailTo
      .split(",")
      .map((item) => item.trim())
      .filter(Boolean);

    const missing: string[] = [];
    if (companies.length === 0) missing.push("pick at least one company");
    if (jobTypes.length === 0) missing.push("pick at least one job type");
    if (!trimmedPrompt) missing.push("fill in your fit criteria");
    if (!trimmedTopic) missing.push("set a notification topic");
    if (!ntfyAck) missing.push("confirm you've subscribed to your ntfy topic");
    if (emails.length === 0) missing.push("add an email recipient");
    if (missing.length > 0) {
      setError(`Before finishing: ${missing.join(", ")}.`);
      return;
    }

    try {
      await saveConfig.mutateAsync({
        fit_prompt: trimmedPrompt,
        companies,
        job_types: jobTypes,
        email_to: emails,
      });
      await saveNtfyTopic.mutateAsync(trimmedTopic);
      await completeOnboarding.mutateAsync();
      void navigate("/listings", { replace: true });
    } catch {
      setError("Failed to save - try again.");
    }
  };

  const isSaving = saveConfig.isPending || saveNtfyTopic.isPending || completeOnboarding.isPending;
  const isLoading = config.isPending || options.isPending || currentUser.isPending;

  return (
    <div className="min-h-dvh flex justify-center p-6">
      <div className="w-full max-w-2xl py-10 space-y-6">
        <div>
          <h1 className="text-lg font-semibold">Welcome to job-alerts</h1>
          <p className="text-sm text-neutral-500 dark:text-neutral-500 mt-1">
            A few things to set up before you start getting notified.
          </p>
        </div>

        <div className={CARD_CLASS}>
          <label className={LABEL_CLASS}>1. Companies</label>
          <p className="text-sm text-neutral-500 dark:text-neutral-500 mb-3">Pick at least one company to track.</p>
          <input
            type="text"
            placeholder="Search companies…"
            value={companySearch}
            onChange={(event) => setCompanySearch(event.target.value)}
            className={`mb-3 ${INPUT_CLASS}`}
          />
          <div className="max-h-64 overflow-y-auto rounded-none border border-neutral-200 dark:border-neutral-700 divide-y divide-neutral-200 dark:divide-neutral-800">
            {isLoading ? (
              <SkeletonBar className="h-40 w-full" />
            ) : (
              <CheckboxList
                options={visibleCompanies}
                selected={selectedCompanies}
                onToggle={toggle(setSelectedCompanies)}
              />
            )}
          </div>
        </div>

        <div className={CARD_CLASS}>
          <label className={LABEL_CLASS}>2. Job types</label>
          <div className="rounded-none border border-neutral-200 dark:border-neutral-700 divide-y divide-neutral-200 dark:divide-neutral-800">
            {isLoading ? (
              <SkeletonBar className="h-28 w-full" />
            ) : (
              <CheckboxList
                options={options.data?.job_types ?? []}
                selected={selectedJobTypes}
                onToggle={toggle(setSelectedJobTypes)}
              />
            )}
          </div>
        </div>

        <div className={CARD_CLASS}>
          <label className={LABEL_CLASS}>3. Fit criteria</label>
          <p className="text-sm text-neutral-500 dark:text-neutral-500 mb-3">
            List the criteria a listing must meet to notify you - just the criteria, not persona or formatting
            instructions, those are already handled for you. Edit the template below to fit you. You can see the exact
            prompt this gets stitched into on the Config page.
          </p>
          <textarea
            rows={8}
            value={fitPrompt}
            onChange={(event) => setFitPrompt(event.target.value)}
            className={`${INPUT_CLASS} font-mono leading-6`}
          />
        </div>

        <div className={CARD_CLASS}>
          <label className={LABEL_CLASS}>4. Notifications</label>
          <p className="text-sm text-neutral-500 dark:text-neutral-500 mb-3">
            Your{" "}
            <a href="https://ntfy.sh" target="_blank" rel="noopener" className="underline hover:opacity-50">
              ntfy
            </a>{" "}
            topic is <code className="font-mono">{currentUser.data?.ntfy_topic ?? ""}</code>. Install the{" "}
            <a href="https://ntfy.sh/#subscribe" target="_blank" rel="noopener" className="underline hover:opacity-50">
              ntfy app
            </a>{" "}
            and subscribe to it - see{" "}
            <a
              href="https://github.com/kevinjin0420/job-alerts/blob/main/docs/ntfy-setup.md"
              target="_blank"
              rel="noopener"
              className="underline hover:opacity-50"
            >
              docs/ntfy-setup.md
            </a>
            .
          </p>
          <div className="flex gap-3 mb-2">
            <input
              type="text"
              placeholder="job-alerts-xxxxxxxxxxxx"
              value={ntfyTopic}
              onChange={(event) => setNtfyTopic(event.target.value)}
              className={`${INPUT_CLASS} font-mono`}
            />
            <button
              type="button"
              onClick={sendTest}
              disabled={testNotification.isPending}
              className="shrink-0 rounded-none border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-900 disabled:opacity-40 text-sm font-medium px-3 py-1.5"
            >
              Send test
            </button>
          </div>
          <p className="text-sm text-neutral-500 dark:text-neutral-500 mb-3">{ntfyStatus}</p>
          <label className="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              checked={ntfyAck}
              onChange={(event) => setNtfyAck(event.target.checked)}
              className="rounded-none border-neutral-300 dark:border-neutral-700"
            />
            I've installed the ntfy app and subscribed to this topic
          </label>
        </div>

        <div className={CARD_CLASS}>
          <label className={LABEL_CLASS}>5. Email recipient</label>
          <input
            type="text"
            placeholder="you@example.com"
            value={emailTo}
            onChange={(event) => setEmailTo(event.target.value)}
            className={`${INPUT_CLASS} font-mono`}
          />
        </div>

        <div className={CARD_CLASS}>
          <label className={LABEL_CLASS}>6. Résumé (optional)</label>
          <p className="text-sm text-neutral-500 dark:text-neutral-500">
            Adds a fit score to each listing - doesn't affect what gets you notified. Skip for now, set it up anytime on
            the Profile page.
          </p>
        </div>

        {error && <div className="text-sm text-red-600 dark:text-red-400">{error}</div>}
        <div className="flex items-center gap-3">
          <button
            type="button"
            onClick={() => void finish()}
            disabled={isSaving}
            className="rounded-none bg-neutral-900 hover:opacity-50 disabled:opacity-40 dark:bg-neutral-100 text-white dark:text-neutral-900 text-sm font-medium px-3 py-1.5"
          >
            Finish setup
          </button>
          <span className="text-sm text-neutral-500 dark:text-neutral-500">{isSaving ? "Saving..." : ""}</span>
        </div>
      </div>
    </div>
  );
}
