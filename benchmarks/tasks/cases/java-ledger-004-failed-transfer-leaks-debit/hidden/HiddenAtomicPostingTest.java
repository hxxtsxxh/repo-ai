package com.example.ledger;

import static com.example.ledger.testing.Check.equal;
import static com.example.ledger.testing.Check.isTrue;
import static com.example.ledger.testing.Check.raises;
import static com.example.ledger.testing.Check.test;

import com.example.ledger.testing.Check;

import com.example.ledger.io.CsvImportException;
import com.example.ledger.io.CsvImporter;
import java.time.LocalDate;
import java.util.List;

public final class HiddenAtomicPostingTest {
    public static void main(String[] args) {
        test("frozen destination leaves source untouched", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            ledger.account("ACC-0002").freeze();
            raises(AccountFrozenException.class, () ->
                    ledger.transfer("ACC-0001", "ACC-0002", Money.parse("100", "USD"), Fixtures.MAR_1, "x"));
            equal(Money.parse("2500", "USD"), ledger.balance("ACC-0001"));
            equal(Money.zero("USD"), ledger.balance("ACC-0002"));
            equal(1, ledger.journal().size());
            ledger.account("ACC-0002").unfreeze();
            ledger.transfer("ACC-0001", "ACC-0002", Money.parse("100", "USD"), Fixtures.MAR_1, "x");
            equal(Money.parse("2400", "USD"), ledger.balance("ACC-0001"));
        });
        test("currency mismatch on later entry", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            ledger.open(new Account("ACC-0900", "Euro wallet", AccountType.ASSET, "EUR"));
            Transaction tx = new Transaction("TX-M", Fixtures.MAR_1, "mixed", List.of(
                    new Entry("ACC-0001", Money.of(-500, "USD")),
                    new Entry("ACC-0200", Money.of(250, "USD")),
                    new Entry("ACC-0900", Money.of(250, "USD"))));
            raises(CurrencyMismatchException.class, () -> ledger.post(tx));
            equal(Money.parse("2500", "USD"), ledger.balance("ACC-0001"));
            equal(Money.zero("USD"), ledger.balance("ACC-0200"));
        });
        test("overdraft on later entry", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            Transaction tx = new Transaction("TX-O", Fixtures.MAR_1, "x", List.of(
                    new Entry("ACC-0200", Money.of(100, "USD")),
                    new Entry("ACC-0002", Money.of(-100, "USD"))));
            raises(InsufficientFundsException.class, () -> ledger.post(tx));
            equal(Money.zero("USD"), ledger.balance("ACC-0200"));
        });
        test("csv row rejected at posting time", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            ledger.account("ACC-0201").freeze();
            CsvImportException e = raises(CsvImportException.class, () -> new CsvImporter(ledger).importText(String.join("\n",
                    "date,description,from,to,amount,currency",
                    "2026-03-03,ok,ACC-0001,ACC-0200,10.00,USD",
                    "2026-03-04,frozen,ACC-0001,ACC-0201,20.00,USD")));
            equal(3, e.line());
            equal(Money.parse("2490", "USD"), ledger.balance("ACC-0001"));
        });
        test("regression: same account twice in one transaction", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            ledger.post(new Transaction("TX-S", LocalDate.of(2026, 3, 2), "shuffle", List.of(
                    new Entry("ACC-0001", Money.of(-250_000, "USD")),
                    new Entry("ACC-0001", Money.of(200_000, "USD")),
                    new Entry("ACC-0002", Money.of(50_000, "USD")))));
            equal(Money.parse("2000", "USD"), ledger.balance("ACC-0001"));
            equal(Money.parse("500", "USD"), ledger.balance("ACC-0002"));
        });
        Check.done();
    }
}
