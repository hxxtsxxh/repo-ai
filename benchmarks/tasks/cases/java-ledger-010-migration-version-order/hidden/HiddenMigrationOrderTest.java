package com.example.ledger;

import static com.example.ledger.testing.Check.equal;
import static com.example.ledger.testing.Check.isTrue;
import static com.example.ledger.testing.Check.raises;
import static com.example.ledger.testing.Check.test;

import com.example.ledger.store.InMemoryDatabase;
import com.example.ledger.store.LedgerSchema;
import com.example.ledger.store.Migration;
import com.example.ledger.store.SchemaMigrator;
import com.example.ledger.testing.Check;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.Set;

public final class HiddenMigrationOrderTest {
    private static List<String> ids(int from, int to) {
        List<String> all = new ArrayList<>();
        for (Migration m : LedgerSchema.migrations()) {
            int v = SchemaMigrator.version(m.id());
            if (v >= from && v <= to) {
                all.add(m.id());
            }
        }
        return all;
    }

    public static void main(String[] args) {
        test("fresh database gets every migration in numeric order", () -> {
            InMemoryDatabase db = new InMemoryDatabase();
            List<String> ran = new SchemaMigrator(LedgerSchema.migrations()).migrate(db);
            equal(ids(1, 12), ran);
            equal(ids(1, 12), db.history());
            equal("V10__add_audit_actor", ran.get(9));
            equal(Set.of("at", "actor"), db.columns("audit_log"));
            isTrue(db.columns("transactions").contains("reversal_of"), "reversal_of column");
            equal(List.of(), new SchemaMigrator(LedgerSchema.migrations()).migrate(db));
        });

        test("database at V9 picks up V10 to V12", () -> {
            InMemoryDatabase db = new InMemoryDatabase();
            new SchemaMigrator(LedgerSchema.migrations().subList(0, 9)).migrate(db);
            equal(9, db.history().size());
            SchemaMigrator full = new SchemaMigrator(LedgerSchema.migrations());
            equal(List.of("V10__add_audit_actor", "V11__add_transaction_reversal_of", "V12__drop_audit_action"),
                    full.pending(db));
            full.migrate(db);
            equal(ids(1, 12), db.history());
        });

        test("listing order does not matter", () -> {
            List<Migration> shuffled = new ArrayList<>(LedgerSchema.migrations());
            Collections.reverse(shuffled);
            Collections.swap(shuffled, 0, 7);
            InMemoryDatabase db = new InMemoryDatabase();
            equal(ids(1, 12), new SchemaMigrator(shuffled).pending(db));
            equal(ids(1, 12), new SchemaMigrator(shuffled).migrate(db));
        });

        test("versions go well past two digits", () -> {
            List<Migration> many = new ArrayList<>();
            List<String> expected = new ArrayList<>();
            for (int v = 120; v >= 1; v--) {
                String id = "V" + v + "__step_" + v;
                many.add(Migration.of(id, db -> { }));
            }
            for (int v = 1; v <= 120; v++) {
                expected.add("V" + v + "__step_" + v);
            }
            InMemoryDatabase db = new InMemoryDatabase();
            equal(expected, new SchemaMigrator(many).migrate(db));
        });

        test("version numbers must be unique", () -> {
            raises(IllegalArgumentException.class, () -> new SchemaMigrator(List.of(
                    Migration.of("V1__a", db -> { }), Migration.of("V2__b", db -> { }), Migration.of("V2__c", db -> { }))));
            raises(IllegalArgumentException.class, () -> new SchemaMigrator(List.of(
                    Migration.of("V2__b", db -> { }), Migration.of("V02__c", db -> { }))));
        });

        test("regressions: id format and version()", () -> {
            raises(IllegalArgumentException.class, () -> new SchemaMigrator(List.of(Migration.of("create_accounts", db -> { }))));
            equal(12, SchemaMigrator.version("V12__drop_audit_action"));
        });

        Check.done();
    }
}
