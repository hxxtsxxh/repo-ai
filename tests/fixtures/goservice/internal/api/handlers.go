package api

import (
	"encoding/json"
	"net/http"

	"example.com/inventory/internal/store"
)

type Handlers struct {
	store store.Store
}

// GetItem returns the stock level for one SKU.
func (h *Handlers) GetItem(w http.ResponseWriter, r *http.Request) {
	item, err := h.store.Get(r.Context(), r.URL.Query().Get("sku"))
	if err != nil {
		http.Error(w, err.Error(), http.StatusNotFound)
		return
	}
	json.NewEncoder(w).Encode(item)
}

// ReserveItem decrements stock, failing when the quantity is unavailable.
func (h *Handlers) ReserveItem(w http.ResponseWriter, r *http.Request) {
	if err := h.store.Reserve(r.Context(), "sku", 1); err != nil {
		http.Error(w, err.Error(), http.StatusConflict)
	}
}
