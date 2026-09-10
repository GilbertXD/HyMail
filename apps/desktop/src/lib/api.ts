import { createApiClient } from "@hymail/api-client";
import type { components } from "@hymail/api-client";

let apiClient = createApiClient({
  baseUrl: "http://127.0.0.1:8000",
});

export function configureApiClient(options: {
  baseUrl: string;
  token?: string;
}): void {
  apiClient = createApiClient(options);
}

export type AccountCreate = components["schemas"]["AccountCreate"];
export type AccountRead = components["schemas"]["AccountRead"];
export type ConnectionTestRequest =
  components["schemas"]["ConnectionTestRequest"];
export type ConnectionTestResponse =
  components["schemas"]["ConnectionTestResponse"];
export type FolderRead = components["schemas"]["FolderRead"];
export type MessageSummary = components["schemas"]["MessageSummary"];
export type MessageDetail = components["schemas"]["MessageDetail"];
export type SyncStatusRead = components["schemas"]["SyncStatusRead"];
export type SyncEventRead = components["schemas"]["SyncEventRead"];

export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `HTTP ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

type FetchResult<T> = {
  data?: T;
  error?: unknown;
  response: Response;
};

function unwrap<T>(result: FetchResult<T>): T {
  if (result.error !== undefined || result.data === undefined) {
    throw new ApiError(
      result.response.status,
      result.error ?? result.response.statusText,
    );
  }
  return result.data;
}

export async function getCurrentAccount(): Promise<AccountRead> {
  return unwrap(await apiClient.GET("/api/v1/accounts/current"));
}

export async function upsertAccount(
  payload: AccountCreate,
): Promise<AccountRead> {
  return unwrap(await apiClient.POST("/api/v1/accounts", { body: payload }));
}

export async function testConnection(
  payload: ConnectionTestRequest,
): Promise<ConnectionTestResponse> {
  return unwrap(await apiClient.POST("/api/v1/accounts/test", { body: payload }));
}

export async function listFolders(): Promise<FolderRead[]> {
  return unwrap(await apiClient.GET("/api/v1/folders"));
}

export async function listMessages(
  folderId: string,
): Promise<MessageSummary[]> {
  return unwrap(
    await apiClient.GET("/api/v1/folders/{folder_id}/messages", {
      params: {
        path: { folder_id: folderId },
        query: { limit: 100, offset: 0 },
      },
    }),
  );
}

export async function getMessage(messageId: string): Promise<MessageDetail> {
  return unwrap(
    await apiClient.GET("/api/v1/messages/{message_id}", {
      params: { path: { message_id: messageId } },
    }),
  );
}

export async function getSyncStatus(
  folder = "INBOX",
): Promise<SyncStatusRead> {
  return unwrap(
    await apiClient.GET("/api/v1/sync/status", {
      params: { query: { folder } },
    }),
  );
}

export async function triggerSync(folder = "INBOX"): Promise<SyncStatusRead> {
  return unwrap(
    await apiClient.POST("/api/v1/sync/trigger", {
      body: { folder },
    }),
  );
}

export async function cancelSync(
  folder = "INBOX",
): Promise<{ cancelled: boolean }> {
  return unwrap(
    await apiClient.POST("/api/v1/sync/cancel", {
      body: { folder },
    }),
  );
}

export async function listSyncEvents(
  afterId = 0,
): Promise<SyncEventRead[]> {
  return unwrap(
    await apiClient.GET("/api/v1/sync/events", {
      params: { query: { after_id: afterId, limit: 200 } },
    }),
  );
}