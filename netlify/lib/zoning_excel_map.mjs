// Cell map for the 重説 sheet's zoning section (rows 96-138), built from a real filled
// example (パラスト池袋301.xlsm) rather than guessed from the blank template: each checkbox
// item has its own "marker" cell right after its label, where (A)/(B)/(A)(B) is written to
// say which zone(s) a checked item applies to. Two zones with the SAME value share one
// checked box + a combined "(A)(B)" marker; two DIFFERENT values use two separate boxes,
// each with its own single-letter marker.
export const ZONING_TYPES = {
  '第1種低層住居専用地域': { box: 'BI96', marker: 'BV96' }, '第2種住居地域': { box: 'BY96', marker: 'CK96' }, '準工業地域': { box: 'CN96', marker: 'DA96' },
  '第2種低層住居専用地域': { box: 'BI98', marker: 'BV98' }, '準住居地域': { box: 'BY98', marker: 'CK98' }, '工業地域': { box: 'CN98', marker: 'DA98' },
  '第1種中高層住居専用地域': { box: 'BI100', marker: 'BV100' }, '田園住居地域': { box: 'BY100', marker: 'CK100' }, '工業専用地域': { box: 'CN100', marker: 'DA100' },
  '第2種中高層住居専用地域': { box: 'BI102', marker: 'BV102' }, '近隣商業地域': { box: 'BY102', marker: 'CK102' }, '用途地域の指定なし': { box: 'CN102', marker: 'DA102' },
  '第1種住居地域': { box: 'BI104', marker: 'BV104' }, '商業地域': { box: 'BY104', marker: 'CK104' },
};

export const DISTRICT_TYPES = {
  '防火地域': { box: 'BI106', marker: 'BV106' }, '風致地区': { box: 'BY106', marker: 'CK106' }, '臨港地区': { box: 'CN106', marker: 'DA106' },
  '準防火地域': { box: 'BI108', marker: 'BV108' }, '災害危険区域': { box: 'BY108', marker: 'CK108' }, '緑化地域': { box: 'CN108', marker: 'DA108' },
  '新たな防火規制区域': { box: 'BI110', marker: 'BV110' }, '地区計画区域': { box: 'BY110', marker: 'CK110' }, '生産緑地地区': { box: 'CN110', marker: 'DA110' },
  '建築基準法第22条区域': { box: 'BI112', marker: 'BV112' }, '特例容積率適用地区': { box: 'BY112', marker: 'CK112' }, '特定用途誘導地区': { box: 'CN112', marker: 'DA112' },
  '特定用途制限地域': { box: 'BY114', marker: 'CK114' }, '特別用途地区': { box: 'CN114', marker: 'DA114' },
  '高層住居誘導地区': { box: 'BY116', marker: 'CK116' },
  '駐車場整備地区': { box: 'BY118', marker: 'CK118' },
  '高度利用地区': { box: 'BI120', marker: 'BV120' }, '都市再生特別地区': { box: 'BY120', marker: 'CK120' },
  '特定街区': { box: 'BI122', marker: 'BV122' }, '特定防災街区整備地区': { box: 'BY122', marker: 'CK122' },
  '景観地区': { box: 'BI124', marker: 'BV124' }, '建築協定区域': { box: 'BY124', marker: 'CK124' },
};

// (value cell, marker cell) triples for 建ぺい率(126)/容積率(130): up to 3 slots.
export const RATIO_SLOTS = {
  building_coverage_ratio: [['BW126', 'CB126'], ['CF126', 'CK126'], ['CO126', 'CT126']],
  floor_area_ratio: [['BW130', 'CB130'], ['CF130', 'CK130'], ['CO130', 'CT130']],
};

// 高度地区（種別＋最高限度）has two slots (one row each) for up to two distinct entries;
// 最低限高度地区 has one slot with a distance value plus its own marker.
export const HEIGHT_DISTRICT_SLOTS = [
  { box: 'BI114', value: 'BP114', marker: 'BV114' },
  { box: 'BI116', value: 'BP116', marker: 'BV116' },
];
export const MIN_HEIGHT_DISTRICT = { box: 'BI118', value: 'BR118', marker: 'BV118' };
// The blank template defaults 無(no)=■ / 有(yes)=□ for all three of these; entering a value
// means flipping that (checking 有, clearing 無).
export const MIN_LOT_AREA = { yes: 'BR138', no: 'BU138', value: 'BX138' };
export const WALL_LINE = { yes: 'BR134', no: 'BU134' }; // marker cell position not yet confirmed by a real differing-zone example
export const WALL_SETBACK = { yes: 'BR136', no: 'BU136' };
export const BI166 = 'BI166';
