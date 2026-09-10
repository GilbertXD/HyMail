import createClient from "openapi-fetch";

import type { components, paths } from "./schema";

export type { components, paths };

export function createApiClient(options: {
  baseUrl: string;
  token?: string;
}) {
  const client = createClient<paths>({
    baseUrl: options.baseUrl,
  });

  if (options.token) {
    client.use({
      onRequest({ request }) {
        request.headers.set(
          "Authorization",
          `Bearer ${options.token}`,
        );
        return request;
      },
    });
  }

  return client;
}

export const apiClient = createApiClient({
  baseUrl: "http://127.0.0.1:8000",
});