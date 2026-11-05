class Ledger:
    def __init__(self):
        self.balances = {}
        self.applied = set()

    def deposit(self, account, cents):
        if cents <= 0:
            raise ValueError("deposit must be positive")
        self.balances[account] = self.balances.get(account, 0) + cents

    def balance(self, account):
        return self.balances.get(account, 0)

    def transfer(self, txid, src, dst, cents):
        if cents <= 0:
            raise ValueError("transfer must be positive")
        self.applied.add(txid)
        self.balances[src] = self.balances.get(src, 0) - cents
        self.balances[dst] = self.balances.get(dst, 0) + cents
