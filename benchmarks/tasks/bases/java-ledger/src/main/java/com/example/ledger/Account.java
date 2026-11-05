package com.example.ledger;

/** A ledger account. Balances live in {@link Ledger}, not here. */
public final class Account {
    private final String id;
    private final String name;
    private final AccountType type;
    private final String currency;
    private boolean frozen;
    private boolean allowOverdraft;

    public Account(String id, String name, AccountType type, String currency) {
        this.id = Validation.accountId(id);
        this.name = Validation.nonBlank(name, "name");
        if (type == null) {
            throw new IllegalArgumentException("type is required");
        }
        this.type = type;
        this.currency = Validation.currency(currency);
    }

    public String id() {
        return id;
    }

    public String name() {
        return name;
    }

    public AccountType type() {
        return type;
    }

    public String currency() {
        return currency;
    }

    public boolean isFrozen() {
        return frozen;
    }

    public void freeze() {
        frozen = true;
    }

    public void unfreeze() {
        frozen = false;
    }

    public boolean allowsOverdraft() {
        return allowOverdraft;
    }

    public Account withOverdraft(boolean allowed) {
        this.allowOverdraft = allowed;
        return this;
    }

    @Override
    public String toString() {
        return id + " (" + name + ", " + type + ", " + currency + ")";
    }
}
