const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const dir=path.join(__dirname,'public-demo-dist');
const files=fs.readdirSync(dir).sort();
assert.deepEqual(files,['app.js','demo-contract.xlsx','index.html','style.css']);
for(const name of files.filter(name=>name.endsWith('.html')||name.endsWith('.css')||name.endsWith('.js'))){
 const source=fs.readFileSync(path.join(dir,name),'utf8');
 assert(!/SUPABASE_SERVICE_ROLE_KEY|sk-proj-|sb_secret_|[A-Z]:[\\/]|127\.0\.0\.1|localhost|\.env|NITOH|東京都|渋谷区/i.test(source),name);
 if(name.endsWith('.js'))new vm.Script(source);
}
const html=fs.readFileSync(path.join(dir,'index.html'),'utf8');
assert.match(html,/src="\/app\.js"/);
const js=fs.readFileSync(path.join(dir,'app.js'),'utf8');
assert.doesNotMatch(js,/fetch\s*\(|XMLHttpRequest|\/api\//);
assert.match(js,/契約書Excelを生成してダウンロード/);
assert.match(js,/scrollIntoView/);
console.log('PASS: four static assets, syntax/privacy audit, no API access, guided review and direct download.');
