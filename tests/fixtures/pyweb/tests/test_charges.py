import pytest

from app.billing.charges import charge_card


def test_rejects_zero_amount():
    with pytest.raises(ValueError):
        charge_card(1, 0)
