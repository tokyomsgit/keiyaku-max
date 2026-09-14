insert into public.field_master(field_code,label_ja,entity_level,data_type,excel_named_range,primary_source) values
('wall_center_area','壁芯面積','unit','number',null,'purchase_important_explanation'),
('floor_plan','間取り','unit','text',null,'purchase_important_explanation'),
('seller_name','購入時の売主名','unit','text',null,'purchase_important_explanation'),
('seller_address','購入時の売主住所','unit','text',null,'purchase_important_explanation'),
('sale_price','購入時の売買代金','unit','number','購入時_sale_price','purchase_important_explanation'),
('earnest_money','購入時の手付金','unit','number','購入時_earnest_money','purchase_important_explanation'),
('handover_date','購入時の引渡日','unit','date','購入時_handover_date_era','purchase_important_explanation')
on conflict(field_code) do nothing;
-- Case-local adopted evidence IDs keep historical documents immutable.
create or replace function public.purchase_source(code text) returns text
language sql immutable security invoker set search_path='' as $$
 select case when code in ('building_name','registry_location','building_structure','floor_areas','house_number','unit_name','unit_type','unit_structure','unit_floor','registered_area','built_date','current_owner_name','current_owner_address','land_lots','has_land_right','land_right_type','land_right_numerator','land_right_denominator','active_mortgages') then 'registry'
 when code in ('pet_restrictions','office_use_allowed','instrument_restrictions','renovation_restrictions','leasing_restrictions','parking_rules','voting_rights_rule','rules_effective_date','unit_use_restrictions','balcony_exclusive_use','private_garden_rules','door_window_exclusive_use','management_association_name','related_rules') then 'management_rules'
 when code in ('wall_center_area','floor_plan','seller_name','seller_address','sale_price','earnest_money','handover_date') then 'purchase_important_explanation'
 else 'important_report' end
$$;
