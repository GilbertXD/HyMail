import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { SyncStatusRead } from "../../lib/api";
import { SyncStatusPanel } from "./SyncStatusPanel";

const baseStatus: SyncStatusRead = {
  account_id: "00000000-0000-0000-0000-000000000001",
  folder: "INBOX",
  running: false,
  state: "idle",
  last_uid: 10,
  uidvalidity: 1,
  uidnext: 11,
  attempts: 0,
  last_error: null,
  trace_id: "trace-1",
  last_sync_at: "2026-01-01T00:00:00Z",
};

describe("SyncStatusPanel", () => {
  it("renders cursor summary and idle state", () => {
    render(<SyncStatusPanel status={baseStatus} />);

    expect(screen.getByText("INBOX")).toBeInTheDocument();
    expect(screen.getByText("IDLE")).toBeInTheDocument();
    expect(screen.getByText("10")).toBeInTheDocument();
    expect(screen.getByText("11")).toBeInTheDocument();
  });

  it("renders retry state when running with an error", () => {
    render(
      <SyncStatusPanel
        status={{
          ...baseStatus,
          running: true,
          state: "error_backoff",
          attempts: 2,
          last_error: "连接被重置",
        }}
      />,
    );

    expect(screen.getByText("重试中")).toBeInTheDocument();
    expect(screen.getByText("连接被重置")).toBeInTheDocument();
    expect(screen.getByText(/预计下次重试/)).toBeInTheDocument();
  });
});