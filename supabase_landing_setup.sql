-- One-time setup for the catalog landing page's admin controls.
-- Run this ONCE in the Supabase SQL editor (safe to re-run: the table and
-- bucket statements skip themselves; the policy statements will error with
-- "already exists" on a second run, which is harmless -- just ignore it).
-- ASCII only on purpose: this file is meant to be hand-pasted.

-- Which products each landing-page row features, and its custom tile image.
create table if not exists public.landing_rows (
  row_id text primary key,
  featured_ids jsonb not null default '[]'::jsonb,
  tile_url text,
  updated_at timestamptz not null default now()
);

alter table public.landing_rows enable row level security;

create policy "landing_rows_public_read"
  on public.landing_rows for select using (true);

create policy "landing_rows_admin_write"
  on public.landing_rows for all to authenticated
  using (true) with check (true);

-- Public storage bucket for hand-made tile images uploaded from admin.html.
insert into storage.buckets (id, name, public)
  values ('landing', 'landing', true)
  on conflict (id) do nothing;

create policy "landing_bucket_public_read"
  on storage.objects for select using (bucket_id = 'landing');

create policy "landing_bucket_admin_insert"
  on storage.objects for insert to authenticated
  with check (bucket_id = 'landing');

create policy "landing_bucket_admin_update"
  on storage.objects for update to authenticated
  using (bucket_id = 'landing');
