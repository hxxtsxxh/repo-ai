package com.example.ledger;

import static com.example.ledger.testing.Check.equal;
import static com.example.ledger.testing.Check.isTrue;
import static com.example.ledger.testing.Check.raises;
import static com.example.ledger.testing.Check.test;

import com.example.ledger.testing.Check;

import java.util.List;

public final class HiddenMixedCurrencyTest {
    public static void main(String[] args) {
        test("plus rejects other currency", () -> {
            CurrencyMismatchException e = raises(CurrencyMismatchException.class,
                    () -> Money.of(500, "EUR").plus(Money.of(500, "USD")));
            equal("EUR", e.expected());
            equal("USD", e.actual());
        });
        test("mixed-currency transaction is not posted", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            ledger.open(new Account("ACC-0900", "Euro wallet", AccountType.ASSET, "EUR"));
            ledger.open(new Account("ACC-0901", "Euro equity", AccountType.EQUITY, "EUR"));
            ledger.transfer("ACC-0901", "ACC-0900", Money.parse("50", "EUR"), Fixtures.MAR_1, "seed");
            Transaction tx = new Transaction("TX-FX", Fixtures.MAR_1, "fx", List.of(
                    new Entry("ACC-0900", Money.of(-500, "EUR")),
                    new Entry("ACC-0001", Money.of(500, "USD"))));
            raises(LedgerException.class, () -> ledger.post(tx));
            equal(Money.parse("50", "EUR"), ledger.balance("ACC-0900"));
            equal(Money.parse("2500", "USD"), ledger.balance("ACC-0001"));
            equal(2, ledger.journal().size());
        });
        test("regression: same currency", () -> {
            equal(Money.of(1_000, "EUR"), Money.of(500, "EUR").plus(Money.of(500, "EUR")));
            equal(Money.zero("USD"), new Transaction("TX-1", Fixtures.MAR_1, "", List.of(
                    new Entry("ACC-0001", Money.of(-1, "USD")), new Entry("ACC-0002", Money.of(1, "USD")))).total());
        });
        Check.done();
    }
}
