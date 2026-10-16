const $ = s => document.querySelector(s), root = $('#workspace');
const types = {single:'单选题', multiple:'多选题', text:'文本填空', number:'数字填空'};
const operators = {eq:'等于',gt:'大于',gte:'大于等于',lt:'小于',lte:'小于等于',contains_any:'包含任一选项',contains_all:'包含全部选项'};
const copy = value => JSON.parse(JSON.stringify(value));
let current = null, editor = null, dirty = false, formDirty = false, serial = 0;

function notice(text) { $('#notice').textContent = text; }
function el(tag, text, parent, cls) {
  const node = document.createElement(tag);
  if (text !== null) node.textContent = text;
  if (cls) node.className = cls;
  if (parent) parent.append(node);
  return node;
}
function button(text, action, parent, secondary = false) {
  const node = el('button', text, parent, secondary ? 'secondary' : ''); node.type = 'button';
  node.onclick = async () => {
    node.disabled = true;
    try { await action(); } catch (error) { notice(error.message); }
    finally { node.disabled = false; }
  };
  return node;
}
function field(parent, title, type = 'text', value = '', onChange) {
  const label = el('label', title, parent), input = el(type === 'textarea' ? 'textarea' : 'input', null, label);
  input.id = 'control_' + (++serial); label.htmlFor = input.id;
  if (type !== 'textarea') input.type = type;
  input.value = value ?? '';
  if (onChange) input.addEventListener('input', () => onChange(input.value));
  return input;
}
function check(parent, title, value = false, onChange) {
  const label = el('label', null, parent), input = el('input', null, label);
  input.type = 'checkbox'; input.checked = value; label.append(document.createTextNode(title));
  if (onChange) input.onchange = () => onChange(input.checked);
  return input;
}
function select(parent, title, choices, value, onChange) {
  const label = el('label', title, parent), input = el('select', null, label);
  input.id = 'control_' + (++serial); label.htmlFor = input.id;
  for (const [key, text] of choices) el('option', text, input).value = key;
  input.value = value;
  if (onChange) input.onchange = () => onChange(input.value);
  return input;
}
async function api(path, method = 'GET', data) {
  const response = await fetch('/api' + path, {method, headers:{'Content-Type':'application/json','X-Survey-Client':'1'},body:data === undefined ? undefined : JSON.stringify(data)});
  const result = await response.json();
  if (!response.ok) throw Error(result.error || '请求失败');
  return result;
}
function clear() { root.replaceChildren(); root.oninput = null; root.onchange = null; formDirty = false; notice(''); }
function markDirty() {
  dirty = true;
  if ($('#saveState')) { $('#saveState').textContent = '有未保存的修改'; $('#saveState').className = 'save-state unsaved'; }
}
window.addEventListener('beforeunload', event => { if (dirty || formDirty) { event.preventDefault(); event.returnValue = ''; } });
function dialog(title, text, actions) {
  const modal = el('dialog', null, document.body);
  el('h2', title, modal); el('p', text, modal);
  const row = el('div', null, modal, 'actions');
  for (const [label, action] of actions) button(label, async () => { await action(); modal.close(); modal.remove(); }, row, label === '取消');
  modal.addEventListener('cancel', () => modal.remove()); modal.showModal();
}
async function leave(next) {
  if (formDirty) return dialog('当前题目尚未应用','请返回并点击“应用到草稿”，或放弃当前题目的编辑。',[
    ['放弃当前题目编辑',() => { formDirty = false; return leave(next); }],['取消',() => {}]
  ]);
  if (!dirty) return next();
  dialog('还有未保存的修改', '选择保存或放弃后离开；取消会继续保留当前草稿。', [
    ['保存并离开', async () => { await saveDraft(); await next(); }],
    ['放弃未保存并离开', async () => { dirty = false; editor = null; await next(); }], ['取消', () => {}]
  ]);
}
function draftData() {
  return {title:editor.title,description:editor.description,deadline:editor.deadline || null,
    allow_anonymous:editor.allow_anonymous,allow_repeat:editor.allow_repeat,questions:copy(editor.questions),revision:editor.revision};
}
async function saveDraft() {
  editor = await api('/surveys/' + editor._id, 'PUT', draftData()); dirty = false;
  if ($('#saveState')) { $('#saveState').textContent = '已保存 · 版本 ' + editor.revision; $('#saveState').className = 'save-state'; }
  notice('草稿已保存');
}
function localTime(iso) {
  if (!iso) return '';
  const date = new Date(iso);
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}
$('#authform').onsubmit = async event => {
  event.preventDefault(); const submit = event.submitter; submit.disabled = true;
  try {
    const data = {username:$('#username').value,password:$('#password').value};
    if (submit.value === 'register') { await api('/register','POST',data); notice('注册成功，请登录'); }
    else { await api('/login','POST',data); await boot(); }
  } catch (error) { notice(error.message); } finally { submit.disabled = false; }
};
$('#logout').onclick = () => leave(async () => { await api('/logout','POST',{}); location.reload(); });
async function boot() {
  try { current = await api('/me'); } catch (error) { if (!error.message.includes('请先登录')) notice(error.message); return; }
  $('#identity').textContent = current.username; $('#logout').hidden = false; $('#auth').hidden = true; root.hidden = false;
  try {
    const match = location.pathname.match(/^\/survey\/([^/]+)$/);
    if (match) await fill(match[1]); else await dashboard();
  } catch (error) { clear(); el('h1','暂时无法打开问卷',root); notice(error.message); button('返回我的问卷',dashboard,root,true); }
}
async function dashboard() {
  clear(); editor = null; dirty = false; el('h1','我的问卷',root);
  el('p','编辑草稿、试填预览，确认后发布并分享填写链接。',root); button('创建问卷',createForm,root);
  const rows = await api('/surveys');
  if (!rows.length) el('p','还没有问卷，点击上方按钮开始。',root);
  for (const s of rows) {
    const item = el('div',null,root,'item'); el('h2',s.title,item);
    el('p',({draft:'草稿',published:'已发布',closed:'已关闭'})[s.status] + ' · ' + (s.deadline ? '截止 ' + new Date(s.deadline).toLocaleString() : '无截止时间'),item);
    button('管理',() => manage(s._id),item); button('统计',() => stats(s._id),item,true);
    if (s.status === 'published') el('a','打开填写链接',item).href = '/survey/' + s._id;
  }
}
function createForm() {
  clear(); el('h1','创建问卷',root);
  const title = field(root,'问卷标题'), description = field(root,'问卷说明','textarea');
  const anonymous = check(root,'允许登录后匿名提交'), repeat = check(root,'允许同一账号多次填写');
  const deadline = field(root,'截止时间（本地时间，可留空）','datetime-local');
  button('创建草稿',async () => {
    const s = await api('/surveys','POST',{title:title.value,description:description.value,allow_anonymous:anonymous.checked,allow_repeat:repeat.checked,deadline:deadline.value ? new Date(deadline.value).toISOString() : null});
    await manage(s._id);
  },root); button('返回列表',dashboard,root,true);
}
async function manage(id) { editor = await api('/surveys/' + id); dirty = false; renderManager(); }
function renderManager() {
  clear(); el('h1',editor.title || '问卷草稿',root);
  if (editor.status !== 'draft') {
    el('p','已发布题目保持固定，以保留历史答卷含义。',root);
    el('a',location.origin + '/survey/' + editor._id,root).href = '/survey/' + editor._id;
    if (editor.status === 'published') button('关闭问卷',() => dialog('关闭问卷','关闭后将不再接受新的填写。',[
      ['确认关闭',async () => { await api('/surveys/' + editor._id + '/close','POST',{}); await manage(editor._id); }],['取消',() => {}]
    ]),root);
    editor.questions.forEach((q,i) => el('p',`${i+1}. ${q.title} · ${types[q.type]}`,root));
    button('查看统计',() => stats(editor._id),root,true); button('返回列表',dashboard,root,true); return;
  }
  el('p',dirty ? '有未保存的修改' : '已保存 · 版本 ' + editor.revision,root,'save-state' + (dirty ? ' unsaved' : '')).id = 'saveState';
  const settings = el('div',null,root,'settings'); el('h2','基本设置',settings);
  field(settings,'问卷标题','text',editor.title,value => { editor.title = value; markDirty(); });
  field(settings,'问卷说明','textarea',editor.description,value => { editor.description = value; markDirty(); });
  field(settings,'截止时间（本地时间，可留空）','datetime-local',localTime(editor.deadline),value => { editor.deadline = value ? new Date(value).toISOString() : null; markDirty(); });
  check(settings,'允许登录后匿名提交',editor.allow_anonymous,value => { editor.allow_anonymous = value; markDirty(); });
  check(settings,'允许同一账号多次填写',editor.allow_repeat,value => { editor.allow_repeat = value; markDirty(); });
  el('h2','题目与跳转',root); el('p','规则按顺序匹配，首条命中生效。题目和设置统一通过“保存草稿”保存。',root,'muted');
  if (!editor.questions.length) el('p','还没有题目，请先添加一道题。',root);
  editor.questions.forEach((q,i) => {
    const item = el('div',null,root,'item'); el('h3',`${i+1}. ${q.title}`,item);
    el('p',`${types[q.type]} · ${q.required ? '必答' : '选填'}`,item,'muted');
    for (const rule of q.rules || []) {
      const at = editor.questions.findIndex(other => other.id === rule.target);
      const target = rule.target === 'END' ? '结束问卷' : at >= 0 ? `第${at+1}题 ${editor.questions[at].title}` : '无效目标题目';
      el('p',`${operators[rule.op]} ${Array.isArray(rule.value) ? rule.value.join('、') : rule.value} → ${target}`,item,'rule-summary');
    }
    button('编辑第' + (i+1) + '题',() => questionForm(q),item,true);
    button('删除第' + (i+1) + '题',() => deleteQuestion(q),item,true);
  });
  const actions = el('div',null,root,'actions');
  button('添加题目',() => questionForm(),actions); button('保存草稿',saveDraft,actions);
  button('试填预览',startPreview,actions,true);
  button('保存并发布',async () => { await saveDraft(); await api('/surveys/' + editor._id + '/publish','POST',{}); await manage(editor._id); },actions);
  const details = el('details',null,root); el('summary','高级编辑：题目 JSON',details);
  const area = el('textarea',null,details); area.id = 'jsonEditor'; area.setAttribute('aria-label','完整题目JSON'); area.value = JSON.stringify(editor.questions,null,2);
  button('应用 JSON 到草稿',async () => {
    const questions = JSON.parse(area.value);
    if (!Array.isArray(questions)) throw Error('题目必须为数组');
    if (questions.length) await api('/surveys/' + editor._id + '/preview','POST',{draft:{...draftData(),questions}});
    editor.questions = questions; markDirty(); renderManager(); notice('已应用，尚未保存');
  },details,true);
  button('返回列表',() => leave(dashboard),root,true);
}
function deleteQuestion(question) {
  const refs = editor.questions.filter(q => q.id !== question.id && (q.rules || []).some(r => r.target === question.id));
  const text = refs.length ? `“${question.title}”被${refs.map(q => '“'+q.title+'”').join('、')}的规则引用。删除时会一并移除这些指向它的规则。修改需要保存后生效。` : `删除“${question.title}”？修改需要保存后生效。`;
  dialog('删除题目',text,[[refs.length ? '删除题目并清理引用' : '确认删除',() => {
    editor.questions = editor.questions.filter(q => q.id !== question.id);
    editor.questions.forEach(q => { q.rules = (q.rules || []).filter(r => r.target !== question.id); });
    markDirty(); renderManager(); notice('已删除题目，尚未保存');
  }],['取消',() => {}]]);
}

