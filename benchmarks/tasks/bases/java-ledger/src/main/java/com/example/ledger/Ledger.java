package com.example.ledger;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.Collection;
import java.util.Collections;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** The book of accounts: opens accounts, posts transactions and answers balance queries. */
public final class Ledger {
    /** One row of an account statement. */
    public record StatementLine(LocalDate date, String transactionId, String description, Money amount, Money balance) {
    }

    private final Map<String, Account> accounts = new LinkedHashMap<>();
    private final Map<String, Money> balances = new HashMap<>();
    private final List<Transaction> journal = new ArrayList<>();
    private int sequence;

    public Account open(Account account) {
        if (accounts.containsKey(account.id())) {
            throw new LedgerException("account " + account.id() + " already exists");
        }
        accounts.put(account.id(), account);
        balances.put(account.id(), Money.zero(account.currency()));
        return account;
    }

    public Account account(String id) {
        Account account = accounts.get(Validation.accountId(id));
        if (account == null) {
            throw new LedgerException("unknown account " + id);
        }
        return account;
    }

    public Collection<Account> accounts() {
        return Collections.unmodifiableCollection(accounts.values());
    }

    public List<Transaction> journal() {
        return Collections.unmodifiableList(journal);
    }

    public String nextTransactionId() {
        sequence++;
        return String.format("TX-%05d", sequence);
    }

    /** Posts a transaction atomically: either every entry is applied or none is. */
    public Transaction post(Transaction tx) {
        if (!tx.isBalanced()) {
            throw new LedgerException("transaction " + tx.id() + " is unbalanced: entries sum to " + tx.total());
        }
        Map<String, Money> pending = new LinkedHashMap<>();
        for (Entry entry : tx.entries()) {
            Account account = account(entry.accountId());
            if (account.isFrozen()) {
                throw new AccountFrozenException(account.id());
            }
            if (!account.currency().equals(entry.amount().currency())) {
                throw new CurrencyMismatchException(account.currency(), entry.amount().currency());
            }
            Money current = pending.getOrDefault(account.id(), balances.get(account.id()));
            Money next = current.plus(entry.amount());
            if (account.type() == AccountType.ASSET && next.isNegative() && !account.allowsOverdraft()) {
                throw new InsufficientFundsException(account.id(), current, entry.amount().negate());
            }
            pending.put(account.id(), next);
        }
        balances.putAll(pending);
        journal.add(tx);
        return tx;
    }

    /** Moves {@code amount} out of {@code fromId} and into {@code toId}. */
    public Transaction transfer(String fromId, String toId, Money amount, LocalDate date, String memo) {
        if (!amount.isPositive()) {
            throw new IllegalArgumentException("transfer amount must be positive");
        }
        List<Entry> entries = List.of(new Entry(fromId, amount.negate()), new Entry(toId, amount));
        return post(new Transaction(nextTransactionId(), date, memo, entries));
    }

    public Money balance(String accountId) {
        return balances.get(account(accountId).id());
    }

    /** Balance including every transaction dated on or before {@code asOf}. */
    public Money balanceAsOf(String accountId, LocalDate asOf) {
        Account account = account(accountId);
        Money total = Money.zero(account.currency());
        for (Transaction tx : journal) {
            if (!tx.date().isAfter(asOf)) {
                total = total.plus(sumFor(tx, account.id()));
            }
        }
        return total;
    }

    private static Money sumFor(Transaction tx, String accountId) {
        Money sum = null;
        for (Entry entry : tx.entries()) {
            if (entry.accountId().equals(accountId)) {
                sum = sum == null ? entry.amount() : sum.plus(entry.amount());
            }
        }
        return sum == null ? Money.zero(tx.entries().get(0).amount().currency()) : sum;
    }

    /** Statement lines for transactions dated within [from, to], with running balance. */
    public List<StatementLine> statement(String accountId, LocalDate from, LocalDate to) {
        Account account = account(accountId);
        Money running = balanceAsOf(account.id(), from.minusDays(1));
        List<StatementLine> lines = new ArrayList<>();
        for (Transaction tx : journal) {
            if (tx.date().isBefore(from) || tx.date().isAfter(to)) {
                continue;
            }
            boolean touches = tx.entries().stream().anyMatch(e -> e.accountId().equals(account.id()));
            if (!touches) {
                continue;
            }
            Money amount = sumFor(tx, account.id());
            running = running.plus(amount);
            lines.add(new StatementLine(tx.date(), tx.id(), tx.description(), amount, running));
        }
        return lines;
    }
}
