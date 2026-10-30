package com.example.ledger;

import static com.example.ledger.testing.Check.equal;
import static com.example.ledger.testing.Check.raises;
import static com.example.ledger.testing.Check.test;

import java.time.LocalDate;
import java.util.List;

public final class LedgerTest {
    public static void run() {
        test("transfer moves money", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            ledger.transfer("ACC-0001", "ACC-0002", Money.parse("500", "USD"), LocalDate.of(2026, 3, 5), "Save");
            equal(Money.parse("2000", "USD"), ledger.balance("ACC-0001"));
            equal(Money.parse("500", "USD"), ledger.balance("acc-0002"));
        });
        test("overdraft rejected", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            raises(InsufficientFundsException.class, () ->
                    ledger.transfer("ACC-0002", "ACC-0001", Money.parse("1", "USD"), Fixtures.MAR_1, "x"));
        });
        test("frozen source rejected", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            ledger.account("ACC-0001").freeze();
            raises(AccountFrozenException.class, () ->
                    ledger.transfer("ACC-0001", "ACC-0002", Money.parse("1", "USD"), Fixtures.MAR_1, "x"));
            equal(Money.parse("2500", "USD"), ledger.balance("ACC-0001"));
        });
        test("unbalanced transaction rejected", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            Transaction tx = new Transaction("TX-X", Fixtures.MAR_1, "bad",
                    List.of(new Entry("ACC-0001", Money.of(-100, "USD")), new Entry("ACC-0200", Money.of(90, "USD"))));
            raises(LedgerException.class, () -> ledger.post(tx));
        });
        test("balance as of earlier date", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            ledger.transfer("ACC-0001", "ACC-0200", Money.parse("40", "USD"), LocalDate.of(2026, 3, 10), "Food");
            equal(Money.parse("2500", "USD"), ledger.balanceAsOf("ACC-0001", LocalDate.of(2026, 3, 9)));
            equal(Money.parse("2460", "USD"), ledger.balanceAsOf("ACC-0001", LocalDate.of(2026, 3, 20)));
        });
        test("even split", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            new ExpenseSplitter(ledger).splitEvenly("ACC-0001", List.of("ACC-0200", "ACC-0201"),
                    Money.parse("90", "USD"), Fixtures.MAR_1, "Shared");
            equal(Money.parse("45", "USD"), ledger.balance("ACC-0201"));
        });
        test("account ids are validated", () ->
                raises(IllegalArgumentException.class, () -> new Account("12", "x", AccountType.ASSET, "USD")));
    }

    public static void main(String[] args) {
        run();
        com.example.ledger.testing.Check.done();
    }
}
