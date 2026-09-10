import { act, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RetryCountdown } from "./RetryCountdown";

describe("RetryCountdown", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("counts down from the estimated backoff", () => {
    vi.useFakeTimers();
    render(<RetryCountdown attempts={3} />);

    expect(screen.getByText(/4s/)).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1000);
    });

    expect(screen.getByText(/3s/)).toBeInTheDocument();
  });
});