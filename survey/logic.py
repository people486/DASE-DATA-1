"""纯业务规则；第二阶段新增题型在此扩展，不依赖 HTTP 或 MongoDB。"""
import math

class Invalid(ValueError):
    pass

def require(ok, message):
    if not ok:
        raise Invalid(message)

def normalize_questions(questions):
    require(isinstance(questions, list) and 0 < len(questions) <= 100, '题目数量须为1至100')
    require(all(isinstance(q, dict) for q in questions), '每道题须为对象')
    ids = [q.get('id') for q in questions]
    require(all(isinstance(x, str) and x for x in ids) and len(set(ids)) == len(ids), '题目ID必须唯一且非空')
    for i, q in enumerate(questions):
        require(q.get('type') in ('single', 'multiple', 'text', 'number'), '不支持的题型')
        require(isinstance(q.get('title'), str) and 0 < len(q['title']) <= 300, '题目标题不能为空或超过300字')
        require(isinstance(q.get('required', False), bool), 'required必须是布尔值')
        if q['type'] in ('single', 'multiple'):
            opts = q.get('options', [])
            require(isinstance(opts, list) and 2 <= len(opts) <= 50, '选择题需要2至50个选项')
            require(all(isinstance(o, str) and o for o in opts) and len(set(opts)) == len(opts), '选项不能重复或为空')
        v = q.get('validation', {})
        require(isinstance(v, dict), 'validation必须为对象')
        allowed = {'single': set(), 'multiple': {'min', 'max', 'exact'}, 'text': {'min', 'max'}, 'number': {'min', 'max', 'integer'}}[q['type']]
        require(not set(v) - allowed, '此题型不支持该校验字段')
        for key, value in v.items():
            if key == 'integer':
                require(isinstance(value, bool), 'integer必须为布尔值')
            else:
                require(type(value) in (int, float) and math.isfinite(value), '校验边界须为有限数值')
                if q['type'] in ('multiple', 'text'):
                    require(type(value) is int and value >= 0, '数量或长度边界须为非负整数')
        require(v.get('min', -math.inf) <= v.get('max', math.inf), '最小值不能大于最大值')
        if q['type'] == 'multiple':
            require(all(v.get(k, 0) <= len(q['options']) for k in ('min', 'max', 'exact')), '选择数量不能超过选项数量')
            require('exact' not in v or (v.get('min', 0) <= v['exact'] <= v.get('max', len(q['options']))), 'exact与min/max冲突')
            require(not q.get('required') or v.get('exact', v.get('max', 1)) > 0, '必答多选不能限制为选择0项')
        rules = q.get('rules', [])
        require(isinstance(rules, list), 'rules必须为数组')
        for rule in rules:
            require(isinstance(rule, dict), '跳转规则须为对象')
            target = rule.get('target')
            require(target == 'END' or target in ids[i+1:], '只能向后跳转或结束，禁止循环')
            op, value = rule.get('op'), rule.get('value')
            if q['type'] == 'single':
                require(op == 'eq' and value in q['options'], '单选跳转使用eq和有效选项')
            elif q['type'] == 'multiple':
                require(op in ('contains_any', 'contains_all') and isinstance(value, list) and value and set(value) <= set(q['options']), '多选跳转规则无效')
            elif q['type'] == 'number':
                require(op in ('eq', 'gt', 'gte', 'lt', 'lte') and type(value) in (int, float) and math.isfinite(value), '数字跳转规则无效')
            else:
                raise Invalid('文本题不支持跳转规则')
    return questions

def validate_answer(q, value):
    empty = value is None or value == '' or value == []
    if empty:
        require(not q.get('required'), q['title'] + '为必答题')
        return None
    t, v = q['type'], q.get('validation', {})
    if t == 'single':
        require(isinstance(value, str) and value in q['options'], '请选择有效选项')
    elif t == 'multiple':
        require(isinstance(value, list) and all(isinstance(x, str) for x in value), '多选答案须为数组')
        require(len(set(value)) == len(value) and set(value) <= set(q['options']), '多选包含重复或无效选项')
        require(v.get('min', 0) <= len(value) <= v.get('max', len(q['options'])), '多选数量超出范围')
        require('exact' not in v or len(value) == v['exact'], '多选数量必须为' + str(v.get('exact')))
    elif t == 'text':
        require(isinstance(value, str), '文本答案须为字符串')
        require(v.get('min', 0) <= len(value) <= v.get('max', 10000), '文本长度超出范围')
    else:
        require(type(value) in (int, float) and math.isfinite(value), '请输入有限数字')
        require(not v.get('integer') or int(value) == value, '必须为整数')
        require(v.get('min', -math.inf) <= value <= v.get('max', math.inf), '数字超出范围')
    return value

def next_id(questions, index, value):
    q = questions[index]
    if value is not None:
        for r in q.get('rules', []):
            op, expected = r['op'], r['value']
            match = (value == expected if op == 'eq' else
                     bool(set(value) & set(expected)) if op == 'contains_any' else
                     set(expected) <= set(value) if op == 'contains_all' else
                     value > expected if op == 'gt' else value >= expected if op == 'gte' else
                     value < expected if op == 'lt' else value <= expected)
            if match:
                return r['target']
    return questions[index+1]['id'] if index+1 < len(questions) else 'END'

def validate_submission(questions, answers):
    require(isinstance(answers, dict), 'answers须为对象')
    indices = {q['id']: i for i, q in enumerate(questions)}
    current, path, clean = questions[0]['id'], [], {}
    while current != 'END':
        i = indices[current]
        value = validate_answer(questions[i], answers.get(current))
        path.append(current)
        if value is not None:
            clean[current] = value
        current = next_id(questions, i, value)
    require(not set(answers) - set(path), '不能提交跳过题目或未知题目的答案')
    return clean, path
