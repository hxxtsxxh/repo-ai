package com.example.ledger.io;

import java.util.ArrayList;
import java.util.List;

/**
 * RFC-4180-style line splitting: fields may be wrapped in double quotes, a
 * quoted field may contain commas, and a doubled quote ("") inside a quoted
 * field stands for one literal quote character.
 */
public final class CsvParser {
    private CsvParser() {
    }

    public static List<String> splitLine(String line) {
        List<String> fields = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        boolean inQuotes = false;
        for (int i = 0; i < line.length(); i++) {
            char c = line.charAt(i);
            if (inQuotes) {
                if (c == '"') {
                    if (i + 1 < line.length() && line.charAt(i + 1) == '"') {
                        current.append('"');
                        i++;
                    } else {
                        inQuotes = false;
                    }
                } else {
                    current.append(c);
                }
            } else if (c == '"') {
                inQuotes = true;
            } else if (c == ',') {
                fields.add(current.toString());
                current.setLength(0);
            } else {
                current.append(c);
            }
        }
        if (inQuotes) {
            throw new IllegalArgumentException("unterminated quoted field");
        }
        fields.add(current.toString());
        return fields;
    }

    /** Quotes a value for output if it contains a comma, quote or newline. */
    public static String quote(String value) {
        if (value.contains(",") || value.contains("\"") || value.contains("\n")) {
            return '"' + value.replace("\"", "\"\"") + '"';
        }
        return value;
    }
}
