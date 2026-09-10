/**
 * Light/dark theme handling.
 *
 * The choice lives on `<html class="dark">` so Tailwind's class-driven `dark:`
 * variant can see it. It is persisted in localStorage, and the same value is
 * applied before first paint by a small inline script in index.html — keep
 * THEME_STORAGE_KEY in sync with that script.
 */

export type Theme = "light" | "dark";

export const THEME_STORAGE_KEY = "hymail.theme";

export function isTheme(value: unknown): value is Theme {
  return value === "light" || value === "dark";
}

export function systemTheme(): Theme {
  return window.matchMedia?.("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

export function readStoredTheme(): Theme | null {
  try {
    const stored = window.localStorage.getItem(THEME_STORAGE_KEY);
    return isTheme(stored) ? stored : null;
  } catch {
    // localStorage can be unavailable (private mode, blocked storage).
    return null;
  }
}

export function persistTheme(theme: Theme): void {
  try {
    window.localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Persisting is best-effort; the in-memory choice still applies.
  }
}

/**
 * An explicit choice wins; otherwise follow the operating system.
 */
export function resolveInitialTheme(): Theme {
  return readStoredTheme() ?? systemTheme();
}

export function applyTheme(theme: Theme): void {
  document.documentElement.classList.toggle("dark", theme === "dark");
}

export function nextTheme(theme: Theme): Theme {
  return theme === "dark" ? "light" : "dark";
}
