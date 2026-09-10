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
      <div className="rounded-2xl border border-slate-200 bg-white p-6 text-sm text-slate-500 shadow-sm">
        还没有同步状态。
      </div>
    );
  }

  const retrying = Boolean(status.running && status.last_error);

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">
            {status.folder}
          </h2>
          <p className="mt-1 text-sm text-slate-500">
            状态：
            <span
              className="ml-1 font-medium text-slate-900"
              data-testid="sync-state"
            >
              {retrying ? "重试中" : formatSyncState(status.state)}
            </span>
          </p>
        </div>
        <div className="rounded-full bg-slate-100 px-3 py-1 text-xs text-slate-600">
          {status.running ? "运行中" : "空闲"}
        </div>
      </div>

      <dl className="mt-6 grid gap-4 text-sm sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <dt className="text-slate-400">last UID</dt>
          <dd
            className="mt-1 font-medium text-slate-900"
            data-testid="sync-last-uid"
          >
            {status.last_uid}
          </dd>
        </div>
        <div>
          <dt className="text-slate-400">UIDVALIDITY</dt>
          <dd className="mt-1 font-medium text-slate-900">
            {status.uidvalidity ?? "-"}
          </dd>
        </div>
        <div>
          <dt className="text-slate-400">UIDNEXT</dt>
          <dd className="mt-1 font-medium text-slate-900">
            {status.uidnext ?? "-"}
          </dd>
        </div>
        <div>
          <dt className="text-slate-400">尝试次数</dt>
          <dd className="mt-1 font-medium text-slate-900">{status.attempts}</dd>
        </div>
      </dl>

      <div className="mt-6 flex flex-wrap items-center gap-4 text-sm text-slate-500">
        <span>最后同步：{formatDateTime(status.last_sync_at)}</span>
        {status.trace_id ? (
          <span className="font-mono text-xs">trace: {status.trace_id}</span>
        ) : null}
      </div>

      {status.last_error ? (
        <div className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
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