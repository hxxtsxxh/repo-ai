package com.example.ledger;

import static com.example.ledger.testing.Check.equal;
import static com.example.ledger.testing.Check.test;

import java.math.BigDecimal;
import java.time.LocalDate;

public final class InterestCalculatorTest {
    public static void run() {
        InterestCalculator calc = new InterestCalculator();
        test("thirty days at 3.65%", () ->
                equal(Money.of(300, "USD"), calc.accrue(Money.of(100_000, "USD"), new BigDecimal("3.65"), 30)));
        test("negative balance earns nothing", () ->
                equal(Money.zero("USD"), calc.accrue(Money.of(-5_000, "USD"), new BigDecimal("5"), 30)));
        test("between dates", () -> equal(Money.of(100, "USD"),
                calc.accrueBetween(Money.of(100_000, "USD"), new BigDecimal("3.65"), LocalDate.of(2026, 1, 1), LocalDate.of(2026, 1, 11))));
        test("compound monthly", () ->
                equal(Money.of(101_002, "USD"), calc.compoundMonthly(Money.of(100_000, "USD"), new BigDecimal("6"), 2)));
    }

    public static void main(String[] args) {
        run();
        com.example.ledger.testing.Check.done();
    }
}
