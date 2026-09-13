'use strict';
let state,csrf,pending;let filters={document:'all',review:false};const results=new Map();
const view=document.querySelector('#view');
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const val=v=>v===null||v===undefined||v===''?'未取得':Array.isArray(v)?v.map(val).join('、'):typeof v==='object'?Object.entries(v).map(([k,x])=>k+'：'+val(x)).join('、'):typeof v==='boolean'?(v?'有':'無'):String(v);
const date=v=>esc(displayScalar(v));
const pill=(text,warn=false)=>`<span class="pill ${warn?'warn':''}">${esc(text)}</span>`;
const route=()=>new URLSearchParams(location.hash.slice(1));
const href=(id,tab='detail')=>`#case=${encodeURIComponent(id)}&tab=${tab}`;
const docLabel=t=>t==='registry'?'謄本':'重調';
function error(e){document.querySelector('#error').textContent=e.message||String(e)}
async function api(path,body){if(window.PublicDemo)return window.PublicDemo.request(path,body);const r=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-CSRF-Token':csrf}:{},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.error||'処理に失敗しました。');return d;}
function render(){
 if(!state)return;
 document.querySelector('#mode').innerHTML=pill(state.mode==='demo'?'DEMO':'Supabase接続');
 document.querySelector('#notice').textContent=state.public_demo?'公開デモ：表示内容は架空のサンプルです。採用・保留はこの画面内だけの操作で、再読込すると元に戻ります。':state.mode==='demo'?(state.db_write_enabled?'デモ表示・DB更新有効：採用操作は実データを更新します。':'デモモード：解析済みJSONを使用しています。採用・保留はこの起動中だけの操作で、DBは更新しません。'):'';
 document.querySelector('#usage').textContent=`AI呼出し ${state.usage.ai_calls}回 ／ DB読込 ${state.usage.db_reads}回 ／ DB更新 ${state.usage.db_writes}回`;
 const id=route().get('case');if(!id)return renderList();
 const c=state.cases.find(c=>c.id===id);if(!c){view.innerHTML='<p class="empty">案件が見つかりません。</p>';return;}
 const tab=route().get('tab')||'detail';
 view.innerHTML=`<div class="top"><div><p class="muted"><a href="#">案件一覧</a> / 案件詳細</p><h1>${esc(c.building_name)} <small>${esc(c.unit_name)}</small></h1><span class="muted">${esc(c.address)}</span></div>${pill(c.status,true)}</div>
 <nav class="tabs">${[['detail','概要'],['registry','謄本'],['lands','土地'],['rights','権利・抵当権'],['report','重調'],['diffs','差分'],['excel','Excel生成'],['review','要確認']].map(([k,t])=>`<a class="${tab===k?'active':''}" href="${href(c.id,k)}">${t}${k==='diffs'&&c.diff_count?' ('+c.diff_count+')':''}</a>`).join('')}</nav>${c.upload_warnings?.length?`<div class="upload-warning" role="alert">${c.upload_warnings.map(x=>`<p>${esc(x)}</p>`).join('')}</div>`:''}<section id="panel"></section>`;
 const panel=document.querySelector('#panel');
 if(['documents','registry','lands','rights','report','review'].includes(tab)){filters.group=({documents:'basic',registry:'basic',lands:'lands',rights:'rights',report:'report',review:'review'})[tab];renderDocuments(c,panel);}else if(tab==='diffs')renderDiffs(c,panel);else if(tab==='excel')renderExcel(c,panel);else renderDetail(c,panel);
}
function renderList(){view.innerHTML=`<div class="top"><div><p class="overline">CONTRACT WORKSPACE</p><h1>案件一覧</h1><p class="muted">${state.cases.length}件の物件を確認できます</p></div><button data-action="refresh">一覧を更新</button></div>
 <div class="card table-scroll"><table><thead><tr><th>物件名 / 号室</th><th>ステータス</th><th>最終更新</th><th>要確認</th><th>未確認差分</th></tr></thead><tbody>${state.cases.map(c=>`<tr class="case-row"><td><a href="${href(c.id)}">${esc(c.building_name)}</a><br><span class="muted">${esc(c.unit_name)}</span></td><td>${pill(c.status,true)}</td><td>${date(c.updated_at)}</td><td>${c.review_count}項目</td><td>${c.diff_count}件</td></tr>`).join('')}</tbody></table>${!state.cases.length?'<p class="empty">登録された案件・住戸がありません。</p>':''}</div>
 ${state.public_demo?'<div class="card"><h2>謄本PDFを追加</h2><p>PDFの読取とExcel生成はローカル版で利用できます。</p></div>':'<div class="card"><h2>謄本PDFを追加</h2><p>同一住戸の建物謄本と土地謄本をまとめて選択できます。</p><label>謄本PDF（複数選択可） <input id="registry-pdfs" type="file" accept=".pdf,application/pdf" multiple></label><div class="actions"><button class="primary" data-action="upload">読み取る</button><span id="upload-status" role="status"></span></div><p class="muted">デモモードでは解析済みの同一PDFのみ再利用します。取込結果はローカルに保存されます。</p></div>'}
 ${state.unmatched.length?`<p class="muted">住戸未照合の資料：${state.unmatched.length}件。物件が確定するまで契約書生成の対象にはしません。</p>`:''}`;}
function renderDetail(c,p){
 p.innerHTML=`<div class="card"><h2>物件情報</h2><dl class="facts">${[['物件名',c.building_name],['号室',c.unit_name],['所在',c.address],['所有者',c.owner],['登記面積',c.area===null?'不明':c.area+' ㎡'],['ステータス',c.status]].map(([k,v])=>`<div><dt>${k}</dt><dd>${esc(val(v))}</dd></div>`).join('')}</dl></div>
 <div class="grid">${['registry','important_report'].map(t=>{const docs=c.documents.filter(d=>d.type===t);return `<div class="card"><h2>${docLabel(t)}</h2>${pill(docs.length?'読取済み':'未読取',!docs.length)}<p class="count">${docs.reduce((n,d)=>n+d.fields.filter(f=>f.needs_review).length,0)} <small class="muted">項目 要確認</small></p><p class="muted">最終取得日 ${date(docs.map(d=>d.date).filter(Boolean).sort().at(-1))}</p><a href="${href(c.id,t==='registry'?'registry':'report')}">読取結果を確認 →</a></div>`;}).join('')}
 <div class="card"><h2>差分</h2><p class="count">${c.diff_count} <small class="muted">件 未確認</small></p><p class="muted">変更候補を確認して採用・保留を選択します。</p><a href="${href(c.id,'diffs')}">差分を確認 →</a></div></div>`;
}
const displayLabels={floor:'階',階:'階',area:'面積',面積:'面積',location:'所在',lot_number:'地番',land_category:'地目',land_area:'地積',right_type:'権利',share:'持分',numerator:'分子',denominator:'分母',rank:'順位',rank_number:'順位',type:'種類',amount:'債権額',debt_amount:'債権額',debtor:'債務者',debtors:'債務者',mortgagee:'抵当権者',creditor:'抵当権者',active:'有効',name:'氏名・名称',address:'住所',company_number:'会社法人等番号',value:'値'};
const unwrap=v=>v&&typeof v==='object'&&!Array.isArray(v)&&Object.hasOwn(v,'value')?v.value:v;
const pick=(row,...keys)=>{for(const k of keys)if(row&&Object.hasOwn(row,k))return unwrap(row[k]);return null;};
const isReview=f=>Boolean(f.needs_review||f.evidence_mismatch||f.source_mismatch||f.source_consistent===false||(typeof f.confidence==='number'&&f.confidence<.85));
const isError=f=>Boolean(f.error||f.error_message||f.status==='error'||f.evidence_mismatch||f.source_mismatch||f.source_consistent===false);
function displayScalar(input,code=''){
 const v=unwrap(input);if(v===null||v===undefined||v==='')return '未取得';if(typeof v==='boolean')return v?'有':'無';
 const text=String(v),d=text.match(/^(\d{4})-(\d{2})(?:-(\d{2}))?(?:T.*)?$/);
 if(d)return `${d[1]}年${Number(d[2])}月${d[3]?Number(d[3])+'日':''}`;
 const money=/fee$|amount|債権額|金額|月額|極度額/.test(code),area=/area$|面積|地積/.test(code);
 if(typeof v==='number'||/^\d+(?:\.\d+)?$/.test(text)){
  const n=Number(v),digits=(text.split('.')[1]||'').length;
  const formatted=['house_number','lot_number','unit_name','rank'].includes(code)?text:n.toLocaleString('ja-JP',{maximumFractionDigits:Math.min(20,digits),minimumFractionDigits:Math.min(20,digits)});
  return formatted+(money?'円':area?'㎡':code==='total_units'?'戸':code==='unit_name'?'号室':code==='floor'||code==='unit_floor'?'階':'');
 }
 return text;
}
function longText(text){const more=text.length>85||text.split('\n').length>3;return `<div class="long-copy"><div class="${more?'clamped':''}">${esc(text)}</div>${more?'<button type="button" class="expand-text" data-expand aria-expanded="false">全文を見る</button>':''}</div>`;}
function shareValue(row){const share=pick(row,'share','right_share','持分','権利の割合');if(share!==null)return share;const n=pick(row,'numerator','share_numerator','持分_分子'),d=pick(row,'denominator','share_denominator','持分_分母');return n!==null&&d!==null?`${n}／${d}`:null;}
function valueTable(rows,columns,label){return `<div class="value-table-wrap"><table class="value-table" aria-label="${esc(label)}"><thead><tr>${columns.map(c=>`<th scope="col">${esc(c[0])}</th>`).join('')}</tr></thead><tbody>${rows.map(row=>`<tr>${columns.map(([name,key,get])=>`<td>${formatValue(get(row),key)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;}
function formatValue(input,code=''){
 const v=unwrap(input);
 if(Array.isArray(v)){
  if(!v.length)return '<span class="muted">該当なし</span>';
  const rows=v.map(unwrap);
  if(code==='floor_areas')return valueTable(rows,[['階','floor',r=>pick(r,'floor','階')],['面積','area',r=>pick(r,'area','面積','各階面積')]],'各階床面積');
  if(['lands','land_lots'].includes(code))return valueTable(rows,[['所在','location',r=>pick(r,'location','所在')],['地番','lot_number',r=>pick(r,'lot_number','地番')],['地目','land_category',r=>pick(r,'land_category','category','地目')],['地積','area',r=>pick(r,'area','land_area','地積')],['権利','right_type',r=>pick(r,'right_type','権利','権利の種類')],['持分','share',shareValue]],'土地一覧');
  if(['mortgages','active_mortgages'].includes(code))return valueTable(rows,[['順位','rank',r=>pick(r,'rank','rank_number','順位','順位番号')],['種類','type',r=>pick(r,'type','kind','種類')],['債権額','amount',r=>pick(r,'amount','debt_amount','債権額','極度額')],['債務者','debtor',r=>pick(r,'debtor','debtors','債務者')],['抵当権者','mortgagee',r=>pick(r,'mortgagee','creditor','抵当権者')],['有効','active',r=>pick(r,'active','有効','現在有効')]],'抵当権一覧');
  if(rows.every(x=>x&&typeof x==='object'&&!Array.isArray(x))){const keys=[...new Set(rows.flatMap(Object.keys))];return valueTable(rows,keys.map(k=>[displayLabels[k]||k,k,r=>r[k]]),'一覧');}
  return `<ul class="value-list">${rows.map(x=>`<li>${formatValue(x)}</li>`).join('')}</ul>`;
 }
 if(v&&typeof v==='object')return `<dl class="object-values">${Object.entries(v).map(([k,x])=>`<div><dt>${esc(displayLabels[k]||k)}</dt><dd>${formatValue(x,k)}</dd></div>`).join('')}</dl>`;
 return longText(displayScalar(v,code));
}
const documentGroups=[['basic','基本情報'],['lands','土地'],['rights','権利・抵当権'],['report','重調'],['review','要確認のみ']];
function fieldGroup(d,f){if(d.type==='important_report')return 'report';if(['land_lots','lands'].includes(f.code))return 'lands';if(/mortgage|land_right|owner|leasehold|tenure/.test(f.code))return 'rights';return 'basic';}
function renderDocuments(c,p){
 const group=filters.group||'basic';
 const all=c.documents.flatMap(d=>d.fields.map(f=>({d,f})));
 const grouped=all.filter(({d,f})=>group==='review'?isReview(f)||isError(f):fieldGroup(d,f)===group);
 const rows=grouped.filter(({d,f})=>(filters.document==='all'||d.version_id===filters.document)&&(!filters.review||isReview(f)||isError(f)));
 p.innerHTML=`<div class="card document-card"><h2>資料確認</h2><div class="toolbar"><label>根拠資料 <select id="document-filter"><option value="all">すべての資料</option>${c.documents.map(d=>`<option value="${esc(d.version_id)}" ${filters.document===d.version_id?'selected':''}>${docLabel(d.type)}・第${d.version}版：${esc(d.filename)}</option>`).join('')}</select></label><label><input id="review-filter" type="checkbox" ${filters.review?'checked':''}> 要確認だけ表示</label><span class="muted">${rows.length}項目</span></div>
 ${c.documents.some(d=>d.source_files?.length)?`<details class="source-files"><summary>統合した原本資料を確認</summary><ul>${[...new Set(c.documents.flatMap(d=>d.source_files||[]))].map(f=>`<li>${esc(f)}</li>`).join('')}</ul></details>`:''}<div class="field-head"><span>項目</span><span>値</span><span>根拠情報</span></div><div class="document-fields">${rows.map(({d,f})=>`<article class="document-field ${isError(f)?'field-error':isReview(f)?'field-review':''}"><div class="field-label"><h3>${esc(f.label)}</h3><code>${esc(f.code)}</code><div class="field-badges">${pill(isError(f)?'エラー':isReview(f)?'要確認':'確認情報',isReview(f))}<span class="muted">確信度：${f.confidence===null||f.confidence===undefined?'未取得':Math.round(f.confidence*100)+'%'}</span></div>${f.approved?'<span class="muted">採用済み</span>':''}</div><div class="field-value">${formatValue(f.value,f.code)}${!f.excel_supported?'<p class="muted">Excel未対応・保存のみ</p>':''}</div><div class="field-source"><strong>${esc(d.filename||'資料名未取得')}</strong><div class="source-meta">ページ：${esc(f.page_no??'未取得')} ／ 基準日：${esc(displayScalar(f.value_as_of_date))}</div>${longText(f.source_text||'根拠テキスト未取得')}${f.error_message?longText(f.error_message):''}</div></article>`).join('')}${!rows.length?'<p class="empty">該当する項目はありません。</p>':''}</div></div>`;
}
function renderDiffs(c,p){p.innerHTML=`<h2>変更候補を確認</h2><p class="muted">採用するまで確定値は変更されません。保留した差分は、後から再確認できます。</p>${c.diffs.map(d=>`<div class="card"><div class="top"><div><h3>${esc(d.label)}</h3><code>${esc(d.code)}</code></div>${pill(({unreviewed:'未確認',reviewed:'保留',applied:'採用済み',ignored:'対象外'})[d.review_status]||d.review_status,d.review_status!=='applied')}</div><div class="diff-values"><div><span class="muted">旧</span><p>${formatValue(d.old_value,d.code)}</p></div><span>→</span><div class="new"><span class="muted">新</span><p>${formatValue(d.new_value,d.code)}</p></div></div><p class="muted">${esc(d.source||'根拠資料の確認が必要')}</p><div class="actions"><button class="primary" data-action="adopt" data-diff="${esc(d.id)}" ${!d.can_adopt||['applied','ignored'].includes(d.review_status)?'disabled':''}>採用</button><button data-action="hold" data-diff="${esc(d.id)}" ${['applied','ignored'].includes(d.review_status)?'disabled':''}>保留</button>${!d.can_adopt?'<span class="muted">根拠確認が必要なため採用できません</span>':''}</div></div>`).join('')}${!c.diffs.length?'<div class="card empty">差分はありません。</div>':''}`;}
function renderExcel(c,p){if(c.generation_blocked){p.innerHTML='<div class="card"><h2>自動入力を停止しました</h2><p>戸建て・物件種別不明・資料間不一致は確認が必要です。区分マンション用ひな形へ自動転記しません。</p><a href="#">別の謄本を選択</a></div>';return;}if(state.public_demo){p.innerHTML='<div class="card"><h2>契約書Excelを生成</h2><p>案件・資料・差分の確認をお試しいただけます。</p><button disabled>Excel生成はローカル版で利用可能</button><p class="muted">公開デモでは契約書の生成・ダウンロードはできません。ローカル版のExcel生成機能は引き続き利用できます。</p></div>';return;}const r=results.get(c.id);p.innerHTML=`<div class="card"><h2>契約書Excelを生成</h2><p>既存の謄本マッピングと、重調の「物件名」「号室」を反映します。</p><p class="muted">重調の要確認・根拠不明・低confidenceの値は転記しません。元のひな形は変更しません。</p>${state.mode==='demo'?'<p class="pill warn">デモ出力です。実務利用前に内容を確認してください。</p>':''}<div class="actions"><button class="primary" data-action="generate">契約書Excelを生成</button></div>${r?`<div class="success"><strong>生成・再読込確認が完了しました</strong><p>謄本の処理：${r.registry_written??0}セル ／ 重調の反映：${r.report_written}項目</p><a class="button primary" href="${esc(r.download)}" download>Excelをダウンロード</a><p class="muted">${esc(r.filename)}</p></div>${r.warnings.length?`<h3>出力の要確認事項</h3><ul>${r.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul>`:''}`:''}</div><div class="card"><h2>Excel未対応の項目</h2><p>管理費・修繕積立金・滞納・管理会社などは、現行ひな形の「基本入力」に対応欄がありません。</p><p class="muted">保存済みの値と根拠は「資料確認」で確認できます。</p><a href="${href(c.id,'registry')}">資料確認へ →</a></div>`;}
view.addEventListener('change',e=>{if(!['document-filter','review-filter'].includes(e.target.id))return;if(e.target.id==='document-filter')filters.document=e.target.value;if(e.target.id==='review-filter')filters.review=e.target.checked;render();});
view.addEventListener('click',async e=>{const expand=e.target.closest('[data-expand]');if(expand){const open=expand.getAttribute('aria-expanded')!=='true';expand.setAttribute('aria-expanded',String(open));expand.previousElementSibling.classList.toggle('clamped',!open);expand.textContent=open?'閉じる':'全文を見る';return;}const group=e.target.closest('[data-group]');if(group){filters.group=group.dataset.group;filters.document='all';filters.review=false;render();return;}const b=e.target.closest('button[data-action]');if(!b)return;const action=b.dataset.action,cid=route().get('case');document.querySelector('#error').textContent='';
 if(action==='upload'){const files=document.querySelector('#registry-pdfs').files;if(!files.length){error(Error('PDFを選択してください。'));return;}const form=new FormData();for(const f of files)form.append('pdfs',f);b.disabled=true;document.querySelector('#upload-status').textContent='謄本を読み取り中…';try{const response=await fetch('/api/upload-registry',{method:'POST',headers:{'X-CSRF-Token':csrf},body:form});const result=await response.json();if(!response.ok)throw Error(result.error);state=result.state;location.hash=href(result.case_id,'registry');render();}catch(e){error(e);b.disabled=false;document.querySelector('#upload-status').textContent='';}return;}
 if(action==='adopt'){pending={case_id:cid,diff_id:b.dataset.diff,action:'adopt'};const d=state.cases.find(c=>c.id===cid).diffs.find(d=>d.id===b.dataset.diff);document.querySelector('#confirm-text').textContent=d.label+'：'+val(d.old_value)+' → '+val(d.new_value);document.querySelector('#confirm').showModal();return;}
 b.disabled=true;const old=b.textContent;if(action==='generate')b.textContent='契約書作成中…';
 try{if(action==='generate')results.set(cid,await api('/api/generate',{case_id:cid}));else if(action==='hold')state=await api('/api/decision',{case_id:cid,diff_id:b.dataset.diff,action:'hold'});else if(action==='refresh')state=await api('/api/refresh',{});render();}catch(e){error(e);b.disabled=false;b.textContent=old;}
});
document.querySelector('#cancel').onclick=()=>document.querySelector('#confirm').close();
document.querySelector('#accept').onclick=async()=>{const b=document.querySelector('#accept');b.disabled=true;try{state=await api('/api/decision',pending);results.delete(pending.case_id);document.querySelector('#confirm').close();render();}catch(e){document.querySelector('#confirm').close();error(e)}finally{b.disabled=false}};
window.addEventListener('hashchange',()=>{document.querySelector('#error').textContent='';filters.document='all';filters.review=false;render()});
api('/api/state').then(d=>{state=d;csrf=d.csrf;render()}).catch(error);
