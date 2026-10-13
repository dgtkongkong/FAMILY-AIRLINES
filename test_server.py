import concurrent.futures, datetime as dt, json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import server as s

CHILD={'id':'child','role':'child','name':'胡庭溢'}
DAD={'id':'dad','role':'parent','name':'爸爸'}
MOM={'id':'mom','role':'parent','name':'妈妈'}

class BusinessTests(unittest.TestCase):
    def setUp(self):
        test_root=Path(__file__).resolve().parent/'.test-work'
        test_root.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=test_root)
        assert Path(self.temp.name).resolve().is_relative_to(test_root)
        self.old=s.DB; s.DB=Path(self.temp.name)/'test.sqlite3'
        self.clock=patch.object(s,'now',return_value=dt.datetime(2026,10,16,18,0,tzinfo=s.TZ));self.clock.start()
        s.init_db({x:'testing-only' for x in ['child','dad','mom']})
    def tearDown(self):
        self.clock.stop();s.DB=self.old;self.temp.cleanup()
    def call(self,fn,u,b):
        with s.transaction() as c:return fn(c,u,b)
    def submit(self,task='chinese',choices=None,day='2026-10-16'):
        return self.call(s.submit_tasks,CHILD,{'day':day,'items':[{'id':task,'choices':[0] if choices is None else choices}]})
    def pending(self):
        with s.transaction() as c:return s.rows(c,"SELECT * FROM requests WHERE status='pending'")
    def approve_all(self):
        for r in self.pending():self.call(s.review,DAD,{'id':r['id'],'approve':True})
    def credit(self,n):
        with s.transaction() as c:c.execute("INSERT INTO ledger(source,created,miles,module,title) VALUES (?,?,?,?,?)",('fixture:'+str(n),s.stamp(),n,'核心巡航','TEST FIXTURE'))
    def test_each_subitem_separate_approval_and_score(self):
        self.submit(choices=[0,1]);self.assertEqual(len(self.pending()),2)
        with s.transaction() as c:self.assertEqual(s.balance(c),0)
        r=self.pending()[0];self.call(s.review,DAD,{'id':r['id'],'approve':True})
        with s.transaction() as c:self.assertEqual(s.balance(c),3)
        self.approve_all()
        with s.transaction() as c:self.assertEqual(s.balance(c),6)
    def test_no_22_daily_cap(self):
        for t in s.RULES['tasks']:
            if t['frequency']=='day':self.submit(t['id'],list(range(len(t['options']))))
        self.approve_all()
        with s.transaction() as c:self.assertGreater(s.balance(c),22)
    def test_same_subitem_cannot_repeat_other_subitem_can(self):
        self.submit(choices=[0]);self.submit(choices=[1]);self.approve_all()
        with self.assertRaises(ValueError):self.submit(choices=[0])
    def test_batch_failure_rolls_back_all(self):
        self.submit('habit')
        with self.assertRaises(ValueError):
            self.call(s.submit_tasks,CHILD,{'day':'2026-10-16','items':[{'id':'math','choices':[0]},{'id':'habit','choices':[0]}]})
        self.assertEqual(len(self.pending()),1)
    def test_rejection_and_resubmit(self):
        self.submit();rid=self.pending()[0]['id']
        self.call(s.review,DAD,{'id':rid,'approve':False,'reason':'请补充朗读时间'})
        self.submit();self.approve_all()
        with s.transaction() as c:self.assertEqual(s.balance(c),3)
    def test_reject_needs_reason(self):
        self.submit()
        with self.assertRaises(ValueError):self.call(s.review,DAD,{'id':self.pending()[0]['id'],'approve':False})
    def test_child_cannot_approve_parent_cannot_submit(self):
        self.submit()
        with self.assertRaises(ValueError):self.call(s.review,CHILD,{'id':self.pending()[0]['id'],'approve':True})
        with self.assertRaises(ValueError):self.call(s.submit_tasks,DAD,{'day':'2026-10-16','items':[]})
    def test_concurrent_parents_only_one_credit(self):
        self.submit();rid=self.pending()[0]['id']
        def review(u):
            try:self.call(s.review,u,{'id':rid,'approve':True});return True
            except ValueError:return False
        with concurrent.futures.ThreadPoolExecutor(2) as pool:result=list(pool.map(review,[DAD,MOM]))
        self.assertEqual(sum(result),1)
        with s.transaction() as c:self.assertEqual(s.balance(c),3)
    def test_redemption_reserve_and_annual_gross(self):
        self.credit(60);self.call(s.submit_redeem,CHILD,{'id':'screen'})
        with s.transaction() as c:self.assertEqual(s.balance(c),60);self.assertEqual(s.reserved(c),50)
        with self.assertRaises(ValueError):self.call(s.submit_redeem,CHILD,{'id':'bedtime'})
        self.approve_all()
        with s.transaction() as c:
            self.assertEqual(s.balance(c),10)
            self.assertEqual(s.total(c,dt.date(2026,1,1),dt.date(2027,1,1)),60)
    def test_rejected_exchange_releases_reservation(self):
        self.credit(50);self.call(s.submit_redeem,CHILD,{'id':'screen'})
        self.call(s.review,MOM,{'id':self.pending()[0]['id'],'approve':False,'reason':'改到下周'})
        with s.transaction() as c:self.assertEqual(s.reserved(c),0);self.assertEqual(s.balance(c),50)
    def test_cash_limit_including_pending(self):
        self.credit(100)
        for _ in range(3):self.call(s.submit_redeem,CHILD,{'id':'cash'})
        with self.assertRaises(ValueError):self.call(s.submit_redeem,CHILD,{'id':'cash'})
        self.approve_all()
        with self.assertRaises(ValueError):self.call(s.submit_redeem,CHILD,{'id':'cash'})
    def test_money_fulfillment_exactly_once(self):
        self.credit(10);self.call(s.submit_redeem,CHILD,{'id':'cash'});self.approve_all()
        with s.transaction() as c:state=s.state(c,DAD)
        self.assertEqual(state['money']['cash_due'],500)
        award=state['awards'][0]
        self.call(s.fulfill,DAD,{'id':award['id']})
        with self.assertRaises(ValueError):self.call(s.fulfill,MOM,{'id':award['id']})
        with s.transaction() as c:state=s.state(c,DAD)
        self.assertEqual(state['money']['cash_due'],0);self.assertEqual(state['money']['cash_paid'],500)
    def test_goal_minimum_no_business_max_and_locked(self):
        with self.assertRaises(ValueError):self.call(s.set_goal,CHILD,{'target':119})
        self.call(s.set_goal,CHILD,{'target':500})
        with self.assertRaises(ValueError):self.call(s.set_goal,CHILD,{'target':120})
    def test_weekly_random_award_once(self):
        self.call(s.set_goal,CHILD,{'target':120});self.credit(120)
        with s.transaction() as c:
            s.trigger_awards(c);s.trigger_awards(c)
            awards=s.rows(c,"SELECT * FROM awards WHERE id LIKE 'week:%'")
        self.assertEqual(len(awards),1);self.assertIn(awards[0]['reward'],s.RULES['weekly_surprises'])
    def test_six_annual_awards_no_duplicates(self):
        self.credit(2500)
        with s.transaction() as c:
            s.trigger_awards(c);s.trigger_awards(c)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM awards WHERE id LIKE 'annual:%'").fetchone()[0],6)
    def test_future_rewards_hidden_from_child(self):
        with s.transaction() as c:state=s.state(c,CHILD)
        self.assertEqual(state['rules']['weekly_surprises'],[])
        self.assertTrue(all(x['reward']=='到达后揭晓的隐藏奖励' for x in state['rules']['annual']))
    def test_honor_parent_verification_fund(self):
        self.call(s.submit_honor,CHILD,{'id':'fund','note':'期末成绩全班第三名，请爸爸核实'})
        self.approve_all()
        with s.transaction() as c:self.assertEqual(s.state(c,CHILD)['money']['fund_due'],80000)
        with self.assertRaises(ValueError):self.call(s.submit_honor,CHILD,{'id':'fund','note':'再申请一次奖励试试'})
    def test_invalid_choices_future_and_old_dates(self):
        for choices,day in [([99],'2026-10-16'),([True],'2026-10-16'),([0,0],'2026-10-16'),([0],'2026-10-17'),([0],'2026-10-09')]:
            with self.assertRaises(ValueError):self.submit(choices=choices,day=day)
    def test_weekly_subitem_cannot_repeat_different_day(self):
        self.submit('excellent',day='2026-10-16')
        with self.assertRaises(ValueError):self.submit('excellent',day='2026-10-15')
    def test_weekend_only(self):
        with self.assertRaises(ValueError):self.submit('share')
    def test_week_report_friday_18_previous_full_week_once(self):
        with s.transaction() as c:
            s.schedule_reports(c,dt.datetime(2026,10,16,17,59,tzinfo=s.TZ))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM reports').fetchone()[0],0)
            s.schedule_reports(c);s.schedule_reports(c)
            r=c.execute('SELECT * FROM reports').fetchone()
            self.assertEqual((r['start'],r['end']),('2026-10-05','2026-10-12'))
            self.assertEqual(c.execute('SELECT COUNT(*) FROM reports').fetchone()[0],1)
    def test_month_rollover_and_offline_catchup(self):
        with s.transaction() as c:
            c.execute("UPDATE settings SET value='2025-12-31' WHERE key='started'")
            s.schedule_reports(c,dt.datetime(2026,2,1,0,0,tzinfo=s.TZ))
            reports=s.rows(c,"SELECT * FROM reports WHERE kind='month'")
            self.assertEqual([(r['start'],r['end']) for r in reports],[('2025-12-01','2026-01-01'),('2026-01-01','2026-02-01')])
    def test_report_no_data_and_cash(self):
        with s.transaction() as c:
            d=s.report_data(c,dt.date(2026,10,1),dt.date(2026,11,1))
            self.assertEqual(d['income'],0);self.assertEqual(d['modules'],[])
            self.assertIn('还没有',d['advice'])
    def test_cancel_releases_cash_quota_and_reserved_miles(self):
        self.credit(10);self.call(s.submit_redeem,CHILD,{'id':'cash'})
        rid=self.pending()[0]['id'];self.call(s.cancel,CHILD,{'id':rid})
        with s.transaction() as c:self.assertEqual(s.reserved(c),0)
        self.call(s.submit_redeem,CHILD,{'id':'cash'})
    def test_cancel_approved_is_rejected(self):
        self.submit();rid=self.pending()[0]['id'];self.approve_all()
        with self.assertRaises(ValueError):self.call(s.cancel,CHILD,{'id':rid})

    def seed_days(self,count,start='2026-08-01',status='approved'):
        first=dt.date.fromisoformat(start)
        with s.transaction() as c:
            for i in range(count):
                day=(first+dt.timedelta(days=i)).isoformat()
                c.execute('INSERT INTO requests(id,kind,item,subitem,period,day,choices,note,status,created,miles,title,rule_version) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(f'fixture-{day}','task','habit',0,day,day,'["test"]','',status,s.stamp(),1,'test','test'))
    def test_streak_uses_completed_days_not_approval_day(self):
        self.seed_days(21)
        with s.transaction() as c:
            s.sync_medals(c);m=s.rows(c,'SELECT * FROM medals')
            self.assertEqual(s.streak_info(c)['best'],21)
        self.assertEqual(len(m),1);self.assertEqual(m[0]['achieved'],'2026-08-21');self.assertIsNone(m[0]['claimed'])
    def test_pending_days_do_not_unlock_plane(self):
        self.seed_days(30,status='pending')
        with s.transaction() as c:s.sync_medals(c);self.assertEqual(c.execute('SELECT COUNT(*) FROM medals').fetchone()[0],0)
    def test_60_days_unlock_three_distinct_planes(self):
        self.seed_days(60)
        with s.transaction() as c:
            s.sync_medals(c);s.sync_medals(c)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM medals').fetchone()[0],3)
        self.call(s.claim_plane,CHILD,{'id':'streak:2026:21days'})
        with s.transaction() as c:self.assertEqual(s.state(c,CHILD)['money']['cash_due'],3000)
        with self.assertRaises(ValueError):self.call(s.claim_plane,CHILD,{'id':'streak:2026:21days'})
        self.call(s.fulfill,DAD,{'id':'streak:2026:21days'})
        with s.transaction() as c:self.assertEqual(s.state(c,CHILD)['money']['cash_due'],0)
    def test_streak_gap_and_approved_backfill(self):
        self.seed_days(21)
        with s.transaction() as c:
            c.execute("UPDATE requests SET status='pending' WHERE day='2026-08-11'")
            s.sync_medals(c);self.assertEqual(c.execute('SELECT COUNT(*) FROM medals').fetchone()[0],0)
            c.execute("UPDATE requests SET status='approved' WHERE day='2026-08-11'")
            s.sync_medals(c);self.assertEqual(c.execute('SELECT COUNT(*) FROM medals').fetchone()[0],1)
    def test_multiple_subitems_one_calendar_day(self):
        self.seed_days(20)
        with s.transaction() as c:
            c.execute("INSERT INTO requests(id,kind,item,period,day,choices,note,status,created,miles,title,rule_version) VALUES ('extra','task','math','2026-08-20','2026-08-20','[]','','approved',?,3,'extra','test')",(s.stamp(),))
            self.assertEqual(s.streak_info(c)['best'],20)
    def test_cross_year_streak(self):
        self.seed_days(21,start='2025-12-20')
        with s.transaction() as c:
            s.sync_medals(c);self.assertIsNotNone(c.execute("SELECT 1 FROM medals WHERE id='streak:2026:21days'").fetchone())
    def test_manual_streak_honor_disallowed(self):
        with self.assertRaises(ValueError):self.call(s.submit_honor,CHILD,{'id':'21days','note':'连续完成了二十一天'})
    def test_annual_awards_grant_six_claimed_medals(self):
        self.credit(2500)
        with s.transaction() as c:
            s.trigger_awards(c);s.sync_medals(c)
            medals=s.rows(c,"SELECT * FROM medals WHERE kind='mileage'")
        self.assertEqual(len(medals),6);self.assertTrue(all(m['claimed'] for m in medals))
    def test_batch_approval_and_atomic_stale_conflict(self):
        self.submit(choices=[0,1]);ids=[r['id'] for r in self.pending()]
        self.call(s.review_batch,DAD,{'ids':ids,'approve':True})
        with s.transaction() as c:self.assertEqual(s.balance(c),6)
        self.submit('math');rid=self.pending()[0]['id']
        with self.assertRaises(ValueError):self.call(s.review_batch,MOM,{'ids':[rid,ids[0]],'approve':True})
        self.assertEqual(len(self.pending()),1)
    def test_batch_rejection_no_points_and_reasons(self):
        self.submit(choices=[0,1]);ids=[r['id'] for r in self.pending()]
        self.call(s.review_batch,DAD,{'ids':ids,'approve':False,'reason':'请补充记录'})
        with s.transaction() as c:self.assertEqual(s.balance(c),0)
        self.assertEqual(self.pending(),[])
    def test_one_week_date_boundary(self):
        self.submit(day='2026-10-10')
        with self.assertRaises(ValueError):self.submit(day='2026-10-09')
    def test_event_task_requires_specific_description(self):
        with self.assertRaises(ValueError):self.submit('merit')
        self.call(s.submit_tasks,CHILD,{'day':'2026-10-16','note':'本学期学校三好学生评选','items':[{'id':'merit','choices':[0]}]})
        self.approve_all()
        with s.transaction() as c:self.assertEqual(s.balance(c),60)
    def test_export_xlsx_inclusive_dates_numeric_and_safe_text(self):
        import io,openpyxl
        self.credit(25)
        with s.transaction() as c:
            c.execute("UPDATE ledger SET title='=HYPERLINK(\"bad\")'")
            payload=s.export_excel(c,'ledger','2026-10-16','2026-10-16')
        book=openpyxl.load_workbook(io.BytesIO(payload))
        sheet=book.active;self.assertEqual(sheet.max_row,2);self.assertEqual(sheet['H2'].value,25)
        self.assertEqual(sheet['F2'].data_type,'s');self.assertEqual(sheet['B2'].value.date(),dt.date(2026,10,16))
        with s.transaction() as c:
            empty=s.export_excel(c,'ledger','2026-10-17','2026-10-18')
            with self.assertRaises(ValueError):s.export_excel(c,'ledger','2026-10-20','2026-10-01')
        self.assertEqual(openpyxl.load_workbook(io.BytesIO(empty)).active.max_row,1)
    def test_report_export_separates_week_month_and_overlap(self):
        import io,openpyxl
        with s.transaction() as c:
            s.save_report(c,'week',dt.date(2026,10,5),dt.date(2026,10,12))
            s.save_report(c,'month',dt.date(2026,10,1),dt.date(2026,11,1))
            payload=s.export_excel(c,'reports','2026-10-10','2026-10-10')
        b=openpyxl.load_workbook(io.BytesIO(payload));self.assertEqual(len(b.worksheets),2)
        self.assertTrue(all(w.max_row==2 for w in b.worksheets))

if __name__=='__main__':unittest.main(verbosity=2)