function questionForm(old) {
  clear(); el('h1',old ? '编辑题目' : '添加题目',root);
  root.oninput = root.onchange = () => { formDirty = true; };
  const model = copy(old || {id:'q_'+crypto.randomUUID().slice(0,8),title:'',type:'single',required:false,options:['选项A','选项B'],validation:{},rules:[]});
  const title = field(root,'题目标题','text',model.title), required = check(root,'必答',model.required);
  const kind = select(root,'题型',Object.entries(types),model.type), content = el('div',null,root);
  let optionsInput, bounds = {}, ruleModels = copy(model.rules || []), readRules = () => [];
  function number(input,label,integer = false) {
    if (!input || input.value === '') return undefined;
    const value = Number(input.value);
    if (!Number.isFinite(value) || (integer && (!Number.isInteger(value) || value < 0))) throw Error(label+'格式不正确');
    return value;
  }
  const optionValues = () => optionsInput ? optionsInput.value.split('\n').map(v => v.trim()).filter(Boolean) : [];
  function drawType() {
    content.replaceChildren(); bounds = {}; optionsInput = null; const type = kind.value;
    if (['single','multiple'].includes(type)) optionsInput = field(content,'选项（每行一个）','textarea',(model.options || ['选项A','选项B']).join('\n'));
    const validation = el('div',null,content,'grid');
    if (type === 'multiple') {
      const mode = select(validation,'数量限制方式',[['range','范围限制'],['exact','恰好选择']],'exact' in (model.validation || {}) ? 'exact' : 'range');
      const box = el('div',null,validation);
      function limits() {
        box.replaceChildren(); bounds = {mode};
        if (mode.value === 'exact') bounds.exact = field(box,'必须选择数量','number',model.validation?.exact ?? '');
        else { bounds.min = field(box,'最少选择数量','number',model.validation?.min ?? ''); bounds.max = field(box,'最多选择数量','number',model.validation?.max ?? ''); }
      }
      mode.onchange = limits; limits();
    } else if (type === 'text' || type === 'number') {
      bounds.min = field(validation,type === 'text' ? '最少字数' : '最小值','number',model.validation?.min ?? '');
      bounds.max = field(validation,type === 'text' ? '最多字数' : '最大值','number',model.validation?.max ?? '');
      bounds.min.step = bounds.max.step = type === 'number' ? 'any' : '1';
      if (type === 'number') bounds.integer = check(validation,'必须为整数',model.validation?.integer || false);
    }
    const rules = el('div',null,content,'rules'); el('h2','跳转规则',rules);
    if (type === 'text') { el('p','文本题按顺序进入下一题。',rules); ruleModels = []; readRules = () => []; return; }
    el('p','从上到下匹配，命中第一条即跳转。没有命中时进入下一题。',rules,'muted');
    const list = el('div',null,rules);
    function drawRules() {
      list.replaceChildren(); const readers = [];
      ruleModels.forEach((rule,i) => {
        const row = el('div',null,list,'rule-row'); el('h3','规则 '+(i+1),row);
        const ops = type === 'single' ? ['eq'] : type === 'multiple' ? ['contains_any','contains_all'] : ['eq','gt','gte','lt','lte'];
        const op = select(row,'判断方式',ops.map(v => [v,operators[v]]),rule.op || ops[0]);
        let readValue;
        if (type === 'single') {
          const choices = optionValues().map(v => [v,v]);
          if (rule.value && !choices.some(([v]) => v === rule.value)) choices.unshift(['','原选项已移除，请重新选择']);
          const value = select(row,'当选择',choices,rule.value ?? choices[0]?.[0] ?? ''); readValue = () => value.value;
        } else if (type === 'multiple') {
          const group = el('fieldset',null,row); el('legend','匹配选项',group);
          const inputs = optionValues().map(value => [value,check(group,value,(rule.value || []).includes(value))]);
          readValue = () => inputs.filter(([,input]) => input.checked).map(([value]) => value);
        } else {
          const value = field(row,'比较数值','number',rule.value ?? 0); value.step = 'any'; readValue = () => number(value,'比较数值');
        }
        const at = editor.questions.findIndex(q => q.id === model.id);
        const choices = [['END','结束问卷'],...editor.questions.map((q,n) => [q.id,`第${n+1}题 ${q.title}`]).filter((_,n) => at >= 0 && n > at)];
        const target = select(row,'跳转到',choices,rule.target || 'END');
        readers.push(() => ({op:op.value,value:readValue(),target:target.value}));
        const controls = el('div',null,row,'actions');
        if (i) button('上移规则',() => { ruleModels = readRules(); [ruleModels[i-1],ruleModels[i]] = [ruleModels[i],ruleModels[i-1]]; drawRules(); },controls,true);
        if (i < ruleModels.length-1) button('下移规则',() => { ruleModels = readRules(); [ruleModels[i+1],ruleModels[i]] = [ruleModels[i],ruleModels[i+1]]; drawRules(); },controls,true);
        button('移除规则',() => { formDirty = true; ruleModels = readRules(); ruleModels.splice(i,1); drawRules(); },controls,true);
      });
      readRules = () => readers.map(read => read());
    }
    drawRules();
    if (optionsInput) optionsInput.addEventListener('change',() => { ruleModels = readRules(); drawRules(); });
    button('添加跳转规则',() => { formDirty = true; ruleModels = readRules(); ruleModels.push({target:'END'}); drawRules(); },rules,true);
  }
  kind.onchange = () => { model.validation = {}; model.options = ['选项A','选项B']; ruleModels = []; drawType(); };
  drawType();
  button('应用到草稿',async () => {
    const q = {id:model.id,title:title.value,type:kind.value,required:required.checked,validation:{},rules:readRules()};
    if (optionsInput) q.options = optionValues();
    for (const key of ['min','max','exact']) { const value = number(bounds[key],key,q.type !== 'number'); if (value !== undefined) q.validation[key] = value; }
    if (bounds.mode?.value === 'exact' && !('exact' in q.validation)) throw Error('请填写必须选择数量');
    if (bounds.integer) q.validation.integer = bounds.integer.checked;
    const questions = copy(editor.questions), index = questions.findIndex(item => item.id === q.id);
    if (index >= 0) questions[index] = q; else questions.push(q);
    await api('/surveys/'+editor._id+'/preview','POST',{draft:{...draftData(),questions}});
    editor.questions = questions; markDirty(); renderManager(); notice('题目已应用到草稿，尚未保存');
  },root);
  button('取消编辑',() => {
    if (!formDirty) return renderManager();
    dialog('放弃题目编辑','当前题目尚未应用到草稿。确认放弃这些修改？',[
      ['放弃题目编辑',renderManager],['取消',() => {}]
    ]);
  },root,true);
}

