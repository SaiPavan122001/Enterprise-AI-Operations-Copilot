"""Authenticated identities and role permissions.

A ``Principal`` is only ever built by the server (session store, API-key table,
explicit system identity) - never from client-supplied fields.

Roles and their explicit permissions (deny by default: a permission not listed
for a role is refused):

  viewer        incidents:search  tools:list  tools:read  actions:read
  investigator  viewer + investigations:run  actions:propose  actions:execute
  admin         investigator + actions:approve  audit:read
"""

from dataclasses import dataclass, field

ROLES = ("viewer", "investigator", "admin")

INCIDENTS_SEARCH = "incidents:search"
INVESTIGATIONS_RUN = "investigations:run"
TOOLS_LIST = "tools:list"
TOOLS_READ = "tools:read"
ACTIONS_READ = "actions:read"
ACTIONS_PROPOSE = "actions:propose"
ACTIONS_APPROVE = "actions:approve"
ACTIONS_EXECUTE = "actions:execute"
AUDIT_READ = "audit:read"

_VIEWER = frozenset({INCIDENTS_SEARCH, TOOLS_LIST, TOOLS_READ, ACTIONS_READ})
_INVESTIGATOR = _VIEWER | {INVESTIGATIONS_RUN, ACTIONS_PROPOSE, ACTIONS_EXECUTE}
_ADMIN = _INVESTIGATOR | {ACTIONS_APPROVE, AUDIT_READ}
ROLE_PERMISSIONS: dict[str, frozenset[str]] = {"viewer": _VIEWER, "investigator": frozenset(_INVESTIGATOR),
                                               "admin": frozenset(_ADMIN)}


@dataclass(frozen=True)
class Principal:
    name: str
    role: str
    tenant: str = "default"
    # Services whose records this principal may read (resolved server-side from
    # the access policy and the user's grants). Empty = no record access.
    services: frozenset[str] = field(default_factory=frozenset)
    method: str = "api_key"           # session | api_key | dev | system
    session_id: str | None = None

    @property
    def permissions(self) -> frozenset[str]:
        return ROLE_PERMISSIONS.get(self.role, frozenset())

    def has(self, permission: str) -> bool:
        return permission in self.permissions

    def can_access_service(self, service: str | None) -> bool:
        return bool(service) and service in self.services
