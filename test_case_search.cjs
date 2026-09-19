// Case list search: newest first, updated date, search across name, room, address, house number and owner.
// Offline. Usage: node test_case_search.cjs
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes={};const el=s=>nodes[s]||(nodes[s]={innerHTML:'',textContent:'',hidden:false,value:'',classList:{add(){},remove(){}},addEventListener(){}});
el('#protected').hidden=true;
const ctx={document:{querySelector:el},window:{addEventListener(){},KeiyakuAuth:{token:()=>'t'}},sessionStorage:{getItem:()=>null,setItem(){},removeItem(){}},console,setTimeout,clearTimeout,fetch:async()=>({ok:true,json:async()=>({})})};
const root=el('#live-app');root.querySelectorAll=()=>[];
vm.runInNewContext(fs.readFileSync(__dirname+'/web/live-app.js','utf8')+'\nglobalThis.t={list,setState:s=>liveState=s};',ctx);
ctx.t.setState({cases:[
 {id:'a',building_name:'サンプルマンシヨン架空',unit_name:'403号',address:'港区架空一丁目',owner:'株式会社テスト',updated_at:'2026-09-01T00:00:00Z',unresolved:0,fields:[{label:'家屋番号',value:'架空一丁目12番3の403'}]},
 {id:'b',building_name:'テストハイツ別館',unit_name:'601',address:'港区架空二丁目',owner:'株式会社別',updated_at:'2026-09-18T00:00:00Z',unresolved:2,fields:[]},
]});
ctx.t.list();
const rows=()=> (el('#case-rows').innerHTML.match(/class="case-row"/g)||[]).length;
assert.equal(rows(),2); assert.equal(el('#case-count').textContent,'2件');
assert(el('#case-rows').innerHTML.indexOf('テストハイツ')<el('#case-rows').innerHTML.indexOf('サンプル'),'newest first');
assert(el('#case-rows').innerHTML.includes('2026/9/18'));
const search=el('#case-search');
for (const [q,n] of [['架空 403',1],['ｻﾝﾌﾟﾙ',1],['サンプルマンション',1],['ｻﾝﾌﾟﾙﾏﾝｼｮﾝ 403',1],['12番3の403',1],['架空二丁目',1],['株式会社',2],['存在しない',0]]) {search.value=q;search.oninput();assert.equal(rows(),n,q);}
search.value='存在しない';search.oninput();assert(el('#case-rows').innerHTML.includes('該当する物件がありません'));assert.equal(el('#case-count').textContent,'2件中 0件');
console.log('PASS: newest first, updated date, search by name/room/address/house number/owner, empty result message');
