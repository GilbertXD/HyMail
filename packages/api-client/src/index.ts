import createClient from "openapi-fetch";

import type { paths } from "./schema";

export const apiClient = createClient<paths>({
  baseUrl: "http://127.0.0.1:8000",
});