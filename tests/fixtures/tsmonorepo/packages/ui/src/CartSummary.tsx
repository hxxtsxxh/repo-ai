import { cartTotal, CartLine } from '@shop/core/cart';

export function CartSummary({ lines }: { lines: CartLine[] }) {
  const total = cartTotal(lines);
  return null;
}
