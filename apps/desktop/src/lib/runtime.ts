export type ApiRuntimeConfig = {
  baseUrl: string;
  token?: string;
};

function isTauriRuntime(): boolean {
  return Object.hasOwn(window, "__TAURI_INTERNALS__");
}

export async function getRuntimeConfig(): Promise<ApiRuntimeConfig> {
  if (isTauriRuntime()) {
    const { invoke } = await import("@tauri-apps/api/core");
    return await invoke<ApiRuntimeConfig>("get_api_config");
  }

  return {
    baseUrl:
      import.meta.env.VITE_API_BASE_URL ?? "http://127.0.0.1:8000",
  };
}

export async function waitForHealth(baseUrl: string): Promise<void> {
  const deadline = Date.now() + 15_000;

  while (Date.now() < deadline) {
    try {
      const response = await fetch(`${baseUrl}/health`);
      if (response.ok) {
        return;
      }
    } catch {
      // retry until deadline
    }
    await new Promise((resolve) => window.setTimeout(resolve, 150));
  }

  throw new Error("HyMail API did not become ready in time");
}