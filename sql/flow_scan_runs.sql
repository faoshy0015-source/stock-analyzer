-- Optional private, server-only storage for post-close investor-flow scans.
-- Run once in the Supabase SQL editor for the user's own project.
-- Never expose SUPABASE_SERVICE_ROLE_KEY to browsers or public GitHub files.
create table if not exists public.flow_scan_runs (
  run_date date primary key,
  data jsonb not null,
  alert_sent boolean not null default false,
  updated_at timestamptz not null default now(),
  constraint flow_scan_runs_data_object check (jsonb_typeof(data) = 'object')
);

alter table public.flow_scan_runs enable row level security;

-- No anon/authenticated SELECT/INSERT/UPDATE policies are defined.
-- These revokes keep the persisted reports private by default.
revoke all on table public.flow_scan_runs from anon;
revoke all on table public.flow_scan_runs from authenticated;
grant select, insert, update on table public.flow_scan_runs to service_role;

comment on table public.flow_scan_runs is
  'Derived EOD KRX stock-investor-flow screening results. Service-role server access only.';

-- Tell PostgREST to pick up the new or existing table after this migration.
notify pgrst, 'reload schema';
