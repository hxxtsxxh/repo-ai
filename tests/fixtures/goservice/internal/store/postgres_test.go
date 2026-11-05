package store

import (
	"context"
	"testing"
)

func TestReserveRejectsZero(t *testing.T) {
	p := NewPostgres("")
	if err := p.Reserve(context.Background(), "a", 0); err == nil {
		t.Fatal("expected error")
	}
}
