import { Router } from 'express';
import { cartTotal } from '@shop/core/cart';

export const checkoutRouter = Router();

checkoutRouter.post('/quote', (req, res) => {
  res.json({ total: cartTotal(req.body.lines, req.body.code) });
});

checkoutRouter.post('/confirm', (req, res) => {
  res.status(201).json({ ok: true });
});
