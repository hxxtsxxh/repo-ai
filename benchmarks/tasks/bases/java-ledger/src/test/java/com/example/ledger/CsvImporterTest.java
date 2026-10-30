package com.example.ledger;

import static com.example.ledger.testing.Check.equal;
import static com.example.ledger.testing.Check.raises;
import static com.example.ledger.testing.Check.test;

import com.example.ledger.io.CsvImportException;
import com.example.ledger.io.CsvImporter;
import com.example.ledger.io.CsvParser;
import java.util.List;

public final class CsvImporterTest {
    public static void run() {
        test("split simple line", () -> equal(List.of("a", "b", "c"), CsvParser.splitLine("a,b,c")));
        test("split quoted comma", () -> equal(List.of("a", "b,c"), CsvParser.splitLine("a,\"b,c\"")));
        test("imports rows", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            String csv = String.join("\n",
                    "date,description,from,to,amount,currency",
                    "# monthly bills",
                    "2026-03-03,Power bill,ACC-0001,ACC-0201,80.25,USD",
                    "",
                    "2026-03-04,Market,ACC-0001,ACC-0200,19.75,USD");
            List<Transaction> txs = new CsvImporter(ledger).importText(csv);
            equal(2, txs.size());
            equal(Money.parse("2400", "USD"), ledger.balance("ACC-0001"));
        });
        test("bad field count reports line", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            CsvImportException e = raises(CsvImportException.class, () -> new CsvImporter(ledger)
                    .importText("date,description,from,to,amount,currency\n2026-03-03,x,ACC-0001,ACC-0201,USD"));
            equal(2, e.line());
        });
        test("bad row leaves ledger untouched", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            raises(CsvImportException.class, () -> new CsvImporter(ledger).importText(String.join("\n",
                    "date,description,from,to,amount,currency",
                    "2026-03-03,ok,ACC-0001,ACC-0201,1.00,USD",
                    "2026-13-03,bad date,ACC-0001,ACC-0201,1.00,USD")));
            equal(1, ledger.journal().size());
        });
        test("missing header", () -> raises(CsvImportException.class,
                () -> new CsvImporter(Fixtures.sampleLedger()).importText("2026-03-03,x,ACC-0001,ACC-0201,1,USD")));
    }

    public static void main(String[] args) {
        run();
        com.example.ledger.testing.Check.done();
    }
}
