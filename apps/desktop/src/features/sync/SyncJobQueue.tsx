import type { SyncJobRead } from "../../lib/api";
import { formatDateTime } from "../../lib/format";

const STATE_LABELS: Record<string, string> = {
  queued: "排队中",
  running: "同步中",
  success: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const STATE_STYLES: Record<string, string> = {
  queued:
    "bg-slate-100 text-slate-600 dark:bg-gh-overlay dark:text-gh-fg-muted",
  running:
    "bg-sky-50 text-sky-700 dark:bg-gh-accent-subtle dark:text-gh-accent",
  success:
    "bg-emerald-50 text-emerald-700 dark:bg-gh-success-subtle dark:text-gh-success",
  failed:
    "bg-red-50 text-red-700 dark:bg-gh-danger-subtle dark:text-gh-danger",
  cancelled:
    "bg-slate-100 text-slate-500 dark:bg-gh-overlay dark:text-gh-fg-subtle",
};

export function SyncJobQueue({ jobs }: { jobs: SyncJobRead[] }) {
  if (!jobs.length) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-6 text-sm text-slate-400 shadow-sm dark:border-gh-border dark:bg-gh-subtle dark:text-gh-fg-subtle">
        队列是空的。
      </div>
    );
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-gh-border dark:bg-gh-subtle">
      <h2 className="text-lg font-semibold text-slate-900 dark:text-gh-fg">
        同步队列
      </h2>
      <ul className="mt-4 space-y-3">
        {jobs.map((job) => (
          <li
            key={job.id}
            className="flex items-start justify-between gap-4"
            data-testid="sync-job-row"
          >
            <div className="min-w-0">
              <div className="truncate text-sm font-medium text-slate-900 dark:text-gh-fg">
                {job.folder_name}
              </div>
              <div className="mt-0.5 text-xs text-slate-400 dark:text-gh-fg-subtle">
                {formatDateTime(job.created_at)}
                {job.attempts > 0 ? ` · 尝试 ${job.attempts} 次` : ""}
              </div>
              {job.last_error ? (
                <div className="mt-1 text-xs text-red-600 dark:text-gh-danger">
                  {job.last_error}
                </div>
              ) : null}
            </div>
            <span
              className={[
                "shrink-0 rounded-full px-2 py-0.5 text-xs",
                STATE_STYLES[job.state] ?? STATE_STYLES.queued,
              ].join(" ")}
            >
              {STATE_LABELS[job.state] ?? job.state}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
