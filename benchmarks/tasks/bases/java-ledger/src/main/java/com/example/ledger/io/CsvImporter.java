package com.example.ledger.io;

import com.example.ledger.Entry;
import com.example.ledger.Ledger;
import com.example.ledger.LedgerException;
import com.example.ledger.Money;
import com.example.ledger.Transaction;
import com.example.ledger.Validation;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Imports transfers from CSV with the header
 * {@code date,description,from,to,amount,currency}. Blank lines and lines
 * starting with '#' are ignored. Every row is parsed before anything is
 * posted, so a malformed file leaves the ledger untouched.
 */
public final class CsvImporter {
    public static final List<String> HEADER = List.of("date", "description", "from", "to", "amount", "currency");

    private final Ledger ledger;

    public CsvImporter(Ledger ledger) {
        this.ledger = ledger;
    }

    private record Row(int line, LocalDate date, String description, String from, String to, Money amount) {
    }

    public List<Transaction> importText(String text) {
        return importLines(List.of(text.split("\\R", -1)));
    }

    public List<Transaction> importLines(List<String> lines) {
        List<Row> rows = new ArrayList<>();
        boolean headerSeen = false;
        for (int i = 0; i < lines.size(); i++) {
            int lineNo = i + 1;
            String line = lines.get(i);
            if (line.isBlank() || line.stripLeading().startsWith("#")) {
                continue;
            }
            List<String> fields = splitOrFail(line, lineNo);
            if (!headerSeen) {
                List<String> header = fields.stream().map(f -> f.trim().toLowerCase(Locale.ROOT)).toList();
                if (!header.equals(HEADER)) {
                    throw new CsvImportException(lineNo, "expected header " + String.join(",", HEADER));
                }
                headerSeen = true;
                continue;
            }
            rows.add(parseRow(fields, lineNo));
        }
        if (!headerSeen) {
            throw new CsvImportException(1, "file is empty");
        }

        List<Transaction> posted = new ArrayList<>();
        for (Row row : rows) {
            List<Entry> entries = List.of(new Entry(row.from(), row.amount().negate()), new Entry(row.to(), row.amount()));
            Transaction tx = new Transaction(ledger.nextTransactionId(), row.date(), row.description(), entries);
            try {
                posted.add(ledger.post(tx));
            } catch (LedgerException e) {
                throw new CsvImportException(row.line(), e.getMessage(), e);
            }
        }
        return posted;
    }

    private static List<String> splitOrFail(String line, int lineNo) {
        try {
            return CsvParser.splitLine(line);
        } catch (IllegalArgumentException e) {
            throw new CsvImportException(lineNo, e.getMessage(), e);
        }
    }

    private Row parseRow(List<String> fields, int lineNo) {
        if (fields.size() != HEADER.size()) {
            throw new CsvImportException(lineNo, "expected " + HEADER.size() + " fields but found " + fields.size());
        }
        try {
            LocalDate date = LocalDate.parse(fields.get(0).trim());
            String description = fields.get(1).trim();
            String from = Validation.accountId(fields.get(2));
            String to = Validation.accountId(fields.get(3));
            Money amount = Money.parse(fields.get(4), fields.get(5));
            if (!amount.isPositive()) {
                throw new CsvImportException(lineNo, "amount must be positive");
            }
            ledger.account(from);
            ledger.account(to);
            return new Row(lineNo, date, description, from, to, amount);
        } catch (DateTimeParseException e) {
            throw new CsvImportException(lineNo, "invalid date '" + fields.get(0) + "'", e);
        } catch (IllegalArgumentException | LedgerException e) {
            if (e instanceof CsvImportException cie) {
                throw cie;
            }
            throw new CsvImportException(lineNo, e.getMessage(), e);
        }
    }
}
