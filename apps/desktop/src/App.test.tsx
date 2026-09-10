import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import App from "./App";

describe("App", () => {
  it("renders the v0.0.1 baseline heading", () => {
    render(<App />);

    expect(
      screen.getByRole("heading", { name: "v0.0.1 工程基线" }),
    ).toBeInTheDocument();
  });
});