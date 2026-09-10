import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { configureApiClient } from "./lib/api";
import { getRuntimeConfig, waitForHealth } from "./lib/runtime";
import "./index.css";

async function bootstrap() {
  const rootElement = document.getElementById("root");

  if (!rootElement) {
    throw new Error("root element not found");
  }

  const root = createRoot(rootElement);

  try {
    const config = await getRuntimeConfig();
    await waitForHealth(config.baseUrl);
    configureApiClient(config);

    root.render(
      <StrictMode>
        <App />
      </StrictMode>,
    );
  } catch (error) {
    root.render(
      <div className="flex min-h-screen items-center justify-center bg-slate-100 p-6">
        <div className="max-w-lg rounded-xl border border-red-200 bg-white p-6 shadow-sm">
          <h1 className="text-lg font-semibold text-red-700">
            HyMail 无法连接本地 API
          </h1>
          <p className="mt-2 text-sm text-slate-600">
            请先启动 FastAPI：
          </p>
          <pre className="mt-3 overflow-auto rounded-lg bg-slate-900 p-3 text-xs text-slate-100">
            uv run uvicorn hymail_api.main:app --reload --host 127.0.0.1 --port 8000
          </pre>
          <p className="mt-3 text-xs text-slate-400">
            {error instanceof Error ? error.message : "unknown error"}
          </p>
        </div>
      </div>,
    );
  }
}

void bootstrap();