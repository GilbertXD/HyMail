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
    error_backoff: "重试中",
    auth_expired: "认证过期",
    running: "运行中",
    starting: "启动中",
    error: "错误",
  };
  return labels[state] ?? state;
}

export function estimateRetrySeconds(attempts: number): number {
  const exponent = Math.max(attempts - 1, 0);
  return Math.min(2 ** exponent, 300);
}