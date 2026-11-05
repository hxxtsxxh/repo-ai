package store

import (
	"context"
	"errors"
)

var ErrInsufficientStock = errors.New("insufficient stock")

type Item struct {
	SKU      string
	Quantity int
}

type Store interface {
	Get(ctx context.Context, sku string) (Item, error)
	Reserve(ctx context.Context, sku string, qty int) error
}
