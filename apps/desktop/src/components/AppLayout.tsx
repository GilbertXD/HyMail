import { NavLink, Outlet } from "react-router-dom";

import { ThemeToggle } from "./ThemeToggle";

const navItems = [
  { to: "/mail", label: "邮件", icon: "✉" },
  { to: "/setup", label: "账号", icon: "⚙" },
];

export function AppLayout() {
  return (
    <div className="flex h-screen overflow-hidden bg-slate-100 text-slate-900 dark:bg-gh-canvas dark:text-gh-fg">
      <aside className="flex w-48 shrink-0 flex-col border-r border-slate-200 bg-white dark:border-gh-border dark:bg-gh-subtle">
        <div className="flex h-14 items-center gap-2 border-b border-slate-100 px-5 text-lg font-semibold tracking-tight dark:border-gh-border">
          <span>📮</span>
          <span>HyMail</span>
        </div>

        <nav className="flex-1 space-y-1 overflow-y-auto p-3">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                [
                  "flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition",
                  isActive
                    ? "bg-sky-50 font-medium text-sky-700 dark:bg-gh-accent-subtle dark:text-gh-accent"
                    : "text-slate-600 hover:bg-slate-100 hover:text-slate-900 dark:text-gh-fg dark:hover:bg-gh-overlay dark:hover:text-gh-fg",
                ].join(" ")
              }
            >
              <span className="w-4 text-center text-base">{item.icon}</span>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="flex items-center justify-start border-t border-slate-100 p-3 dark:border-gh-border">
          <ThemeToggle />
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center border-b border-slate-200 bg-white px-5 text-xs text-slate-500 dark:border-gh-border dark:bg-gh-subtle dark:text-gh-fg-muted">
          本地邮件客户端 · IMAP
        </header>
        <main className="min-h-0 flex-1 overflow-hidden bg-slate-100 dark:bg-gh-canvas">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
