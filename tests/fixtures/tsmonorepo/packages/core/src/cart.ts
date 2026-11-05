import { applyDiscount } from '@shop/core/pricing';

export interface CartLine { sku: string; qty: number; unitPrice: number }

export function cartTotal(lines: CartLine[], code?: string): number {
  const subtotal = lines.reduce((sum, l) => sum + l.qty * l.unitPrice, 0);
  return code ? applyDiscount(subtotal, code) : subtotal;
}
