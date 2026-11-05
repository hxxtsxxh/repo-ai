package com.example.ledger;

import static com.example.ledger.testing.Check.equal;
import static com.example.ledger.testing.Check.isTrue;
import static com.example.ledger.testing.Check.raises;
import static com.example.ledger.testing.Check.test;

import com.example.ledger.testing.Check;

import java.util.List;

public final class HiddenAllocateRemainderTest {
    public static void main(String[] args) {
        test("leftover cents go to the first shares", () -> {
            Money[] parts = Money.of(10_000, "USD").allocate(1, 1, 1);
            equal(Money.of(3_334, "USD"), parts[0]);
            equal(Money.of(3_333, "USD"), parts[1]);
            equal(Money.of(3_333, "USD"), parts[2]);
            Money[] five = Money.of(1_002, "USD").allocate(1, 1, 1, 1, 1);
            equal(Money.of(201, "USD"), five[0]);
            equal(Money.of(201, "USD"), five[1]);
            equal(Money.of(200, "USD"), five[4]);
        });
        test("shares always sum to the total", () -> {
            int[][] ratioSets = {{1, 1, 1}, {3, 2, 2}, {7, 0, 3}, {1, 1, 1, 1, 1, 1, 1}, {5}};
            for (long amount : new long[] {1, 2, 99, 10_000, 12_345, -100, -12_345}) {
                for (int[] ratios : ratioSets) {
                    long sum = 0;
                    for (Money m : Money.of(amount, "USD").allocate(ratios)) {
                        sum += m.minor();
                    }
                    equal(amount, sum);
                }
            }
        });
        test("negative amounts and zero ratios", () -> {
            Money[] parts = Money.of(-100, "USD").allocate(1, 1, 1);
            equal(Money.of(-34, "USD"), parts[0]);
            equal(Money.of(-33, "USD"), parts[2]);
            Money[] skip = Money.of(10, "USD").allocate(0, 1, 1);
            equal(Money.zero("USD"), skip[0]);
            equal(Money.of(5, "USD"), skip[1]);
        });
        test("three-way bill posts", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            ledger.open(new Account("ACC-0202", "Internet", AccountType.EXPENSE, "USD"));
            new ExpenseSplitter(ledger).splitEvenly("ACC-0001", List.of("ACC-0200", "ACC-0201", "ACC-0202"),
                    Money.parse("100.00", "USD"), Fixtures.MAR_1, "Utilities");
            equal(Money.parse("2400", "USD"), ledger.balance("ACC-0001"));
            equal(Money.parse("33.34", "USD"), ledger.balance("ACC-0200"));
            equal(Money.parse("33.33", "USD"), ledger.balance("ACC-0202"));
        });
        test("regression: exact splits", () -> {
            Money[] parts = Money.of(900, "USD").allocate(1, 1, 1);
            equal(Money.of(300, "USD"), parts[1]);
            raises(IllegalArgumentException.class, () -> Money.of(1, "USD").allocate(0, 0));
        });
        Check.done();
    }
}
