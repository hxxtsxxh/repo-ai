package com.example.ledger;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;

/**
 * Interest on savings balances. Amounts are rounded to the cent with
 * banker's rounding (half-even), matching the core banking system.
 */
public final class InterestCalculator {
    public static final int DAYS_IN_YEAR = 365;
    private static final BigDecimal MONTHS_PERCENT = BigDecimal.valueOf(1200);

    /** Simple accrual: balance x annualRatePercent / 100 x days / 365. */
    public Money accrue(Money balance, BigDecimal annualRatePercent, int days) {
        if (days < 0) {
            throw new IllegalArgumentException("days must not be negative");
        }
        if (!balance.isPositive()) {
            return Money.zero(balance.currency());
        }
        BigDecimal interest = balance.toDecimal()
                .multiply(annualRatePercent)
                .multiply(BigDecimal.valueOf(days))
                .divide(BigDecimal.valueOf(100L * DAYS_IN_YEAR), 2, RoundingMode.HALF_EVEN);
        return Money.of(interest.movePointRight(2).longValueExact(), balance.currency());
    }

    public Money accrueBetween(Money balance, BigDecimal annualRatePercent, LocalDate from, LocalDate to) {
        long days = ChronoUnit.DAYS.between(from, to);
        return accrue(balance, annualRatePercent, Math.toIntExact(days));
    }

    /** Compounds monthly, rounding each month's interest to the cent. Returns the final balance. */
    public Money compoundMonthly(Money principal, BigDecimal annualRatePercent, int months) {
        Money balance = principal;
        BigDecimal monthlyRate = annualRatePercent.divide(MONTHS_PERCENT, 12, RoundingMode.HALF_EVEN);
        for (int month = 0; month < months; month++) {
            balance = balance.plus(balance.times(monthlyRate, RoundingMode.HALF_EVEN));
        }
        return balance;
    }
}
