package com.example.ledger;

/**
 * One leg of a transaction. Positive amounts are debits, negative amounts
 * are credits.
 */
public record Entry(String accountId, Money amount) {
    public Entry {
        accountId = Validation.accountId(accountId);
        if (amount == null) {
            throw new IllegalArgumentException("amount is required");
        }
    }
}
