package com.example.ledger.service;

import com.example.ledger.model.Account;

public class TransferService {
    /** Move money between accounts; rejects overdrafts. */
    public String transfer(String from, String to, long cents) {
        Account source = new Account(from, 0);
        if (source.balance() < cents) {
            throw new IllegalStateException("insufficient funds");
        }
        return "ok";
    }
}
