-- Landing page setup / repair. SAFE TO RUN REPEATEDLY: every statement
-- either applies or quietly skips if it already happened, so a run that
-- gets interrupted (deadlock, timeout, platform incident) is fixed by
-- simply running this again. ASCII only on purpose: hand-pasted file.

-- The table (skips if present).
create table if not exists public.landing_rows (
  row_id text primary key,
  featured_ids jsonb not null default '[]'::jsonb,
  tile_url text,
  updated_at timestamptz not null default now()
);

-- Access grants. These were the missing piece after a partial first run:
-- without them even a signed-in admin gets "permission denied".
grant usage on schema public to anon, authenticated;
grant select on public.landing_rows to anon, authenticated;
grant insert, update, delete on public.landing_rows to authenticated;

alter table public.landing_rows enable row level security;

do $$ begin
  create policy "landing_rows_public_read"
    on public.landing_rows for select using (true);
exception when duplicate_object then null; end $$;

do $$ begin
  create policy "landing_rows_admin_write"
    on public.landing_rows for all to authenticated
    using (true) with check (true);
exception when duplicate_object then null; end $$;

-- Storage bucket for tile images (skips if present).
insert into storage.buckets (id, name, public)
  values ('landing', 'landing', true)
  on conflict (id) do nothing;

-- Storage policies. If THIS section deadlocks (it fights for a lock on
-- storage.objects with Supabase's own storage service, especially during
-- a platform incident), everything above stays applied -- just re-run.
do $$ begin
  create policy "landing_bucket_public_read"
    on storage.objects for select using (bucket_id = 'landing');
exception when duplicate_object then null; end $$;

do $$ begin
  create policy "landing_bucket_admin_insert"
    on storage.objects for insert to authenticated
    with check (bucket_id = 'landing');
exception when duplicate_object then null; end $$;

do $$ begin
  create policy "landing_bucket_admin_update"
    on storage.objects for update to authenticated
    using (bucket_id = 'landing');
exception when duplicate_object then null; end $$;
