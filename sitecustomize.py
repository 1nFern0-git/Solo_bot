from __future__ import annotations

import warnings

warnings.filterwarnings(
    "ignore",
    message=r'.*Field "model_custom_emoji_id" in UniqueGiftColors has conflict with protected namespace',
    category=UserWarning,
)

try:
    import aiogram.types
    from pydantic import ConfigDict

    unique_gift_colors = getattr(aiogram.types, "UniqueGiftColors", None)
    if unique_gift_colors is not None:
        cfg = getattr(unique_gift_colors, "model_config", None)
        base = dict(cfg) if cfg is not None else {}
        unique_gift_colors.model_config = ConfigDict(**base, protected_namespaces=())
except Exception:
    pass

try:
    from alembic.ddl.postgresql import PostgresqlImpl
    from sqlalchemy import text

    _LEGACY_TABLES = {"blocked_users", "manual_bans", "temporary_data"}
    _IGNORED_USERS_INDEXES = {"ix_users_id", "uq_users_tg_id"}

    def _columns(conn, table_name: str) -> set[str]:
        rows = conn.execute(
            text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = :table_name
                """
            ),
            {"table_name": table_name},
        ).fetchall()
        return {row[0] for row in rows}

    def _pk_columns(conn, table_name: str) -> list[str]:
        rows = conn.execute(
            text(
                """
                SELECT a.attname
                FROM pg_constraint c
                JOIN pg_class t ON t.oid = c.conrelid
                JOIN pg_namespace n ON n.oid = t.relnamespace
                JOIN unnest(c.conkey) WITH ORDINALITY AS u(attnum, ord) ON true
                JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = u.attnum
                WHERE n.nspname = 'public'
                  AND t.relname = :table_name
                  AND c.contype = 'p'
                ORDER BY u.ord
                """
            ),
            {"table_name": table_name},
        ).fetchall()
        return [row[0] for row in rows]

    def _fill_user_id_from_tg(conn, table_name: str, user_col: str, tg_col: str) -> None:
        cols = _columns(conn, table_name)
        if user_col not in cols or tg_col not in cols:
            return
        conn.execute(
            text(
                f"""
                UPDATE "{table_name}" AS t
                SET "{user_col}" = u.id
                FROM users AS u
                WHERE t."{user_col}" IS NULL
                  AND t."{tg_col}" IS NOT NULL
                  AND t."{tg_col}" = u.tg_id
                """
            )
        )

    def _delete_nulls(conn, table_name: str, col: str) -> None:
        cols = _columns(conn, table_name)
        if col not in cols:
            return
        conn.execute(text(f'DELETE FROM "{table_name}" WHERE "{col}" IS NULL'))

    def _prepare_not_null(conn, table_name: str, column_name: str) -> None:
        mapping = {
            ("notifications", "user_id"): ("user_id", "tg_id"),
            ("gift_usages", "user_id"): ("user_id", "tg_id"),
            ("blocked_users", "user_id"): ("user_id", "tg_id"),
            ("manual_bans", "user_id"): ("user_id", "tg_id"),
            ("temporary_data", "user_id"): ("user_id", "tg_id"),
            ("scheduled_broadcasts", "created_by_user_id"): ("created_by_user_id", "created_by_tg_id"),
            ("gifts", "sender_user_id"): ("sender_user_id", "sender_tg_id"),
        }
        if (table_name, column_name) in mapping:
            user_col, tg_col = mapping[(table_name, column_name)]
            _fill_user_id_from_tg(conn, table_name, user_col, tg_col)
            _delete_nulls(conn, table_name, user_col)
            return
        if table_name == "referrals" and column_name == "referred_user_id":
            _fill_user_id_from_tg(conn, table_name, "referred_user_id", "referred_tg_id")
            _delete_nulls(conn, table_name, "referred_user_id")
        if table_name == "referrals" and column_name == "referrer_user_id":
            _fill_user_id_from_tg(conn, table_name, "referrer_user_id", "referrer_tg_id")
            _delete_nulls(conn, table_name, "referrer_user_id")

    _orig_alter_column = PostgresqlImpl.alter_column
    _orig_drop_table = PostgresqlImpl.drop_table
    _orig_drop_index = PostgresqlImpl.drop_index
    _orig_create_index = PostgresqlImpl.create_index

    def _index_table_name(index) -> str | None:
        table = getattr(index, "table", None)
        return getattr(table, "name", None)

    if not getattr(PostgresqlImpl.alter_column, "_solo_guarded", False):
        def _guarded_alter_column(self, table_name, column_name, *args, **kwargs):
            nullable = kwargs.get("nullable")
            if nullable is True and column_name in _pk_columns(self.connection, table_name):
                return
            if table_name in _LEGACY_TABLES and column_name in {"user_id", "tg_id"}:
                return
            if nullable is False:
                _prepare_not_null(self.connection, table_name, column_name)
            return _orig_alter_column(self, table_name, column_name, *args, **kwargs)

        _guarded_alter_column._solo_guarded = True
        PostgresqlImpl.alter_column = _guarded_alter_column

    if not getattr(PostgresqlImpl.drop_table, "_solo_guarded", False):
        def _guarded_drop_table(self, table, **kwargs):
            if getattr(table, "name", None) == "schema_migrations":
                return
            return _orig_drop_table(self, table, **kwargs)

        _guarded_drop_table._solo_guarded = True
        PostgresqlImpl.drop_table = _guarded_drop_table

    if not getattr(PostgresqlImpl.drop_index, "_solo_guarded", False):
        def _guarded_drop_index(self, index, **kwargs):
            table_name = _index_table_name(index)
            index_name = getattr(index, "name", None)
            if table_name in _LEGACY_TABLES:
                return
            if table_name == "users" and index_name in _IGNORED_USERS_INDEXES:
                return
            return _orig_drop_index(self, index, **kwargs)

        _guarded_drop_index._solo_guarded = True
        PostgresqlImpl.drop_index = _guarded_drop_index

    if not getattr(PostgresqlImpl.create_index, "_solo_guarded", False):
        def _guarded_create_index(self, index, **kwargs):
            table_name = _index_table_name(index)
            index_name = getattr(index, "name", None)
            if table_name in _LEGACY_TABLES:
                return
            if table_name == "users" and index_name in _IGNORED_USERS_INDEXES:
                return
            return _orig_create_index(self, index, **kwargs)

        _guarded_create_index._solo_guarded = True
        PostgresqlImpl.create_index = _guarded_create_index
except Exception:
    pass
