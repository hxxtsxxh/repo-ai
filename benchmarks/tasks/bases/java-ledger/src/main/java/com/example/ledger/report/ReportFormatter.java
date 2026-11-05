package com.example.ledger.report;

import com.example.ledger.Account;
import com.example.ledger.Ledger;
import com.example.ledger.Money;
import java.text.DecimalFormat;
import java.text.DecimalFormatSymbols;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/** Plain-text reports: trial balance and account statements. */
public final class ReportFormatter {
    private static final int ID_WIDTH = 10;
    private static final int NAME_WIDTH = 24;
    private static final int AMOUNT_WIDTH = 14;

    private ReportFormatter() {
    }

    /** "1,234.50" / "-12.00" (no currency symbol). */
    public static String formatAmount(Money money) {
        DecimalFormat format = new DecimalFormat("#,##0.00", DecimalFormatSymbols.getInstance(Locale.ROOT));
        return format.format(money.toDecimal());
    }

    private static String pad(String text, int width) {
        if (text.length() > width) {
            return text.substring(0, width);
        }
        return text + " ".repeat(width - text.length());
    }

    private static String padLeft(String text, int width) {
        return text.length() >= width ? text : " ".repeat(width - text.length()) + text;
    }

    /**
     * Trial balance for all accounts in {@code currency}. Debit balances go
     * in the DEBIT column and credit balances (shown as positive numbers) in
     * the CREDIT column.
     */
    public static List<String> trialBalance(Ledger ledger, String currency) {
        List<String> lines = new ArrayList<>();
        lines.add(pad("ACCOUNT", ID_WIDTH) + pad("NAME", NAME_WIDTH) + padLeft("DEBIT", AMOUNT_WIDTH)
                + padLeft("CREDIT", AMOUNT_WIDTH));
        Money debits = Money.zero(currency);
        Money credits = Money.zero(currency);
        for (Account account : ledger.accounts()) {
            if (!account.currency().equals(currency)) {
                continue;
            }
            Money balance = ledger.balance(account.id());
            String debit = "";
            String credit = "";
            if (balance.isPositive()) {
                debit = formatAmount(balance);
                debits = debits.plus(balance);
            } else if (balance.isNegative()) {
                credit = formatAmount(balance.abs());
                credits = credits.plus(balance.abs());
            }
            lines.add((pad(account.id(), ID_WIDTH) + pad(account.name(), NAME_WIDTH) + padLeft(debit, AMOUNT_WIDTH)
                    + padLeft(credit, AMOUNT_WIDTH)).stripTrailing());
        }
        lines.add(pad("TOTAL", ID_WIDTH + NAME_WIDTH) + padLeft(formatAmount(debits), AMOUNT_WIDTH)
                + padLeft(formatAmount(credits), AMOUNT_WIDTH));
        return lines;
    }

    /** Statement with opening balance, one line per transaction and closing balance. */
    public static List<String> statement(Ledger ledger, String accountId, LocalDate from, LocalDate to) {
        Account account = ledger.account(accountId);
        List<String> lines = new ArrayList<>();
        lines.add("Statement for " + account.id() + " " + account.name() + " (" + account.currency() + ")");
        lines.add("Period " + from + " to " + to);
        Money opening = ledger.balanceAsOf(account.id(), from.minusDays(1));
        lines.add(pad("Opening balance", 48) + padLeft(formatAmount(opening), AMOUNT_WIDTH));
        Money closing = opening;
        for (Ledger.StatementLine line : ledger.statement(account.id(), from, to)) {
            lines.add(pad(line.date() + " " + line.description(), 34) + padLeft(formatAmount(line.amount()), AMOUNT_WIDTH)
                    + padLeft(formatAmount(line.balance()), AMOUNT_WIDTH));
            closing = line.balance();
        }
        lines.add(pad("Closing balance", 48) + padLeft(formatAmount(closing), AMOUNT_WIDTH));
        return lines;
    }
}
