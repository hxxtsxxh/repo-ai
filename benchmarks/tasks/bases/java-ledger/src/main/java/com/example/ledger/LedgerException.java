package com.example.ledger;

/** Base class for every domain error raised by the ledger. */
public class LedgerException extends RuntimeException {
    public LedgerException(String message) {
        super(message);
    }

    public LedgerException(String message, Throwable cause) {
        super(message, cause);
    }
}
