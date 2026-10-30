import { applyDiscount } from './pricing';

test('applies spring discount', () => {
  expect(applyDiscount(100, 'SPRING10')).toBe(90);
});
