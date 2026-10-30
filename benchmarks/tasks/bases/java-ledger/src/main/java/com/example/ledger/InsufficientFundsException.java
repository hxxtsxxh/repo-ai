package com.example.ledger;

/** Raised when an asset account without overdraft would go negative. */
public class InsufficientFundsException extends LedgerException {
    public InsufficientFundsException(String accountId, Money balance, Money requested) {
        super("insufficient funds in " + accountId + ": balance " + balance + ", requested " + requested);
    }
}
