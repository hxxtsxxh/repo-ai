package main

import (
	"log"
	"net/http"

	"example.com/inventory/internal/api"
	"example.com/inventory/internal/store"
)

func main() {
	s := store.NewPostgres("postgres://localhost/inventory")
	log.Fatal(http.ListenAndServe(":8080", api.NewRouter(s)))
}
