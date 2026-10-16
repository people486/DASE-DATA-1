"""标准环境启动入口；依赖按requirements安装，本机离线包仅为可选回退。"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

ROOT = Path(__file__).resolve().parent
try:
    from pymongo import MongoClient
except ImportError:
    if (ROOT / '.packages').is_dir():
        sys.path.insert(0, str(ROOT / '.packages'))
    try:
        from pymongo import MongoClient
    except ImportError:
        raise SystemExit('请先执行 python -m pip install -r requirements.txt，参见README.md。')

def ensure_mongo():
    uri = os.getenv('MONGO_URI', 'mongodb://127.0.0.1:27019/')
    os.environ['MONGO_URI'] = uri
    client = MongoClient(uri, serverSelectionTimeoutMS=1000)
    try:
        client.admin.command('ping')
        return
    except Exception:
        if uri != 'mongodb://127.0.0.1:27019/':
            raise RuntimeError('无法连接MONGO_URI指定的数据库，请确认MongoDB已运行及连接配置正确。')
    finally:
        client.close()
    configured = os.getenv('MONGOD_EXE')
    found = configured or shutil.which('mongod')
    if not found:
        raise SystemExit('未找到mongod。请把MongoDB的bin目录加入PATH，设置MONGOD_EXE完整路径，或用MONGO_URI连接已启动的MongoDB。')
    binary = Path(found)
    if not binary.is_file():
        raise SystemExit('MONGOD_EXE对应文件不存在，请检查路径。')
    data_root = Path(os.getenv('MONGO_DATA_DIR', str(ROOT / '.mongo'))).resolve()
    (data_root / 'data').mkdir(parents=True, exist_ok=True)
    child = subprocess.Popen([
        str(binary), '--dbpath', str(data_root / 'data'),
        '--logpath', str(data_root / 'mongod.log'), '--logappend',
        '--bind_ip', '127.0.0.1', '--port', '27019',
    ], creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    for _ in range(30):
        if child.poll() is not None:
            raise RuntimeError('MongoDB启动失败，请查看.mongo/mongod.log。')
        c = MongoClient(uri, serverSelectionTimeoutMS=500)
        try:
            c.admin.command('ping')
            return
        except Exception:
            time.sleep(.3)
        finally:
            c.close()
    raise RuntimeError('MongoDB启动超时，请查看.mongo/mongod.log。')

if __name__ == '__main__':
    os.chdir(ROOT)
    ensure_mongo()
    if '--test' in sys.argv:
        import unittest
        suite = unittest.defaultTestLoader.discover(str(ROOT / 'tests'))
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        raise SystemExit(0 if result.wasSuccessful() else 1)
    if '--no-browser' not in sys.argv:
        threading.Timer(1, lambda: webbrowser.open('http://127.0.0.1:' + os.getenv('PORT', '5000'))).start()
    from app import main
    main()
