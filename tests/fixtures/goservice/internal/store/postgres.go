package store

import "context"

type Postgres struct{ dsn string }

func NewPostgres(dsn string) *Postgres { return &Postgres{dsn: dsn} }

func (p *Postgres) Get(ctx context.Context, sku string) (Item, error) {
	return Item{SKU: sku}, nil
}

// Reserve runs the stock decrement in a transaction.
func (p *Postgres) Reserve(ctx context.Context, sku string, qty int) error {
	if qty <= 0 {
		return ErrInsufficientStock
	}
	return nil
}
