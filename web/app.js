'use strict';
let state,csrf,pending;let filters={document:'all',review:false};const results=new Map();
const view=document.querySelector('#view');
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const val=v=>v===null||v===undefined||v===''?'—':typeof v==='object'?JSON.stringify(v,null,2):String(v);
const date=v=>v?esc(String(v).slice(0,10)):'不明';
const pill=(text,warn=false)=>`<span class="pill ${warn?'warn':''}">${esc(text)}</span>`;
const route=()=>new URLSearchParams(location.hash.slice(1));
const href=(id,tab='detail')=>`#case=${encodeURIComponent(id)}&tab=${tab}`;
const docLabel=t=>t==='registry'?'謄本':'重調';
function error(e){document.querySelector('#error').textContent=e.message||String(e)}
async function api(path,body){if(window.PublicDemo)return window.PublicDemo.request(path,body);const r=await fetch(path,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json','X-CSRF-Token':csrf}:{},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.error||'処理に失敗しました。');return d;}
function render(){
 if(!state)return;
 document.querySelector('#mode').innerHTML=pill(state.mode==='demo'?'DEMO':'Supabase接続');
 document.querySelector('#notice').textContent=state.public_demo?'公開デモ：物件名・号室以外は架空のサンプルです。採用・保留はこの画面内だけの操作で、再読込すると元に戻ります。':state.mode==='demo'?(state.db_write_enabled?'デモ表示・DB更新有効：採用操作は実データを更新します。':'デモモード：解析済みJSONを使用しています。採用・保留はこの起動中だけの操作で、DBは更新しません。'):'';
 document.querySelector('#usage').textContent=`AI呼出し ${state.usage.ai_calls}回 ／ DB読込 ${state.usage.db_reads}回 ／ DB更新 ${state.usage.db_writes}回`;
 const id=route().get('case');if(!id)return renderList();
 const c=state.cases.find(c=>c.id===id);if(!c){view.innerHTML='<p class="empty">案件が見つかりません。</p>';return;}
 const tab=route().get('tab')||'detail';
 view.innerHTML=`<div class="top"><div><p class="muted"><a href="#">案件一覧</a> / 案件詳細</p><h1>${esc(c.building_name)} <small>${esc(c.unit_name)}</small></h1><span class="muted">${esc(c.address)}</span></div>${pill(c.status,true)}</div>
 <nav class="tabs">${[['detail','案件詳細'],['documents','資料確認'],['diffs','差分確認'],['excel','Excel生成']].map(([k,t])=>`<a class="${tab===k?'active':''}" href="${href(c.id,k)}">${t}${k==='diffs'&&c.diff_count?' ('+c.diff_count+')':''}</a>`).join('')}</nav><section id="panel"></section>`;
 const panel=document.querySelector('#panel');
 if(tab==='documents')renderDocuments(c,panel);else if(tab==='diffs')renderDiffs(c,panel);else if(tab==='excel')renderExcel(c,panel);else renderDetail(c,panel);
}
function renderList(){view.innerHTML=`<div class="top"><div><p class="overline">CONTRACT WORKSPACE</p><h1>案件一覧</h1><p class="muted">${state.cases.length}件の物件を確認できます</p></div><button data-action="refresh">一覧を更新</button></div>
 <div class="card table-scroll"><table><thead><tr><th>物件名 / 号室</th><th>ステータス</th><th>最終更新</th><th>要確認</th><th>未確認差分</th></tr></thead><tbody>${state.cases.map(c=>`<tr class="case-row"><td><a href="${href(c.id)}">${esc(c.building_name)}</a><br><span class="muted">${esc(c.unit_name)}</span></td><td>${pill(c.status,true)}</td><td>${date(c.updated_at)}</td><td>${c.review_count}項目</td><td>${c.diff_count}件</td></tr>`).join('')}</tbody></table>${!state.cases.length?'<p class="empty">登録された案件・住戸がありません。</p>':''}</div>
 ${state.unmatched.length?`<p class="muted">住戸未照合の資料：${state.unmatched.length}件。物件が確定するまで契約書生成の対象にはしません。</p>`:''}`;}
function renderDetail(c,p){
 p.innerHTML=`<div class="card"><h2>物件情報</h2><dl class="facts">${[['物件名',c.building_name],['号室',c.unit_name],['所在',c.address],['所有者',c.owner],['登記面積',c.area===null?'不明':c.area+' ㎡'],['ステータス',c.status]].map(([k,v])=>`<div><dt>${k}</dt><dd>${esc(val(v))}</dd></div>`).join('')}</dl></div>
 <div class="grid">${['registry','important_report'].map(t=>{const docs=c.documents.filter(d=>d.type===t);return `<div class="card"><h2>${docLabel(t)}</h2>${pill(docs.length?'読取済み':'未読取',!docs.length)}<p class="count">${docs.reduce((n,d)=>n+d.fields.filter(f=>f.needs_review).length,0)} <small class="muted">項目 要確認</small></p><p class="muted">最終取得日 ${date(docs.map(d=>d.date).filter(Boolean).sort().at(-1))}</p><a href="${href(c.id,'documents')}">読取結果を確認 →</a></div>`;}).join('')}
 <div class="card"><h2>差分</h2><p class="count">${c.diff_count} <small class="muted">件 未確認</small></p><p class="muted">変更候補を確認して採用・保留を選択します。</p><a href="${href(c.id,'diffs')}">差分を確認 →</a></div></div>`;
}
function renderDocuments(c,p){
 const docs=c.documents.filter(d=>filters.document==='all'||d.version_id===filters.document);
 let rows=[];for(const d of docs)for(const f of d.fields)if(!filters.review||f.needs_review)rows.push({d,f});
 p.innerHTML=`<div class="card"><h2>読取結果</h2><div class="toolbar"><label>根拠資料 <select id="document-filter"><option value="all">すべての資料</option>${c.documents.map(d=>`<option value="${esc(d.version_id)}" ${filters.document===d.version_id?'selected':''}>${docLabel(d.type)}・第${d.version}版：${esc(d.filename)}</option>`).join('')}</select></label><label><input id="review-filter" type="checkbox" ${filters.review?'checked':''}> 要確認だけ表示</label><span class="muted">${rows.length}項目</span></div>
 <div class="table-scroll"><table class="field-table"><thead><tr><th>項目 / field_code</th><th>読取値</th><th>根拠資料・ページ・原文</th><th>confidence / 状態</th></tr></thead><tbody>${rows.map(({d,f})=>`<tr><td>${esc(f.label)}<code>${esc(f.code)}</code></td><td class="evidence">${esc(val(f.value))}${!f.excel_supported?'<p class="muted">Excel未対応・保存のみ</p>':''}</td><td><strong>${esc(d.filename)}</strong><br><span class="muted">ページ：${esc(f.page_no??'不明')} ／ 基準日：${date(f.value_as_of_date)}</span><div class="evidence">${esc(f.source_text||'根拠テキストなし')}</div></td><td>${f.confidence===null||f.confidence===undefined?'不明':Math.round(f.confidence*100)+'%'}<br>${pill(f.needs_review?'要確認':'根拠あり',f.needs_review)}${f.approved?'<p class="muted">採用済み</p>':''}</td></tr>`).join('')}</tbody></table>${!rows.length?'<p class="empty">該当する項目はありません。</p>':''}</div></div>`;
}
function renderDiffs(c,p){p.innerHTML=`<h2>変更候補を確認</h2><p class="muted">採用するまで確定値は変更されません。保留した差分は、後から再確認できます。</p>${c.diffs.map(d=>`<div class="card"><div class="top"><div><h3>${esc(d.label)}</h3><code>${esc(d.code)}</code></div>${pill(({unreviewed:'未確認',reviewed:'保留',applied:'採用済み',ignored:'対象外'})[d.review_status]||d.review_status,d.review_status!=='applied')}</div><div class="diff-values"><div><span class="muted">旧</span><p>${esc(val(d.old_value))}</p></div><span>→</span><div class="new"><span class="muted">新</span><p>${esc(val(d.new_value))}</p></div></div><p class="muted">${esc(d.source||'根拠資料の確認が必要')}</p><div class="actions"><button class="primary" data-action="adopt" data-diff="${esc(d.id)}" ${!d.can_adopt||['applied','ignored'].includes(d.review_status)?'disabled':''}>採用</button><button data-action="hold" data-diff="${esc(d.id)}" ${['applied','ignored'].includes(d.review_status)?'disabled':''}>保留</button>${!d.can_adopt?'<span class="muted">根拠確認が必要なため採用できません</span>':''}</div></div>`).join('')}${!c.diffs.length?'<div class="card empty">差分はありません。</div>':''}`;}
function renderExcel(c,p){if(state.public_demo){p.innerHTML='<div class="card"><h2>契約書Excelを生成</h2><p>案件・資料・差分の確認をお試しいただけます。</p><button disabled>WEB版では準備中</button><p class="muted">公開デモでは契約書の生成・ダウンロードはできません。ローカル版のExcel生成機能は引き続き利用できます。</p></div>';return;}const r=results.get(c.id);p.innerHTML=`<div class="card"><h2>契約書Excelを生成</h2><p>既存の謄本マッピングと、重調の「物件名」「号室」を反映します。</p><p class="muted">重調の要確認・根拠不明・低confidenceの値は転記しません。元のひな形は変更しません。</p>${state.mode==='demo'?'<p class="pill warn">デモ出力です。実務利用前に内容を確認してください。</p>':''}<div class="actions"><button class="primary" data-action="generate">契約書Excelを生成</button></div>${r?`<div class="success"><strong>生成・再読込確認が完了しました</strong><p>重調の反映：${r.report_written}項目</p><a class="button primary" href="${esc(r.download)}" download>Excelをダウンロード</a><p class="muted">${esc(r.filename)}</p></div>${r.warnings.length?`<h3>出力の要確認事項</h3><ul>${r.warnings.map(w=>`<li>${esc(w)}</li>`).join('')}</ul>`:''}`:''}</div><div class="card"><h2>Excel未対応の項目</h2><p>管理費・修繕積立金・滞納・管理会社などは、現行ひな形の「基本入力」に対応欄がありません。</p><p class="muted">保存済みの値と根拠は「資料確認」で確認できます。</p><a href="${href(c.id,'documents')}">資料確認へ →</a></div>`;}
view.addEventListener('change',e=>{if(e.target.id==='document-filter')filters.document=e.target.value;if(e.target.id==='review-filter')filters.review=e.target.checked;render();});
view.addEventListener('click',async e=>{const b=e.target.closest('button[data-action]');if(!b)return;const action=b.dataset.action,cid=route().get('case');document.querySelector('#error').textContent='';
 if(action==='adopt'){pending={case_id:cid,diff_id:b.dataset.diff,action:'adopt'};const d=state.cases.find(c=>c.id===cid).diffs.find(d=>d.id===b.dataset.diff);document.querySelector('#confirm-text').textContent=d.label+'：'+val(d.old_value)+' → '+val(d.new_value);document.querySelector('#confirm').showModal();return;}
 b.disabled=true;const old=b.textContent;if(action==='generate')b.textContent='契約書作成中…';
 try{if(action==='generate')results.set(cid,await api('/api/generate',{case_id:cid}));else if(action==='hold')state=await api('/api/decision',{case_id:cid,diff_id:b.dataset.diff,action:'hold'});else if(action==='refresh')state=await api('/api/refresh',{});render();}catch(e){error(e);b.disabled=false;b.textContent=old;}
});
document.querySelector('#cancel').onclick=()=>document.querySelector('#confirm').close();
document.querySelector('#accept').onclick=async()=>{const b=document.querySelector('#accept');b.disabled=true;try{state=await api('/api/decision',pending);results.delete(pending.case_id);document.querySelector('#confirm').close();render();}catch(e){document.querySelector('#confirm').close();error(e)}finally{b.disabled=false}};
window.addEventListener('hashchange',()=>{document.querySelector('#error').textContent='';render()});
api('/api/state').then(d=>{state=d;csrf=d.csrf;render()}).catch(error);