async function startPreview() {
  const draft = draftData(), survey = await api('/surveys/'+editor._id+'/preview','POST',{draft});
  renderRunner(survey,draft);
}
async function fill(id) { renderRunner(await api('/surveys/'+id+'/public')); }
function constraintText(q) {
  const v = q.validation || {}, parts = [];
  if (q.required) parts.push('必答');
  if ('exact' in v) parts.push('恰好选择'+v.exact+'项');
  if ('min' in v) parts.push((q.type === 'text' ? '最少字数' : q.type === 'multiple' ? '最少选择' : '最小值')+' '+v.min);
  if ('max' in v) parts.push((q.type === 'text' ? '最多字数' : q.type === 'multiple' ? '最多选择' : '最大值')+' '+v.max);
  if (v.integer) parts.push('必须为整数');
  return parts.join(' · ') || '选填';
}
function renderRunner(survey,previewDraft) {
  clear(); const preview = previewDraft !== undefined, id = survey._id;
  if (preview) el('p','预览模式 · 不保存答卷',root,'preview-banner');
  el('h1',survey.title,root); el('p',survey.description || '请按顺序完成问卷。',root);
  if (preview) button('返回编辑',renderManager,root,true);
  const anonymous = !preview && survey.allow_anonymous ? check(root,'匿名提交（作者看不到身份）') : null;
  const area = el('div',null,root), answers = {}, trail = [], requestId = crypto.randomUUID();
  let qid = survey.questions[0].id;
  function back() {
    if (!trail.length) return;
    const previous = trail.pop(), keep = new Set([...trail,previous]);
    for (const key of Object.keys(answers)) if (!keep.has(key)) delete answers[key];
    qid = previous; show();
  }
  function show() {
    area.replaceChildren(); notice('');
    if (qid === 'END') {
      el('h2','已完成所有适用题目',area);
      button(preview ? '检查预览答案' : '提交答卷',async () => {
        if (preview) { await api('/surveys/'+id+'/preview-submit','POST',{draft:previewDraft,answers}); notice('预览校验通过，未保存任何答卷'); }
        else {
          const result = await api('/surveys/'+id+'/responses','POST',{answers,anonymous:anonymous?.checked || false,request_id:requestId});
          area.replaceChildren(); el('h2','提交成功',area); el('p','答卷编号 '+result.id,area);
          if (anonymous) anonymous.disabled = true;
          button('返回我的问卷',dashboard,area,true);
        }
      },area); button('返回上一题',back,area,true); return;
    }
    const q = survey.questions.find(question => question.id === qid);
    el('p',`第 ${survey.questions.indexOf(q)+1} / ${survey.questions.length} 题`,area,'muted');
    el('h2',q.title,area); el('p',constraintText(q),area,'muted');
    let input, choices = [];
    if (q.type === 'single' || q.type === 'multiple') {
      for (const option of q.options) {
        const label = el('label',null,area,'option'), control = el('input',null,label);
        control.type = q.type === 'single' ? 'radio' : 'checkbox'; control.name = 'answer'; control.value = option;
        control.checked = q.type === 'single' ? answers[qid] === option : (answers[qid] || []).includes(option);
        label.append(document.createTextNode(option)); choices.push(control);
      }
    } else { input = field(area,'你的回答',q.type === 'number' ? 'number' : 'textarea',answers[qid] ?? ''); if (q.type === 'number') input.step = 'any'; }
    button('下一题',async () => {
      let value;
      if (choices.length) value = q.type === 'single' ? choices.find(c => c.checked)?.value ?? null : choices.filter(c => c.checked).map(c => c.value);
      else value = input.value === '' ? null : q.type === 'number' ? Number(input.value) : input.value;
      const result = await api('/surveys/'+id+(preview ? '/preview-next' : '/next'),'POST',{question_id:qid,value,...(preview ? {draft:previewDraft} : {})});
      if (value === null || Array.isArray(value) && !value.length) delete answers[qid]; else answers[qid] = value;
      trail.push(qid); qid = result.next; show();
    },area); if (trail.length) button('返回上一题',back,area,true);
  }
  show();
}

