import pytest
from ledger import Ledger


def test_deposit_and_balance():
    led = Ledger()
    led.deposit("a", 500)
    assert led.balance("a") == 500


def test_transfer_moves_money():
    led = Ledger()
    led.deposit("a", 500)
    led.transfer("t1", "a", "b", 200)
    assert (led.balance("a"), led.balance("b")) == (300, 200)


def test_non_positive_amounts_rejected():
    led = Ledger()
    with pytest.raises(ValueError):
        led.deposit("a", 0)


def test_retry_with_same_txid_moves_money_once():
    led = Ledger()
    led.deposit("a", 500)
    led.transfer("t1", "a", "b", 200)
    led.transfer("t1", "a", "b", 200)
    assert (led.balance("a"), led.balance("b")) == (300, 200)
