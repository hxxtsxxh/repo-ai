package com.example.ledger;

import static com.example.ledger.testing.Check.equal;
import static com.example.ledger.testing.Check.isTrue;
import static com.example.ledger.testing.Check.raises;
import static com.example.ledger.testing.Check.test;

import com.example.ledger.testing.Check;

import com.example.ledger.io.CsvImporter;
import com.example.ledger.io.CsvParser;
import java.util.List;

public final class HiddenCsvQuotesTest {
    public static void main(String[] args) {
        test("doubled quotes inside quoted field", () -> {
            List<String> f = CsvParser.splitLine("2026-03-05,\"Invoice \"\"Q3-17\"\", net 30\",ACC-0001,ACC-0300,120.00,USD");
            equal(6, f.size());
            equal("Invoice \"Q3-17\", net 30", f.get(1));
            equal(List.of("\"quoted\"", "x"), CsvParser.splitLine("\"\"\"quoted\"\"\",x"));
            equal(List.of("a\"b"), CsvParser.splitLine("\"a\"\"b\""));
        });
        test("round trip with quote()", () -> {
            for (String value : List.of("plain", "with, comma", "say \"hi\"", "\"\"")) {
                equal(List.of(value, "end"), CsvParser.splitLine(CsvParser.quote(value) + ",end"));
            }
        });
        test("importer keeps quotes", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            List<Transaction> txs = new CsvImporter(ledger).importText(
                    "date,description,from,to,amount,currency\n"
                    + "2026-03-05,\"Invoice \"\"Q3-17\"\", net 30\",ACC-0001,ACC-0300,120.00,USD\n");
            equal("Invoice \"Q3-17\", net 30", txs.get(0).description());
        });
        test("regression: empty quoted field and plain fields", () -> {
            equal(List.of("", "b"), CsvParser.splitLine("\"\",b"));
            equal(List.of("a", "b,c"), CsvParser.splitLine("a,\"b,c\""));
            raises(IllegalArgumentException.class, () -> CsvParser.splitLine("\"open"));
        });
        Check.done();
    }
}
