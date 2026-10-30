package com.example.ledger.io;

import com.example.ledger.LedgerException;

/** An import failure tied to a 1-based line number of the source file. */
public class CsvImportException extends LedgerException {
    private final int line;

    public CsvImportException(int line, String message) {
        super("line " + line + ": " + message);
        this.line = line;
    }

    public CsvImportException(int line, String message, Throwable cause) {
        super("line " + line + ": " + message, cause);
        this.line = line;
    }

    public int line() {
        return line;
    }
}
