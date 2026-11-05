package com.example.ledger;

/** Classic chart-of-accounts categories. */
public enum AccountType {
    ASSET(true),
    EXPENSE(true),
    LIABILITY(false),
    EQUITY(false),
    INCOME(false);

    private final boolean debitNormal;

    AccountType(boolean debitNormal) {
        this.debitNormal = debitNormal;
    }

    /** True when a positive (debit) balance is the normal state of the account. */
    public boolean isDebitNormal() {
        return debitNormal;
    }
}
