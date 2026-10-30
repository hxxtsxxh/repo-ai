// Fixed-width text tables.
import { padEndTo, truncate, displayWidth } from "../../core/src/strings.ts";

export interface Column<T> {
  header: string;
  value: (row: T) => string;
  maxWidth?: number;
}

export function renderTable<T>(columns: Column<T>[], rows: T[]): string[] {
  const cells = rows.map((row) =>
    columns.map((col) => {
      const text = col.value(row);
      return col.maxWidth ? truncate(text, col.maxWidth) : text;
    }),
  );
  const widths = columns.map((col, i) =>
    Math.max(displayWidth(col.header), ...cells.map((r) => displayWidth(r[i]))),
  );
  const line = (values: string[]) =>
    values
      .map((v, i) => padEndTo(v, widths[i]))
      .join("  ")
      .trimEnd();
  return [line(columns.map((c) => c.header)), ...cells.map(line)];
}
