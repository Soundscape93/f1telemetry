"""Additive schema upkeep for existing databases.

``create_all`` creates missing *tables* but never alters an existing one, so a newly added
column doesn't appear in a database created before it. Until the first non-additive migration
forces Alembic (a rename / type change / drop / backfill — see docs/DECISIONS.md → Migrations),
``ensure_schema`` covers the additive case: it inspects each mapped table and ``ADD COLUMN`` for
any column the ORM defines but the database lacks. It is idempotent and safe to run on every
startup, right after ``create_all``.

Additive only by design: it never drops, renames, or retypes a column. New columns must carry a
default (they do — ``mapped_column(default=...)``) so existing rows get a value.
"""
from __future__ import annotations

from sqlalchemy import Engine, inspect, text
from sqlalchemy.schema import CreateColumn

from .schema import Base


def _add_column_sql(table_name: str, column, dialect) -> str:
    """The ``ALTER TABLE ... ADD COLUMN`` statement for one missing column.

    Reuses SQLAlchemy's own column compiler for the ``name TYPE [NOT NULL] [DEFAULT x]`` fragment
    so the type and default render the same way ``create_all`` would have written them.
    """
    fragment = CreateColumn(column).compile(dialect=dialect).string
    return f"ALTER TABLE {table_name} ADD COLUMN {fragment}"


def ensure_schema(engine: Engine) -> None:
    """Add any ORM-defined columns missing from existing tables. Idempotent."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            continue                                    # a brand-new table: create_all handles it
        present = {col["name"] for col in inspector.get_columns(table.name)}
        missing = [col for col in table.columns if col.name not in present]
        if not missing:
            continue
        with engine.begin() as conn:
            for column in missing:
                conn.execute(text(_add_column_sql(table.name, column, engine.dialect)))
