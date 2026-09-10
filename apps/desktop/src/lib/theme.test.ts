import { afterEach, describe, expect, it, vi } from "vitest";

import {
  applyTheme,
  nextTheme,
  persistTheme,
  readStoredTheme,
  resolveInitialTheme,
  systemTheme,
  THEME_STORAGE_KEY,
} from "./theme";

function stubSystemTheme(theme: "light" | "dark") {
  vi.stubGlobal(
    "matchMedia",
    vi.fn().mockReturnValue({
      matches: theme === "dark",
      media: "(prefers-color-scheme: dark)",
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.localStorage.clear();
  document.documentElement.classList.remove("dark");
});

describe("systemTheme", () => {
  it("follows the prefers-color-scheme media query", () => {
    stubSystemTheme("dark");
    expect(systemTheme()).toBe("dark");

    stubSystemTheme("light");
    expect(systemTheme()).toBe("light");
  });
});

describe("resolveInitialTheme", () => {
  it("prefers an explicit stored choice over the system", () => {
    stubSystemTheme("dark");
    persistTheme("light");
    expect(resolveInitialTheme()).toBe("light");

    stubSystemTheme("light");
    persistTheme("dark");
    expect(resolveInitialTheme()).toBe("dark");
  });

  it("falls back to the system when nothing is stored", () => {
    stubSystemTheme("dark");
    expect(resolveInitialTheme()).toBe("dark");
  });

  it("ignores an unrecognised stored value", () => {
    stubSystemTheme("light");
    window.localStorage.setItem(THEME_STORAGE_KEY, "neon");
    expect(readStoredTheme()).toBeNull();
    expect(resolveInitialTheme()).toBe("light");
  });
});

describe("applyTheme", () => {
  it("toggles the class Tailwind's dark variant keys off", () => {
    applyTheme("dark");
    expect(document.documentElement.classList.contains("dark")).toBe(true);

    applyTheme("light");
    expect(document.documentElement.classList.contains("dark")).toBe(false);
  });
});

describe("nextTheme", () => {
  it("flips between the two themes", () => {
    expect(nextTheme("light")).toBe("dark");
    expect(nextTheme("dark")).toBe("light");
  });
});

describe("storage", () => {
  it("round-trips a theme", () => {
    persistTheme("dark");
    expect(window.localStorage.getItem(THEME_STORAGE_KEY)).toBe("dark");
    expect(readStoredTheme()).toBe("dark");
  });

  it("survives storage being unavailable", () => {
    // jsdom's Storage is proxy-backed, so spyOn does not intercept it; the
    // whole global has to be replaced.
    vi.stubGlobal("localStorage", {
      getItem() {
        throw new Error("blocked");
      },
      setItem() {
        throw new Error("blocked");
      },
    });

    expect(() => persistTheme("dark")).not.toThrow();
    expect(readStoredTheme()).toBeNull();
    expect(resolveInitialTheme()).toBe("light");
  });
});
