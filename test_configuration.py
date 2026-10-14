import contextlib, json, sqlite3, unittest
from unittest.mock import patch
import server as s
import test_server as base

class ConfigurationTests(unittest.TestCase):
    setUp=base.BusinessTests.setUp
    tearDown=base.BusinessTests.tearDown
    call=base.BusinessTests.call
    pending=base.BusinessTests.pending
    approve_all=base.BusinessTests.approve_all
    credit=base.BusinessTests.credit
    submit=base.BusinessTests.submit
    def publish(self,kind='tasks',user=base.MOM,**values):
        body={'kind':kind,'name':'自定义成长','module':'核心巡航（学习）','frequency':'day','miles':7,'options':['阅读','复述'],'cost':5,'description':'亲子活动','threshold':125,'reward':'亲子机场体验','aircraft':'Airbus A321neo'}
        body.update(values)
        return self.call(s.publish_item,user,body)['id']
    def test_custom_subtasks_persist_and_score_separately(self):
        tid=self.publish()
        s.init_db()
        self.submit(tid,[0,1]);self.approve_all()
        with s.transaction() as c:
            self.assertEqual(s.balance(c),14)
            self.assertEqual(len([x for x in s.state(c,base.CHILD)['rules']['tasks'] if x['id']==tid]),1)
        with self.assertRaises(ValueError):self.submit(tid,[0])
    def test_custom_redemption_and_annual_medal(self):
        self.credit(130)
        self.publish('annual')
        sid=self.publish('shop')
        self.call(s.submit_redeem,base.CHILD,{'id':sid});self.approve_all()
        with s.transaction() as c:
            self.assertEqual(s.balance(c),125)
            self.assertEqual(c.execute("SELECT model FROM medals WHERE id='annual:2026:125'").fetchone()[0],'Airbus A321neo')
            self.assertEqual(c.execute("SELECT COUNT(*) FROM awards WHERE id='annual:2026:125'").fetchone()[0],1)
    def test_publish_validation_and_child_forbidden(self):
        for data in ({'user':base.CHILD},{'miles':True},{'miles':0},{'options':['a','a']},{'options':['']},{'frequency':'invalid'},{'kind':'annual','threshold':300},{'kind':'annual','aircraft':'<svg>'}):
            with self.assertRaises(ValueError):self.publish(**data)
        with s.transaction() as c:self.assertEqual(len(s.family_rules(c)['tasks']),len(s.RULES['tasks']))
    def test_reset_only_dad_two_steps_and_preserves_configuration(self):
        tid=self.publish();self.submit(tid,[0]);self.approve_all()
        self.call(s.set_goal,base.CHILD,{'target':120})
        for u in [base.CHILD,base.MOM]:
            with self.assertRaises(ValueError):self.call(s.reset_prepare,u,{'confirm':True})
            with self.assertRaises(ValueError):self.call(s.reset_all,u,{})
        with self.assertRaises(ValueError):self.call(s.reset_all,base.DAD,{'confirmation':'确认全部归零'})
        token=self.call(s.reset_prepare,base.DAD,{'confirm':True})['token']
        with self.assertRaises(ValueError):self.call(s.reset_all,base.DAD,{'token':token,'confirmation':'no'})
        self.call(s.reset_all,base.DAD,{'token':token,'confirmation':'确认全部归零'})
        with s.transaction() as c:
            self.assertEqual(s.balance(c),0)
            for table in s.RESET_TABLES:
                self.assertEqual(c.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],1 if table=='audit' else 0)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM users').fetchone()[0],3)
            self.assertTrue(any(t['id']==tid for t in s.family_rules(c)['tasks']))
            s.schedule_reports(c)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM reports').fetchone()[0],0)
        backup=next((s.DB.parent/'reset-backups').glob('*.sqlite3'))
        with contextlib.closing(sqlite3.connect(backup)) as c:self.assertEqual(c.execute('SELECT SUM(miles) FROM ledger').fetchone()[0],7)
        with self.assertRaises(ValueError):self.call(s.reset_all,base.DAD,{'token':token,'confirmation':'确认全部归零'})
    def test_reset_cancel_expiry_and_changed_ledger(self):
        self.credit(30)
        token=self.call(s.reset_prepare,base.DAD,{'confirm':True})['token']
        with patch.object(s.time,'time',return_value=s.time.time()+121):
            with self.assertRaises(ValueError):self.call(s.reset_all,base.DAD,{'token':token,'confirmation':'确认全部归零'})
        self.publish()
        with self.assertRaises(ValueError):self.call(s.reset_all,base.DAD,{'token':token,'confirmation':'确认全部归零'})
        with s.transaction() as c:self.assertEqual(s.balance(c),30)
    def test_backup_failure_cancels_reset(self):
        self.credit(55)
        token=self.call(s.reset_prepare,base.DAD,{'confirm':True})['token']
        with patch.object(s.os,'open',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.call(s.reset_all,base.DAD,{'token':token,'confirmation':'确认全部归零'})
        with s.transaction() as c:self.assertEqual(s.balance(c),55)

