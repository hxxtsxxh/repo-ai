package api

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"example.com/inventory/internal/store"
)

// NewRouter wires the HTTP routes.
func NewRouter(s store.Store) http.Handler {
	r := chi.NewRouter()
	h := &Handlers{store: s}
	r.Get("/items/{sku}", h.GetItem)
	r.Post("/items/{sku}/reserve", h.ReserveItem)
	return r
}
