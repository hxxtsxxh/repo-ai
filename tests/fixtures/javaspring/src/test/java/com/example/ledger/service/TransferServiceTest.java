package com.example.ledger.service;

import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.assertThrows;

class TransferServiceTest {
    @Test
    void rejectsOverdraft() {
        assertThrows(IllegalStateException.class, () -> new TransferService().transfer("a", "b", 5));
    }
}
