const milestones = [
  "M0.1 FastAPI 骨架",
  "M0.2 React + Vite + Tailwind",
  "M1 SQLite 数据层",
  "M2 Mock IMAP 与 IMAP 适配器",
  "M3 同步状态机",
  "M4 API 契约",
  "M5 可观测面板与 Tauri",
];

function App() {
  return (
    <main className="mx-auto flex min-h-screen max-w-4xl flex-col justify-center gap-8 px-6 py-16">
      <header className="space-y-3">
        <p className="text-sm font-medium uppercase tracking-[0.3em] text-sky-600">
          HyMail
        </p>
        <h1 className="text-4xl font-semibold tracking-tight text-slate-950">
          v0.0.1 工程基线
        </h1>
        <p className="max-w-2xl text-base leading-7 text-slate-600">
          单账号 IMAP 同步引擎 + 可观测状态面板。
        </p>
      </header>

      <section className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="text-lg font-semibold text-slate-900">当前里程碑</h2>
        <ol className="mt-4 space-y-2 text-sm text-slate-600">
          {milestones.map((milestone) => (
            <li key={milestone} className="flex gap-3">
              <span className="text-sky-600">•</span>
              <span>{milestone}</span>
            </li>
          ))}
        </ol>
      </section>
    </main>
  );
}

export default App;