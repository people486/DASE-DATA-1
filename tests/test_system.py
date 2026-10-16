"""真实 MongoDB + 真实 HTTP 集成测试；每次使用独立数据库，结束仅删除本次库。"""
import concurrent.futures
import http.cookiejar
import json
import sys
import threading
import unittest
import urllib.request
import urllib.error
from datetime import timedelta
from pathlib import Path
from uuid import uuid4
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import make_handler
from http.server import ThreadingHTTPServer
from survey.storage import connect, initialize
from survey.service import Service, now
from survey.logic import Invalid, normalize_questions, validate_submission

def questions():
    return [
        {'id':'q1','title':'是否在校','type':'single','required':True,'options':['是','否'],'rules':[{'op':'eq','value':'否','target':'q3'}]},
        {'id':'q2','title':'爱好','type':'multiple','required':True,'options':['阅读','运动','音乐'],'validation':{'exact':2},'rules':[{'op':'contains_all','value':['阅读','运动'],'target':'q4'}]},
        {'id':'q3','title':'年龄','type':'number','required':True,'validation':{'min':0,'max':120,'integer':True},'rules':[{'op':'gte','value':60,'target':'END'}]},
        {'id':'q4','title':'建议','type':'text','required':True,'validation':{'min':2,'max':20}}]

class SystemTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=connect('lab4_test_'+uuid4().hex)
        initialize(cls.db)
        cls.service=Service(cls.db)
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),make_handler(cls.service))
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
        cls.url='http://127.0.0.1:'+str(cls.server.server_port)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close()
        cls.db.client.drop_database(cls.db.name)
        cls.db.client.close()

    def setUp(self):
        name='用户'+uuid4().hex[:8]
        self.owner=self.service.register({'username':name,'password':'testpass123'})['id']
        self.other=self.service.register({'username':name+'另','password':'testpass123'})['id']
        self.s=self.service.create(self.owner,{'title':'校园调查','allow_anonymous':True})
        self.sid=self.s['_id']

    def publish(self, repeat=False):
        self.service.edit(self.owner,self.sid,{'questions':questions(),'revision':1})
        if repeat:self.db.surveys.update_one({'_id':self.sid},{'$set':{'allow_repeat':True}})
        self.service.transition(self.owner,self.sid,'publish')

    def submit(self, answers=None, **kw):
        return self.service.submit(self.other,self.sid,{'answers':answers or {'q1':'否','q3':30,'q4':'很好'},'request_id':uuid4().hex,**kw})

    def test_01_create_and_add_questions(self):
        self.assertEqual(self.s['status'],'draft')
        s=self.service.edit(self.owner,self.sid,{'questions':questions(),'revision':1})
        self.assertEqual(len(s['questions']),4);self.assertEqual(s['revision'],2)

    def test_02_login_password_and_session(self):
        name=self.db.users.find_one({'_id':self.owner})['username']
        t=self.service.login({'username':name,'password':'testpass123'})
        self.assertEqual(self.service.authenticate(t),self.owner)
        self.assertNotIn('testpass123',self.db.users.find_one({'_id':self.owner})['password_hash'])
        with self.assertRaises(Invalid):self.service.login({'username':name,'password':'wrong'})
        self.db.sessions.update_many({'user_id':self.owner},{'$set':{'expires_at':now()-timedelta(seconds=1)}})
        self.assertIsNone(self.service.authenticate(t))

    def test_03_all_jump_types(self):
        qs=normalize_questions(questions())
        _,p=validate_submission(qs,{'q1':'否','q3':60});self.assertEqual(p,['q1','q3'])
        _,p=validate_submission(qs,{'q1':'是','q2':['阅读','运动'],'q4':'很好'});self.assertEqual(p,['q1','q2','q4'])
        _,p=validate_submission(qs,{'q1':'是','q2':['音乐','运动'],'q3':20,'q4':'很好'});self.assertEqual(p,['q1','q2','q3','q4'])

    def test_04_validation_and_forged_answers(self):
        qs=questions()
        for a in [{},{'q1':'未知'},{'q1':'否','q3':1.5},{'q1':'否','q3':121},{'q1':'否','q3':True},{'q1':'否','q3':float('nan')},{'q1':'否','q3':20,'q4':'短'},{'q1':'是','q2':['阅读','阅读']},{'q1':'是','q2':['阅读']},{'q1':'否','q2':['阅读','运动'],'q3':60}]:
            with self.subTest(a=a),self.assertRaises(Invalid):validate_submission(qs,a)

    def test_05_rule_schema_and_conflicts(self):
        qs=questions();qs[2]['rules'][0]['target']='q1'
        with self.assertRaises(Invalid):normalize_questions(qs)
        self.service.edit(self.owner,self.sid,{'questions':questions(),'revision':1})
        with self.assertRaises(Invalid):self.service.edit(self.owner,self.sid,{'questions':questions(),'revision':1})

    def test_06_submit_anonymous_and_duplicate(self):
        self.publish();r=self.submit(anonymous=True)
        doc=self.db.responses.find_one({'_id':r['id']});self.assertNotIn('user_id',doc)
        with self.assertRaises(Invalid):self.submit()

    def test_07_repeat_idempotency_and_statistics(self):
        self.publish(True)
        self.submit({'q1':'否','q3':20,'q4':'满意'})
        self.submit({'q1':'否','q3':40,'q4':'很好'})
        body={'answers':{'q1':'是','q2':['阅读','运动'],'q4':'不错'},'request_id':uuid4().hex}
        r=self.service.submit(self.other,self.sid,body)
        self.assertEqual(r['id'],self.service.submit(self.other,self.sid,body)['id'])
        st=self.service.statistics(self.owner,self.sid)
        self.assertEqual(st['total_responses'],3)
        self.assertEqual(st['questions'][0]['options'],{'是':1,'否':2})
        self.assertEqual(st['questions'][1]['options']['阅读'],1)
        self.assertEqual(st['questions'][2]['average'],30)
        self.assertEqual(st['questions'][2]['answered'],2)
        self.assertEqual(len(self.service.statistics(self.owner,self.sid,'q3')['questions']),1)

    def test_08_ownership_and_lifecycle(self):
        with self.assertRaises(Invalid):self.service.survey(self.sid,self.other)
        with self.assertRaises(Invalid):self.service.statistics(self.other,self.sid)
        with self.assertRaises(Invalid):self.service.available(self.sid)
        self.publish()
        with self.assertRaises(Invalid):self.service.edit(self.owner,self.sid,{'questions':questions(),'revision':2})
        self.service.transition(self.owner,self.sid,'close')
        with self.assertRaises(Invalid):self.submit()

    def test_09_deadline_and_anonymous_restriction(self):
        self.publish()
        self.db.surveys.update_one({'_id':self.sid},{'$set':{'allow_anonymous':False}})
        with self.assertRaises(Invalid):self.submit(anonymous=True)
        self.db.surveys.update_one({'_id':self.sid},{'$set':{'deadline':now()-timedelta(seconds=1)}})
        with self.assertRaises(Invalid):self.submit()

    def test_10_concurrent_no_repeat(self):
        self.publish()
        def work(_):
            try:self.submit();return True
            except Invalid:return False
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(work,range(12)))
        self.assertEqual(sum(results),1)
        self.assertEqual(self.db.responses.count_documents({'survey_id':self.sid}),1)

    def test_11_http_workflow_and_csrf(self):
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        def call(path,body=None,method=None,header=True):
            req=urllib.request.Request(self.url+path,data=json.dumps(body).encode() if body is not None else None,method=method,headers={'Content-Type':'application/json',**({'X-Survey-Client':'1'} if header else {})})
            with opener.open(req) as r:return json.load(r)
        with self.assertRaises(urllib.error.HTTPError) as ctx:call('/api/surveys')
        self.assertEqual(ctx.exception.code,401)
        name='http'+uuid4().hex
        call('/api/register',{'username':name,'password':'password123'})
        with self.assertRaises(urllib.error.HTTPError) as ctx:call('/api/login',{'username':name,'password':'password123'},header=False)
        self.assertEqual(ctx.exception.code,400)
        call('/api/login',{'username':name,'password':'password123'})
        s=call('/api/surveys',{'title':'HTTP测试'})
        sid=s['_id'];call('/api/surveys/'+sid,{'questions':questions(),'revision':1},'PUT')
        call('/api/surveys/'+sid+'/publish',{})
        self.assertEqual(call('/api/surveys/'+sid+'/next',{'question_id':'q1','value':'否'})['next'],'q3')
        call('/api/surveys/'+sid+'/responses',{'answers':{'q1':'否','q3':60},'request_id':uuid4().hex})
        self.assertEqual(call('/api/surveys/'+sid+'/statistics')['total_responses'],1)
        with opener.open(self.url+'/survey/'+sid) as r:self.assertIn('text/html',r.headers['Content-Type'])
        call('/api/logout',{})
        with self.assertRaises(urllib.error.HTTPError):call('/api/me')

    def test_12_mongodb_schema_rejects_bad_record(self):
        from pymongo.errors import WriteError
        with self.assertRaises(WriteError):self.db.responses.insert_one({'survey_id':123})

    def test_13_multiuser_concurrent(self):
        self.publish()
        users=[self.service.register({'username':'parallel'+uuid4().hex,'password':'testpass123'})['id'] for _ in range(6)]
        def work(user):
            return self.service.submit(user,self.sid,{'answers':{'q1':'否','q3':60},'request_id':uuid4().hex})
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            rows=list(pool.map(work,users))
        self.assertEqual(len({r['id'] for r in rows}),6)
        self.assertEqual(self.service.statistics(self.owner,self.sid)['total_responses'],6)

    def test_14_optional_zero_and_operator_edges(self):
        from survey.logic import validate_answer, next_id
        self.assertEqual(validate_answer({'type':'number','title':'数字','validation':{'integer':True,'min':0}},0),0)
        self.assertIsNone(validate_answer({'type':'text','title':'文字','validation':{'min':2}},''))
        for op,x,y,expected in [('gt',2,1,True),('gte',1,1,True),('lt',0,1,True),('lte',1,1,True),('eq',1,1,True),('gt',1,2,False),('contains_any',['A'],['A','B'],True)]:
            q=[{'id':'a','rules':[{'op':op,'value':y,'target':'END'}]},{'id':'b'}]
            self.assertEqual(next_id(q,0,x),'END' if expected else 'b')

    def test_15_empty_statistics_and_username_uniqueness(self):
        self.publish()
        st=self.service.statistics(self.owner,self.sid)
        self.assertEqual(st['total_responses'],0)
        self.assertIsNone(st['questions'][2]['average'])
        name=self.db.users.find_one({'_id':self.owner})['username']
        with self.assertRaises(Invalid):self.service.register({'username':name,'password':'testpass123'})

    def test_16_all_declared_validation_limits(self):
        from survey.logic import validate_answer
        multi={'title':'兴趣','type':'multiple','required':True,'options':['A','B','C','D'],'validation':{'min':2,'max':3}}
        for answer in [['A','B'],['A','B','C']]:self.assertEqual(validate_answer(multi,answer),answer)
        for answer in [['A'],['A','B','C','D']]:
            with self.assertRaises(Invalid):validate_answer(multi,answer)
        multi['validation']={'exact':2}
        self.assertEqual(validate_answer(multi,['A','B']),['A','B'])
        with self.assertRaises(Invalid):validate_answer(multi,['A','B','C'])
        text={'title':'建议','type':'text','required':True,'validation':{'min':2,'max':4}}
        for answer in ['很好','非常满意']:self.assertEqual(validate_answer(text,answer),answer)
        for answer in ['好','希望活动更多']:
            with self.assertRaises(Invalid):validate_answer(text,answer)
        number={'title':'年龄','type':'number','required':True,'validation':{'min':0,'max':120,'integer':True}}
        for answer in [0,120]:self.assertEqual(validate_answer(number,answer),answer)
        for answer in [-1,121,1.5]:
            with self.assertRaises(Invalid):validate_answer(number,answer)
        phone={'title':'手机号','type':'number','required':True,'validation':{'integer':True}}
        self.assertEqual(validate_answer(phone,13800138000),13800138000)

    def test_17_create_deadline_configuration(self):
        future=(now()+timedelta(days=1)).isoformat()
        s=self.service.create(self.owner,{'title':'截止时间检查','deadline':future})
        self.assertGreater(s['deadline'],now())
        self.service.edit(self.owner,s['_id'],{'questions':questions(),'revision':1})
        self.service.transition(self.owner,s['_id'],'publish')
        self.assertEqual(self.service.available(s['_id'])['_id'],s['_id'])
        for deadline in [(now()-timedelta(days=1)).isoformat(),'2027-01-01T00:00:00','not-a-date']:
            with self.subTest(deadline=deadline),self.assertRaises(Invalid):
                self.service.create(self.owner,{'title':'无效截止时间','deadline':deadline})

    def test_18_partial_settings_and_revision(self):
        s=self.service.edit(self.owner,self.sid,{'revision':1,'title':'修改后的调查','allow_repeat':True})
        self.assertEqual(s['title'],'修改后的调查');self.assertTrue(s['allow_repeat'])
        self.assertTrue(s['allow_anonymous']);self.assertEqual(s['revision'],2)
        with self.assertRaises(Invalid):self.service.edit(self.owner,self.sid,{'revision':1,'title':'旧版本'})
        with self.assertRaises(Invalid):self.service.edit(self.other,self.sid,{'revision':2,'title':'越权'})

    def test_19_unsaved_preview_is_read_only(self):
        before=self.db.surveys.find_one({'_id':self.sid})
        draft={'revision':1,'questions':questions(),'title':'预览标题'}
        p=self.service.preview(self.owner,self.sid,draft)
        self.assertEqual(p['title'],'预览标题');self.assertEqual(len(p['questions']),4)
        self.assertEqual(before,self.db.surveys.find_one({'_id':self.sid}))
        self.assertEqual(self.db.responses.count_documents({'survey_id':self.sid}),0)
        with self.assertRaises(Invalid):self.service.preview(self.other,self.sid,draft)
        for invalid in [[],False,'']:
            with self.subTest(invalid=invalid),self.assertRaises(Invalid):self.service.preview(self.owner,self.sid,invalid)

    def test_20_empty_draft_and_invalid_settings(self):
        s=self.service.edit(self.owner,self.sid,{'revision':1,'questions':[],'description':'待补充'})
        self.assertEqual(s['questions'],[])
        with self.assertRaises(Invalid):self.service.transition(self.owner,self.sid,'publish')
        with self.assertRaises(Invalid):self.service.preview(self.owner,self.sid)
        for field,value in [('allow_repeat','true'),('title',''),('deadline','bad-date')]:
            with self.subTest(field=field),self.assertRaises(Invalid):self.service.edit(self.owner,self.sid,{'revision':2,field:value})

    def test_21_delete_target_requires_clean_references(self):
        qs=questions();qs.pop(2)
        with self.assertRaises(Invalid):self.service.edit(self.owner,self.sid,{'revision':1,'questions':qs})
        qs[0]['rules']=[]
        saved=self.service.edit(self.owner,self.sid,{'revision':1,'questions':qs})
        self.assertEqual(len(saved['questions']),3)

    def test_22_aggregation_pages_and_global_average(self):
        qs=[{'id':'n','title':'分数','type':'number','required':True},
            {'id':'t','title':'意见','type':'text','required':True},
            {'id':'s','title':'选择','type':'single','options':['A','B'],'required':True}]
        self.service.edit(self.owner,self.sid,{'revision':1,'questions':qs,'allow_repeat':True})
        self.service.transition(self.owner,self.sid,'publish')
        for n in range(25):self.service.submit(self.other,self.sid,{'answers':{'n':n,'t':'意见'+str(n),'s':'A' if n%2==0 else 'B'},'request_id':uuid4().hex})
        result=self.service.statistics(self.owner,self.sid,page=2,page_size=10)
        self.assertEqual(result['total_responses'],25)
        n,t,s=result['questions']
        self.assertEqual(n['average'],12);self.assertEqual(n['values'],list(range(10,20)))
        self.assertEqual(t['values_total'],25);self.assertTrue(t['has_more'])
        self.assertEqual(s['options'],{'A':13,'B':12})
        last=self.service.statistics(self.owner,self.sid,'t',3,10)['questions'][0]
        self.assertEqual(len(last['values']),5);self.assertFalse(last['has_more'])
        for page,size in [(0,10),(1,101)]:
            with self.assertRaises(Invalid):self.service.statistics(self.owner,self.sid,page=page,page_size=size)

    def test_23_http_preview_validates_without_submission(self):
        name=self.db.users.find_one({'_id':self.owner})['username']
        jar=http.cookiejar.CookieJar();client=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        def post(path,body):
            req=urllib.request.Request(self.url+path,json.dumps(body).encode(),{'Content-Type':'application/json','X-Survey-Client':'1'})
            with client.open(req) as r:return json.load(r)
        post('/api/login',{'username':name,'password':'testpass123'})
        draft={'revision':1,'questions':questions()};base='/api/surveys/'+self.sid
        step=post(base+'/preview-next',{'draft':draft,'question_id':'q1','value':'否'})
        self.assertEqual(step['next'],'q3')
        result=post(base+'/preview-submit',{'draft':draft,'answers':{'q1':'否','q3':60}})
        self.assertFalse(result['saved']);self.assertEqual(result['path'],['q1','q3'])
        with self.assertRaises(urllib.error.HTTPError):post(base+'/preview-submit',{'draft':draft,'answers':{'q1':'否','q3':121}})
        with self.assertRaises(urllib.error.HTTPError):client.open(self.url+base+'/public')
        self.assertEqual(self.db.responses.count_documents({'survey_id':self.sid}),0)
        self.assertEqual(self.db.surveys.find_one({'_id':self.sid})['revision'],1)

if __name__=='__main__':unittest.main(verbosity=2)
