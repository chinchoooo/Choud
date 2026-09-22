"""Platform-independent column types.

Kept minimal on purpose (Rule 2: don't over-engineer) — currently just the
UUID primary-key type every model uses.
"""

import uuid

from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.types import CHAR, TypeDecorator


class GUID(TypeDecorator):
    """A UUID column that works against both PostgreSQL and SQLite.

    Production (and `docker compose`) always run PostgreSQL, which stores
    this as its native UUID type. The test suite runs against an in-memory
    SQLite database instead of a real PostgreSQL server (see
    `server/tests/conftest.py`) — spinning up Postgres just to exercise the
    ORM layer would be exactly the unnecessary infrastructure Rule 2 warns
    against for a personal project. On SQLite the same column is stored as
    a 32-character hex string instead.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(32))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        if dialect.name == "postgresql":
            return str(value)
        return value.hex

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(value)
