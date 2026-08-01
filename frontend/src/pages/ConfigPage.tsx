import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useConfigOptions, useSaveConfig, useTestClassifier, useUserConfig } from "../api/hooks";
import type { PromptPreview } from "../api/types";
import { PageHeader } from "../components/AppLayout";
import { SkeletonBar, Spinner } from "../components/Skeleton";
import { useLocalStorage } from "../lib/useLocalStorage";

const TUNER_STORAGE_KEY = "job-alerts-tuner-fields";

interface TunerFields {
  company: string;
  title: string;
  locations: string;
  description: string;
}

const DEFAULT_TUNER_SAMPLE: TunerFields = {
  company: "Google",
  title: "Software Engineering Intern, Summer 2027",
  locations: "Mountain View, CA, USA",
  description: [
    "Google is seeking a Software Engineering Intern for Summer 2027. As an intern, you'll work on real projects critical to Google's needs, with opportunities to develop knowledge and skills in your areas of interest.",
    "Minimum qualifications:\n- Currently pursuing a Bachelor's degree in Computer Science or a related technical field.\n- Experience with Data Structures and Algorithms.\n- Experience coding in one or more general purpose languages (e.g. Java, C/C++, Python, Go).",
    "Preferred qualifications:\n- Experience developing accessible technologies.\n- Ability to speak and write in English fluently.",
    "About the job:\nAs a Software Engineering Intern, you'll specialize in the design, development, and technical leadership of software products used by millions of people, using your knowledge and experience in areas such as full-stack, back-end, front-end, mobile, algorithms, infrastructure, developer tools, distributed systems, or security.",
  ].join("\n\n"),
};

const INPUT_CLASS =
  "rounded-none border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-neutral-500";
const CARD_CLASS = "border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-3";
const LABEL_CLASS =
  "block text-xs font-medium uppercase tracking-wide text-neutral-500 dark:text-neutral-500 mb-2";
const SMALL_BUTTON_CLASS =
  "text-xs px-2 py-1 rounded-none border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-900";

function promptPreviewText(preview: PromptPreview | undefined): { before: string; after: string } {
  if (!preview) {
    return { before: "", after: "" };
  }
  const afterLines: string[] = [];
  if (preview.has_resume) {
    afterLines.push(`${preview.resume_label}\n<resume text>`);
  }
  afterLines.push(preview.response_instruction);
  return { before: `${preview.system_preamble}\n${preview.criteria_label}`, after: afterLines.join("\n") };
}

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

