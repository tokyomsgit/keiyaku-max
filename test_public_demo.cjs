const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const dir=path.join(__dirname,'public-demo-dist');
const files=fs.readdirSync(dir).sort();
assert.deepEqual(files,['app.js','demo.json','index.html','public-demo.js','style.css']);
for(const name of files){
 const source=fs.readFileSync(path.join(dir,name),'utf8');
 assert(!/SUPABASE_SERVICE_ROLE_KEY|sk-proj-|sb_secret_|[A-Z]:[\\/]|127\.0\.0\.1|localhost|\.env|NITOH|東京都|渋谷区/i.test(source),name);
 if(name.endsWith('.js'))new vm.Script(source);
}
const html=fs.readFileSync(path.join(dir,'index.html'),'utf8');
assert(html.indexOf('/public-demo.js')<html.indexOf('/app.js'));
let fetches=[];
function client(){
 const context={window:{},fetch:async url=>{fetches.push(url);assert.equal(url,'/demo.json');return {ok:true,json:async()=>JSON.parse(fs.readFileSync(path.join(dir,'demo.json'),'utf8'))};}};
 vm.runInNewContext(fs.readFileSync(path.join(dir,'public-demo.js'),'utf8'),context);return context.window.PublicDemo;
}
(async()=>{
 const api=client();let s=await api.request('/api/state');assert.equal(s.cases.length,1);assert.equal(s.cases[0].documents.length,2);
 assert.equal(s.cases[0].review_count,4);assert.equal(s.db_write_enabled,false);
 const before=s.cases[0].owner;
 s=await api.request('/api/decision',{case_id:'demo-case',diff_id:'demo-current_owner_name',action:'hold'});
 assert.equal(s.cases[0].owner,before);assert.equal(s.cases[0].diffs[1].review_status,'reviewed');
 s=await api.request('/api/decision',{case_id:'demo-case',diff_id:'demo-management_fee',action:'adopt'});
 assert.equal(s.cases[0].confirmed_values.management_fee,13500);assert.equal(s.cases[0].diff_count,0);
 assert.equal(s.cases[0].documents[1].fields.find(f=>f.code==='management_fee').value,12000);
 await assert.rejects(()=>api.request('/api/decision',{case_id:'demo-case',diff_id:'demo-management_fee',action:'adopt'}));
 await assert.rejects(()=>api.request('/api/generate',{case_id:'demo-case'}));
 assert.equal(fetches.length,1);
 assert.equal((await client().request('/api/state')).cases[0].diff_count,2);
 console.log('PASS: asset audit, syntax, case/documents, hold, explicit adopt, duplicate blocked, source preserved, Excel disabled, reload reset. Backend/AI/DB requests: 0.');
})();
