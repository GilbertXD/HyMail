import { useTheme } from "../lib/useTheme";

/**
 * Compact icon-only toggle. It sits at the bottom-left of the sidebar and
 * deliberately does not stretch across it.
 */
export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  const label = dark ? "切换到日间模式" : "切换到夜间模式";

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={label}
      title={label}
      data-testid="theme-toggle"
      className="flex h-8 w-8 items-center justify-center rounded-full border border-slate-200 bg-white text-sm leading-none transition hover:bg-slate-100 dark:border-gh-border dark:bg-gh-overlay dark:hover:bg-gh-border"
    >
      <span aria-hidden="true">{dark ? "☀️" : "🌙"}</span>
    </button>
  );
}
