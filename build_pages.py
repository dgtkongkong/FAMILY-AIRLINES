"""Build a static Pages portal and read-only preview; never package real data."""
from pathlib import Path
import json, tempfile, shutil
import server

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'docs'
OUT.mkdir(exist_ok=True)
PREVIEW = OUT / 'preview'
PREVIEW.mkdir(exist_ok=True)
for name in ['style.css', 'icon.svg']:
    shutil.copyfile(ROOT/'web'/name, PREVIEW/name)
index=(ROOT/'web/index.html').read_text('utf-8')
index=index.replace('href="/', 'href="./').replace('src="/', 'src="./')
index=index.replace('<link rel="manifest" href="./manifest.webmanifest">','')
(PREVIEW/'index.html').write_text(index,encoding='utf-8')
script=(ROOT/'web/app.js').read_text('utf-8')
start=script.index('async function api(')
end=script.index('async function refresh(',start)
script=script[:start]+'''let previewUser=null;
async function api(path,body){
 if(path==='login'){previewUser=body.user;return {message:'进入只读预览'}}
 if(path==='logout'){previewUser=null;S=null;renderLogin();return {}}
 if(path==='seen')return {};
 if(path==='state'){
  if(!previewUser){demo=false;renderLogin();throw Error('请选择预览身份')}
  const response=await fetch('./sample-'+(previewUser==='child'?'child':'parent')+'.json');
  if(!response.ok)throw Error('预览载入失败');const data=await response.json();if(previewUser==='mom'){data.user.id='mom';data.user.name='妈妈'}return data;
 }
 throw Error('只读预览不保存操作。正式打卡与审批请连接云端家庭塔台。');
}
'''+script[end:]
script=script.replace('src="/icon.svg"','src="./icon.svg"')
script=script.replace("if('serviceWorker'in navigator)navigator.serviceWorker.register('/sw.js').catch(()=>{});",'')
script=script.replace('体验环境 · 当前数据仅用于试运行。正式使用请创建独立家庭账号。','GitHub Pages 只读预览 · 无真实家庭数据，不保存提交或审批。')
script += '''
const realRenderLogin=renderLogin;
renderLogin=function(){realRenderLogin();
 document.querySelector('.login-form h2').textContent='浏览应用预览';
 document.querySelector('.login-form .muted').textContent='选择身份查看界面，无需输入真实密码。正式服务尚待部署。';
 const password=document.querySelector('input[name="password"]');password.value='previewonly';password.closest('label').remove();
 document.querySelector('#login button').textContent='进入只读预览 →';
};
const realBind=bind;
bind=function(){realBind();
 document.querySelectorAll('[data-export-kind]').forEach(f=>f.onsubmit=e=>{e.preventDefault();toast('只读预览不导出账本，请在正式家庭塔台使用。')});
};
renderLogin();
'''
(PREVIEW/'app.js').write_text(script,encoding='utf-8')
(ROOT/'.test-work').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=ROOT/'.test-work') as folder:
    server.DB=Path(folder)/'synthetic.sqlite3'
    server.DEMO=True
    server.init_db({'child':'previewonly','dad':'previewonly','mom':'previewonly'})
    with server.transaction() as connection:
        server.schedule_reports(connection)
        for label,uid in [('child','child'),('parent','dad')]:
            user=connection.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone()
            data=server.state(connection,user)
            data['audit']=[]
            (PREVIEW/f'sample-{label}.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
print('Pages build complete: docs/; fresh synthetic data only.')
