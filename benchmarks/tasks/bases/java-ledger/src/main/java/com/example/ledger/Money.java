package com.example.ledger;

import java.math.BigDecimal;
import java.math.RoundingMode;

/** An immutable amount of money stored as whole minor units (cents). */
public final class Money implements Comparable<Money> {
    private final long minor;
    private final String currency;

    private Money(long minor, String currency) {
        this.minor = minor;
        this.currency = currency;
    }

    public static Money of(long minor, String currency) {
        return new Money(minor, Validation.currency(currency));
    }

    public static Money zero(String currency) {
        return of(0, currency);
    }

    /** Parses "1234.5" or "-0.25"; more than two decimals is an error. */
    public static Money parse(String amount, String currency) {
        if (amount == null) {
            throw new IllegalArgumentException("amount is required");
        }
        try {
            BigDecimal value = new BigDecimal(amount.trim().replace(",", ""));
            return of(value.movePointRight(2).setScale(0, RoundingMode.UNNECESSARY).longValueExact(), currency);
        } catch (NumberFormatException | ArithmeticException e) {
            throw new IllegalArgumentException("invalid amount: '" + amount + "'", e);
        }
    }

    public long minor() {
        return minor;
    }

    public String currency() {
        return currency;
    }

    public Money plus(Money other) {
        requireSameCurrency(other);
        return new Money(Math.addExact(minor, other.minor), currency);
    }

    public Money minus(Money other) {
        requireSameCurrency(other);
        return new Money(Math.subtractExact(minor, other.minor), currency);
    }

    public Money negate() {
        return new Money(Math.negateExact(minor), currency);
    }

    public Money abs() {
        return minor < 0 ? negate() : this;
    }

    public Money times(BigDecimal factor, RoundingMode rounding) {
        BigDecimal result = BigDecimal.valueOf(minor).multiply(factor).setScale(0, rounding);
        return new Money(result.longValueExact(), currency);
    }

    /**
     * Splits this amount by the given ratios. The shares always add up to
     * exactly this amount; leftover cents go to the first shares.
     */
    public Money[] allocate(int... ratios) {
        if (ratios.length == 0) {
            throw new IllegalArgumentException("at least one ratio is required");
        }
        long total = 0;
        for (int ratio : ratios) {
            if (ratio < 0) {
                throw new IllegalArgumentException("ratios must not be negative");
            }
            total += ratio;
        }
        if (total == 0) {
            throw new IllegalArgumentException("ratios must not all be zero");
        }
        long[] shares = new long[ratios.length];
        long remainder = minor;
        for (int i = 0; i < ratios.length; i++) {
            shares[i] = minor * ratios[i] / total;
            remainder -= shares[i];
        }
        long step = Long.signum(remainder);
        for (int i = 0; remainder != 0; i = (i + 1) % shares.length) {
            if (ratios[i] == 0) {
                continue;
            }
            shares[i] += step;
            remainder -= step;
        }
        Money[] result = new Money[shares.length];
        for (int i = 0; i < shares.length; i++) {
            result[i] = new Money(shares[i], currency);
        }
        return result;
    }

    public boolean isZero() {
        return minor == 0;
    }

    public boolean isNegative() {
        return minor < 0;
    }

    public boolean isPositive() {
        return minor > 0;
    }

    public BigDecimal toDecimal() {
        return BigDecimal.valueOf(minor, 2);
    }

    private void requireSameCurrency(Money other) {
        if (!currency.equals(other.currency)) {
            throw new CurrencyMismatchException(currency, other.currency);
        }
    }

    @Override
    public int compareTo(Money other) {
        requireSameCurrency(other);
        return Long.compare(minor, other.minor);
    }

    @Override
    public boolean equals(Object o) {
        if (!(o instanceof Money)) {
            return false;
        }
        Money m = (Money) o;
        return minor == m.minor && currency.equals(m.currency);
    }

    @Override
    public int hashCode() {
        return Long.hashCode(minor) * 31 + currency.hashCode();
    }

    @Override
    public String toString() {
        return toDecimal().toPlainString() + " " + currency;
    }
}
