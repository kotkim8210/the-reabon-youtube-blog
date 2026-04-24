create table if not exists public.automation_batches (
  id bigint generated always as identity primary key,
  local_batch_id bigint not null unique,
  user_id bigint not null,
  source_key text not null,
  batch_name text not null,
  template_name text not null,
  output_filename text not null,
  total_rows integer not null default 0,
  total_quantity integer not null default 0,
  processed_at timestamptz not null,
  sync_version integer not null default 1,
  created_at timestamptz not null default timezone('utc', now())
);

create table if not exists public.automation_batch_items (
  id bigint generated always as identity primary key,
  batch_local_id bigint not null,
  user_id bigint not null,
  source_key text not null,
  product_name text not null,
  platform_option_name text not null default '',
  supply_option_name text not null default '',
  quantity integer not null default 0,
  external_order_id text not null default '',
  receiver_name text not null default '',
  receiver_phone text not null default '',
  receiver_address text not null default '',
  memo text not null default '',
  processed_at timestamptz not null,
  created_at timestamptz not null default timezone('utc', now())
);

create index if not exists automation_batch_items_batch_local_id_idx
  on public.automation_batch_items (batch_local_id);

create index if not exists automation_batch_items_processed_at_idx
  on public.automation_batch_items (processed_at desc);

