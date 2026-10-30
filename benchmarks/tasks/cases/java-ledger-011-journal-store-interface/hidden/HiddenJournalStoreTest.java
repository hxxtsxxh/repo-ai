package com.example.ledger;

import static com.example.ledger.testing.Check.equal;
import static com.example.ledger.testing.Check.isTrue;
import static com.example.ledger.testing.Check.raises;
import static com.example.ledger.testing.Check.test;

import com.example.ledger.testing.Check;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;

public final class HiddenJournalStoreTest {
    static final class RecordingStore implements JournalStore {
        final List<Transaction> items = new ArrayList<>();
        int appends;
        boolean failing;

        @Override
        public void append(Transaction tx) {
            appends++;
            if (failing) {
                throw new IllegalStateException("disk full");
            }
            items.add(tx);
        }

        @Override
        public List<Transaction> all() {
            return items;
        }
    }

    private static final LocalDate MAR_1 = LocalDate.of(2026, 3, 1);

    private static Ledger ledger(JournalStore store) {
        Ledger ledger = new Ledger(store);
        ledger.open(new Account("ACC-0001", "Checking", AccountType.ASSET, "USD"));
        ledger.open(new Account("ACC-0002", "Savings", AccountType.ASSET, "USD"));
        ledger.open(new Account("ACC-0100", "Owner equity", AccountType.EQUITY, "USD"));
        return ledger;
    }

    public static void main(String[] args) {
        test("postings go through the injected store", () -> {
            RecordingStore store = new RecordingStore();
            Ledger ledger = ledger(store);
            Transaction tx = ledger.transfer("ACC-0100", "ACC-0001", Money.parse("100", "USD"), MAR_1, "Deposit");
            equal(1, store.appends);
            isTrue(store.items.get(0) == tx, "the posted transaction is stored");
            equal(store.items, ledger.journal());
            equal(Money.parse("100", "USD"), ledger.balance("ACC-0001"));
        });

        test("history is read from the store", () -> {
            RecordingStore store = new RecordingStore();
            Ledger ledger = ledger(store);
            ledger.transfer("ACC-0100", "ACC-0001", Money.parse("100", "USD"), MAR_1, "Deposit");
            store.items.add(new Transaction("TX-LOADED", LocalDate.of(2026, 3, 2), "Loaded from disk",
                    List.of(new Entry("ACC-0100", Money.of(-2_500, "USD")), new Entry("ACC-0001", Money.of(2_500, "USD")))));
            equal(2, ledger.journal().size());
            equal(Money.parse("125", "USD"), ledger.balanceAsOf("ACC-0001", LocalDate.of(2026, 3, 31)));
            equal(2, ledger.statement("ACC-0001", MAR_1, LocalDate.of(2026, 3, 31)).size());
        });

        test("a failing store leaves balances untouched", () -> {
            RecordingStore store = new RecordingStore();
            Ledger ledger = ledger(store);
            ledger.transfer("ACC-0100", "ACC-0001", Money.parse("100", "USD"), MAR_1, "Deposit");
            store.failing = true;
            IllegalStateException e = raises(IllegalStateException.class, () ->
                    ledger.transfer("ACC-0001", "ACC-0002", Money.parse("40", "USD"), MAR_1, "Save"));
            equal("disk full", e.getMessage());
            equal(Money.parse("100", "USD"), ledger.balance("ACC-0001"));
            equal(Money.zero("USD"), ledger.balance("ACC-0002"));
            equal(1, ledger.journal().size());
            store.failing = false;
            ledger.transfer("ACC-0001", "ACC-0002", Money.parse("40", "USD"), MAR_1, "Save");
            equal(Money.parse("60", "USD"), ledger.balance("ACC-0001"));
        });

        test("rejected postings never reach the store", () -> {
            RecordingStore store = new RecordingStore();
            Ledger ledger = ledger(store);
            raises(InsufficientFundsException.class, () ->
                    ledger.transfer("ACC-0002", "ACC-0001", Money.parse("1", "USD"), MAR_1, "x"));
            ledger.account("ACC-0001").freeze();
            raises(AccountFrozenException.class, () ->
                    ledger.transfer("ACC-0100", "ACC-0001", Money.parse("1", "USD"), MAR_1, "x"));
            raises(LedgerException.class, () -> ledger.post(new Transaction("TX-BAD", MAR_1, "bad",
                    List.of(new Entry("ACC-0100", Money.of(-100, "USD")), new Entry("ACC-0002", Money.of(90, "USD"))))));
            equal(0, store.appends);
        });

        test("default ledger and in-memory store", () -> {
            InMemoryJournalStore memory = new InMemoryJournalStore();
            JournalStore asInterface = memory;
            Ledger ledger = ledger(asInterface);
            ledger.transfer("ACC-0100", "ACC-0001", Money.parse("5", "USD"), MAR_1, "a");
            ledger.transfer("ACC-0100", "ACC-0001", Money.parse("6", "USD"), MAR_1, "b");
            equal(List.of("a", "b"), memory.all().stream().map(Transaction::description).toList());
            Ledger plain = Fixtures.sampleLedger();
            equal(1, plain.journal().size());
            raises(UnsupportedOperationException.class, () -> plain.journal().add(plain.journal().get(0)));
        });

        Check.done();
    }
}
