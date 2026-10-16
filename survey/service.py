import hashlib
import hmac
import secrets
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from uuid import uuid4
from pymongo.errors import DuplicateKeyError
from .logic import Invalid, require, normalize_questions, validate_submission, validate_answer, next_id

def now():
    return datetime.now(timezone.utc)

def uid():
    return uuid4().hex

class Service:
    def __init__(self, db):
        self.db = db

    def register(self, data):
        username, password = data.get('username', ''), data.get('password', '')
        require(isinstance(username, str) and 2 <= len(username.strip()) <= 40, '用户名长度须为2至40')
        require(isinstance(password, str) and 8 <= len(password) <= 200, '密码长度须为8至200')
        salt = secrets.token_hex(16)
        hashed = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 260000).hex()
        user = {'_id': uid(), 'username': username.strip(), 'password_hash': salt + ':' + hashed, 'created_at': now()}
        try:
            self.db.users.insert_one(user)
        except DuplicateKeyError:
            raise Invalid('用户名已存在')
        return {'id': user['_id'], 'username': user['username']}

    def login(self, data):
        user = self.db.users.find_one({'username': data.get('username')})
        require(user is not None and isinstance(data.get('password'), str), '用户名或密码错误')
        salt, old = user['password_hash'].split(':')
        hashed = hashlib.pbkdf2_hmac('sha256', data['password'].encode(), salt.encode(), 260000).hex()
        require(hmac.compare_digest(old, hashed), '用户名或密码错误')
        token = secrets.token_urlsafe(32)
        self.db.sessions.insert_one({'_id': hashlib.sha256(token.encode()).hexdigest(), 'user_id': user['_id'], 'expires_at': now() + timedelta(hours=12)})
        return token

    def authenticate(self, token):
        key = hashlib.sha256(token.encode()).hexdigest()
        session = self.db.sessions.find_one({'_id': key, 'expires_at': {'$gt': now()}})
        return session['user_id'] if session else None

    def survey(self, sid, owner=None):
        survey = self.db.surveys.find_one({'_id': sid})
        require(survey is not None, '问卷不存在')
        if owner is not None:
            require(survey['owner_id'] == owner, '无权访问该问卷')
        return survey

    def _settings(self, data):
        """创建、草稿编辑和预览共用同一套设置校验。只返回传入字段。"""
        result = {}
        if 'title' in data:
            title = data['title']
            require(isinstance(title, str) and 0 < len(title.strip()) <= 200, '标题须为1至200字')
            result['title'] = title.strip()
        if 'description' in data:
            require(isinstance(data['description'], str) and len(data['description']) <= 5000, '说明须为5000字以内文本')
            result['description'] = data['description']
        for key in ('allow_anonymous', 'allow_repeat'):
            if key in data:
                require(isinstance(data[key], bool), '匿名与重复设置须为布尔值')
                result[key] = data[key]
        if 'deadline' in data:
            deadline = data['deadline']
            require(deadline is None or isinstance(deadline, str), '截止时间须为ISO时间文本或null')
            if not deadline:
                result['deadline'] = None
                return result
            try:
                deadline = datetime.fromisoformat(deadline.replace('Z', '+00:00'))
                require(deadline.tzinfo is not None and deadline > now(), '截止时间须包含时区且在未来')
            except (ValueError, TypeError):
                raise Invalid('截止时间格式错误，须为带时区ISO时间')
            result['deadline'] = deadline
        return result

    def create(self, user, data):
        settings = self._settings({'title': '', 'description': '', 'allow_anonymous': False, 'allow_repeat': False, 'deadline': None, **data})
        s = {'_id': uid(), 'owner_id': user, **settings, 'status': 'draft', 'questions': [], 'created_at': now(), 'schema_version': 1, 'revision': 1}
        self.db.surveys.insert_one(s)
        return s

    def _draft_changes(self, s, data):
        require(s['status'] == 'draft', '只能编辑草稿；已发布问卷保留结构以保护历史答卷')
        require(type(data.get('revision')) is int and data['revision'] == s['revision'], '版本冲突，请刷新后再保存')
        changes = self._settings(data)
        if 'questions' in data:
            qs = data['questions']
            # 空草稿可以保存，发布和预览仍须至少一道题。
            changes['questions'] = [] if isinstance(qs, list) and not qs else normalize_questions(qs)
        require(bool(changes), '没有可保存的草稿内容')
        return changes

    def edit(self, user, sid, data):
        s = self.survey(sid, user)
        changes = self._draft_changes(s, data)
        changed = self.db.surveys.update_one({'_id': sid, 'status': 'draft', 'revision': s['revision']}, {'$set': changes, '$inc': {'revision': 1}})
        require(changed.modified_count == 1, '并发修改冲突，请刷新')
        return self.survey(sid, user)

    def preview(self, user, sid, draft=None):
        """作者可预览未保存的草稿；不修改问卷、revision或答卷集合。"""
        candidate = deepcopy(self.survey(sid, user))
        if draft is not None:
            require(isinstance(draft, dict), 'draft须为对象')
            candidate.update(self._draft_changes(candidate, draft))
        normalize_questions(candidate['questions'])
        return {key: value for key, value in candidate.items() if key not in ('owner_id', 'created_at')}

    def transition(self, user, sid, action):
        s = self.survey(sid, user)
        target = {'publish': 'published', 'close': 'closed'}.get(action)
        require(target is not None, '未知操作')
        require(s['status'] == ('draft' if action == 'publish' else 'published'), '状态转换不允许')
        if action == 'publish':
            normalize_questions(s['questions'])
            require(s['deadline'] is None or s['deadline'] > now(), '截止时间已过')
        result = self.db.surveys.update_one({'_id': sid, 'status': s['status'], 'revision': s['revision']}, {'$set': {'status': target}})
        require(result.modified_count == 1, '状态已被其他请求修改')
        return {'status': target}

    def available(self, sid):
        s = self.survey(sid)
        require(s['status'] == 'published', '问卷未发布或已关闭')
        require(s['deadline'] is None or s['deadline'] > now(), '问卷已截止')
        return s

    def submit(self, user, sid, data):
        s = self.available(sid)
        require(isinstance(data.get('anonymous', False), bool), 'anonymous须为布尔值')
        require(not data.get('anonymous') or s['allow_anonymous'], '此问卷不允许匿名')
        request_id = data.get('request_id')
        require(isinstance(request_id, str) and 8 <= len(request_id) <= 100, 'request_id须为8至100字，用于防止网络重试重复提交')
        # 身份摘要仅用于重复控制，不向问卷作者返回；匿名并非对数据库管理员不可关联。
        key = hashlib.sha256((sid + ':' + user).encode()).hexdigest()
        old = self.db.responses.find_one({'survey_id': sid, 'request_id': request_id})
        if old:
            require(old['submitter_key'] == key, '提交标识冲突')
            return {'id': old['_id'], 'replayed': True}
        answers, path = validate_submission(s['questions'], data.get('answers'))
        r = {'_id': uid(), 'survey_id': sid, 'survey_revision': s['revision'], 'schema_version': 1, 'answers': answers, 'path': path, 'submitted_at': now(), 'anonymous': data.get('anonymous', False), 'submitter_key': key, 'request_id': request_id}
        if not r['anonymous']:
            r['user_id'] = user
        if not s['allow_repeat']:
            r['dedupe_key'] = key
        try:
            self.db.responses.insert_one(r)
        except DuplicateKeyError:
            old = self.db.responses.find_one({'survey_id': sid, 'request_id': request_id, 'submitter_key': key})
            if old:
                return {'id': old['_id'], 'replayed': True}
            raise Invalid('该账号已经提交，问卷不允许重复填写')
        return {'id': r['_id'], 'replayed': False}

    def statistics(self, user, sid, qid=None, page=1, page_size=20):
        s = self.survey(sid, user)
        require(type(page) is int and page >= 1, 'page须为正整数')
        require(type(page_size) is int and 1 <= page_size <= 100, 'page_size须为1至100')
        total = self.db.responses.count_documents({'survey_id': sid})
        result = []
        for q in s['questions']:
            if qid and q['id'] != qid:
                continue
            # $getField将题目ID视为字段名，避免把点号等解释为MongoDB路径。
            pipeline = [
                {'$match': {'survey_id': sid}},
                {'$project': {'value': {'$getField': {'field': {'$literal': q['id']}, 'input': '$answers'}}, 'submitted_at': 1}},
                {'$match': {'value': {'$exists': True, '$ne': None}}},
            ]
            summary = list(self.db.responses.aggregate(pipeline + [{'$group': {
                '_id': None, 'answered': {'$sum': 1},
                'average': {'$avg': '$value'},
            }}]))
            answered = summary[0]['answered'] if summary else 0
            item = {'id': q['id'], 'title': q['title'], 'type': q['type'], 'answered': answered}
            if q['type'] in ('single', 'multiple'):
                counts = {row['_id']: row['count'] for row in self.db.responses.aggregate(pipeline + [
                    {'$unwind': '$value'}, {'$group': {'_id': '$value', 'count': {'$sum': 1}}},
                ])}
                item['options'] = {o: counts.get(o, 0) for o in q['options']}
            else:
                values = self.db.responses.aggregate(pipeline + [
                    {'$sort': {'submitted_at': 1, '_id': 1}},
                    {'$skip': (page - 1) * page_size}, {'$limit': page_size},
                ])
                item.update(values=[row['value'] for row in values], page=page, page_size=page_size,
                            values_total=answered, has_more=page * page_size < answered)
                if q['type'] == 'number':
                    item['average'] = summary[0]['average'] if summary else None
            result.append(item)
        require(qid is None or bool(result), '题目不存在')
        return {'total_responses': total, 'questions': result}
