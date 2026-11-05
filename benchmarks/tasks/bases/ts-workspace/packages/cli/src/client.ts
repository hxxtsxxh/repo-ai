// In-process API client used by every command.
import type { ApiRequest, ApiResponse } from "../../api/src/http.ts";

export const CLI_VERSION = "1.5.0";

export class CliError extends Error {
  exitCode: number;

  constructor(message: string, exitCode = 1) {
    super(message);
    this.name = "CliError";
    this.exitCode = exitCode;
  }
}

export interface ApiLike {
  handle(request: ApiRequest): ApiResponse;
}

export interface RequestOptions {
  query?: Record<string, string>;
  body?: unknown;
}

export interface ApiClient {
  request<T = unknown>(method: string, path: string, options?: RequestOptions): T;
}

export function createLocalClient(api: ApiLike, apiKey: string): ApiClient {
  return {
    request<T>(method: string, path: string, options: RequestOptions = {}): T {
      const response = api.handle({
        method,
        path,
        query: options.query ?? {},
        body: options.body,
        headers: { authorization: `Bearer ${apiKey}`, "x-client-version": CLI_VERSION },
      });
      if (response.status >= 400) {
        const error = (response.body as { error?: { message?: string } })?.error;
        const exitCode = response.status === 404 ? 3 : response.status === 401 || response.status === 403 ? 4 : 1;
        throw new CliError(error?.message ?? `request failed with status ${response.status}`, exitCode);
      }
      return response.body as T;
    },
  };
}
