// API keys and scopes. Scopes are "<resource>:<action>"; "admin" implies everything.
import type { ApiRequest } from "./http.ts";
import { header } from "./http.ts";
import { forbidden, unauthorized } from "./errors.ts";

export type Scope = "jobs:read" | "jobs:write" | "admin";

export interface Principal {
  name: string;
  key: string;
  scopes: Scope[];
}

export type KeyTable = Record<string, { name: string; scopes: Scope[] }>;

export function authenticate(request: ApiRequest, keys: KeyTable): Principal {
  const auth = header(request, "authorization") ?? "";
  const match = /^Bearer\s+(\S+)$/i.exec(auth.trim());
  const key = match ? match[1] : header(request, "x-api-key");
  if (!key) throw unauthorized();
  const entry = keys[key];
  if (!entry) throw unauthorized();
  return { name: entry.name, key, scopes: entry.scopes };
}

export function hasScope(principal: Principal, scope: Scope): boolean {
  return principal.scopes.includes("admin") || principal.scopes.includes(scope);
}

export function requireScope(principal: Principal, scope: Scope): void {
  if (!hasScope(principal, scope)) {
    throw forbidden(`API key "${principal.name}" lacks scope ${scope}`);
  }
}
