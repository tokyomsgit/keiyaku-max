-- Atomic import endpoint; no existing master values are overwritten.
begin;
create table if not exists public.registry_imports (
  content_hash text primary key,
  document_version_id uuid not null references public.document_versions(document_version_id),
  raw_json jsonb not null,
  result jsonb not null,
  created_at timestamptz not null default now()
);
alter table public.registry_imports enable row level security;
revoke all on public.registry_imports from anon, authenticated;
grant select, insert on public.registry_imports to service_role;
create unique index if not exists units_house_number_import_unique
  on public.units(house_number) where house_number is not null and house_number <> '';

create or replace function public.save_registry_import(p jsonb)
returns jsonb language plpgsql security invoker set search_path = '' as $function$
declare
  b jsonb := p->'building'; u jsonb := p->'unit'; d jsonb := p->'document';
  old public.units; bid uuid; uid uuid; did uuid; vid uuid; oldvid uuid;
  result jsonb; item jsonb; field text; oldvalue jsonb; newvalue jsonb;
  matches integer; version integer; diffs integer := 0; is_new boolean := false;
begin
  if nullif(u->>'house_number','') is null or coalesce(p->>'content_hash','') !~ '^[a-f0-9]{64}$'
     or coalesce(d->>'file_hash','') !~ '^[a-f0-9]{64}$' or p->'raw_json' is null then
    raise exception 'Invalid import identity';
  end if;
  -- Serialize import transactions, including building matching and version numbers.
  perform pg_catalog.pg_advisory_xact_lock(710904, 1);
  select r.result into result from public.registry_imports r where r.content_hash=p->>'content_hash';
  if found then return result || jsonb_build_object('reused',true,'diffs_created',0); end if;
  select count(*) into matches from public.units where house_number=u->>'house_number';
  if matches > 1 then raise exception 'Ambiguous unit'; end if;
  select * into old from public.units where house_number=u->>'house_number' for update;
  if found then
    uid := old.unit_id; bid := old.building_id;
  else
    is_new := true;
    if nullif(b->>'registry_location','') is null or jsonb_array_length(coalesce(b->'land_lots','[]'))=0
      or exists (select 1 from jsonb_array_elements(b->'land_lots') x
                 where nullif(x->>'location','') is null or nullif(x->>'lot_number','') is null) then
      raise exception 'Building identity is incomplete';
    end if;
    -- Area/category changes must not create another building for the same parcels.
    select count(*), (array_agg(building_id))[1] into matches,bid from public.buildings bb
    where regexp_replace(bb.registry_location,'[[:space:]・]+','','g')=regexp_replace(b->>'registry_location','[[:space:]・]+','','g')
      and (select jsonb_agg(jsonb_build_array(x->>'location',x->>'lot_number') order by x->>'location',x->>'lot_number') from jsonb_array_elements(bb.land_lots) x)
        = (select jsonb_agg(jsonb_build_array(x->>'location',x->>'lot_number') order by x->>'location',x->>'lot_number') from jsonb_array_elements(b->'land_lots') x);
    if matches > 1 then raise exception 'Ambiguous building'; end if;
    if bid is null then
      insert into public.buildings(building_name,registry_location,building_structure,land_lots,floor_areas)
      values(b->>'building_name',b->>'registry_location',b->>'building_structure',b->'land_lots',coalesce(b->'floor_areas','[]'))
      returning building_id into bid;
    end if;
    insert into public.units(building_id,house_number,unit_name,unit_type,unit_structure,unit_floor,
      registered_area,built_date,current_owner_name,current_owner_address,has_land_right,
      land_right_type,land_right_numerator,land_right_denominator,active_mortgages)
    values(bid,u->>'house_number',u->>'unit_name',u->>'unit_type',u->>'unit_structure',u->>'unit_floor',
      (u->>'registered_area')::numeric,(u->>'built_date')::date,u->>'current_owner_name',u->>'current_owner_address',
      (u->>'has_land_right')::boolean,u->>'land_right_type',(u->>'land_right_numerator')::numeric,
      (u->>'land_right_denominator')::numeric,coalesce(u->'active_mortgages','[]')) returning unit_id into uid;
  end if;
  select count(*),(array_agg(document_id))[1] into matches,did from public.documents where unit_id=uid and document_type='registry';
  if matches>1 then raise exception 'Ambiguous registry document'; end if;
  if did is null then
    insert into public.documents(document_type,building_id,unit_id) values('registry',bid,uid) returning document_id into did;
  end if;
  select document_version_id into oldvid from public.document_versions where document_id=did order by is_current desc,version_no desc limit 1;
  select coalesce(max(version_no),0)+1 into version from public.document_versions where document_id=did;
  insert into public.document_versions(document_id,version_no,source_type,as_of_date,status,original_filename,file_hash)
    values(did,version,coalesce(d->>'source_type','seller_provided'),(d->>'as_of_date')::date,
      coalesce(d->>'status','provisional'),d->>'original_filename',d->>'file_hash') returning document_version_id into vid;
  for item in select * from jsonb_array_elements(p->'values') loop
    insert into public.extracted_values(document_version_id,field_code,value,confidence,source_text,page_no,value_as_of_date)
    values(vid,item->>'field_code',item->'value',(item->>'confidence')::numeric,item->>'source_text',
      (item->>'page_no')::integer,(item->>'value_as_of_date')::date);
  end loop;
  if not is_new then
    foreach field in array array['current_owner_name','current_owner_address','active_mortgages','registered_area',
      'land_right_type','land_right_numerator','land_right_denominator'] loop
      if not u ? field or u->field='null'::jsonb then continue; end if;
      oldvalue := to_jsonb(old)->field; newvalue := u->field;
      if oldvalue is distinct from newvalue then
        if not exists(select 1 from public.value_diffs where document_id=did and field_code=field
          and old_value is not distinct from oldvalue and new_value is not distinct from newvalue) then
          insert into public.value_diffs(document_id,old_version_id,new_version_id,field_code,old_value,new_value,review_status,affected_field)
            values(did,oldvid,vid,field,oldvalue,newvalue,'unreviewed','units.'||field);
          diffs := diffs+1;
        end if;
      end if;
    end loop;
  end if;
  result := jsonb_build_object('building_id',bid,'unit_id',uid,'document_id',did,'document_version_id',vid,
    'unit_created',is_new,'diffs_created',diffs,'reused',false);
  insert into public.registry_imports(content_hash,document_version_id,raw_json,result) values(p->>'content_hash',vid,p->'raw_json',result);
  return result;
end;
$function$;
revoke all on function public.save_registry_import(jsonb) from public,anon,authenticated;
grant execute on function public.save_registry_import(jsonb) to service_role;
commit;
