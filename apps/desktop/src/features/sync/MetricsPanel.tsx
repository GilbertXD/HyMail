import { useQuery } from "@tanstack/react-query";

import { getMetrics } from "../../lib/api";
import {
  formatDateTime,
  formatDuration,
  formatPercent,
} from "../../lib/format";

/**
 * What the sync pipeline actually did over a rolling window.
 *
 * Everything here is derived from rows the pipeline already writes, so it is
 * a view of the real work rather than a separate tally that could drift.
 */
export function MetricsPanel({ enabled }: { enabled: boolean }) {
  const metricsQuery = useQuery({
    queryKey: ["metrics"],
    queryFn: () => getMetrics(24),
    enabled,
    refetchInterval: 5000,
    retry: false,
  });

  if (!enabled) {
    return null;
  }

  const metrics = metricsQuery.data;

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-gh-border dark:bg-gh-subtle">
      <h2 className="text-lg font-semibold text-slate-900 dark:text-gh-fg">
        同步指标
      </h2>
      <p className="mt-1 text-sm text-slate-500 dark:text-gh-fg-muted">
        最近 {metrics?.window_hours ?? 24} 小时。
      </p>

      {metricsQuery.error ? (
        <p className="mt-3 text-sm text-red-600 dark:text-gh-danger">
          读取指标失败。
        </p>
      ) : null}

      {metrics ? (
        <>
          <dl className="mt-4 grid grid-cols-2 gap-4 text-sm sm:grid-cols-3 lg:grid-cols-6">
            <div>
              <dt className="text-slate-400 dark:text-gh-fg-subtle">同步次数</dt>
              <dd
                className="mt-1 font-medium text-slate-900 dark:text-gh-fg"
                data-testid="metrics-runs"
              >
                {metrics.runs}
              </dd>
            </div>
            <div>
              <dt className="text-slate-400 dark:text-gh-fg-subtle">失败率</dt>
              <dd className="mt-1 font-medium text-slate-900 dark:text-gh-fg">
                {formatPercent(metrics.failure_rate)}
                {metrics.failures > 0 ? `（${metrics.failures}）` : ""}
              </dd>
            </div>
            <div>
              <dt className="text-slate-400 dark:text-gh-fg-subtle">拉取邮件</dt>
              <dd
                className="mt-1 font-medium text-slate-900 dark:text-gh-fg"
                data-testid="metrics-fetched"
              >
                {metrics.fetched}
              </dd>
            </div>
            <div>
              <dt className="text-slate-400 dark:text-gh-fg-subtle">重试次数</dt>
              <dd className="mt-1 font-medium text-slate-900 dark:text-gh-fg">
                {metrics.retries}
              </dd>
            </div>
            <div>
              <dt className="text-slate-400 dark:text-gh-fg-subtle">平均耗时</dt>
              <dd className="mt-1 font-medium text-slate-900 dark:text-gh-fg">
                {formatDuration(metrics.avg_duration_ms)}
              </dd>
            </div>
            <div>
              <dt className="text-slate-400 dark:text-gh-fg-subtle">P95 耗时</dt>
              <dd className="mt-1 font-medium text-slate-900 dark:text-gh-fg">
                {formatDuration(metrics.p95_duration_ms)}
              </dd>
            </div>
          </dl>

          <p className="mt-4 text-xs text-slate-500 dark:text-gh-fg-muted">
            待发送修改 {metrics.outbox.outstanding}
            {metrics.outbox.failed > 0
              ? `，其中 ${metrics.outbox.failed} 个发送失败`
              : ""}
          </p>

          <div className="mt-5 overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs text-slate-400 dark:text-gh-fg-subtle">
                <tr>
                  <th className="py-1 font-normal">文件夹</th>
                  <th className="py-1 text-right font-normal">同步</th>
                  <th className="py-1 text-right font-normal">失败</th>
                  <th className="py-1 text-right font-normal">拉取</th>
                  <th className="py-1 text-right font-normal">平均</th>
                  <th className="py-1 text-right font-normal">最后同步</th>
                </tr>
              </thead>
              <tbody>
                {metrics.folders.map((folder) => (
                  <tr
                    key={folder.folder_id}
                    className="border-t border-slate-100 dark:border-gh-border"
                    data-testid="metrics-folder-row"
                  >
                    <td className="max-w-[14rem] truncate py-1.5 text-slate-700 dark:text-gh-fg">
                      {folder.folder_name}
                    </td>
                    <td className="py-1.5 text-right text-slate-600 dark:text-gh-fg-muted">
                      {folder.runs}
                    </td>
                    <td
                      className={[
                        "py-1.5 text-right",
                        folder.failures > 0
                          ? "text-red-600 dark:text-gh-danger"
                          : "text-slate-600 dark:text-gh-fg-muted",
                      ].join(" ")}
                    >
                      {folder.failures}
                    </td>
                    <td className="py-1.5 text-right text-slate-600 dark:text-gh-fg-muted">
                      {folder.fetched}
                    </td>
                    <td className="py-1.5 text-right text-slate-600 dark:text-gh-fg-muted">
                      {formatDuration(folder.avg_duration_ms)}
                    </td>
                    <td className="py-1.5 text-right text-xs text-slate-400 dark:text-gh-fg-subtle">
                      {formatDateTime(folder.last_sync_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </section>
  );
}
