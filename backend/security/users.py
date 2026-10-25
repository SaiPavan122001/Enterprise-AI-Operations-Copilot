"""User store for browser sign-in: scrypt password hashes, role, tenant and
optional service grants, kept server-side in ``USERS_FILE`` (git-ignored).

    python -m security.users add <username> --role investigator [--tenant default] [--services a,b]
    python -m security.users passwd <username>
    python -m security.users disable <username>
    python -m security.users list

Passwords are generated (printed once) unless RCA_NEW_PASSWORD is set; they are
never written anywhere except as a salted scrypt hash.
"""

import argparse
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from config import settings
from security.access import resolve_services
from security.principals import ROLES, Principal

_N, _R, _P = 2 ** 14, 8, 1
_lock = threading.Lock()


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, r, p, salt, digest = stored.split("$")
        got = hashlib.scrypt(password.encode("utf-8"), salt=bytes.fromhex(salt), n=int(n), r=int(r), p=int(p),
                             dklen=len(bytes.fromhex(digest)))
        return hmac.compare_digest(got.hex(), digest)
    except (ValueError, TypeError):
        return False


# Compared against when the user does not exist, so timing does not reveal valid names.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


@dataclass(frozen=True)
class User:
    username: str
    role: str
    tenant: str
    services: tuple[str, ...]
    disabled: bool

    def principal(self, session_id: str | None = None) -> Principal:
        return Principal(name=self.username, role=self.role, tenant=self.tenant,
                         services=resolve_services(self.tenant, list(self.services) or None),
                         method="session", session_id=session_id)


def _path() -> Path:
    return Path(settings.USERS_FILE)


def _read() -> dict:
    p = _path()
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"users": {}}


def _write(data: dict) -> None:
    p = _path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(p)


def get_user(username: str) -> User | None:
    rec = _read().get("users", {}).get(username)
    if not rec or rec.get("role") not in ROLES:
        return None
    return User(username, rec["role"], rec.get("tenant", "default"), tuple(rec.get("services") or ()),
                bool(rec.get("disabled")))


def authenticate_password(username: str, password: str) -> User | None:
    rec = _read().get("users", {}).get(username)
    ok = verify_password(password, rec["password"] if rec else _DUMMY_HASH)
    user = get_user(username) if (rec and ok) else None
    return user if user and not user.disabled else None


def has_users() -> bool:
    return bool(_read().get("users"))


def add_user(username: str, role: str, password: str, tenant: str = "default",
             services: list[str] | None = None) -> None:
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    if len(password) < 12:
        raise ValueError("password must be at least 12 characters")
    with _lock:
        data = _read()
        data.setdefault("users", {})[username] = {
            "password": hash_password(password), "role": role, "tenant": tenant,
            "services": services or [], "disabled": False,
            "created": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        _write(data)


def set_disabled(username: str, disabled: bool = True) -> None:
    with _lock:
        data = _read()
        if username not in data.get("users", {}):
            raise KeyError(username)
        data["users"][username]["disabled"] = disabled
        _write(data)


def set_password(username: str, password: str) -> None:
    with _lock:
        data = _read()
        if username not in data.get("users", {}):
            raise KeyError(username)
        data["users"][username]["password"] = hash_password(password)
        _write(data)


def _new_password() -> str:
    return os.getenv("RCA_NEW_PASSWORD") or secrets.token_urlsafe(18)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m security.users")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add")
    a.add_argument("username")
    a.add_argument("--role", required=True, choices=ROLES)
    a.add_argument("--tenant", default="default")
    a.add_argument("--services", default="", help="comma-separated service grants (default: all of the tenant)")
    sub.add_parser("passwd").add_argument("username")
    sub.add_parser("disable").add_argument("username")
    sub.add_parser("list")
    args = p.parse_args(argv)
    if args.cmd == "add":
        pw = _new_password()
        add_user(args.username, args.role, pw, args.tenant, [s for s in args.services.split(",") if s])
        print(f"user {args.username} ({args.role}, tenant {args.tenant}) created")
        if not os.getenv("RCA_NEW_PASSWORD"):
            print(f"password (shown once, store it in a password manager): {pw}")
    elif args.cmd == "passwd":
        pw = _new_password()
        set_password(args.username, pw)
        if not os.getenv("RCA_NEW_PASSWORD"):
            print(f"new password (shown once): {pw}")
    elif args.cmd == "disable":
        set_disabled(args.username)
        print(f"user {args.username} disabled")
    else:
        for name, rec in sorted(_read().get("users", {}).items()):
            print(f"{name:20s} {rec['role']:13s} tenant={rec.get('tenant')} services={rec.get('services') or 'tenant'}"
                  f"{' DISABLED' if rec.get('disabled') else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
