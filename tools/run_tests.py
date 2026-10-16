"""生成可追溯测试结果；避免把未执行项目写成通过。"""
import io
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from run_local import ensure_mongo
ensure_mongo()
stream=io.StringIO()
suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'))
result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
output=stream.getvalue()
(ROOT/'docs/test-output.txt').write_text(output,encoding='utf-8')
(ROOT/'docs/test-result.json').write_text(json.dumps({'executed_at':datetime.now().astimezone().isoformat(),'database':'真实MongoDB，随机lab4_test_前缀数据库，结束删除本次测试库','tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'successful':result.wasSuccessful()},ensure_ascii=False,indent=2),encoding='utf-8')
print(output)
raise SystemExit(0 if result.wasSuccessful() else 1)
