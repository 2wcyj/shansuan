"""Request-local tenant identity derived only from a validated cloud session."""
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import UUID


_TENANT_ID: ContextVar[UUID | None] = ContextVar("shansuan_cloud_tenant_id", default=None)


class TenantContextError(RuntimeError):
    pass


@contextmanager
def tenant_context(account_id: UUID):
    if not isinstance(account_id, UUID):
        raise TenantContextError("A validated account identifier is required")
    token = _TENANT_ID.set(account_id)
    try:
        yield
    finally:
        _TENANT_ID.reset(token)


def current_tenant_id() -> UUID:
    value = _TENANT_ID.get()
    if value is None:
        raise TenantContextError("Tenant access requires an authenticated request context")
    return value
