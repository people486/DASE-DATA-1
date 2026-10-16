"""生成阶段一基线；第二阶段开始前不要覆盖旧清单，保留历史副本。"""
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
files=[]
for p in ROOT.rglob('*'):
    rel=p.relative_to(ROOT)
    if p.is_file() and not p.name.startswith('~$') and not any(x.startswith('.') or x=='__pycache__' for x in rel.parts) and p.name not in ('baseline-sha256.json','GitHub上传清单.txt') and p.suffix in ('.py','.js','.css','.html','.md','.txt','.cmd','.json','.docx'):
        files.append(p)
result={p.relative_to(ROOT).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
(ROOT/'docs/baseline-sha256.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
print('基线文件数',len(result))
