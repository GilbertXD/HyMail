export function formatDateTime(value?: string | null): string {
  if (!value) {
    return "从未";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

export function formatSyncState(state: string): string {
  const labels: Record<string, string> = {
    idle: "IDLE",
    initial_sync: "初始同步中",
    incremental_sync: "增量同步中",
    resync: "UIDVALIDITY 变化，重新同步",
    reconcile: "对账中",
    error_backoff: "重试中",
    auth_expired: "认证过期",
    running: "同步中",
    starting: "启动中",
    error: "错误",
    // Batch states.
    queued: "排队中",
    completed: "已完成",
    partial: "部分完成",
    failed: "失败",
    cancelled: "已取消",
    empty: "没有需要同步的文件夹",
  };
  return labels[state] ?? state;
}

export function estimateRetrySeconds(attempts: number): number {
  const exponent = Math.max(attempts - 1, 0);
  return Math.min(2 ** exponent, 300);
}