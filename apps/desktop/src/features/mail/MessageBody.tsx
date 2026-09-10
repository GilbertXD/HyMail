import { useEffect, useRef, useState } from "react";

import { buildSrcDoc } from "../../lib/messageHtml";

/**
 * Renders a message body.
 *
 * HTML bodies go into a sandboxed iframe rather than the app document, so the
 * message's own styles and fonts cannot leak into the UI. Plain text messages
 * keep the simple `<pre>` rendering.
 */
export function MessageBody({
  html,
  text,
}: {
  html?: string | null;
  text?: string | null;
}) {
  const [allowRemoteImages, setAllowRemoteImages] = useState(false);
  const [height, setHeight] = useState(0);
  const [frameLoads, setFrameLoads] = useState(0);
  const frameRef = useRef<HTMLIFrameElement | null>(null);

  const srcDoc = html ? buildSrcDoc(html, { allowRemoteImages }) : undefined;

  useEffect(() => {
    if (!srcDoc) {
      return;
    }
    const doc = frameRef.current?.contentDocument;
    if (!doc?.body) {
      return;
    }

    const measure = () => {
      const next = Math.max(
        doc.documentElement?.scrollHeight ?? 0,
        doc.body.scrollHeight,
      );
      if (next > 0) {
        setHeight(next);
      }
    };

    measure();

    if (typeof ResizeObserver === "undefined") {
      return;
    }
    const observer = new ResizeObserver(measure);
    observer.observe(doc.body);
    return () => observer.disconnect();
  }, [srcDoc, frameLoads]);

  if (!html) {
    return (
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm dark:border-gh-border dark:bg-gh-subtle">
        <pre className="whitespace-pre-wrap break-words font-sans text-sm leading-7 text-slate-700 dark:text-gh-fg">
          {text || "(无正文)"}
        </pre>
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm dark:border-gh-border dark:bg-gh-subtle">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-100 bg-slate-50 px-4 py-2 text-xs text-slate-500 dark:border-gh-border dark:bg-gh-subtle dark:text-gh-fg-muted">
        <span>
          {allowRemoteImages
            ? "已允许加载远程图片"
            : "远程图片已屏蔽，避免被发件人追踪"}
        </span>
        <label className="flex items-center gap-2 text-slate-600 dark:text-gh-fg">
          <input
            type="checkbox"
            checked={allowRemoteImages}
            onChange={(event) => setAllowRemoteImages(event.target.checked)}
            data-testid="message-allow-images"
          />
          显示远程图片
        </label>
      </div>

      {/* The frame keeps a white canvas on purpose: messages are authored for
          a light background and would be unreadable if inverted. */}
      <iframe
        ref={frameRef}
        title="邮件正文"
        sandbox="allow-same-origin"
        srcDoc={srcDoc}
        onLoad={() => setFrameLoads((count) => count + 1)}
        data-testid="message-body-frame"
        className="w-full border-0 bg-white"
        style={{ height: height > 0 ? `${height}px` : "320px" }}
      />
    </div>
  );
}
