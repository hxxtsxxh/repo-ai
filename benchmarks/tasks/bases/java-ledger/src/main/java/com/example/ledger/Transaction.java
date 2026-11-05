package com.example.ledger;

import java.time.LocalDate;
import java.util.List;

/** A dated, balanced set of entries. */
public final class Transaction {
    private final String id;
    private final LocalDate date;
    private final String description;
    private final List<Entry> entries;

    public Transaction(String id, LocalDate date, String description, List<Entry> entries) {
        this.id = Validation.nonBlank(id, "id");
        if (date == null) {
            throw new IllegalArgumentException("date is required");
        }
        this.date = date;
        this.description = description == null ? "" : description.trim();
        if (entries == null || entries.size() < 2) {
            throw new IllegalArgumentException("a transaction needs at least two entries");
        }
        this.entries = List.copyOf(entries);
    }

    public String id() {
        return id;
    }

    public LocalDate date() {
        return date;
    }

    public String description() {
        return description;
    }

    public List<Entry> entries() {
        return entries;
    }

    /** Sum of all entries; zero for a balanced transaction. */
    public Money total() {
        Money sum = Money.zero(entries.get(0).amount().currency());
        for (Entry entry : entries) {
            sum = sum.plus(entry.amount());
        }
        return sum;
    }

    public boolean isBalanced() {
        return total().isZero();
    }

    @Override
    public String toString() {
        return id + " " + date + " " + description + " " + entries;
    }
}
