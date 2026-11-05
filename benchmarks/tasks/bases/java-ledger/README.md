# java-ledger

A small double-entry ledger written in plain Java 17 with no dependencies.

## Model

* `Money` - immutable amount in minor units (cents) plus an ISO currency code.
  Combining different currencies throws `CurrencyMismatchException`.
  `allocate(ratios...)` splits an amount so the shares always add back up
  to the original.
* `Account` / `AccountType` - ids look like `ACC-0001` and are
  case-insensitive (canonicalised to upper case by `Validation`).
* `Entry` / `Transaction` - positive entries are debits, negative entries are
  credits; a transaction must sum to zero.
* `Ledger` - opens accounts, posts transactions atomically (all entries or
  none), transfers, balances, `balanceAsOf(date)` (inclusive of that date)
  and statements.
* `InterestCalculator` - simple daily accrual over a 365-day year and monthly
  compounding; rounding is banker's rounding (half-even) to the cent.
* `ExpenseSplitter` - splits one payment across several expense accounts.
* `io.CsvParser` / `io.CsvImporter` - CSV import with header
  `date,description,from,to,amount,currency`; quoted fields may contain
  commas and doubled quotes (`""`).
* `report.ReportFormatter` - trial balance (with a TOTAL line) and statements.

## Build and test

No Maven or Gradle download is needed (`pom.xml` is descriptive only).

```
mkdir -p out
javac -d out $(find src/main/java src/test/java -name '*.java')
java -cp out com.example.ledger.AllTests
```

Individual test classes (`MoneyTest`, `LedgerTest`, ...) also have a `main`
method. Tests use the tiny assertion helper in
`src/test/java/com/example/ledger/testing/Check.java`.
