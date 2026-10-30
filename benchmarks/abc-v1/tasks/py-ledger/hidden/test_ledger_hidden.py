import pytest
from ledger import Ledger


def test_overdraft_is_rejected_and_changes_nothing():
    led = Ledger()
    led.deposit("a", 100)
    with pytest.raises(ValueError):
        led.transfer("t1", "a", "b", 101)
    assert (led.balance("a"), led.balance("b")) == (100, 0)


def test_rejected_transfer_does_not_consume_txid():
    led = Ledger()
    led.deposit("a", 100)
    with pytest.raises(ValueError):
        led.transfer("t1", "a", "b", 150)
    led.deposit("a", 100)
    led.transfer("t1", "a", "b", 150)
    assert (led.balance("a"), led.balance("b")) == (50, 150)


def test_exact_balance_transfer_is_allowed():
    led = Ledger()
    led.deposit("a", 100)
    led.transfer("t1", "a", "b", 100)
    assert (led.balance("a"), led.balance("b")) == (0, 100)


def test_retry_is_idempotent_across_many_retries():
    led = Ledger()
    led.deposit("a", 1000)
    for _ in range(5):
        led.transfer("t9", "a", "b", 100)
    assert (led.balance("a"), led.balance("b")) == (900, 100)
