package com.example.ledger;

import static com.example.ledger.testing.Check.equal;
import static com.example.ledger.testing.Check.isTrue;
import static com.example.ledger.testing.Check.raises;
import static com.example.ledger.testing.Check.test;

import com.example.ledger.testing.Check;

import com.example.ledger.report.ReportFormatter;
import java.time.LocalDate;
import java.util.List;

public final class HiddenMonthEndTest {
    public static void main(String[] args) {
        LocalDate mar31 = LocalDate.of(2026, 3, 31);
        test("balance as of includes that day", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            ledger.transfer("ACC-0001", "ACC-0200", Money.parse("100", "USD"), mar31, "Rent");
            equal(Money.parse("2400", "USD"), ledger.balanceAsOf("ACC-0001", mar31));
            equal(Money.parse("2500", "USD"), ledger.balanceAsOf("ACC-0001", LocalDate.of(2026, 3, 30)));
            equal(Money.parse("2500", "USD"), ledger.balanceAsOf("ACC-0001", Fixtures.MAR_1));
            equal(Money.zero("USD"), ledger.balanceAsOf("ACC-0001", LocalDate.of(2026, 2, 28)));
        });
        test("april opening equals march closing", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            ledger.transfer("ACC-0001", "ACC-0200", Money.parse("100", "USD"), mar31, "Rent");
            ledger.transfer("ACC-0001", "ACC-0201", Money.parse("10", "USD"), LocalDate.of(2026, 4, 2), "Power");
            List<String> march = ReportFormatter.statement(ledger, "ACC-0001", Fixtures.MAR_1, mar31);
            List<String> april = ReportFormatter.statement(ledger, "ACC-0001", LocalDate.of(2026, 4, 1), LocalDate.of(2026, 4, 30));
            isTrue(march.get(march.size() - 1).endsWith("2,400.00"), "march closing " + march);
            isTrue(april.get(2).endsWith("2,400.00"), "april opening " + april);
            isTrue(april.get(april.size() - 1).endsWith("2,390.00"), "april closing " + april);
        });
        test("regression: statement lines", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            ledger.transfer("ACC-0001", "ACC-0200", Money.parse("40", "USD"), LocalDate.of(2026, 3, 10), "Food");
            equal(1, ledger.statement("ACC-0001", LocalDate.of(2026, 3, 2), mar31).size());
            equal(2, ledger.statement("ACC-0001", Fixtures.MAR_1, mar31).size());
        });
        Check.done();
    }
}
