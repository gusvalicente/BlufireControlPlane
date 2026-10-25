-- Maps users migrated from Supabase to their Entra identity. Linked on first sign-in (see docs/sop/migrate-from-supabase.md).
create table if not exists identity_map (
    supabase_user_id uuid primary key,
    email text not null unique,
    entra_oid text unique,
    entra_tid text,
    linked_at timestamptz
);
