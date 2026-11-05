package com.example.ledger.model;

public record Account(String id, long balanceCents) {
    public long balance() { return balanceCents; }
}
