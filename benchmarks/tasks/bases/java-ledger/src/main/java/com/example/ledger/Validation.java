package com.example.ledger;

import java.util.Locale;
import java.util.regex.Pattern;

/**
 * Shared input rules. Account ids are case-insensitive and canonicalised to
 * upper case ("acc-0012" becomes "ACC-0012"); currencies are ISO-4217 style
 * three-letter codes.
 */
public final class Validation {
    private static final Pattern ACCOUNT_ID = Pattern.compile("ACC-\\d{4}");
    private static final Pattern CURRENCY = Pattern.compile("[A-Z]{3}");

    private Validation() {
    }

    public static String accountId(String raw) {
        if (raw == null) {
            throw new IllegalArgumentException("account id is required");
        }
        String id = raw.trim().toUpperCase(Locale.ROOT);
        if (!ACCOUNT_ID.matcher(id).matches()) {
            throw new IllegalArgumentException("invalid account id: '" + raw + "'");
        }
        return id;
    }

    public static String currency(String raw) {
        if (raw == null) {
            throw new IllegalArgumentException("currency is required");
        }
        String code = raw.trim().toUpperCase(Locale.ROOT);
        if (!CURRENCY.matcher(code).matches()) {
            throw new IllegalArgumentException("invalid currency: '" + raw + "'");
        }
        return code;
    }

    public static String nonBlank(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(field + " must not be blank");
        }
        return value.trim();
    }
}
