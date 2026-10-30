package com.example.ledger;

import static com.example.ledger.testing.Check.equal;
import static com.example.ledger.testing.Check.isTrue;
import static com.example.ledger.testing.Check.raises;
import static com.example.ledger.testing.Check.test;

import com.example.ledger.testing.Check;

import java.math.BigDecimal;
import java.time.LocalDate;

public final class HiddenHalfCentInterestTest {
    public static void main(String[] args) {
        InterestCalculator calc = new InterestCalculator();
        BigDecimal rate = new BigDecimal("3.65");
        test("half cents round to even", () -> {
            equal(Money.of(0, "USD"), calc.accrue(Money.of(1_000, "USD"), rate, 5));
            equal(Money.of(2, "USD"), calc.accrue(Money.of(3_000, "USD"), rate, 5));
            equal(Money.of(2, "USD"), calc.accrue(Money.of(5_000, "USD"), rate, 5));
            equal(Money.of(4, "USD"), calc.accrue(Money.of(7_000, "USD"), rate, 5));
        });
        test("between dates uses the same rounding", () -> equal(Money.of(0, "EUR"),
                calc.accrueBetween(Money.of(1_000, "EUR"), rate, LocalDate.of(2026, 1, 1), LocalDate.of(2026, 1, 6))));
        test("regression: exact and above-half amounts", () -> {
            equal(Money.of(300, "USD"), calc.accrue(Money.of(100_000, "USD"), rate, 30));
            equal(Money.of(1, "USD"), calc.accrue(Money.of(1_200, "USD"), rate, 5));
            equal(Money.of(101_002, "USD"), calc.compoundMonthly(Money.of(100_000, "USD"), new BigDecimal("6"), 2));
        });
        Check.done();
    }
}
