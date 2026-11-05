import express from 'express';
import { checkoutRouter } from './routes/checkout';

const app = express();
app.use('/checkout', checkoutRouter);
app.listen(3000);
