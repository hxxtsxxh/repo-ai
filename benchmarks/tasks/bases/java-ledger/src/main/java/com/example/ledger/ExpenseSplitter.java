package com.example.ledger;

import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** Splits one payment across several expense accounts in a single transaction. */
public final class ExpenseSplitter {
    private final Ledger ledger;

    public ExpenseSplitter(Ledger ledger) {
        this.ledger = ledger;
    }

    public Transaction splitEvenly(String payerId, List<String> expenseIds, Money total, LocalDate date, String memo) {
        int[] ratios = new int[expenseIds.size()];
        java.util.Arrays.fill(ratios, 1);
        return split(payerId, expenseIds, ratios, total, date, memo);
    }

    public Transaction splitWeighted(String payerId, Map<String, Integer> weights, Money total, LocalDate date, String memo) {
        List<String> ids = new ArrayList<>(weights.keySet());
        int[] ratios = new int[ids.size()];
        for (int i = 0; i < ids.size(); i++) {
            ratios[i] = weights.get(ids.get(i));
        }
        return split(payerId, ids, ratios, total, date, memo);
    }

    private Transaction split(String payerId, List<String> expenseIds, int[] ratios, Money total, LocalDate date, String memo) {
        if (expenseIds.isEmpty()) {
            throw new IllegalArgumentException("at least one expense account is required");
        }
        Money[] shares = total.allocate(ratios);
        List<Entry> entries = new ArrayList<>();
        entries.add(new Entry(payerId, total.negate()));
        for (int i = 0; i < expenseIds.size(); i++) {
            if (!shares[i].isZero()) {
                entries.add(new Entry(expenseIds.get(i), shares[i]));
            }
        }
        return ledger.post(new Transaction(ledger.nextTransactionId(), date, memo, entries));
    }
}
