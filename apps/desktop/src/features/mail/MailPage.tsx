import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { ErrorState, LoadingState } from "../../components/AsyncState";
import { SyncEventTimeline } from "../sync/SyncEventTimeline";
import { SyncStatusPanel } from "../sync/SyncStatusPanel";
import { MessageBody } from "./MessageBody";
import {
  ApiError,
  cancelSync,
  getCurrentAccount,
  getMessage,
  getSyncStatus,
  listAllMessages,
  listFolders,
  listMessages,
  listSyncEvents,
  refreshFolders,
  triggerSync,
} from "../../lib/api";
import { formatDateTime, formatSyncState } from "../../lib/format";

type MailView = "all" | string;

export function MailPage() {
  const queryClient = useQueryClient();
  const [view, setView] = useState<MailView>("all");
  const [messageId, setMessageId] = useState<string | null>(null);
  const [showSyncDetail, setShowSyncDetail] = useState(false);

  const accountQuery = useQuery({
    queryKey: ["account"],
    queryFn: getCurrentAccount,
    retry: false,
  });

  const foldersQuery = useQuery({
    queryKey: ["folders"],
    queryFn: listFolders,
    retry: false,
  });

  const folders = foldersQuery.data ?? [];
  const selectedFolder =
    view === "all" ? null : folders.find((folder) => folder.id === view) ?? null;

  const allMessagesQuery = useQuery({
    queryKey: ["messages", "all"],
    queryFn: () => listAllMessages(200, 0),
    enabled: view === "all",
    refetchInterval: 2000,
    retry: false,
  });

  const folderMessagesQuery = useQuery({
    queryKey: ["messages", view],
    queryFn: () => listMessages(view),
    enabled: view !== "all",
    refetchInterval: 2000,
    retry: false,
  });

  const messageQuery = useQuery({
    queryKey: ["message", messageId],
    queryFn: () => getMessage(messageId as string),
    enabled: Boolean(messageId),
    retry: false,
  });

  const syncStatusQuery = useQuery({
    queryKey: ["sync-status", selectedFolder?.name],
    queryFn: () => getSyncStatus(selectedFolder!.name),
    enabled: Boolean(selectedFolder),
    refetchInterval: 1500,
    retry: false,
  });

  const syncEventsQuery = useQuery({
    queryKey: ["sync-events"],
    queryFn: () => listSyncEvents(0),
    enabled: showSyncDetail,
    refetchInterval: 1500,
    retry: false,
  });

  const refreshFoldersMutation = useMutation({
    mutationFn: refreshFolders,
    onSuccess: (nextFolders) => {
      queryClient.setQueryData(["folders"], nextFolders);
    },
  });

  const autoRefreshedFolders = useRef(false);

  useEffect(() => {
    if (autoRefreshedFolders.current) {
      return;
    }
    if (
      accountQuery.data &&
      foldersQuery.isSuccess &&
      folders.length === 0
    ) {
      autoRefreshedFolders.current = true;
      refreshFoldersMutation.mutate();
    }
  }, [
    accountQuery.data,
    foldersQuery.isSuccess,
    folders.length,
    refreshFoldersMutation,
  ]);

  const triggerMutation = useMutation({
    mutationFn: () => triggerSync(selectedFolder!.name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sync-status"] });
      queryClient.invalidateQueries({ queryKey: ["messages"] });
      queryClient.invalidateQueries({ queryKey: ["folders"] });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => cancelSync(selectedFolder!.name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["sync-status"] });
      queryClient.invalidateQueries({ queryKey: ["messages"] });
    },
  });

  if (
    foldersQuery.error instanceof ApiError &&
    foldersQuery.error.status === 404
  ) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <div className="rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm dark:border-gh-border dark:bg-gh-subtle">
          <h1 className="text-xl font-semibold">还没有配置账号</h1>
          <p className="mt-2 text-sm text-slate-500 dark:text-gh-fg-muted">
            先配置 IMAP 账号，再触发同步。
          </p>
          <Link
            to="/setup"
            className="mt-4 inline-block rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white dark:bg-gh-accent-emphasis dark:text-white"
          >
            去配置账号
          </Link>
        </div>
      </div>
    );
  }

  const messages =
    view === "all"
      ? allMessagesQuery.data ?? []
      : folderMessagesQuery.data ?? [];

  const messagesLoading =
    view === "all"
      ? allMessagesQuery.isLoading
      : folderMessagesQuery.isLoading;

  const messagesError =
    view === "all" ? allMessagesQuery.error : folderMessagesQuery.error;

  const syncStatus = syncStatusQuery.data;
  const retrying = Boolean(syncStatus?.running && syncStatus?.last_error);

  return (
    <div className="flex h-full overflow-hidden">
      <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-slate-50 dark:border-gh-border dark:bg-gh-subtle">
        <div className="border-b border-slate-200 p-3 dark:border-gh-border">
          <div className="truncate text-sm font-semibold text-slate-900 dark:text-gh-fg">
            {accountQuery.data?.email ?? "当前账号"}
          </div>
          <button
            type="button"
            className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50 dark:border-gh-border dark:bg-gh-canvas dark:text-gh-fg dark:hover:bg-gh-overlay"
            onClick={() => refreshFoldersMutation.mutate()}
            disabled={refreshFoldersMutation.isPending}
          >
            {refreshFoldersMutation.isPending ? "刷新中..." : "刷新文件夹"}
          </button>
          {refreshFoldersMutation.error ? (
            <div className="mt-2 text-xs text-red-600 dark:text-gh-danger">
              {refreshFoldersMutation.error instanceof Error
                ? refreshFoldersMutation.error.message
                : "刷新失败"}
            </div>
          ) : null}
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          <button
            type="button"
            onClick={() => {
              setView("all");
              setMessageId(null);
            }}
            className={[
              "flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition",
              view === "all"
                ? "bg-sky-50 font-medium text-sky-700 dark:bg-gh-accent-subtle dark:text-gh-accent"
                : "text-slate-600 hover:bg-slate-100 dark:text-gh-fg dark:hover:bg-gh-overlay",
            ].join(" ")}
          >
            <span>全部邮件</span>
            <span className="text-xs opacity-60">
              {allMessagesQuery.data?.length ?? 0}
            </span>
          </button>

          <div className="mt-2 space-y-1">
            {folders.map((folder) => (
              <button
                key={folder.id}
                type="button"
                onClick={() => {
                  setView(folder.id);
                  setMessageId(null);
                }}
                className={[
                  "flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm transition",
                  folder.id === view
                    ? "bg-sky-50 font-medium text-sky-700 dark:bg-gh-accent-subtle dark:text-gh-accent"
                    : "text-slate-600 hover:bg-slate-100 dark:text-gh-fg dark:hover:bg-gh-overlay",
                ].join(" ")}
              >
                <span className="truncate">{folder.name}</span>
                <span className="text-xs opacity-60">
                  {folder.message_count}
                </span>
              </button>
            ))}
          </div>
        </div>
      </aside>

      <section className="flex w-96 shrink-0 flex-col border-r border-slate-200 bg-white dark:border-gh-border dark:bg-gh-subtle">
        <div className="flex h-12 shrink-0 items-center justify-between border-b border-slate-100 px-4 dark:border-gh-border">
          <h2 className="truncate text-sm font-semibold text-slate-700 dark:text-gh-fg">
            {view === "all" ? "全部邮件" : selectedFolder?.name ?? "邮件"}
          </h2>
          <span className="text-xs text-slate-400 dark:text-gh-fg-subtle">
            {messages.length} 封
          </span>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-2 text-xs dark:border-gh-border">
          <span className="text-slate-500 dark:text-gh-fg-muted">状态：</span>
          <span
            className="font-medium text-slate-800 dark:text-gh-fg"
            data-testid="mail-sync-state"
          >
            {retrying
              ? "重试中"
              : formatSyncState(syncStatus?.state ?? "idle")}
          </span>
          {syncStatus ? (
            <span
              className="text-slate-400 dark:text-gh-fg-subtle"
              data-testid="mail-sync-last-uid"
            >
              last UID: {syncStatus.last_uid}
            </span>
          ) : null}
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-1 font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-40 dark:border-gh-border dark:text-gh-fg dark:hover:bg-gh-overlay"
            onClick={() => triggerMutation.mutate()}
            disabled={!selectedFolder || triggerMutation.isPending}
          >
            同步
          </button>
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-1 font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-40 dark:border-gh-border dark:text-gh-fg dark:hover:bg-gh-overlay"
            onClick={() => cancelMutation.mutate()}
            disabled={!selectedFolder || cancelMutation.isPending}
          >
            取消
          </button>
          <button
            type="button"
            className={[
              "rounded border px-2 py-1 font-medium transition",
              showSyncDetail
                ? "border-sky-300 bg-sky-50 text-sky-700 dark:border-gh-accent dark:bg-gh-accent-subtle dark:text-gh-accent"
                : "border-slate-300 text-slate-600 hover:bg-slate-100 dark:border-gh-border dark:text-gh-fg dark:hover:bg-gh-overlay",
            ].join(" ")}
            onClick={() => setShowSyncDetail((current) => !current)}
            data-testid="mail-sync-detail-toggle"
          >
            同步详情
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          {messagesLoading ? (
            <div className="p-4">
              <LoadingState label="读取邮件..." />
            </div>
          ) : null}
          {messagesError ? (
            <div className="p-4">
              <ErrorState
                message={
                  messagesError instanceof Error
                    ? messagesError.message
                    : "读取邮件失败"
                }
              />
            </div>
          ) : null}
          {messages.map((message) => (
            <button
              key={message.id}
              type="button"
              onClick={() => {
                setShowSyncDetail(false);
                setMessageId(message.id);
              }}
              className={[
                "block w-full border-b border-slate-100 px-4 py-3 text-left transition dark:border-gh-border",
                message.id === messageId
                  ? "bg-sky-50 dark:bg-gh-accent-subtle"
                  : "hover:bg-slate-50 dark:hover:bg-gh-overlay",
              ].join(" ")}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="truncate text-sm font-medium text-slate-900 dark:text-gh-fg">
                  {message.subject || "(无主题)"}
                </span>
                <span className="shrink-0 text-xs text-slate-400 dark:text-gh-fg-subtle">
                  {formatDateTime(message.date)}
                </span>
              </div>
              <div className="mt-1 flex items-center gap-2 text-xs text-slate-500 dark:text-gh-fg-muted">
                {view === "all" && message.folder_name ? (
                  <span className="rounded bg-slate-100 px-2 py-0.5 dark:bg-gh-overlay">
                    {message.folder_name}
                  </span>
                ) : null}
                <span className="truncate">
                  {message.from_name || message.from_addr || "未知发件人"}
                </span>
              </div>
            </button>
          ))}
          {!messages.length && !messagesLoading ? (
            <div className="px-4 py-8 text-sm text-slate-400 dark:text-gh-fg-subtle">
              {view === "all"
                ? "还没有同步到任何邮件。"
                : "这个文件夹还没有同步到邮件。"}
            </div>
          ) : null}
        </div>
      </section>

      <section className="min-w-0 flex-1 overflow-y-auto bg-slate-100 p-4 dark:bg-gh-canvas">
        <div className="mx-auto max-w-4xl space-y-3">
          {showSyncDetail ? (
            <>
              <SyncStatusPanel status={syncStatus} />
              {syncEventsQuery.isLoading ? (
                <LoadingState label="读取同步事件..." />
              ) : null}
              {syncEventsQuery.error ? (
                <ErrorState
                  message={
                    syncEventsQuery.error instanceof Error
                      ? syncEventsQuery.error.message
                      : "读取同步事件失败"
                  }
                />
              ) : null}
              <SyncEventTimeline events={syncEventsQuery.data ?? []} />
            </>
          ) : (
            <>
              {messageQuery.isLoading ? (
                <LoadingState label="读取邮件..." />
              ) : null}
              {messageQuery.error ? (
                <ErrorState
                  message={
                    messageQuery.error instanceof Error
                      ? messageQuery.error.message
                      : "读取邮件失败"
                  }
                />
              ) : null}

              {messageQuery.data ? (
                <article className="space-y-3">
                  <header className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-gh-border dark:bg-gh-subtle">
                    <h1 className="text-xl font-semibold leading-7 text-slate-900 dark:text-gh-fg">
                      {messageQuery.data.subject || "(无主题)"}
                    </h1>
                    <div className="mt-3 space-y-1 text-sm text-slate-500 dark:text-gh-fg-muted">
                      <div>
                        {messageQuery.data.from_name || "未知"} &lt;
                        {messageQuery.data.from_addr || "未知"} &gt;
                      </div>
                      <div>{formatDateTime(messageQuery.data.date)}</div>
                    </div>
                  </header>

                  <MessageBody
                    key={messageQuery.data.id}
                    html={messageQuery.data.body_html}
                    text={messageQuery.data.body_text}
                  />
                </article>
              ) : null}

              {!messageId ? (
                <div className="flex h-64 items-center justify-center text-sm text-slate-400 dark:text-gh-fg-subtle">
                  选择一封邮件查看详情。
                </div>
              ) : null}
            </>
          )}
        </div>
      </section>
    </div>
  );
}