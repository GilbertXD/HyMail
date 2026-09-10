import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { LoadingState, ErrorState } from "../../components/AsyncState";
import {
  ApiError,
  getMessage,
  listFolders,
  listMessages,
} from "../../lib/api";
import { formatDateTime } from "../../lib/format";

export function MailPage() {
  const [selectedFolderId, setSelectedFolderId] = useState<string | null>(null);
  const [messageId, setMessageId] = useState<string | null>(null);

  const foldersQuery = useQuery({
    queryKey: ["folders"],
    queryFn: listFolders,
    retry: false,
  });

  const folderId = selectedFolderId ?? foldersQuery.data?.[0]?.id ?? null;

  const messagesQuery = useQuery({
    queryKey: ["messages", folderId],
    queryFn: () => listMessages(folderId as string),
    enabled: Boolean(folderId),
    retry: false,
  });

  const messageQuery = useQuery({
    queryKey: ["message", messageId],
    queryFn: () => getMessage(messageId as string),
    enabled: Boolean(messageId),
    retry: false,
  });

  if (foldersQuery.isLoading) {
    return <LoadingState label="读取文件夹..." />;
  }

  if (foldersQuery.error instanceof ApiError && foldersQuery.error.status === 404) {
    return (
      <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center shadow-sm">
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
    );
  }

  if (foldersQuery.error) {
    return (
      <ErrorState
        message={
          foldersQuery.error instanceof Error
            ? foldersQuery.error.message
            : "读取文件夹失败"
        }
      />
    );
  }

  const folders = foldersQuery.data ?? [];
  const messages = messagesQuery.data ?? [];

  return (
    <div className="grid min-h-[620px] grid-cols-12 gap-5">
      <aside className="col-span-3 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
        <h2 className="mb-3 text-sm font-semibold text-slate-500">文件夹</h2>
        <div className="space-y-1">
          {folders.map((folder) => (
            <button
              key={folder.id}
              type="button"
              onClick={() => {
                setSelectedFolderId(folder.id);
                setMessageId(null);
              }}
              className={[
                "flex w-full items-center justify-between rounded-lg px-3 py-2 text-left text-sm",
                folder.id === folderId
                  ? "bg-slate-900 text-white"
                  : "text-slate-700 hover:bg-slate-100",
              ].join(" ")}
            >
              <span>{folder.name}</span>
              <span className="text-xs opacity-70">{folder.message_count}</span>
            </button>
          ))}
        </div>
      </aside>

      <section className="col-span-4 rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 px-4 py-3">
          <h2 className="text-sm font-semibold text-slate-500">邮件</h2>
        </div>
        <div className="divide-y divide-slate-100">
          {messages.map((message) => (
            <button
              key={message.id}
              type="button"
              onClick={() => setMessageId(message.id)}
              className={[
                "block w-full px-4 py-3 text-left",
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
              <p className="mt-1 truncate text-xs text-slate-500">
                {message.from_name || message.from_addr || "未知发件人"}
              </p>
            </button>
          ))}
          {!messages.length ? (
            <div className="px-4 py-8 text-sm text-slate-400">
              这个文件夹还没有同步到邮件。
            </div>
          ) : null}
        </div>
      </section>

      <section className="col-span-5 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        {messageQuery.isLoading ? <LoadingState label="读取邮件..." /> : null}
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
          <article className="space-y-5">
            <header className="space-y-2 border-b border-slate-200 pb-4">
              <h1 className="text-xl font-semibold text-slate-900">
                {messageQuery.data.subject || "(无主题)"}
              </h1>
              <div className="text-sm text-slate-500">
                <div>
                  {messageQuery.data.from_name || "未知"} &lt;
                  {messageQuery.data.from_addr || "未知"} &gt;
                </div>
                <div>{formatDateTime(messageQuery.data.date)}</div>
              </div>
            </header>
            {messageQuery.data.body_html ? (
              <div
                className="prose prose-slate max-w-none text-sm"
                dangerouslySetInnerHTML={{ __html: messageQuery.data.body_html }}
              />
            ) : (
              <pre className="whitespace-pre-wrap font-sans text-sm leading-7 text-slate-700">
                {messageQuery.data.body_text || "(无正文)"}
              </pre>
            )}
          </article>
        ) : null}
        {!messageId ? (
          <div className="text-sm text-slate-400">选择一封邮件查看详情。</div>
        ) : null}
      </section>
    </div>
  );
}