export function ConfigPage() {
  const config = useUserConfig();
  const options = useConfigOptions();
  const saveConfig = useSaveConfig();
  const testClassifier = useTestClassifier();

  const [fitPrompt, setFitPrompt] = useState("");
  const [selectedCompanies, setSelectedCompanies] = useState<Set<string>>(new Set());
  const [selectedJobTypes, setSelectedJobTypes] = useState<Set<string>>(new Set());
  const [companySearch, setCompanySearch] = useState("");
  const [tuner, setTuner] = useLocalStorage<TunerFields>(TUNER_STORAGE_KEY, DEFAULT_TUNER_SAMPLE);
  const promptRef = useRef<HTMLTextAreaElement>(null);

  // Server state seeds the form once it lands; edits after that are local until saved.
  const loadedConfig = config.data;
  useEffect(() => {
    if (!loadedConfig) {
      return;
    }
    setFitPrompt(loadedConfig.fit_prompt ?? "");
    setSelectedCompanies(new Set((loadedConfig.companies ?? []).map((name) => name.toLowerCase())));
    setSelectedJobTypes(new Set((loadedConfig.job_types ?? ["intern"]).map((name) => name.toLowerCase())));
  }, [loadedConfig]);

  const autoResize = useCallback((textarea: HTMLTextAreaElement | null) => {
    if (textarea === null) {
      return;
    }
    textarea.style.height = "auto";
    textarea.style.height = `${textarea.scrollHeight}px`;
  }, []);

  // Callback ref, not just an effect: config and options resolve independently, so
  // the textarea can mount after fitPrompt is already set.
  const attachPrompt = useCallback(
    (textarea: HTMLTextAreaElement | null) => {
      promptRef.current = textarea;
      autoResize(textarea);
    },
    [autoResize],
  );

  useEffect(() => {
    autoResize(promptRef.current);
  }, [fitPrompt, autoResize]);

  const visibleCompanies = useMemo(() => {
    const query = companySearch.trim().toLowerCase();
    const all = options.data?.companies ?? [];
    return query ? all.filter((name) => name.toLowerCase().includes(query)) : all;
  }, [options.data, companySearch]);

  const preview = promptPreviewText(config.data?.prompt_preview);

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

  const setVisibleCompanies = (checked: boolean) =>
    setSelectedCompanies((current) => {
      const next = new Set(current);
      for (const name of visibleCompanies) {
        if (checked) {
          next.add(name.toLowerCase());
        } else {
          next.delete(name.toLowerCase());
        }
      }
      return next;
    });

  // Selections are lowercased for matching; the API stores the catalog's casing.
  const selectedFrom = (all: string[], selected: Set<string>) =>
    all.filter((name) => selected.has(name.toLowerCase()));

  const save = () =>
    saveConfig.mutate({
      fit_prompt: fitPrompt,
      companies: selectedFrom(options.data?.companies ?? [], selectedCompanies),
      job_types: selectedFrom(options.data?.job_types ?? [], selectedJobTypes),
    });

  const isLoading = config.isPending || options.isPending;

  const saveStatus = saveConfig.isPending
    ? "Saving…"
    : saveConfig.isError
      ? "Failed to save"
      : saveConfig.isSuccess
        ? "Saved"
        : config.isError
          ? "Failed to load config"
          : "";

  return (
    <>
      <PageHeader title="Config">
        <span className="text-sm text-neutral-500 dark:text-neutral-500">{saveStatus}</span>
        <button
          type="button"
          onClick={save}
          disabled={isLoading || saveConfig.isPending}
          className="rounded-none bg-neutral-900 hover:opacity-50 disabled:opacity-40 dark:bg-neutral-100 text-white dark:text-neutral-900 text-sm font-medium px-3 py-1.5"
        >
          Save config
        </button>
      </PageHeader>

      <div className="grid lg:grid-cols-3 gap-6 items-start">
        <div className="lg:col-span-2 flex flex-col gap-6 lg:h-[calc(100dvh-160px)]">
          <div className={CARD_CLASS}>
            <label className={LABEL_CLASS}>Prompt</label>
            <div className="rounded-none border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-950 p-3 font-mono text-sm leading-6">
              {isLoading ? (
                <SkeletonBar className="h-24 w-full" />
              ) : (
                <>
                  <div className="whitespace-pre-wrap text-neutral-500 dark:text-neutral-500">{preview.before}</div>
                  <textarea
                    ref={attachPrompt}
                    rows={1}
                    value={fitPrompt}
                    onChange={(event) => setFitPrompt(event.target.value)}
                    placeholder={"1. ...\n2. ..."}
                    className="block w-full my-2 rounded-none border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm font-mono leading-6 resize-none overflow-hidden focus:outline-none focus:ring-1 focus:ring-neutral-500"
                  />
                  <div className="whitespace-pre-wrap text-neutral-500 dark:text-neutral-500">{preview.after}</div>
                </>
              )}
            </div>
          </div>

          <div className={`flex-1 flex flex-col min-h-0 ${CARD_CLASS}`}>
            <label className={LABEL_CLASS}>Prompt tuner</label>
            <div className="grid sm:grid-cols-2 gap-3 mb-3">
              <input
                type="text"
                placeholder="Company"
                value={tuner.company}
                onChange={(event) => setTuner({ ...tuner, company: event.target.value })}
                className={INPUT_CLASS}
              />
              <input
                type="text"
                placeholder="Title"
                value={tuner.title}
                onChange={(event) => setTuner({ ...tuner, title: event.target.value })}
                className={INPUT_CLASS}
              />
              <input
                type="text"
                placeholder="Locations (comma separated)"
                value={tuner.locations}
                onChange={(event) => setTuner({ ...tuner, locations: event.target.value })}
                className={`sm:col-span-2 ${INPUT_CLASS}`}
              />
            </div>
            <textarea
              placeholder="Job description"
              value={tuner.description}
              onChange={(event) => setTuner({ ...tuner, description: event.target.value })}
              className={`w-full mb-3 flex-1 min-h-0 ${INPUT_CLASS}`}
            />
            <button
              type="button"
              onClick={() =>
                testClassifier.mutate({
                  fit_prompt: fitPrompt,
                  company_name: tuner.company,
                  title: tuner.title,
                  locations: tuner.locations,
                  description: tuner.description,
                })
              }
              disabled={testClassifier.isPending}
              className="rounded-none border border-neutral-300 dark:border-neutral-700 hover:bg-neutral-100 dark:hover:bg-neutral-900 disabled:opacity-40 text-sm font-medium px-3 py-1.5 flex items-center justify-center gap-2"
            >
              {testClassifier.isPending && <Spinner className="w-3.5 h-3.5" />}
              {testClassifier.isPending ? "Testing…" : "Test"}
            </button>
            {(testClassifier.isSuccess || testClassifier.isError) && (
              <div
                className={`mt-3 rounded-none border border-neutral-200 dark:border-neutral-700 px-3 py-2 text-sm ${
                  testClassifier.isError
                    ? "text-red-600 dark:text-red-400"
                    : testClassifier.data.fits
                      ? "text-green-700 dark:text-green-400"
                      : "text-red-600 dark:text-red-400"
                }`}
              >
                {testClassifier.isError
                  ? (testClassifier.error.message || "Test failed")
                  : `${testClassifier.data.fits ? "Fits" : "Dismissed"}: ${testClassifier.data.reason}`}
              </div>
            )}
          </div>
        </div>

        <div className="lg:col-span-1 flex flex-col gap-6 lg:h-[calc(100dvh-160px)]">
          <div className={CARD_CLASS}>
            <label className={LABEL_CLASS}>Job types</label>
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

          <div className={`flex-1 flex flex-col min-h-0 ${CARD_CLASS}`}>
            <div className="flex items-center justify-between mb-2">
              <label className="block text-xs font-medium uppercase tracking-wide text-neutral-500 dark:text-neutral-500">
                Companies
              </label>
              <div className="flex gap-2">
                <button type="button" onClick={() => setVisibleCompanies(true)} className={SMALL_BUTTON_CLASS}>
                  Select all
                </button>
                <button type="button" onClick={() => setVisibleCompanies(false)} className={SMALL_BUTTON_CLASS}>
                  Deselect all
                </button>
              </div>
            </div>
            <input
              type="text"
              placeholder="Search companies…"
              value={companySearch}
              onChange={(event) => setCompanySearch(event.target.value)}
              className={`w-full mb-3 ${INPUT_CLASS}`}
            />
            <div className="flex-1 min-h-0 overflow-y-auto rounded-none border border-neutral-200 dark:border-neutral-700 divide-y divide-neutral-200 dark:divide-neutral-800">
              {isLoading ? (
                <SkeletonBar className="h-full w-full" />
              ) : visibleCompanies.length === 0 ? (
                <div className="px-3 py-4 text-sm text-neutral-500 dark:text-neutral-500 text-center">
                  No companies match your search
                </div>
              ) : (
                <CheckboxList
                  options={visibleCompanies}
                  selected={selectedCompanies}
                  onToggle={toggle(setSelectedCompanies)}
                />
              )}
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
