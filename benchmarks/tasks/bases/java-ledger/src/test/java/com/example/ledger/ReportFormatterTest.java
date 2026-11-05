package com.example.ledger;

import static com.example.ledger.testing.Check.equal;
import static com.example.ledger.testing.Check.isTrue;
import static com.example.ledger.testing.Check.test;

import com.example.ledger.report.ReportFormatter;
import java.time.LocalDate;
import java.util.List;

public final class ReportFormatterTest {
    public static void run() {
        test("format amount", () -> {
            equal("1,234.50", ReportFormatter.formatAmount(Money.of(123_450, "USD")));
            equal("-0.05", ReportFormatter.formatAmount(Money.of(-5, "USD")));
        });
        test("trial balance columns", () -> {
            List<String> lines = ReportFormatter.trialBalance(Fixtures.sampleLedger(), "USD");
            isTrue(lines.get(0).startsWith("ACCOUNT"), "header first");
            isTrue(lines.get(1).startsWith("ACC-0001  Checking") && lines.get(1).endsWith("2,500.00"), lines.get(1));
            isTrue(lines.stream().anyMatch(l -> l.startsWith("ACC-0100") && l.endsWith("2,500.00")), "equity credit row");
        });
        test("statement", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            ledger.transfer("ACC-0001", "ACC-0200", Money.parse("40", "USD"), LocalDate.of(2026, 3, 10), "Food");
            List<String> lines = ReportFormatter.statement(ledger, "ACC-0001", LocalDate.of(2026, 3, 5), LocalDate.of(2026, 3, 31));
            isTrue(lines.get(2).endsWith("2,500.00"), "opening " + lines.get(2));
            isTrue(lines.get(lines.size() - 1).endsWith("2,460.00"), "closing");
        });
    }

    public static void main(String[] args) {
        run();
        com.example.ledger.testing.Check.done();
    }
}
