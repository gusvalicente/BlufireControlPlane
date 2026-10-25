"""Link users migrated from Supabase to their Entra identity on first sign-in.

identity_map is seeded from Supabase auth.users (email, old user id) during migration. The first time a user
signs in with Entra, their object id is stored against the matching email. Only tenants in ALLOWED_TENANTS can
sign in at all (app.auth), so an email claim from another organization never reaches this code.
"""

from __future__ import annotations

from .auth import User


def link(conn, user: User) -> str | None:
    """Return the user's old Supabase id (to look up their existing rows), linking it on first sign-in."""
    row = conn.execute("select supabase_user_id from identity_map where entra_oid = %s", (user.oid,)).fetchone()
    if row:
        return str(row[0])
    if not user.email:
        return None
    row = conn.execute(
        "update identity_map set entra_oid = %s, entra_tid = %s, linked_at = now() "
        "where lower(email) = %s and entra_oid is null returning supabase_user_id",
        (user.oid, user.tid, user.email),
    ).fetchone()
    return str(row[0]) if row else None
