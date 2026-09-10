import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { LoadingState, ErrorState } from "../../components/AsyncState";
import {
  cancelSync,
  getSyncStatus,
  listSyncEvents,
  triggerSync,
} from "../../lib/api";
import { SyncEventTimeline } from "./SyncEventTimeline";
import { SyncStatusPanel } from "./SyncStatusPanel";

export function SyncPage() {
  const queryClient = useQueryClient();

  const statusQuery = useQuery({
    queryKey: ["sync-status", "INBOX"],
    queryFn: () => getSyncStatus("INBOX"),
    refetchInterval: 1500,
    retry: false,
  });

  const eventsQuery = useQuery({
    queryKey: ["sync-events"],
    queryFn: () => listSyncEvents(0),
    refetchInterval: 1500,
    retry: false,
  });

  const triggerMutation = useMutation({
    mutationFn: () => triggerSync("INBOX"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sync-status"] });
      queryClient.invalidateQueries({ queryKey: ["sync-events"] });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => cancelSync("INBOX"),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sync-status"] });
      queryClient.invalidateQueries({ queryKey: ["sync-events"] });
    },
  });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">同步面板</h1>
          <p className="mt-1 text-sm text-slate-500">
            手动触发和观察 INBOX 同步状态。
          </p>
        </div>
        <div className="flex gap-3">
          <button
            type="button"
            className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            onClick={() => triggerMutation.mutate()}
            disabled={triggerMutation.isPending}
          >
            {triggerMutation.isPending ? "触发中..." : "手动同步"}
          </button>
          <button
            type="button"
            className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-100 disabled:opacity-50"
            onClick={() => cancelMutation.mutate()}
            disabled={cancelMutation.isPending}
          >
            {cancelMutation.isPending ? "取消中..." : "取消同步"}
          </button>
        </div>
      </div>

      {statusQuery.isLoading ? <LoadingState label="读取同步状态..." /> : null}
      {statusQuery.error ? (
        <ErrorState
          message={
            statusQuery.error instanceof Error
              ? statusQuery.error.message
              : "读取同步状态失败"
          }
        />
      ) : null}
      <SyncStatusPanel status={statusQuery.data} />

      {eventsQuery.isLoading ? <LoadingState label="读取同步事件..." /> : null}
      {eventsQuery.error ? (
        <ErrorState
          message={
            eventsQuery.error instanceof Error
              ? eventsQuery.error.message
              : "读取同步事件失败"
          }
        />
      ) : null}
      <SyncEventTimeline events={eventsQuery.data ?? []} />
    </div>
  );
}