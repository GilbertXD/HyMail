/**
 * Builds the sandboxed document used to render an email body.
 *
 * Email HTML is untrusted and self-contained: it ships its own `<style>`
 * blocks, fonts and remote images. Injecting it into the app document lets
 * those styles escape and restyle the whole UI (a `<style>` tag applies
 * document-wide no matter where it was inserted), so the body is rendered
 * inside an `<iframe srcdoc>` instead, where CSS cannot reach the app.
 *
 * The frame carries no `allow-scripts`, and the CSP below locks the document
 * down to inline styles only. Remote images are blocked by default so that
 * opening a message cannot ping a tracking pixel.
 */

export type MessageHtmlOptions = {
  allowRemoteImages: boolean;
};

export function buildMessageCsp(allowRemoteImages: boolean): string {
  return [
    "default-src 'none'",
    "style-src 'unsafe-inline'",
    allowRemoteImages ? "img-src * data: cid:" : "img-src data: cid:",
    "font-src data:",
    "form-action 'none'",
    "base-uri 'none'",
  ].join("; ");
}

/**
 * `<meta http-equiv="refresh">` would let a message navigate the frame to a
 * remote page, which the CSP does not cover.
 */
function stripMetaRefresh(html: string): string {
  return html.replace(
    /<meta[^>]+http-equiv\s*=\s*["']?refresh["']?[^>]*>/gi,
    "",
  );
}

export function buildSrcDoc(
  html: string,
  options: MessageHtmlOptions,
): string {
  const head =
    `<meta http-equiv="Content-Security-Policy" ` +
    `content="${buildMessageCsp(options.allowRemoteImages)}">` +
    `<meta name="referrer" content="no-referrer">`;

  const content = stripMetaRefresh(html);

  const headTag = /<head[^>]*>/i.exec(content);
  if (headTag) {
    const insertAt = headTag.index + headTag[0].length;
    return content.slice(0, insertAt) + head + content.slice(insertAt);
  }

  return (
    `<!doctype html><html><head><meta charset="utf-8">${head}</head>` +
    `<body>${content}</body></html>`
  );
}
