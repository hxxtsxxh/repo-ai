package com.example.ledger;

import com.example.ledger.testing.Check;

/** Runs every visible test class. */
public final class AllTests {
    public static void main(String[] args) {
        MoneyTest.run();
        LedgerTest.run();
        InterestCalculatorTest.run();
        CsvImporterTest.run();
        ReportFormatterTest.run();
        Check.done();
    }
}
