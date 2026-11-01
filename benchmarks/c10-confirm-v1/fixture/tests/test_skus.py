import pytest

from stockroom import InvalidSkuError, StockroomError, normalize_sku


def test_normalize_strips_and_uppercases():
    assert normalize_sku("  blt-0042 ") == "BLT-0042"


@pytest.mark.parametrize("raw", ["BLT0042", "BL-0042", "BLT-042", "", "BLT-00421", 42])
def test_invalid_skus_rejected(raw):
    with pytest.raises(InvalidSkuError):
        normalize_sku(raw)


def test_invalid_sku_is_stockroom_and_value_error():
    assert issubclass(InvalidSkuError, StockroomError)
    assert issubclass(InvalidSkuError, ValueError)
