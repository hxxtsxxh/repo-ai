package com.example.ledger;

/** Raised when two amounts in different currencies are combined. */
public class CurrencyMismatchException extends LedgerException {
    private final String expected;
    private final String actual;

    public CurrencyMismatchException(String expected, String actual) {
        super("currency mismatch: expected " + expected + " but got " + actual);
        this.expected = expected;
        this.actual = actual;
    }

    public String expected() {
        return expected;
    }

    public String actual() {
        return actual;
    }
}
