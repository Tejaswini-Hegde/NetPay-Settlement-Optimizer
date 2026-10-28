"""SQLite ledger: durable, idempotent record of every settlement payment."""
from __future__ import annotations
import sqlite3, time


class Ledger:
    def __init__(self, path: str = "netpay.db"):
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS settlements(
            request_key TEXT PRIMARY KEY, plan_id TEXT, payer TEXT, payee TEXT,
            amount_cents INTEGER, currency TEXT, invoice_id TEXT, status TEXT, updated_at REAL)""")
        self.db.commit()

    def get(self, key: str):
        row = self.db.execute("SELECT * FROM settlements WHERE request_key=?", (key,)).fetchone()
        return dict(row) if row else None

    def record(self, key, plan_id, p, invoice_id, status):
        self.db.execute("INSERT INTO settlements VALUES(?,?,?,?,?,?,?,?,?)",
                        (key, plan_id, p.payer, p.payee, p.amount_cents, p.currency, invoice_id, status, time.time()))
        self.db.commit()

    def set_status(self, key, status):
        self.db.execute("UPDATE settlements SET status=?, updated_at=? WHERE request_key=?", (status, time.time(), key))
        self.db.commit()
