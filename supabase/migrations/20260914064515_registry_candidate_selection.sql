create or replace function public.web_registry_match(p jsonb) returns jsonb
language plpgsql security invoker set search_path='' as $$
declare b jsonb:=p->'building';u jsonb:=p->'unit'; bs uuid[]; us uuid[]; bid uuid; uid uuid;
 candidates jsonb:='[]'; cs jsonb:='[]'; state text:='new'; reason text:='';
begin
 if coalesce(b->>'property_type','') not in ('condominium_land_right','condominium_no_land_right','leasehold_condominium') then
  return jsonb_build_object('status','blocked','reason','物件種別が対象外です。','candidates','[]'::jsonb,'cases','[]'::jsonb);
 end if;
 select array_agg(unit_id) into us from public.units where nullif(u->>'house_number','') is not null and house_number=u->>'house_number';
 if coalesce(cardinality(us),0)=0 then
  select array_agg(building_id) into bs from public.buildings x where
   (nullif(b->>'registry_location','') is not null and public.registry_match_text(x.registry_location)=public.registry_match_text(b->>'registry_location') and
    ((public.registry_parcels(b->'land_lots')<>'[]' and public.registry_parcels(x.land_lots)=public.registry_parcels(b->'land_lots')) or
     (nullif(b->>'building_name','') is not null and public.registry_match_text(x.building_name)=public.registry_match_text(b->>'building_name')))) or
   (public.registry_parcels(b->'land_lots')<>'[]' and public.registry_parcels(x.land_lots)=public.registry_parcels(b->'land_lots') and
    nullif(b->>'building_name','') is not null and public.registry_match_text(x.building_name)=public.registry_match_text(b->>'building_name'));
  select array_agg(unit_id) into us from public.units x where building_id=any(bs) and nullif(u->>'unit_name','') is not null
   and regexp_replace(public.registry_match_text(x.unit_name),'号室$','')=regexp_replace(public.registry_match_text(u->>'unit_name'),'号室$','');
 end if;
 -- A human choice may narrow only the candidates found by the unchanged match rules.
 -- This runs again inside the registration transaction and its advisory lock.
 if nullif(p->>'selected_unit_id','') is not null then
  if not coalesce((p->>'selected_unit_id')=any(us::text[]),false) then
   return jsonb_build_object('status','blocked','reason','選択した住戸は現在の候補にありません。再照合してください。','candidates','[]'::jsonb,'cases','[]'::jsonb);
  end if;
  us:=array[(p->>'selected_unit_id')::uuid];
 elsif nullif(p->>'selected_building_id','') is not null then
  if coalesce(cardinality(us),0)>0 or not coalesce((p->>'selected_building_id')=any(bs::text[]),false) then
   return jsonb_build_object('status','blocked','reason','選択した建物は現在の候補にありません。再照合してください。','candidates','[]'::jsonb,'cases','[]'::jsonb);
  end if;
  bs:=array[(p->>'selected_building_id')::uuid];
 end if;
 if coalesce(cardinality(us),0)>1 then state:='ambiguous';reason:='住戸候補が複数あります。自動登録しません。';
 elsif cardinality(us)=1 then
  uid:=us[1];select building_id into bid from public.units where unit_id=uid;state:='existing';
 elsif coalesce(cardinality(bs),0)>1 then state:='ambiguous';reason:='一棟候補が複数あります。自動登録しません。';
 else
  bid:=bs[1];
  if nullif(u->>'house_number','') is null or nullif(u->>'unit_name','') is null or nullif(b->>'registry_location','') is null
   or public.registry_parcels(b->'land_lots')='[]' or exists(select 1 from jsonb_array_elements(b->'land_lots') x where nullif(x->>'location','') is null or nullif(x->>'lot_number','') is null) then
   state:='incomplete';reason:='新規登録に必要な家屋番号・号室・所在・土地の対応を確認してください。';
  end if;
 end if;
 if us is not null then
  select coalesce(jsonb_agg(jsonb_build_object('unit_id',x.unit_id,'building_id',x.building_id,'building_name',y.building_name,
    'unit_name',x.unit_name,'house_number',x.house_number,'registry_location',y.registry_location,'current_owner_name',x.current_owner_name,
    'updated_at',x.updated_at) order by x.unit_id),'[]') into candidates from public.units x join public.buildings y using(building_id) where x.unit_id=any(us);
 elsif bs is not null then
  select coalesce(jsonb_agg(jsonb_build_object('building_id',x.building_id,'building_name',x.building_name,'registry_location',x.registry_location,'updated_at',x.updated_at) order by x.building_id),'[]') into candidates from public.buildings x where x.building_id=any(bs);
 end if;
 if uid is not null then select coalesce(jsonb_agg(jsonb_build_object('case_id',case_id,'case_status',case_status,'updated_at',updated_at) order by created_at),'[]') into cs from public.cases where unit_id=uid; end if;
 return jsonb_build_object('status',state,'reason',reason,'building_id',bid,'unit_id',uid,'candidates',candidates,'cases',cs);
end $$;

