"""ACE Captain: Python 3.10+ / SQLite; no third-party runtime dependencies."""
import argparse, contextlib, datetime as dt, hashlib, hmac, json, mimetypes, os
import secrets, sqlite3, threading, time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from http.cookies import SimpleCookie
from urllib.parse import urlparse, parse_qs
from excel_export import workbook

ROOT = Path(__file__).resolve().parent
RULES = json.loads((ROOT / 'rules.json').read_text(encoding='utf-8'))
TASKS = {x['id']: x for x in RULES['tasks']}
SHOP = {x['id']: x for x in RULES['shop']}
HONORS = {x['id']: x for x in RULES['honors']}
TZ = dt.timezone(dt.timedelta(hours=8))
DB = ROOT / 'data' / 'captain.sqlite3'
DEMO = False
LOGIN_FAILURES = {}
LOGIN_LOCK = threading.Lock()

def now(): return dt.datetime.now(TZ)
def stamp(): return now().isoformat(timespec='seconds')
def week(d): return d - dt.timedelta(days=d.weekday())
def month_before(d): return (d.replace(day=1)-dt.timedelta(days=1)).replace(day=1)
def keydate(d): return d.isoformat()
def encode(v): return json.dumps(v, ensure_ascii=False, separators=(',', ':'))
def rows(c, q, p=()): return [dict(r) for r in c.execute(q,p)]
def require(ok, message):
    if not ok: raise ValueError(message)

@contextlib.contextmanager
def transaction():
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('BEGIN IMMEDIATE')
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally: c.close()

def hash_password(password, salt):
    return hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),260000).hex()

