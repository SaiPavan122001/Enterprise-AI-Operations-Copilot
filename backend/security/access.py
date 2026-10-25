"""Resource-level authorization: which incidents, deployments, logs and runbooks
a principal may read. Deny by default - an unknown tenant, an unlisted runbook
or a missing principal grants nothing.

Policy: ``security/access_policy.json`` (``ACCESS_POLICY_FILE`` overrides it).
A principal's readable services = its tenant's services, narrowed to the user's
own service grants when the user has any.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

from config import settings
from security.principals import Principal

POLICY_PATH = Path(__file__).with_name("access_policy.json")


@lru_cache(maxsize=4)
def _load(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def policy() -> dict:
    return _load(str(settings.ACCESS_POLICY_FILE or POLICY_PATH))


def tenant_services(tenant: str) -> frozenset[str]:
    t = policy().get("tenants", {}).get(tenant)
    return frozenset(t.get("services", [])) if t else frozenset()


def resolve_services(tenant: str, grants: list[str] | None) -> frozenset[str]:
    """Readable services: the tenant's services, narrowed to explicit grants."""
    owned = tenant_services(tenant)
    return owned if not grants else owned & frozenset(grants)


def system_principal(name: str = "system", tenant: str = "default") -> Principal:
    """Explicit trusted identity for local, non-HTTP callers (evaluation harness,
    CLI). It is never available through the API."""
    return Principal(name=name, role="investigator", tenant=tenant, services=tenant_services(tenant),
                     method="system")


# --------------------------------------------------------------------------- filters

def can_read(principal: Principal | None, service: str | None) -> bool:
    return principal is not None and principal.can_access_service(service)


def filter_by_service(principal: Principal | None, items: list, attr: str = "service") -> list:
    return [x for x in items if can_read(principal, getattr(x, attr, None) if not isinstance(x, dict)
                                         else x.get(attr))]


def can_read_runbook(principal: Principal | None, name: str | None) -> bool:
    if principal is None or not name:
        return False
    covered = policy().get("runbooks", {}).get(name)
    if not covered:
        return False                      # unlisted runbook: denied
    if "*" in covered:
        return bool(principal.services)
    return bool(principal.services & set(covered))


_SERVICE_RE = re.compile(r"\b[a-z]+-service\b")


def scoped_detail(principal: Principal | None, text: str | None) -> str | None:
    """A note that names a service the principal cannot read (e.g. the service of a
    quarantined deployment) is replaced, so it does not disclose that service's data."""
    if text is None or principal is None:
        return text
    named = set(_SERVICE_RE.findall(text))
    if named - set(principal.services):
        prefix = re.match(r"\s*(INC-\d+:\s*)", text)
        return (prefix.group(1) if prefix else "") + \
            "the referenced deployment belongs to a service outside your authorized scope; link not used"
    return text
