import { describe, expect, it } from "vitest";

import { buildMessageCsp, buildSrcDoc } from "./messageHtml";

const FULL_DOCUMENT =
  '<!DOCTYPE HTML><html><head><title>Mail</title>' +
  "<style>body{font-family:Comic Sans MS}</style></head>" +
  "<body><p>hello</p></body></html>";

describe("buildMessageCsp", () => {
  it("blocks remote images by default", () => {
    const csp = buildMessageCsp(false);
    expect(csp).toContain("img-src data: cid:");
    expect(csp).not.toContain("img-src *");
  });

  it("allows remote images when the user opts in", () => {
    expect(buildMessageCsp(true)).toContain("img-src * data: cid:");
  });

  it("never allows scripts", () => {
    for (const allow of [true, false]) {
      const csp = buildMessageCsp(allow);
      expect(csp).toContain("default-src 'none'");
      expect(csp).not.toContain("script-src");
      expect(csp).not.toContain("'unsafe-inline' 'self'");
    }
  });
});

describe("buildSrcDoc", () => {
  it("injects the policy right after an existing head tag", () => {
    const srcDoc = buildSrcDoc(FULL_DOCUMENT, { allowRemoteImages: false });
    const headEnd = srcDoc.indexOf("<head>") + "<head>".length;

    expect(srcDoc.slice(headEnd)).toMatch(
      /^<meta http-equiv="Content-Security-Policy"/,
    );
    expect(srcDoc).toContain("default-src 'none'");
  });

  it("keeps the message's own styles intact", () => {
    // The email's CSS must survive; it is only *contained*, not stripped.
    const srcDoc = buildSrcDoc(FULL_DOCUMENT, { allowRemoteImages: false });
    expect(srcDoc).toContain("body{font-family:Comic Sans MS}");
    expect(srcDoc).toContain("<p>hello</p>");
  });

  it("wraps fragments in a full document", () => {
    const srcDoc = buildSrcDoc("<p>bare</p>", { allowRemoteImages: false });
    expect(srcDoc.startsWith("<!doctype html>")).toBe(true);
    expect(srcDoc).toContain("<p>bare</p>");
    expect(srcDoc).toContain("Content-Security-Policy");
  });

  it("adds a no-referrer policy", () => {
    expect(
      buildSrcDoc(FULL_DOCUMENT, { allowRemoteImages: false }),
    ).toContain('name="referrer" content="no-referrer"');
  });

  it("strips meta refresh", () => {
    const srcDoc = buildSrcDoc(
      '<html><head><meta http-equiv="refresh" content="0;url=http://evil.test">' +
        "</head><body>x</body></html>",
      { allowRemoteImages: false },
    );
    expect(srcDoc.toLowerCase()).not.toContain("http-equiv=\"refresh\"");
    expect(srcDoc).toContain("x");
  });

  it("switches the image policy when remote images are allowed", () => {
    expect(
      buildSrcDoc(FULL_DOCUMENT, { allowRemoteImages: true }),
    ).toContain("img-src * data: cid:");
  });
});
