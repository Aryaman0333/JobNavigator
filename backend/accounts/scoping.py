"""Central account scoping (MT-2): two listeners on the Session *class*, so every
session from every sessionmaker (SessionLocal, test fixtures, scripts) is covered.

- do_orm_execute: every ORM SELECT / bulk UPDATE / bulk DELETE gets
  `with_loader_criteria(AccountScoped, account_id == current)`, which reaches every
  account-owned entity in the statement (joins, aliases, relationship loads).
- before_flush: new account-owned instances without an account get the current one.

Not covered (see MT-PLAN.md "Unscoped call sites"): `text()` / Core-table statements,
and `Session.get()` / `Query.get()` hits served from the identity map.
"""
from sqlalchemy import event
from sqlalchemy.orm import Session, with_loader_criteria

from backend.accounts.context import (
    current_account, is_unscoped, owner_id_for_session, resolve_account, strict_mode,
)

_installed = False


def install_scoping(marker) -> None:
    """Attach the listeners once; `marker` is the mixin every account-owned model carries."""
    global _installed
    if _installed:
        return
    _installed = True

    @event.listens_for(Session, "do_orm_execute")
    def _scope_statement(state):
        if not (state.is_select or state.is_update or state.is_delete):
            return
        # Lazy/column loads inherit the criteria from the statement that loaded the parent.
        if state.is_column_load or state.is_relationship_load:
            return
        if is_unscoped() or state.execution_options.get("jn_unscoped"):
            return
        try:
            mappers = state.all_mappers
        except Exception:
            return
        if any(issubclass(m.class_, marker) for m in mappers):
            account = resolve_account(state.session)  # raises in strict mode without a context
        elif not mappers and not state.is_select:
            return  # Core-table UPDATE/DELETE: not ORM, not scoped
        else:
            # An unowned entity that may join an owned one (JobLocation → Job), or a SELECT
            # whose entities sit in a subquery (Query.count()): scope it when we can.
            account = current_account.get()
            if account is None and not strict_mode():
                account = owner_id_for_session(state.session)
        if account is None:
            return
        state.statement = state.statement.options(
            with_loader_criteria(marker, lambda cls: cls.account_id == account, include_aliases=True)
        )

    @event.listens_for(Session, "before_flush")
    def _stamp_new_rows(session, flush_context, instances):
        new = [o for o in session.new
               if isinstance(o, marker) and getattr(o, "account_id", None) is None]
        if not new:
            return
        account = current_account.get()
        if account is None:
            account = owner_id_for_session(session) if is_unscoped() else resolve_account(session)
        if account is None:
            return
        for obj in new:
            obj.account_id = account
