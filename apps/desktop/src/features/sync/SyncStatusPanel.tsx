import type { SyncStatusRead } from "../../lib/api";
import { formatDateTime, formatSyncState } from "../../lib/format";
import { RetryCountdown } from "./RetryCountdown";

export function SyncStatusPanel({
  status,
}: {
  status: SyncStatusRead | undefined;
}) {
  if (!status) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm dark:border-gh-border dark:bg-gh-subtle dark:text-gh-fg-muted">
        还没有同步状态。
      </div>
    );
  }

  const retrying = Boolean(status.running && status.last_error);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-gh-border dark:bg-gh-subtle">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-gh-fg">
            {status.folder}
          </h2>
          <p className="mt-1 text-sm text-slate-500 dark:text-gh-fg-muted">
            状态：
            <span
              className="ml-1 font-medium text-slate-900 dark:text-gh-fg"
              data-testid="sync-state"
            >
              {retrying ? "重试中" : formatSyncState(status.state)}
            </span>
          </p>
        </div>
        <div className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600 dark:bg-gh-overlay dark:text-gh-fg">
          {status.running ? "运行中" : "空闲"}
        </div>
      </div>

      <dl className="mt-6 grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="text-slate-400 dark:text-gh-fg-subtle">last UID</dt>
          <dd
            className="mt-1 font-medium text-slate-900 dark:text-gh-fg"
            data-testid="sync-last-uid"
          >
            {status.last_uid}
          </dd>
        </div>
        <div>
          <dt className="text-slate-400 dark:text-gh-fg-subtle">UIDVALIDITY</dt>
          <dd className="mt-1 font-medium text-slate-900 dark:text-gh-fg">
            {status.uidvalidity ?? "-"}
          </dd>
        </div>
        <div>
          <dt className="text-slate-400 dark:text-gh-fg-subtle">UIDNEXT</dt>
          <dd className="mt-1 font-medium text-slate-900 dark:text-gh-fg">
            {status.uidnext ?? "-"}
          </dd>
        </div>
        <div>
          <dt className="text-slate-400 dark:text-gh-fg-subtle">尝试次数</dt>
          <dd className="mt-1 font-medium text-slate-900 dark:text-gh-fg">
            {status.attempts}
          </dd>
        </div>
      </dl>

      <div className="mt-6 flex flex-wrap items-center gap-4 text-sm text-slate-500 dark:text-gh-fg-muted">
        <span>最后同步：{formatDateTime(status.last_sync_at)}</span>
        {status.trace_id ? (
          <span className="font-mono text-xs">trace: {status.trace_id}</span>
        ) : null}
      </div>

      {status.last_error ? (
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-gh-danger dark:bg-gh-danger-subtle dark:text-gh-danger">
          <div className="font-medium">错误原因</div>
          <div className="mt-1">{status.last_error}</div>
          {retrying ? (
            <div className="mt-2 text-xs">
              <RetryCountdown
                key={status.attempts}
                attempts={status.attempts}
              />
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