def init_db(passwords=None):
    DB.parent.mkdir(parents=True, exist_ok=True)
    with transaction() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,name TEXT NOT NULL,role TEXT NOT NULL,salt TEXT NOT NULL,hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user TEXT REFERENCES users(id),expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,kind TEXT NOT NULL,item TEXT NOT NULL,subitem INTEGER NOT NULL DEFAULT -1,period TEXT NOT NULL,day TEXT NOT NULL,choices TEXT NOT NULL,note TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',created TEXT NOT NULL,reviewer TEXT,reviewed TEXT,reason TEXT,miles INTEGER NOT NULL,cash INTEGER NOT NULL DEFAULT 0,fund INTEGER NOT NULL DEFAULT 0,title TEXT NOT NULL,rule_version TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY,source TEXT UNIQUE NOT NULL,created TEXT NOT NULL,miles INTEGER NOT NULL,cash INTEGER NOT NULL DEFAULT 0,fund INTEGER NOT NULL DEFAULT 0,module TEXT NOT NULL,title TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS goals(week TEXT PRIMARY KEY,target INTEGER NOT NULL CHECK(target>=120),created TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS awards(id TEXT PRIMARY KEY,created TEXT NOT NULL,title TEXT NOT NULL,reward TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'unlocked',seen INTEGER NOT NULL DEFAULT 0,reviewer TEXT,fulfilled TEXT);
        CREATE TABLE IF NOT EXISTS reports(id TEXT PRIMARY KEY,kind TEXT NOT NULL,start TEXT NOT NULL,end TEXT NOT NULL,created TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,created TEXT NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,detail TEXT NOT NULL);
        ''')
        c.execute('CREATE TABLE IF NOT EXISTS medals(id TEXT PRIMARY KEY,kind TEXT NOT NULL,year INTEGER NOT NULL,model TEXT NOT NULL,title TEXT NOT NULL,achieved TEXT NOT NULL,claimed TEXT,cash INTEGER NOT NULL DEFAULT 0,fund INTEGER NOT NULL DEFAULT 0,reward TEXT NOT NULL)')
        if 'subitem' not in [r[1] for r in c.execute('PRAGMA table_info(requests)')]:
            c.execute('ALTER TABLE requests ADD COLUMN subitem INTEGER NOT NULL DEFAULT -1')
        c.execute('DROP INDEX IF EXISTS one_task')
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_subtask ON requests(kind,item,subitem,period) WHERE status IN ('pending','approved') AND kind IN ('task','honor')")
        c.execute("INSERT OR IGNORE INTO settings VALUES ('started',?)", (keydate(now().date()),))
        if not c.execute('SELECT 1 FROM users').fetchone():
            require(passwords is not None,'首次运行需要设置账号密码。请运行 python server.py --setup')
            for uid,name,role in [('child','胡庭溢','child'),('dad','爸爸','parent'),('mom','妈妈','parent')]:
                password = passwords[uid]
                require(len(password)>=8,'密码至少 8 位')
                salt=secrets.token_hex(16)
                c.execute('INSERT INTO users VALUES (?,?,?,?,?)',(uid,name,role,salt,hash_password(password,salt)))

def audit(c,actor,action,detail):
    c.execute('INSERT INTO audit(created,actor,action,detail) VALUES (?,?,?,?)',(stamp(),actor,action,encode(detail)))

def family_rules(c):
    result=json.loads(encode(RULES))
    for kind in ('tasks','shop','annual'):
        row=c.execute('SELECT value FROM settings WHERE key=?',('custom:'+kind,)).fetchone()
        if row: result[kind].extend(json.loads(row[0]))
    result['annual'].sort(key=lambda a:a['threshold'])
    return result

def publish_item(c,u,b):
    require(u['role']=='parent','仅父母可发布家庭规则')
    kind=b.get('kind');require(kind in ('tasks','shop','annual'),'请选择有效类型')
    def text_field(key,limit):
        value=b.get(key)
        require(isinstance(value,str) and 1<=len(value.strip())<=limit,'请填写有效的 '+key)
        return value.strip()
    def integer(key,minimum=1,maximum=1000000):
        value=b.get(key);require(type(value) is int and minimum<=value<=maximum,'请填写有效整数 '+key)
        return value
    item={'id':'custom-'+secrets.token_hex(12),'name':text_field('name',60)}
    if kind=='tasks':
        module=text_field('module',30)
        require(module in ('地面保障（生活）','核心巡航（学习）','平稳飞行（情绪）','机场勋章（德行）'),'模块无效')
        options=b.get('options')
        require(isinstance(options,list) and 1<=len(options)<=30,'请填写 1 至 30 个子项')
        require(all(isinstance(v,str) and 1<=len(v.strip())<=200 for v in options),'每个子项须为 1 至 200 字')
        options=[v.strip() for v in options];require(len(set(options))==len(options),'子项不能重复')
        frequency=b.get('frequency');require(frequency in ('day','week','weekend','event'),'任务频率无效')
        item.update(module=module,options=options,frequency=frequency,miles=integer('miles',1,10000))
    elif kind=='shop':
        item.update(cost=integer('cost'),description=text_field('description',500),cash=0)
    else:
        threshold=integer('threshold')
        require(all(a['threshold']!=threshold for a in family_rules(c)['annual']),'该里程目标已存在')
        aircraft=text_field('aircraft',40)
        require(aircraft in ('Airbus A220-300','Airbus A319neo','Airbus A320neo','Airbus A321neo','Boeing 737-800','Boeing 737 MAX 8','Embraer E195-E2','COMAC C919'),'请选择有效飞机型号')
        item.update(threshold=threshold,reward=text_field('reward',500),aircraft=aircraft)
    key='custom:'+kind
    row=c.execute('SELECT value FROM settings WHERE key=?',(key,)).fetchone()
    items=json.loads(row[0]) if row else []
    require(len(items)<200,'此类型自定义项目已达到 200 项上限')
    items.append(item)
    c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)',(key,encode(items)))
    audit(c,u['id'],'publish',{'kind':kind,'item':item})
    trigger_awards(c);sync_medals(c)
    return {'message':'已发布，家庭成员刷新后即可看到','id':item['id']}

RESET_TABLES=('requests','ledger','goals','awards','medals','reports','audit')

def reset_prepare(c,u,b):
    require(u['id']=='dad','仅爸爸可将账本归零')
    require(b.get('confirm') is True,'请完成第一次确认')
    token=secrets.token_urlsafe(32)
    data={'hash':hashlib.sha256(token.encode()).hexdigest(),'expires':time.time()+120,
          'revision':c.execute('SELECT COALESCE(MAX(id),0) FROM audit').fetchone()[0]}
    c.execute("INSERT OR REPLACE INTO settings VALUES ('reset_challenge',?)",(encode(data),))
    return {'token':token,'message':'第一次确认完成，请在两分钟内输入确认文字'}

def reset_all(c,u,b):
    require(u['id']=='dad','仅爸爸可将账本归零')
    row=c.execute("SELECT value FROM settings WHERE key='reset_challenge'").fetchone()
    require(row is not None,'请先完成第一次确认')
    data=json.loads(row[0])
    require(data['expires']>=time.time(),'确认已过期，请重新开始')
    require(hmac.compare_digest(data['hash'],hashlib.sha256(str(b.get('token','')).encode()).hexdigest()),'确认凭据无效')
    require(b.get('confirmation')=='确认全部归零','请准确输入：确认全部归零')
    require(data['revision']==c.execute('SELECT COALESCE(MAX(id),0) FROM audit').fetchone()[0],'确认期间账本发生变化，请重新核对后归零')
    # Read from a separate connection: captures the committed database before deletion.
    backup_dir=DB.parent/'reset-backups';backup_dir.mkdir(mode=0o700,exist_ok=True)
    backup=backup_dir/('before-reset-'+secrets.token_hex(16)+'.sqlite3')
    fd=os.open(backup,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
    with contextlib.closing(sqlite3.connect(DB)) as source, contextlib.closing(sqlite3.connect(backup)) as destination:
        source.backup(destination)
        require(destination.execute('PRAGMA integrity_check').fetchone()[0]=='ok','备份校验失败，已取消归零')
    counts={table:c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in RESET_TABLES}
    for table in RESET_TABLES: c.execute('DELETE FROM '+table)
    c.execute("DELETE FROM settings WHERE key='reset_challenge'")
    c.execute("INSERT OR REPLACE INTO settings VALUES ('started',?)",(keydate(now().date()),))
    c.execute("INSERT OR REPLACE INTO settings VALUES ('reset_date',?)",(keydate(now().date()),))
    c.execute("DELETE FROM sessions WHERE user!='dad'")
    audit(c,u['id'],'reset-all',{'counts':counts,'backup':backup.name})
    return {'message':'所有成长账本已归零；账号、家庭配置及归零前备份已保留'}

def total(c,start,end):
    return c.execute('SELECT COALESCE(SUM(miles),0) FROM ledger WHERE miles>0 AND substr(created,1,10)>=? AND substr(created,1,10)<?',(keydate(start),keydate(end))).fetchone()[0]

def balance(c):
    return c.execute('SELECT COALESCE(SUM(miles),0) FROM ledger').fetchone()[0]

def reserved(c):
    return c.execute("SELECT COALESCE(SUM(miles),0) FROM requests WHERE kind='redeem' AND status='pending'").fetchone()[0]

def trigger_awards(c):
    today=now().date(); start=week(today)
    goal=c.execute('SELECT target FROM goals WHERE week=?',(keydate(start),)).fetchone()
    if goal and total(c,start,start+dt.timedelta(days=7))>=goal[0]:
        c.execute('INSERT OR IGNORE INTO awards(id,created,title,reward) VALUES (?,?,?,?)',('week:'+keydate(start),stamp(),'周目标达成 · 惊喜航班',secrets.choice(RULES['weekly_surprises'])))
    annual=total(c,dt.date(today.year,1,1),dt.date(today.year+1,1,1))
    for stage in family_rules(c)['annual']:
        if annual>=stage['threshold']:
            c.execute('INSERT OR IGNORE INTO awards(id,created,title,reward) VALUES (?,?,?,?)',(f"annual:{today.year}:{stage['threshold']}",stamp(),stage['name'],stage['reward']))

def submit_tasks(c,u,b):
    require(u['role']=='child','仅机长可提交打卡')
    tasks={x['id']:x for x in family_rules(c)['tasks']}
    items=b.get('items',[]); require(isinstance(items,list) and 1<=len(items)<=len(tasks),'请选择有效任务')
    day=dt.date.fromisoformat(b.get('day',''))
    require(now().date()-dt.timedelta(days=6)<=day<=now().date(),'仅允许提交今天及前 6 天的记录')
    ids=[]
    for item in items:
        t=tasks.get(item.get('id')); require(t is not None,'任务不存在')
        choices=item.get('choices',[])
        require(isinstance(choices,list) and choices and all(type(i) is int and 0<=i<len(t['options']) for i in choices),'请选择有效达标标准')
        require(len(choices)==len(set(choices)),'标准不能重复')
        if t['frequency']=='week': require(day.weekday()>=4,'周全勤仅周五至周日提交')
        if t['frequency']=='weekend': require(day.weekday()>=5,'家庭分享仅周末提交')
        period=keydate(day if t['frequency'] in ('day','event') else week(day))
        if t['frequency']=='event': require(len(str(b.get('note','')).strip())>=5,'荣誉奖励请填写至少 5 个字的具体测验、评奖或赛事说明')
        for choice in choices:
            rid=secrets.token_hex(12)
            try:
                c.execute('INSERT INTO requests(id,kind,item,subitem,period,day,choices,note,created,miles,title,rule_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(rid,'task',t['id'],choice,period,keydate(day),encode([t['options'][choice]]),str(b.get('note',''))[:500],stamp(),t['miles'],t['name'],RULES['version']))
            except sqlite3.IntegrityError: raise ValueError(t['name']+' 的所选子项已提交或已通过；未通过的可重新申请')
            ids.append(rid)
    audit(c,u['id'],'submit',ids)
    return {'message':f'已提交 {len(ids)} 个子项，等待塔台逐项审批'}

def submit_redeem(c,u,b):
    require(u['role']=='child','仅机长可申请兑换')
    s={x['id']:x for x in family_rules(c)['shop']}.get(b.get('id')); require(s is not None,'权益不存在')
    require(balance(c)-reserved(c)>=s['cost'],'可申请里程不足（含待审批预留）')
    start=keydate(week(now().date()))
    if s['cash']:
        used=c.execute("SELECT COALESCE(SUM(cash),0) FROM requests WHERE kind='redeem' AND item='cash' AND period=? AND status IN ('pending','approved')",(start,)).fetchone()[0]
        require(used+s['cash']<=1500,'每周现金兑换上限 15 元，含待审批申请')
    rid=secrets.token_hex(12)
    c.execute('INSERT INTO requests(id,kind,item,period,day,choices,note,created,miles,cash,title,rule_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(rid,'redeem',s['id'],start,keydate(now().date()),'[]','',stamp(),s['cost'],s['cash'],s['name'],RULES['version']))
    audit(c,u['id'],'redeem-request',rid)
    return {'message':'兑换申请已提交；塔台确认后扣除里程'}

def submit_honor(c,u,b):
    require(u['role']=='child','仅机长可申请荣誉')
    h=HONORS.get(b.get('id')); require(h is not None,'荣誉不存在')
    require(not h.get('days'),'连续荣誉由系统自动统计，请在荣誉机库领取飞机')
    note=str(b.get('note','')).strip(); require(5<=len(note)<=500,'请填写至少 5 个字的达标记录及日期，供父母核实')
    rid=secrets.token_hex(12)
    try:
        c.execute('INSERT INTO requests(id,kind,item,period,day,choices,note,created,miles,cash,fund,title,rule_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(rid,'honor',h['id'],str(now().year),keydate(now().date()),encode([h['condition']]),note,stamp(),0,h['cash'],h['fund'],h['name'],RULES['version']))
    except sqlite3.IntegrityError: raise ValueError('本年度已申请或领取此荣誉')
    audit(c,u['id'],'honor-request',rid)
    return {'message':'荣誉申请已发送，请父母核实条件'}

def review(c,u,b):
    require(u['role']=='parent','只有爸爸或妈妈可以审批')
    r=c.execute('SELECT * FROM requests WHERE id=?',(b.get('id'),)).fetchone()
    require(r is not None,'申请不存在'); require(r['status']=='pending','此申请已处理，请刷新')
    approve=b.get('approve'); require(type(approve) is bool,'请选择通过或不通过')
    reason=str(b.get('reason','')).strip()[:500]
    require(approve or bool(reason),'请填写不通过原因，帮助机长调整')
    if approve and r['kind']=='honor' and HONORS[r['item']].get('days'):
        require(False,'该连续荣誉现已改为系统统计，请退回旧申请，在机库自动领取')
    if approve and r['kind']=='redeem': require(balance(c)>=r['miles'],'余额不足')
    c.execute('UPDATE requests SET status=?,reviewer=?,reviewed=?,reason=? WHERE id=?',('approved' if approve else 'rejected',u['name'],stamp(),reason,r['id']))
    if approve:
        module=next(t['module'] for t in family_rules(c)['tasks'] if t['id']==r['item']) if r['kind']=='task' else ('权益兑换' if r['kind']=='redeem' else '公约荣誉')
        miles=-r['miles'] if r['kind']=='redeem' else r['miles']
        c.execute('INSERT INTO ledger(source,created,miles,cash,fund,module,title) VALUES (?,?,?,?,?,?,?)',(r['id'],stamp(),miles,r['cash'],r['fund'],module,r['title']))
        if r['kind'] in ('redeem','honor'):
            reward=next(t['description'] for t in family_rules(c)['shop'] if t['id']==r['item']) if r['kind']=='redeem' else HONORS[r['item']]['reward']
            c.execute('INSERT INTO awards(id,created,title,reward) VALUES (?,?,?,?)',('request:'+r['id'],stamp(),r['title'],reward))
        trigger_awards(c)
    sync_medals(c)
    audit(c,u['id'],'approve' if approve else 'reject',{'id':r['id'],'reason':reason})
    return {'message':'已通过，账本已更新' if approve else '已退回，机长可以完善后重新提交'}

def set_goal(c,u,b):
    require(u['role']=='child','由机长设定周计划')
    target=b.get('target'); require(type(target) is int and target>=120 and target<=9007199254740991,'目标须为不低于 120 的整数')
    start=keydate(week(now().date()))
    require(not c.execute('SELECT 1 FROM goals WHERE week=?',(start,)).fetchone(),'本周目标已起飞，不可降低或重复设定')
    c.execute('INSERT INTO goals VALUES (?,?,?)',(start,target,stamp()))
    audit(c,u['id'],'goal',target); trigger_awards(c)
    return {'message':'周计划已起飞，达标将解锁一次随机奖励'}

def fulfill(c,u,b):
    require(u['role']=='parent','只有父母可以确认兑现')
    a=c.execute('SELECT * FROM awards WHERE id=?',(b.get('id'),)).fetchone()
    require(a is not None and a['status']=='unlocked','奖励不存在或已兑现')
    c.execute("UPDATE awards SET status='fulfilled',reviewer=?,fulfilled=? WHERE id=?",(u['name'],stamp(),a['id']))
    if a['id'].startswith('request:'):
        r=c.execute('SELECT * FROM requests WHERE id=?',(a['id'][8:],)).fetchone()
        if r['cash'] or r['fund']:
            c.execute('INSERT INTO ledger(source,created,miles,cash,fund,module,title) VALUES (?,?,?,?,?,?,?)',('paid:'+r['id'],stamp(),0,-r['cash'],-r['fund'],'兑现支出',r['title']))
    elif a['id'].startswith('streak:'):
        m=c.execute('SELECT * FROM medals WHERE id=?',(a['id'],)).fetchone()
        if m and (m['cash'] or m['fund']):
            c.execute('INSERT INTO ledger(source,created,miles,cash,fund,module,title) VALUES (?,?,?,?,?,?,?)',('paid:'+m['id'],stamp(),0,-m['cash'],-m['fund'],'兑现支出',m['title']))
    audit(c,u['id'],'fulfill',a['id'])
    return {'message':'已记录实际兑现；现金或基金待兑现余额已更新'}

def cancel(c,u,b):
    require(u['role']=='child','只有机长可以撤回自己的申请')
    r=c.execute('SELECT * FROM requests WHERE id=?',(b.get('id'),)).fetchone()
    require(r is not None and r['status']=='pending','仅可撤回尚未审批的申请')
    c.execute("UPDATE requests SET status='cancelled',reviewed=?,reason='机长主动撤回' WHERE id=?",(stamp(),r['id']))
    audit(c,u['id'],'cancel',r['id'])
    return {'message':'申请已撤回；如有预留里程，已释放'}

def report_data(c,start,end):
    a,b=keydate(start),keydate(end)
    incoming=total(c,start,end)
    spent=-c.execute('SELECT COALESCE(SUM(miles),0) FROM ledger WHERE miles<0 AND substr(created,1,10)>=? AND substr(created,1,10)<?',(a,b)).fetchone()[0]
    modules=rows(c,'SELECT module,SUM(miles) value FROM ledger WHERE miles>0 AND substr(created,1,10)>=? AND substr(created,1,10)<? GROUP BY module',(a,b))
    merged={}
    for row in modules:
        module=MODULE_NAMES.get(row['module'],row['module']);merged[module]=merged.get(module,0)+row['value']
    modules=[{'module':k,'value':v} for k,v in merged.items()]
    approved=c.execute("SELECT COUNT(*) FROM requests WHERE kind='task' AND status='approved' AND substr(reviewed,1,10)>=? AND substr(reviewed,1,10)<?",(a,b)).fetchone()[0]
    rejected=c.execute("SELECT COUNT(*) FROM requests WHERE kind='task' AND status='rejected' AND substr(reviewed,1,10)>=? AND substr(reviewed,1,10)<?",(a,b)).fetchone()[0]
    money=dict(c.execute('SELECT COALESCE(SUM(CASE WHEN cash>0 THEN cash ELSE 0 END),0) cash_earned,COALESCE(-SUM(CASE WHEN cash<0 THEN cash ELSE 0 END),0) cash_paid,COALESCE(SUM(CASE WHEN fund>0 THEN fund ELSE 0 END),0) fund_earned,COALESCE(-SUM(CASE WHEN fund<0 THEN fund ELSE 0 END),0) fund_paid FROM ledger WHERE substr(created,1,10)>=? AND substr(created,1,10)<?',(a,b)).fetchone())
    advice = '本期还没有审批入账记录。先选择一个能完成的小任务，再请塔台确认。'
    if incoming:
        top=max(modules,key=lambda x:x['value'])['module']
        advice=f'本期完成 {approved} 项审批入账，获得 {incoming} 里程；{top}贡献最多。建议下周保持有效习惯，选一个记录较少的模块尝试一次。'
        if rejected: advice+=f' 有 {rejected} 项未通过，请对照审批意见补充达标证据。'
    return {'income':incoming,'spent':spent,'net':incoming-spent,'modules':modules,'approved':approved,'rejected':rejected,'money':money,'advice':advice,'basis':'北京时间，按审批入账时间统计；记录少不等于能力弱，尚未审批不计入。'}

def schedule_reports(c,at=None):
    at=at or now()
    start=dt.date.fromisoformat(c.execute("SELECT value FROM settings WHERE key='started'").fetchone()[0])
    day=start
    while day<=at.date():
        if day.weekday()==4 and (day<at.date() or at.hour>=18):
            end=week(day); begin=end-dt.timedelta(days=7)
            save_report(c,'week',begin,end)
        if day.day==1:
            save_report(c,'month',month_before(day),day)
        day+=dt.timedelta(days=1)

def save_report(c,kind,start,end):
    reset=c.execute("SELECT value FROM settings WHERE key='reset_date'").fetchone()
    if reset and keydate(end)<=reset[0]: return
    rid=kind+':'+keydate(start)
    if not c.execute('SELECT 1 FROM reports WHERE id=?',(rid,)).fetchone():
        c.execute('INSERT INTO reports VALUES (?,?,?,?,?,?)',(rid,kind,keydate(start),keydate(end),stamp(),encode(report_data(c,start,end))))

def state(c,u):
    sync_medals(c)
    today=now().date(); tomorrow=today+dt.timedelta(days=1); start=week(today)
    cash=dict(c.execute('SELECT COALESCE(SUM(cash),0) cash_due,COALESCE(SUM(fund),0) fund_due,COALESCE(SUM(CASE WHEN cash>0 THEN cash ELSE 0 END),0) cash_earned,COALESCE(SUM(CASE WHEN fund>0 THEN fund ELSE 0 END),0) fund_earned,COALESCE(-SUM(CASE WHEN cash<0 THEN cash ELSE 0 END),0) cash_paid,COALESCE(-SUM(CASE WHEN fund<0 THEN fund ELSE 0 END),0) fund_paid FROM ledger').fetchone())
    goal=c.execute('SELECT target FROM goals WHERE week=?',(keydate(start),)).fetchone()
    annual=total(c,dt.date(today.year,1,1),dt.date(today.year+1,1,1))
    rules=family_rules(c)
    if u['role']=='child':
        rules['weekly_surprises']=[]
        for stage in rules['annual']:
            if annual<stage['threshold']: stage['reward']='到达后揭晓的隐藏奖励'
    return {'user':{'id':u['id'],'name':u['name'],'role':u['role']},'demo':DEMO,'today':keydate(today),'min_task_date':keydate(today-dt.timedelta(days=6)),'streak':streak_info(c),'medals':rows(c,'SELECT * FROM medals ORDER BY achieved DESC,id'),'rules':rules,'balance':balance(c),'reserved':reserved(c),'stats':{'day':total(c,today,tomorrow),'week':total(c,start,start+dt.timedelta(days=7)),'month':total(c,today.replace(day=1),tomorrow),'year':annual},'money':cash,'goal':goal[0] if goal else None,'requests':rows(c,"SELECT * FROM requests WHERE status='pending' OR rowid IN (SELECT rowid FROM requests ORDER BY created DESC,rowid DESC LIMIT 300) ORDER BY created DESC,rowid DESC"),'awards':rows(c,'SELECT * FROM awards ORDER BY created DESC'),'ledger':rows(c,'SELECT * FROM ledger ORDER BY id DESC LIMIT 200'),'reports':rows(c,'SELECT * FROM reports ORDER BY end DESC,kind'),'current_report':report_data(c,today.replace(day=1),tomorrow),'audit':rows(c,'SELECT * FROM audit ORDER BY id DESC LIMIT 100') if u['role']=='parent' else []}

MODULE_NAMES={'地面保障':'地面保障（生活）','核心巡航':'核心巡航（学习）','平稳飞行':'平稳飞行（情绪）','机长勋章':'机场勋章（德行）'}

def streak_info(c):
    days=[dt.date.fromisoformat(r[0]) for r in c.execute("SELECT DISTINCT day FROM requests WHERE kind='task' AND status='approved' ORDER BY day")]
    run=best=0;prev=None;achievements={}
    for day in days:
        run=run+1 if prev and day==prev+dt.timedelta(days=1) else 1
        best=max(best,run);prev=day
        for h in RULES['honors']:
            if h.get('days') and run>=h['days']:
                achievements.setdefault(f"streak:{day.year}:{h['id']}",{'day':keydate(day),'year':day.year,'honor':h})
    current=run if prev and prev>=now().date()-dt.timedelta(days=1) else 0
    return {'current':current,'best':best,'valid_days':len(days),'achievements':achievements}

def sync_medals(c):
    info=streak_info(c)
    for mid,a in info['achievements'].items():
        h=a['honor']
        c.execute('INSERT OR IGNORE INTO medals(id,kind,year,model,title,achieved,cash,fund,reward) VALUES (?,?,?,?,?,?,?,?,?)',(mid,'honor',a['year'],h['aircraft'],h['name'],a['day'],h['cash'],h['fund'],h['reward']))
    for row in c.execute("SELECT id,created,title,reward FROM awards WHERE id LIKE 'annual:%'").fetchall():
        _,year,threshold=row['id'].split(':');stage=next((a for a in family_rules(c)['annual'] if a['threshold']==int(threshold)),None)
        if stage:c.execute('INSERT OR IGNORE INTO medals(id,kind,year,model,title,achieved,claimed,reward) VALUES (?,?,?,?,?,?,?,?)',(row['id'],'mileage',int(year),stage['aircraft'],row['title'],row['created'][:10],row['created'],row['reward']))

def claim_plane(c,u,b):
    require(u['role']=='child','由机长领取飞机');sync_medals(c)
    m=c.execute('SELECT * FROM medals WHERE id=?',(b.get('id'),)).fetchone()
    require(m is not None and m['kind']=='honor','尚未达标，暂不能领取')
    require(not m['claimed'],'这枚飞机已领取')
    c.execute('UPDATE medals SET claimed=? WHERE id=?',(stamp(),m['id']))
    hid=m['id'].split(':')[-1]
    legacy=c.execute("SELECT 1 FROM requests WHERE kind='honor' AND item=? AND period=? AND status='approved'",(hid,str(m['year']))).fetchone()
    if not legacy:
        c.execute('INSERT INTO ledger(source,created,miles,cash,fund,module,title) VALUES (?,?,?,?,?,?,?)',(m['id'],stamp(),0,m['cash'],m['fund'],'公约荣誉',m['title']))
        c.execute('INSERT INTO awards(id,created,title,reward) VALUES (?,?,?,?)',(m['id'],stamp(),m['title'],m['reward']))
    audit(c,u['id'],'claim-plane',m['id'])
    return {'message':'飞机已收入机库！荣誉奖励已记入待兑现账本。'}

def review_batch(c,u,b):
    require(u['role']=='parent','仅父母可批量审批')
    ids=b.get('ids');require(isinstance(ids,list) and 1<=len(ids)<=200 and all(isinstance(x,str) for x in ids),'请选择 1–200 个申请')
    require(len(ids)==len(set(ids)),'不能重复选择申请')
    for rid in ids:
        row=c.execute('SELECT status FROM requests WHERE id=?',(rid,)).fetchone()
        require(row is not None and row['status']=='pending','有申请已被处理，请刷新后重新选择；本批次未入账')
    for rid in ids:review(c,u,{'id':rid,'approve':b.get('approve'),'reason':b.get('reason','')})
    return {'message':f"已批量{'通过' if b.get('approve') else '退回'} {len(ids)} 项"}

def export_excel(c,kind,start,end):
    try:a=dt.date.fromisoformat(start);b=dt.date.fromisoformat(end)
    except (ValueError,TypeError):raise ValueError('请选择有效起始日期和截止日期')
    require(a<=b,'起始日期不能晚于截止日期');require(kind in ('ledger','reports'),'导出类型无效')
    if kind=='ledger':
        records=rows(c,'SELECT l.*,r.day,r.choices,r.reviewer FROM ledger l LEFT JOIN requests r ON r.id=l.source WHERE substr(l.created,1,10)>=? AND substr(l.created,1,10)<=? ORDER BY l.created,l.id',(start,end))
        data=[[r['id'],dt.date.fromisoformat(r['created'][:10]),r['created'][11:19],r['day'] or '',MODULE_NAMES.get(r['module'],r['module']),r['title'],' / '.join(json.loads(r['choices'] or '[]')),r['miles'],r['cash']/100,r['fund']/100,r['reviewer'] or '',r['source']] for r in records]
        return workbook([('里程账本',['流水号','入账日期（北京时间）','入账时间','任务完成日期','模块','项目','达标子项','里程变动','现金变动（元）','基金变动（元）','审批人','来源编号'],data)])
    sheets=[]
    for report_kind,title in [('week','周报统计账本'),('month','月报统计账本')]:
        data=[]
        for r in rows(c,'SELECT * FROM reports WHERE kind=? AND start<=? AND end>? ORDER BY start',(report_kind,end,start)):
            p=json.loads(r['payload']);money=p['money'];modules={}
            for m in p['modules']:
                key=MODULE_NAMES.get(m['module'],m['module']);modules[key]=modules.get(key,0)+m['value']
            data.append([r['id'],dt.date.fromisoformat(r['start']),dt.date.fromisoformat(r['end'])-dt.timedelta(days=1),r['created'],p['income'],p['spent'],p['net'],p['approved'],p['rejected'],money['cash_earned']/100,money['cash_paid']/100,money['fund_earned']/100,money['fund_paid']/100,*[modules.get(v,0) for v in MODULE_NAMES.values()],p['advice'],'与筛选区间相交的完整周期快照；不按天切分，不合并周/月重复计数'])
        sheets.append((title,['报告编号','周期开始','周期截止（含）','生成时间','获得里程','兑换里程','净增加','通过子项','退回子项','现金获得（元）','现金兑现（元）','基金获得（元）','基金兑现（元）',*MODULE_NAMES.values(),'客观分析建议','统计口径'],data))
    return workbook(sheets)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def reply(self,status,payload,cookie=None):
        body=encode(payload).encode(); self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Cache-Control','no-store'); self.send_header('X-Content-Type-Options','nosniff')
        if cookie: self.send_header('Set-Cookie',cookie)
        self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
    def current_user(self,c):
        cookie=SimpleCookie(self.headers.get('Cookie','')); token=cookie.get('captain')
        if not token: return None
        digest=hashlib.sha256(token.value.encode()).hexdigest()
        return c.execute('SELECT users.* FROM sessions JOIN users ON users.id=sessions.user WHERE token=? AND expires>?',(digest,time.time())).fetchone()
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/api/state':
            with transaction() as c:
                u=self.current_user(c)
                if not u: return self.reply(401,{'error':'请先登录','demo':DEMO})
                return self.reply(200,state(c,u))
        if path=='/api/export.xlsx':
            try:
                with transaction() as c:
                    u=self.current_user(c)
                    if not u or u['role']!='parent': return self.reply(403,{'error':'仅父母可导出'})
                    q=parse_qs(urlparse(self.path).query)
                    data=export_excel(c,q.get('kind',['ledger'])[0],q.get('start',[''])[0],q.get('end',[''])[0])
                self.send_response(200)
                self.send_header('Content-Type','application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
                self.send_header('Content-Disposition','attachment; filename="captain-export.xlsx"')
                self.send_header('Cache-Control','no-store')
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            except ValueError as e:self.reply(400,{'error':str(e)})
            return
        if path=='/api/export':
            with transaction() as c:
                u=self.current_user(c)
                if not u or u['role']!='parent': return self.reply(403,{'error':'仅父母可导出'})
                return self.reply(200,{t:rows(c,'SELECT * FROM '+t) for t in ['requests','ledger','goals','awards','reports','audit','medals']})
        files={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/icon.svg':'icon.svg','/manifest.webmanifest':'manifest.webmanifest','/sw.js':'sw.js'}
        if path not in files: return self.reply(404,{'error':'不存在'})
        p=ROOT/'web'/files[path]; data=p.read_bytes(); self.send_response(200)
        self.send_header('Content-Type',(mimetypes.guess_type(str(p))[0] or 'text/plain')+'; charset=utf-8')
        self.send_header('Cache-Control','no-cache'); self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")
        self.send_header('Content-Length',str(len(data))); self.end_headers(); self.wfile.write(data)
    def do_POST(self):
        try:
            require(self.headers.get('X-Captain-Client')=='1','无效客户端请求')
            origin=self.headers.get('Origin')
            require(not origin or urlparse(origin).netloc==self.headers.get('Host'),'来源不匹配')
            length=int(self.headers.get('Content-Length',0)); require(0<length<=20000,'请求大小不合法')
            b=json.loads(self.rfile.read(length)); require(isinstance(b,dict),'请求格式不合法')
            path=urlparse(self.path).path
            with transaction() as c:
                if path=='/api/login':
                    ip=self.client_address[0]
                    with LOGIN_LOCK:
                        attempts=[t for t in LOGIN_FAILURES.get(ip,[]) if t>time.time()-300]
                        LOGIN_FAILURES[ip]=attempts
                        require(len(attempts)<10,'尝试过多，请 5 分钟后再试')
                    u=c.execute('SELECT * FROM users WHERE id=?',(str(b.get('user','')),)).fetchone()
                    valid=u and hmac.compare_digest(u['hash'],hash_password(str(b.get('password','')),u['salt']))
                    if not valid:
                        with LOGIN_LOCK: LOGIN_FAILURES[ip].append(time.time())
                        return self.reply(401,{'error':'账号或密码不正确'})
                    token=secrets.token_urlsafe(32)
                    c.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
                    c.execute('INSERT INTO sessions VALUES (?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),u['id'],time.time()+86400*7))
                    secure='; Secure' if os.getenv('CAPTAIN_SECURE_COOKIE')=='1' else ''
                    return self.reply(200,{'message':'欢迎登机'},'captain='+token+'; Path=/; HttpOnly; SameSite=Strict; Max-Age=604800'+secure)
                u=self.current_user(c)
                if not u: return self.reply(401,{'error':'请先登录'})
                if path=='/api/logout':
                    cookie=SimpleCookie(self.headers.get('Cookie',''))
                    c.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(cookie['captain'].value.encode()).hexdigest(),))
                    return self.reply(200,{'message':'已退出'},'captain=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0')
                routes={'/api/publish':publish_item,'/api/reset-prepare':reset_prepare,'/api/reset-all':reset_all,'/api/tasks':submit_tasks,'/api/redeem':submit_redeem,'/api/honor':submit_honor,'/api/review':review,'/api/goal':set_goal,'/api/fulfill':fulfill,'/api/cancel':cancel,'/api/review-batch':review_batch,'/api/claim-plane':claim_plane}
                if path=='/api/seen':
                    require(u['role']=='child','仅机长确认已读')
                    c.execute('UPDATE awards SET seen=1 WHERE id=?',(b.get('id'),)); result={'message':'已收入荣誉机库'}
                elif path in routes: result=routes[path](c,u,b)
                else: return self.reply(404,{'error':'不存在'})
            self.reply(200,result)
        except (ValueError,TypeError,KeyError) as e: self.reply(400,{'error':str(e)})
        except Exception:
            self.reply(500,{'error':'服务器处理失败，操作未完成，请重试'})

def scheduler(stop):
    while not stop.is_set():
        try:
            with transaction() as c: schedule_reports(c)
        except Exception as e: print('Report scheduler:',type(e).__name__,flush=True)
        stop.wait(30)

def has_accounts():
    if not DB.exists(): return False
    c=sqlite3.connect(DB)
    try: return bool(c.execute('SELECT COUNT(*) FROM users').fetchone()[0])
    except sqlite3.OperationalError: return False
    finally: c.close()

def main():
    global DB,DEMO
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',default='127.0.0.1'); parser.add_argument('--port',type=int,default=8765)
    parser.add_argument('--db'); parser.add_argument('--setup',action='store_true'); parser.add_argument('--demo',action='store_true')
    args=parser.parse_args(); DEMO=args.demo
    if args.db: DB=Path(args.db).resolve()
    elif DEMO: DB=ROOT/'data'/'demo.sqlite3'
    passwords=None
    if DEMO: passwords={x:'fly2026demo' for x in ['child','dad','mom']}
    elif args.setup and not has_accounts():
        import getpass
        passwords={}
        for uid,label in [('child','胡庭溢'),('dad','爸爸'),('mom','妈妈')]:
            passwords[uid]=getpass.getpass(label+' password (8+ characters): ')
    init_db(passwords)
    with transaction() as c: schedule_reports(c)
    stop=threading.Event(); threading.Thread(target=scheduler,args=(stop,),daemon=True).start()
    server=ThreadingHTTPServer((args.host,args.port),Handler)
    print(f'ACE Captain running: http://{args.host}:{args.port}',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: stop.set(); server.server_close()

if __name__=='__main__': main()
