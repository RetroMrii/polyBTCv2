"""Keep WAL files open without holding a read transaction or sharing writers."""
from pathlib import Path
import sqlite3


class WALReaders:
    def __init__(self, paths=()):
        self.connections = []
        try:
            for path in paths:
                connection = sqlite3.connect(
                    Path(path).resolve().as_uri() + '?mode=ro', uri=True,
                    check_same_thread=False,
                )
                self.connections.append(connection)
                if connection.execute('PRAGMA journal_mode').fetchone()[0] != 'wal':
                    raise ValueError('WAL required for runtime database')
                connection.execute('SELECT name FROM sqlite_master LIMIT 1').fetchall()
                # No BEGIN and no live cursor: checkpoints remain free to advance.
                assert not connection.in_transaction
        except BaseException:
            self.close()
            raise

    def close(self):
        for connection in self.connections:
            connection.close()
        self.connections.clear()
