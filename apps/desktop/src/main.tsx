import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { configureApiClient } from "./lib/api";
import { getRuntimeConfig, waitForHealth } from "./lib/runtime";
import "./index.css";

async function bootstrap() {
  const config = await getRuntimeConfig();
  await waitForHealth(config.baseUrl);
  configureApiClient(config);

  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

void bootstrap();