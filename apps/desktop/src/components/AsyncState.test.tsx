import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ErrorState } from "./AsyncState";

describe("ErrorState", () => {
  it("renders an error message", () => {
    render(<ErrorState message="同步失败" />);
    expect(screen.getByText("同步失败")).toBeInTheDocument();
  });
});