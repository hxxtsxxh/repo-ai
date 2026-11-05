package com.example.ledger;

import static com.example.ledger.testing.Check.equal;
import static com.example.ledger.testing.Check.isTrue;
import static com.example.ledger.testing.Check.raises;
import static com.example.ledger.testing.Check.test;

import com.example.ledger.testing.Check;

import com.example.ledger.io.CsvImportException;
import com.example.ledger.io.CsvImporter;
import java.util.List;

public final class HiddenImporterIdsTest {
    public static void main(String[] args) {
        String header = "date,description,from,to,amount,currency\n";
        test("lower-case and padded ids are accepted", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            List<Transaction> txs = new CsvImporter(ledger).importText(header
                    + "2026-03-03,Power,acc-0001, acc-0201 ,80.25,USD\n"
                    + "2026-03-04,Food,Acc-0001,ACC-0200,19.75,usd\n");
            equal(2, txs.size());
            equal("ACC-0201", txs.get(0).entries().get(1).accountId());
            equal(Money.parse("2400", "USD"), ledger.balance("ACC-0001"));
            equal(Money.parse("80.25", "USD"), ledger.balance("ACC-0201"));
        });
        test("malformed ids still report the line", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            CsvImportException e = raises(CsvImportException.class, () -> new CsvImporter(ledger).importText(header
                    + "2026-03-03,ok,ACC-0001,ACC-0201,1.00,USD\n"
                    + "2026-03-03,bad,ACC-12,ACC-0201,1.00,USD\n"));
            equal(3, e.line());
            isTrue(e.getMessage().contains("invalid account id"), e.getMessage());
            equal(1, ledger.journal().size());
        });
        test("regression: unknown account", () -> {
            Ledger ledger = Fixtures.sampleLedger();
            CsvImportException e = raises(CsvImportException.class, () -> new CsvImporter(ledger).importText(header
                    + "2026-03-03,x,ACC-0001,acc-9999,1.00,USD\n"));
            equal(2, e.line());
            isTrue(e.getMessage().contains("unknown account"), e.getMessage());
        });
        Check.done();
    }
}
