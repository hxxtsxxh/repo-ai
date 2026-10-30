const DISCOUNTS: Record<string, number> = { SPRING10: 0.1, VIP20: 0.2 };

/** Apply a promotional discount code to a subtotal. */
export function applyDiscount(subtotal: number, code: string): number {
  const rate = DISCOUNTS[code.toUpperCase()] ?? 0;
  return Math.round(subtotal * (1 - rate) * 100) / 100;
}
