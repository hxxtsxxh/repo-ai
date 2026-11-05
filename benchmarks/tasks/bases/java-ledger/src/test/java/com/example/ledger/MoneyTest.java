package com.example.ledger;

import static com.example.ledger.testing.Check.equal;
import static com.example.ledger.testing.Check.raises;
import static com.example.ledger.testing.Check.test;

import java.math.BigDecimal;
import java.math.RoundingMode;

public final class MoneyTest {
    public static void run() {
        test("parse and format", () -> {
            equal(123450L, Money.parse("1,234.50", "usd").minor());
            equal("1234.50 USD", Money.parse("1234.5", "USD").toString());
        });
        test("too many decimals rejected", () -> raises(IllegalArgumentException.class, () -> Money.parse("1.234", "USD")));
        test("arithmetic", () -> {
            Money a = Money.of(1000, "USD");
            equal(Money.of(1250, "USD"), a.plus(Money.of(250, "USD")));
            equal(Money.of(750, "USD"), a.minus(Money.of(250, "USD")));
            equal(Money.of(-1000, "USD"), a.negate());
        });
        test("minus rejects other currency", () ->
                raises(CurrencyMismatchException.class, () -> Money.of(1, "USD").minus(Money.of(1, "EUR"))));
        test("times", () -> equal(Money.of(150, "USD"), Money.of(1000, "USD").times(new BigDecimal("0.15"), RoundingMode.HALF_EVEN)));
        test("allocate evenly divisible", () -> {
            Money[] parts = Money.of(900, "USD").allocate(1, 1, 1);
            equal(Money.of(300, "USD"), parts[0]);
            equal(Money.of(300, "USD"), parts[2]);
        });
        test("allocate weighted", () -> {
            Money[] parts = Money.of(1000, "USD").allocate(3, 1);
            equal(Money.of(750, "USD"), parts[0]);
            equal(Money.of(250, "USD"), parts[1]);
        });
    }

    public static void main(String[] args) {
        run();
        com.example.ledger.testing.Check.done();
    }
}
