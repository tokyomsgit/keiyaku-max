const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const dir=path.join(__dirname,'public-demo-dist');
const files=fs.readdirSync(dir).sort();
assert.deepEqual(files,['app.js','auth.js','demo-contract.xlsx','index.html','style.css']);
for(const name of files.filter(name=>name.endsWith('.html')||name.endsWith('.css')||name.endsWith('.js'))){
 const source=fs.readFileSync(path.join(dir,name),'utf8');
 assert(!/SUPABASE_SERVICE_ROLE_KEY|sk-proj-|sb_secret_|(?:^|[\s"'(])[A-Z]:[\\/]|127\.0\.0\.1|localhost|\.env|NITOH|東京都|渋谷区/im.test(source),name);
 if(name.endsWith('.js'))new vm.Script(source);
}
const html=fs.readFileSync(path.join(dir,'index.html'),'utf8');
assert.match(html,/src="\/app\.js"/);
assert.match(html,/src="\/auth\.js"/);
const js=fs.readFileSync(path.join(dir,'app.js'),'utf8');
assert.doesNotMatch(js,/fetch\s*\(|XMLHttpRequest|\/api\//);
assert.match(js,/契約書Excelを生成してダウンロード/);
assert.match(js,/scrollIntoView/);
const auth=fs.readFileSync(path.join(dir,'auth.js'),'utf8');
assert.match(auth,/provider=google/);
assert.match(auth,/\/auth\/v1\/user/);
assert.doesNotMatch(auth,/service_role|sb_secret_/i);
console.log('PASS: five static assets, syntax/privacy audit, Google Auth gate, guided review and direct download.');
