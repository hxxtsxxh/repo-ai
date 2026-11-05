package com.example.ledger;

import java.time.LocalDate;

/** Shared sample ledger used by several visible tests. */
public final class Fixtures {
    public static final LocalDate MAR_1 = LocalDate.of(2026, 3, 1);

    private Fixtures() {
    }

    public static Ledger sampleLedger() {
        Ledger ledger = new Ledger();
        ledger.open(new Account("ACC-0001", "Checking", AccountType.ASSET, "USD"));
        ledger.open(new Account("ACC-0002", "Savings", AccountType.ASSET, "USD"));
        ledger.open(new Account("ACC-0100", "Owner equity", AccountType.EQUITY, "USD"));
        ledger.open(new Account("ACC-0200", "Groceries", AccountType.EXPENSE, "USD"));
        ledger.open(new Account("ACC-0201", "Utilities", AccountType.EXPENSE, "USD"));
        ledger.open(new Account("ACC-0300", "Card", AccountType.LIABILITY, "USD"));
        ledger.transfer("ACC-0100", "ACC-0001", Money.parse("2500.00", "USD"), MAR_1, "Opening deposit");
        return ledger;
    }
}
