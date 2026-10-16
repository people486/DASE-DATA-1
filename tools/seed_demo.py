"""可重复执行的演示数据；不清空数据库。"""
import sys
from pathlib import Path
from uuid import uuid4
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from run_local import ensure_mongo
from survey.storage import connect, initialize
from survey.service import Service

def seed():
    ensure_mongo();db=connect();initialize(db);svc=Service(db)
    def user(name):
        u=db.users.find_one({'username':name})
        return u['_id'] if u else svc.register({'username':name,'password':'DemoPass123!'})['id']
    owner=user('demo_owner')
    old=db.surveys.find_one({'owner_id':owner,'title':'校园生活体验调查'})
    if old:
        print('演示问卷已存在：/survey/'+old['_id']);return
    s=svc.create(owner,{'title':'校园生活体验调查','description':'演示单选、多选、数字、文本与三类跳转。选择非在校生会跳过爱好题；年龄60及以上直接结束。','allow_anonymous':True,'allow_repeat':True})
    from tests.test_system import questions
    svc.edit(owner,s['_id'],{'questions':questions(),'revision':1});svc.transition(owner,s['_id'],'publish')
    participant=user('demo_filler')
    for a in [{'q1':'否','q3':20,'q4':'环境很好'},{'q1':'否','q3':40,'q4':'课程丰富'},{'q1':'是','q2':['阅读','运动'],'q4':'希望增加活动'}]:
        svc.submit(participant,s['_id'],{'answers':a,'anonymous':True,'request_id':uuid4().hex})
    print('演示问卷：/survey/'+s['_id'])
    print('demo_owner / DemoPass123!   demo_filler / DemoPass123!')

if __name__=='__main__':seed()
