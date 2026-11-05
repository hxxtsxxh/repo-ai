package com.example.ledger;

/** Raised when a posting touches an account that has been frozen. */
public class AccountFrozenException extends LedgerException {
    private final String accountId;

    public AccountFrozenException(String accountId) {
        super("account " + accountId + " is frozen");
        this.accountId = accountId;
    }

    public String accountId() {
        return accountId;
    }
}
