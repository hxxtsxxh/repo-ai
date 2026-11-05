package com.example.ledger.web;

import com.example.ledger.service.TransferService;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class TransferController {
    private final TransferService service;

    public TransferController(TransferService service) {
        this.service = service;
    }

    @PostMapping("/transfers")
    public String transfer(String from, String to, long cents) {
        return service.transfer(from, to, cents);
    }
}
