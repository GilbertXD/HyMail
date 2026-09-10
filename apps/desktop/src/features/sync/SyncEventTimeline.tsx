import type { SyncEventRead } from "../../lib/api";
import { formatDateTime, formatSyncState } from "../../lib/format";

export function SyncEventTimeline({
  events,
}: {
  events: SyncEventRead[];
}) {
  if (!events.length) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-6 text-sm text-slate-400 shadow-sm dark:border-gh-border dark:bg-gh-subtle dark:text-gh-fg-subtle">
        还没有同步事件。
      </div>
    );
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-gh-border dark:bg-gh-subtle">
      <h2 className="text-lg font-semibold text-slate-900 dark:text-gh-fg">
        同步事件时间线
      </h2>
      <ol className="mt-4 space-y-4">
        {events.map((event) => (
          <li key={event.id} className="flex gap-4">
            <div className="mt-1 h-2 w-2 shrink-0 rounded-full bg-sky-500" />
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2 text-sm">
                <span className="font-medium text-slate-900 dark:text-gh-fg">
                  {event.event_type}
                </span>
                <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs text-slate-600 dark:bg-gh-overlay dark:text-gh-fg">
                  {formatSyncState(event.state)}
                </span>
                <span className="text-xs text-slate-400 dark:text-gh-fg-subtle">
                  {formatDateTime(event.created_at)}
                </span>
              </div>
              <p className="mt-1 text-sm text-slate-500 dark:text-gh-fg-muted">
                {event.uid_from != null && event.uid_to != null
                  ? `UID ${event.uid_from} - ${event.uid_to}`
                  : event.message || "状态更新"}
                {event.fetched_count ? `，共 ${event.fetched_count} 封` : ""}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
