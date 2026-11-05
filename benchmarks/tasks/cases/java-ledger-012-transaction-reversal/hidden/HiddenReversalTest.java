package com.example.ledger;

import static com.example.ledger.testing.Check.equal;
import static com.example.ledger.testing.Check.isTrue;
import static com.example.ledger.testing.Check.raises;
import static com.example.ledger.testing.Check.test;

import com.example.ledger.testing.Check;
import java.time.LocalDate;
import java.util.List;

public final class HiddenReversalTest {
    private static final LocalDate MAR_10 = LocalDate.of(2026, 3, 10);
    private static final LocalDate MAR_31 = LocalDate.of(2026, 3, 31);
    private static final LocalDate APR_2 = LocalDate.of(2026, 4, 2);

    private static Money usd(String amount) {
        return Money.parse(amount, "USD");
    }

    public static void main(String[] args) {
        test("reversing a transfer restores both balances", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            Transaction food = ledger.transfer("ACC-0001", "ACC-0200", usd("100"), MAR_10, "Food");
            Transaction reversal = ledger.reverse(food.id(), APR_2);
            equal(usd("2500"), ledger.balance("ACC-0001"));
            equal(usd("0"), ledger.balance("ACC-0200"));
            equal(food.id(), reversal.reversalOf());
            isTrue(reversal.isReversal(), "reversal flag");
            isTrue(reversal.description().startsWith("Reversal of " + food.id()), reversal.description());
            isTrue(ledger.isReversed(food.id()), "original marked as reversed");
            equal(3, ledger.journal().size());
        });

        test("reversal is booked on the reversal date", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            Transaction food = ledger.transfer("ACC-0001", "ACC-0200", usd("100"), MAR_10, "Food");
            Transaction reversal = ledger.reverse(food.id(), APR_2);
            equal(APR_2, reversal.date());
            equal(usd("2400"), ledger.balanceAsOf("ACC-0001", MAR_31));
            equal(usd("2500"), ledger.balanceAsOf("ACC-0001", APR_2));
            List<Ledger.StatementLine> march = ledger.statement("ACC-0001", Fixtures.MAR_1, MAR_31);
            equal(2, march.size());
            equal(usd("2400"), march.get(1).balance());
            List<Ledger.StatementLine> april = ledger.statement("ACC-0001", LocalDate.of(2026, 4, 1), LocalDate.of(2026, 4, 30));
            equal(1, april.size());
            equal(usd("100"), april.get(0).amount());
        });

        test("a transaction can be reversed only once", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            Transaction food = ledger.transfer("ACC-0001", "ACC-0200", usd("100"), MAR_10, "Food");
            Transaction reversal = ledger.reverse(food.id(), APR_2);
            raises(LedgerException.class, () -> ledger.reverse(food.id(), APR_2));
            raises(LedgerException.class, () -> ledger.reverse(reversal.id(), APR_2));
            equal(3, ledger.journal().size());
            equal(usd("2500"), ledger.balance("ACC-0001"));
            equal(usd("0"), ledger.balance("ACC-0200"));
        });

        test("multi-leg transactions reverse every leg", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            Transaction split = new ExpenseSplitter(ledger).splitEvenly("ACC-0001", List.of("ACC-0200", "ACC-0201"),
                    usd("90.01"), MAR_10, "Shared");
            ledger.reverse(split.id(), APR_2);
            equal(usd("2500"), ledger.balance("ACC-0001"));
            equal(usd("0"), ledger.balance("ACC-0200"));
            equal(usd("0"), ledger.balance("ACC-0201"));
        });

        test("negated legs flip the sign", () -> {
            equal(Money.of(500, "USD"), new Entry("ACC-0001", Money.of(-500, "USD")).negated().amount());
            equal(Money.of(-500, "USD"), new Entry("ACC-0001", Money.of(500, "USD")).negated().amount());
            equal("ACC-0001", new Entry("acc-0001", Money.of(1, "USD")).negated().accountId());
        });

        test("unknown transaction", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            raises(LedgerException.class, () -> ledger.reverse("TX-99999", APR_2));
            equal(1, ledger.journal().size());
        });

        Check.done();
    }
}
