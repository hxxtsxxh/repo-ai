"""Refund eligibility rules."""


class RefundPolicy:
    window_days = 14

    def allows(self, charge_id: str) -> bool:
        return bool(charge_id)
