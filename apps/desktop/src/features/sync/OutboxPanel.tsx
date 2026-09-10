import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import {
  discardOutboxAction,
  listOutbox,
  retryOutboxAction,
} from "../../lib/api";
import { formatDateTime } from "../../lib/format";

const TYPE_LABELS: Record<string, string> = {
  mark_read: "已读状态",
  star: "星标",
};

const STATE_LABELS: Record<string, string> = {
  pending: "待发送",
  inflight: "发送中",
  success: "已发送",
  failed: "发送失败",
  abandoned: "已丢弃",
};

const STATE_STYLES: Record<string, string> = {
  pending:
    "bg-slate-100 text-slate-600 dark:bg-gh-overlay dark:text-gh-fg-muted",
  inflight:
    "bg-sky-50 text-sky-700 dark:bg-gh-accent-subtle dark:text-gh-accent",
  success:
    "bg-emerald-50 text-emerald-700 dark:bg-gh-success-subtle dark:text-gh-success",
  failed:
    "bg-red-50 text-red-700 dark:bg-gh-danger-subtle dark:text-gh-danger",
  abandoned:
    "bg-slate-100 text-slate-500 dark:bg-gh-overlay dark:text-gh-fg-subtle",
};

/**
 * Local changes that have not reached the server yet.
 *
 * A failed write keeps the optimistic value on screen, so this panel is where
 * the user decides: send it again, or drop it and go back to what the server
 * says.
 */
export function OutboxPanel({ enabled }: { enabled: boolean }) {
  const queryClient = useQueryClient();

  const actionsQuery = useQuery({
    queryKey: ["outbox"],
    queryFn: () => listOutbox({ limit: 30 }),
    enabled,
    refetchInterval: 2000,
    retry: false,
  });

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ["outbox"] });
    queryClient.invalidateQueries({ queryKey: ["messages"] });
    queryClient.invalidateQueries({ queryKey: ["message"] });
  };

  const retryMutation = useMutation({
    mutationFn: retryOutboxAction,
    onSuccess: invalidate,
  });

  const discardMutation = useMutation({
    mutationFn: discardOutboxAction,
    onSuccess: invalidate,
  });

  const actions = actionsQuery.data ?? [];

  if (!enabled) {
    return null;
  }

  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm dark:border-gh-border dark:bg-gh-subtle">
      <h2 className="text-lg font-semibold text-slate-900 dark:text-gh-fg">
        待发送的修改
      </h2>
      <p className="mt-1 text-sm text-slate-500 dark:text-gh-fg-muted">
        已读和星标的改动先写本地，再排队送到服务器。
      </p>

      {actions.length === 0 ? (
        <p className="mt-4 text-sm text-slate-400 dark:text-gh-fg-subtle">
          没有待发送的修改。
        </p>
      ) : (
        <ul className="mt-4 space-y-3">
          {actions.map((action) => (
            <li
              key={action.id}
              className="flex items-start justify-between gap-4"
              data-testid="outbox-row"
            >
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-slate-900 dark:text-gh-fg">
                  {action.subject || "(无主题)"}
                </div>
                <div className="mt-0.5 text-xs text-slate-400 dark:text-gh-fg-subtle">
                  {TYPE_LABELS[action.type] ?? action.type} ·{" "}
                  {action.value ? "设为是" : "设为否"} ·{" "}
                  {formatDateTime(action.created_at)}
                  {action.attempts > 0 ? ` · 尝试 ${action.attempts} 次` : ""}
                </div>
                {action.last_error ? (
                  <div className="mt-1 text-xs text-red-600 dark:text-gh-danger">
                    {action.last_error}
                  </div>
                ) : null}
              </div>

              <div className="flex shrink-0 items-center gap-2">
                {action.state === "failed" ||
                action.state === "abandoned" ? (
                  <button
                    type="button"
                    className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-100 dark:border-gh-border dark:text-gh-fg dark:hover:bg-gh-overlay"
                    onClick={() => retryMutation.mutate(action.id)}
                    data-testid="outbox-retry"
                  >
                    重试
                  </button>
                ) : null}
                {action.state === "pending" ||
                action.state === "failed" ||
                action.state === "inflight" ? (
                  <button
                    type="button"
                    className="rounded border border-slate-300 px-2 py-0.5 text-xs text-slate-600 hover:bg-slate-100 dark:border-gh-border dark:text-gh-fg dark:hover:bg-gh-overlay"
                    onClick={() => discardMutation.mutate(action.id)}
                    title="丢弃这次改动并恢复到服务器上的状态"
                    data-testid="outbox-discard"
                  >
                    丢弃
                  </button>
                ) : null}
                <span
                  className={[
                    "rounded-full px-2 py-0.5 text-xs",
                    STATE_STYLES[action.state] ?? STATE_STYLES.pending,
                  ].join(" ")}
                >
                  {STATE_LABELS[action.state] ?? action.state}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
