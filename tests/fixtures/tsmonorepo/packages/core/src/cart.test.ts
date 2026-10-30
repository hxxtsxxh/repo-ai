import { cartTotal } from './cart';

test('sums lines', () => {
  expect(cartTotal([{ sku: 'a', qty: 2, unitPrice: 5 }])).toBe(10);
});
