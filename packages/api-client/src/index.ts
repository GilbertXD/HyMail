import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export const apiClient = createClient<paths>({
  baseUrl: "http://127.0.0.1:8000",
});

export type { components, paths };