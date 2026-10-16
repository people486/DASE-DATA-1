"""本地教学服务器；所有业务数据保存在 MongoDB。"""
import json
import logging
import os
from datetime import datetime
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from survey.storage import connect, initialize
from survey.service import Service
from survey.logic import Invalid, require, validate_answer, next_id, validate_submission

ROOT = Path(__file__).resolve().parent

def make_handler(service):
    class Handler(BaseHTTPRequestHandler):
        def reply(self, status, data, cookie=None):
            raw = json.dumps(data, ensure_ascii=False, default=lambda v: v.isoformat() if isinstance(v, datetime) else str(v)).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            if cookie:
                self.send_header('Set-Cookie', cookie)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            self.dispatch()

        def do_POST(self):
            self.dispatch()

        def do_PUT(self):
            self.dispatch()

        def dispatch(self):
            try:
                path = urlsplit(self.path).path
                if self.command == 'GET' and (path == '/' or path.startswith('/survey/') or path in ('/static/app.js', '/static/style.css')):
                    f = ROOT / ('static/index.html' if path == '/' or path.startswith('/survey/') else path.lstrip('/'))
                    raw = f.read_bytes()
                    self.send_response(200)
                    self.send_header('Content-Type', {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8', '.css': 'text/css; charset=utf-8'}[f.suffix])
                    self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
                    self.send_header('Content-Length', str(len(raw)))
                    self.end_headers()
                    self.wfile.write(raw)
                    return
                body = {}
                if self.command in ('POST', 'PUT'):
                    # 自定义请求头触发浏览器跨源预检；服务器不开放CORS。
                    require(self.headers.get('X-Survey-Client') == '1', '缺少客户端请求头')
                    require(self.headers.get('Content-Type', '').startswith('application/json'), '仅接受JSON')
                    length = int(self.headers.get('Content-Length', '0'))
                    require(0 < length <= 1000000, '请求体须为1至1000000字节')
                    body = json.loads(self.rfile.read(length))
                    require(isinstance(body, dict), '请求体须为对象')
                if path == '/api/register' and self.command == 'POST':
                    return self.reply(201, service.register(body))
                if path == '/api/login' and self.command == 'POST':
                    token = service.login(body)
                    return self.reply(200, {'ok': True}, 'sid=' + token + '; HttpOnly; SameSite=Strict; Path=/; Max-Age=43200')
                cookies = SimpleCookie()
                cookies.load(self.headers.get('Cookie', ''))
                token = cookies['sid'].value if 'sid' in cookies else ''
                user = service.authenticate(token)
                if not user:
                    return self.reply(401, {'error': '请先登录'})
                if path == '/api/me' and self.command == 'GET':
                    u = service.db.users.find_one({'_id': user})
                    return self.reply(200, {'id': user, 'username': u['username']})
                if path == '/api/logout' and self.command == 'POST':
                    import hashlib
                    service.db.sessions.delete_one({'_id': hashlib.sha256(token.encode()).hexdigest()})
                    return self.reply(200, {'ok': True}, 'sid=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
                if path == '/api/surveys':
                    if self.command == 'GET':
                        return self.reply(200, list(service.db.surveys.find({'owner_id': user}, {'questions': 0}).sort('created_at', -1)))
                    if self.command == 'POST':
                        return self.reply(201, service.create(user, body))
                parts = path.strip('/').split('/')
                if len(parts) >= 3 and parts[:2] == ['api', 'surveys']:
                    sid = parts[2]
                    action = parts[3] if len(parts) == 4 else None
                    if len(parts) == 3 and self.command == 'GET':
                        return self.reply(200, service.survey(sid, user))
                    if len(parts) == 3 and self.command == 'PUT':
                        return self.reply(200, service.edit(user, sid, body))
                    if action in ('publish', 'close') and self.command == 'POST':
                        return self.reply(200, service.transition(user, sid, action))
                    if action in ('preview', 'preview-next', 'preview-submit') and self.command == 'POST':
                        s = service.preview(user, sid, body.get('draft'))
                        if action == 'preview':
                            return self.reply(200, s)
                        if action == 'preview-submit':
                            answers, path = validate_submission(s['questions'], body.get('answers'))
                            return self.reply(200, {'preview': True, 'saved': False, 'path': path, 'answered': len(answers)})
                        idx = next((i for i, q in enumerate(s['questions']) if q['id'] == body.get('question_id')), None)
                        require(idx is not None, '题目不存在')
                        value = validate_answer(s['questions'][idx], body.get('value'))
                        return self.reply(200, {'next': next_id(s['questions'], idx, value)})
                    if action == 'public' and self.command == 'GET':
                        s = service.available(sid)
                        return self.reply(200, {k: v for k, v in s.items() if k not in ('owner_id', 'created_at')})
                    if action == 'next' and self.command == 'POST':
                        s = service.available(sid)
                        qid = body.get('question_id')
                        idx = next((i for i, q in enumerate(s['questions']) if q['id'] == qid), None)
                        require(idx is not None, '题目不存在')
                        value = validate_answer(s['questions'][idx], body.get('value'))
                        return self.reply(200, {'next': next_id(s['questions'], idx, value)})
                    if action == 'responses' and self.command == 'POST':
                        return self.reply(201, service.submit(user, sid, body))
                    if action == 'statistics' and self.command == 'GET':
                        query = parse_qs(urlsplit(self.path).query)
                        qid = query.get('question_id', [None])[0]
                        return self.reply(200, service.statistics(user, sid, qid,
                            int(query.get('page', ['1'])[0]), int(query.get('page_size', ['20'])[0])))
                self.reply(404, {'error': '接口不存在'})
            except (Invalid, ValueError, TypeError, KeyError, OverflowError) as e:
                self.reply(400, {'error': str(e) or '请求格式错误'})
            except Exception:
                logging.exception('Request failed')
                self.reply(503, {'error': '服务暂不可用，请检查数据库与服务器日志'})
    return Handler

def main():
    db = connect()
    initialize(db)
    address = ('127.0.0.1', int(os.getenv('PORT', '5000')))
    server = ThreadingHTTPServer(address, make_handler(Service(db)))
    print('问卷系统 http://127.0.0.1:%s  数据库 %s' % (address[1], db.name), flush=True)
    server.serve_forever()

if __name__ == '__main__':
    main()
