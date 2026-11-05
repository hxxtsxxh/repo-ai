// Opaque cursor pagination. A cursor encodes the id of the last item returned.
import { badRequest } from "./errors.ts";

export const DEFAULT_LIMIT = 20;
export const MAX_LIMIT = 100;

export function encodeCursor(id: string): string {
  return Buffer.from(JSON.stringify({ after: id }), "utf8").toString("base64url");
}

export function decodeCursor(cursor: string): string {
  try {
    const parsed = JSON.parse(Buffer.from(cursor, "base64url").toString("utf8"));
    if (typeof parsed?.after !== "string") throw new Error("missing after");
    return parsed.after;
  } catch {
    throw badRequest("invalid cursor");
  }
}

export function parseLimit(raw: string | undefined): number {
  if (raw === undefined) return DEFAULT_LIMIT;
  const limit = Number(raw);
  if (!Number.isInteger(limit) || limit < 1) throw badRequest("limit must be a positive integer");
  return Math.min(limit, MAX_LIMIT);
}

export interface PageOf<T> {
  items: T[];
  nextCursor: string | null;
}

export function paginate<T extends { id: string }>(items: T[], limit: number, cursor?: string): PageOf<T> {
  let start = 0;
  if (cursor !== undefined) {
    const after = decodeCursor(cursor);
    const index = items.findIndex((item) => item.id === after);
    if (index < 0) throw badRequest("cursor does not match any item");
    start = index + 1;
  }
  const page = items.slice(start, start + limit);
  const hasMore = start + limit < items.length;
  return {
    items: page,
    nextCursor: hasMore ? encodeCursor(page[page.length - 1].id) : null,
  };
}
