package com.example.ledger;

import static com.example.ledger.testing.Check.equal;
import static com.example.ledger.testing.Check.isTrue;
import static com.example.ledger.testing.Check.raises;
import static com.example.ledger.testing.Check.test;

import com.example.ledger.testing.Check;

import com.example.ledger.report.ReportFormatter;
import java.time.LocalDate;
import java.util.List;

public final class HiddenTrialBalanceTotalTest {
    public static void main(String[] args) {
        test("total row sums both columns", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            ledger.transfer("ACC-0300", "ACC-0200", Money.parse("1234.50", "USD"), LocalDate.of(2026, 3, 3), "Card");
            ledger.transfer("ACC-0001", "ACC-0201", Money.parse("65.50", "USD"), LocalDate.of(2026, 3, 3), "Power");
            List<String> lines = ReportFormatter.trialBalance(ledger, "USD");
            String header = lines.get(0);
            String total = lines.get(lines.size() - 1);
            isTrue(total.startsWith("TOTAL"), "last line: " + total);
            int debitEnd = header.indexOf("DEBIT") + "DEBIT".length();
            int creditEnd = header.indexOf("CREDIT") + "CREDIT".length();
            String debits = "3,734.50";
            String credits = "3,734.50";
            equal(debitEnd, total.indexOf(debits) + debits.length());
            equal(creditEnd, total.lastIndexOf(credits) + credits.length());
            equal(creditEnd, total.length());
        });
        test("only the requested currency is counted", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            ledger.open(new Account("ACC-0900", "Euro wallet", AccountType.ASSET, "EUR"));
            ledger.open(new Account("ACC-0901", "Euro equity", AccountType.EQUITY, "EUR"));
            ledger.transfer("ACC-0901", "ACC-0900", Money.parse("99", "EUR"), Fixtures.MAR_1, "fx");
            List<String> usd = ReportFormatter.trialBalance(ledger, "USD");
            String total = usd.get(usd.size() - 1);
            isTrue(total.matches("TOTAL\\s+2,500\\.00\\s+2,500\\.00"), total);
            List<String> eur = ReportFormatter.trialBalance(ledger, "EUR");
            isTrue(eur.get(eur.size() - 1).matches("TOTAL\\s+99\\.00\\s+99\\.00"), eur.toString());
        });
        test("empty report", () -> {
            List<String> lines = ReportFormatter.trialBalance(new Ledger(), "GBP");
            equal(2, lines.size());
            isTrue(lines.get(1).matches("TOTAL\\s+0\\.00\\s+0\\.00"), lines.get(1));
        });
        test("regression: account rows", () -> {
            List<String> lines = ReportFormatter.trialBalance(Fixtures.sampleLedger(), "USD");
            isTrue(lines.get(1).startsWith("ACC-0001  Checking") && lines.get(1).endsWith("2,500.00"), lines.get(1));
            equal(8, lines.size());
        });
        Check.done();
    }
}