async function stats(id) {
  clear(); editor = null; dirty = false;
  const survey = await api('/surveys/'+id); el('h1',survey.title+' 统计',root);
  const summary = el('p',null,root), filter = select(root,'查看范围',[['','整个问卷'],...survey.questions.map(q => [q.id,q.title])],'');
  const out = el('div',null,root);
  async function loadQuestion(qid,page) {
    const data = await api('/surveys/'+id+'/statistics?question_id='+encodeURIComponent(qid)+'&page='+page+'&page_size=10');
    const container = document.getElementById('stat_'+survey.questions.findIndex(q => q.id === qid));
    if (container) renderQuestion(data.questions[0],container);
  }
  function renderQuestion(q,container) {
    container.replaceChildren(); el('h2',q.title,container); el('p','有效回答 '+q.answered+' 份',container);
    if (q.options) {
      for (const [option,count] of Object.entries(q.options)) {
        const row = el('div',null,container,'stat-option'); el('span',option,row); el('strong',String(count),row);
        const meter = el('progress',null,row); meter.max = Math.max(q.answered,1); meter.value = count; meter.setAttribute('aria-label',option+'：'+count);
      }
    } else {
      if (q.type === 'number') el('p','平均值（全部有效答案）：'+(q.average ?? '暂无数据'),container);
      const list = el('ol',null,container,'answer-list'); list.start = (q.page-1)*q.page_size+1;
      q.values.forEach(value => el('li',String(value),list));
      if (!q.values.length) el('p','本页暂无答案',container,'muted');
      el('p',`第 ${q.page} 页 · 共 ${q.values_total} 条`,container,'muted');
      if (q.page > 1) button('上一页',() => loadQuestion(q.id,q.page-1),container,true);
      if (q.has_more) button('下一页',() => loadQuestion(q.id,q.page+1),container,true);
    }
  }
  async function load() {
    const data = await api('/surveys/'+id+'/statistics?page_size=10'+(filter.value ? '&question_id='+encodeURIComponent(filter.value) : ''));
    summary.textContent = '累计答卷 '+data.total_responses+' 份；跳过题不计入有效回答数，多选按答卷计数。'; out.replaceChildren();
    for (const q of data.questions) {
      const container = el('div',null,out,'item'); container.id = 'stat_'+survey.questions.findIndex(other => other.id === q.id); renderQuestion(q,container);
    }
  }
  filter.onchange = () => load().catch(error => notice(error.message));
  await load(); button('返回列表',dashboard,root,true);
}
boot();
