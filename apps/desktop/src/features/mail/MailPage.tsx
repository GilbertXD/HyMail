import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { ErrorState, LoadingState } from "../../components/AsyncState";
import {
  ApiError,
  cancelSync,
  getCurrentAccount,
  getMessage,
  getSyncStatus,
  listAllMessages,
  listFolders,
  listMessages,
  refreshFolders,
  triggerSync,
} from "../../lib/api";
import { formatDateTime, formatSyncState } from "../../lib/format";

type MailView = "all" | string;

export function MailPage() {
  const queryClient = useQueryClient();
  const [view, setView] = useState<MailView>("all");
  const [messageId, setMessageId] = useState<string | null>(null);

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
        <div className="rounded-xl border border-slate-200 bg-white p-8 text-center shadow-sm">
          <h1 className="text-xl font-semibold">还没有配置账号</h1>
          <p className="mt-2 text-sm text-slate-500">
            先配置 IMAP 账号，再触发同步。
          </p>
          <Link
            to="/setup"
            className="mt-4 inline-block rounded-lg bg-slate-900 px-4 py-2 text-sm font-medium text-white"
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
      <aside className="flex w-64 shrink-0 flex-col border-r border-slate-200 bg-slate-50">
        <div className="border-b border-slate-200 p-3">
          <div className="truncate text-sm font-semibold text-slate-900">
            {accountQuery.data?.email ?? "当前账号"}
          </div>
          <button
            type="button"
            className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-50"
            onClick={() => refreshFoldersMutation.mutate()}
            disabled={refreshFoldersMutation.isPending}
          >
            {refreshFoldersMutation.isPending ? "刷新中..." : "刷新文件夹"}
          </button>
          {refreshFoldersMutation.error ? (
            <div className="mt-2 text-xs text-red-600">
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
                ? "bg-sky-50 font-medium text-sky-700"
                : "text-slate-600 hover:bg-slate-100",
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
                    ? "bg-sky-50 font-medium text-sky-700"
                    : "text-slate-600 hover:bg-slate-100",
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

      <section className="flex w-96 shrink-0 flex-col border-r border-slate-200 bg-white">
        <div className="flex h-12 shrink-0 items-center justify-between border-b border-slate-100 px-4">
          <h2 className="truncate text-sm font-semibold text-slate-700">
            {view === "all" ? "全部邮件" : selectedFolder?.name ?? "邮件"}
          </h2>
          <span className="text-xs text-slate-400">{messages.length} 封</span>
        </div>

        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-2 text-xs">
          <span className="text-slate-500">状态：</span>
          <span
            className="font-medium text-slate-800"
            data-testid="mail-sync-state"
          >
            {retrying
              ? "重试中"
              : formatSyncState(syncStatus?.state ?? "idle")}
          </span>
          {syncStatus ? (
            <span className="text-slate-400" data-testid="mail-sync-last-uid">
              last UID: {syncStatus.last_uid}
            </span>
          ) : null}
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-1 font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-40"
            onClick={() => triggerMutation.mutate()}
            disabled={!selectedFolder || triggerMutation.isPending}
          >
            同步
          </button>
          <button
            type="button"
            className="rounded border border-slate-300 px-2 py-1 font-medium text-slate-600 hover:bg-slate-100 disabled:opacity-40"
            onClick={() => cancelMutation.mutate()}
            disabled={!selectedFolder || cancelMutation.isPending}
          >
            取消
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
              onClick={() => setMessageId(message.id)}
              className={[
                "block w-full border-b border-slate-100 px-4 py-3 text-left transition",
                message.id === messageId ? "bg-sky-50" : "hover:bg-slate-50",
              ].join(" ")}
            >
              <div className="flex items-center justify-between gap-3">
                <span className="truncate text-sm font-medium text-slate-900">
                  {message.subject || "(无主题)"}
                </span>
                <span className="shrink-0 text-xs text-slate-400">
                  {formatDateTime(message.date)}
                </span>
              </div>
              <div className="mt-1 flex items-center gap-2 text-xs text-slate-500">
                {view === "all" && message.folder_name ? (
                  <span className="rounded bg-slate-100 px-2 py-0.5">
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
            <div className="px-4 py-8 text-sm text-slate-400">
              {view === "all"
                ? "还没有同步到任何邮件。"
                : "这个文件夹还没有同步到邮件。"}
            </div>
          ) : null}
        </div>
      </section>

      <section className="min-w-0 flex-1 overflow-y-auto bg-slate-100 p-4">
        <div className="mx-auto max-w-4xl space-y-3">
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
              <header className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                <h1 className="text-xl font-semibold leading-7 text-slate-900">
                  {messageQuery.data.subject || "(无主题)"}
                </h1>
                <div className="mt-3 space-y-1 text-sm text-slate-500">
                  <div>
                    {messageQuery.data.from_name || "未知"} &lt;
                    {messageQuery.data.from_addr || "未知"} &gt;
                  </div>
                  <div>{formatDateTime(messageQuery.data.date)}</div>
                </div>
              </header>

              <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
                {messageQuery.data.body_html ? (
                  <div
                    className="prose prose-slate max-w-none break-words text-sm"
                    dangerouslySetInnerHTML={{
                      __html: messageQuery.data.body_html,
                    }}
                  />
                ) : (
                  <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-7 text-slate-700">
                    {messageQuery.data.body_text || "(无正文)"}
                  </pre>
                )}
              </div>
            </article>
          ) : null}

          {!messageId ? (
            <div className="flex h-64 items-center justify-center text-sm text-slate-400">
              选择一封邮件查看详情。
            </div>
          ) : null}
        </div>
      </section>
    </div>
  );
}