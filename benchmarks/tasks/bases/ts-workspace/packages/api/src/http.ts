// Request/response shapes. The API is transport-agnostic: callers hand in plain objects.

export interface ApiRequest {
  method: string;
  path: string;
  query?: Record<string, string>;
  headers?: Record<string, string>;
  body?: unknown;
}

export interface ApiResponse {
  status: number;
  headers: Record<string, string>;
  body: unknown;
}

export function json(status: number, body: unknown, headers: Record<string, string> = {}): ApiResponse {
  return { status, headers: { "content-type": "application/json", ...headers }, body };
}

export function noContent(): ApiResponse {
  return { status: 204, headers: {}, body: null };
}

// Header names are case-insensitive.
export function header(request: ApiRequest, name: string): string | undefined {
  const wanted = name.toLowerCase();
  for (const [key, value] of Object.entries(request.headers ?? {})) {
    if (key.toLowerCase() === wanted) return value;
  }
  return undefined;
}

export function queryParam(request: ApiRequest, name: string): string | undefined {
  const value = request.query?.[name];
  return value === undefined || value === "" ? undefined : value;
}
