# API 说明

基础地址 `http://127.0.0.1:5000`。所有写请求使用 `Content-Type: application/json` 和 `X-Survey-Client: 1`。登录返回 HttpOnly SameSite=Strict 会话Cookie；后续携带Cookie。无跨源访问授权。数据错误返回400，未登录401，未知路由404，内部或数据库故障503。无权限与不存在问卷当前均返回400及错误说明。

|方法|路径|输入及输出|
|---|---|---|
|POST|/api/register|username password；201返回id username|
|POST|/api/login|username password；200设置sid Cookie|
|POST|/api/logout|{}；删除MongoDB会话并清Cookie|
|GET|/api/me|当前账号id username|
|GET|/api/surveys|仅本人问卷列表，不含题目数组|
|POST|/api/surveys|title description allow_anonymous allow_repeat deadline；创建草稿|
|GET|/api/surveys/{id}|本人完整问卷|
|PUT|/api/surveys/{id}|revision及待修改的设置或questions；仅草稿可编辑，revision加1|
|POST|/api/surveys/{id}/publish|{}；草稿发布|
|POST|/api/surveys/{id}/close|{}；发布状态关闭|
|GET|/api/surveys/{id}/public|已登录填写者获取开放问卷，无owner_id|
|POST|/api/surveys/{id}/next|question_id value；校验当前题并返回next（题目ID或END）|
|POST|/api/surveys/{id}/responses|answers anonymous request_id；201返回答卷id和replayed|
|GET|/api/surveys/{id}/statistics|仅作者；question_id可筛选单题，page/page_size控制填空答案分页|

deadline为带时区ISO8601，例如 `2027-01-01T00:00:00+08:00`；省略或null为不限。标题、说明、匿名与重复权限、截止时间和题目都可在草稿阶段修改，保存须携带当前revision；发布后冻结编辑以保护历史答卷。

## 问卷题目契约

```json
{
  "questions": [
    {"id":"q1","title":"身份","type":"single","required":true,
     "options":["学生","其他"],"validation":{},
     "rules":[{"op":"eq","value":"其他","target":"q3"}]},
    {"id":"q2","title":"爱好","type":"multiple","required":true,
     "options":["阅读","运动","音乐"],"validation":{"min":2,"max":3},"rules":[]},
    {"id":"q3","title":"年龄","type":"number","required":true,
     "validation":{"min":0,"max":120,"integer":true},"rules":[]},
    {"id":"q4","title":"建议","type":"text","required":false,
     "validation":{"min":2,"max":100},"rules":[]}
  ],
  "revision":1
}
```

选择题用选项字符串作为稳定值；第二阶段若支持发布后改选项，需引入选项ID和问卷版本，不能直接改旧值。题目ID在同一问卷内唯一。前端自动生成ID，可在高级JSON中配置易读ID。

校验：多选min/max/exact，文本min/max长度，数字min/max/integer。选填题空值不执行长度或数量约束，必答题必须非空；数字0是有效值。单选无validation字段。规则操作符：单选eq；多选contains_any或contains_all（value数组）；数字eq/gt/gte/lt/lte。按rules顺序首次命中生效；无命中进入下一题。target只能为后续题ID或END。文本题不支持条件跳转。

## 提交示例

```json
{"answers":{"q1":"其他","q3":22,"q4":"希望更多活动"},"anonymous":true,"request_id":"4e261d83-aaa0-45b4-a2ac-000000000001"}
```

answers只包含实际路径上的有值题目；空选填可省略。跳过的必答题无须回答。包含未知题、跳过题、无效答案会拒绝。request_id由客户端生成，同一次提交重试必须复用；新一轮填写必须生成新值。成功后的相同request_id返回原答卷，首个提交内容生效。不同账号不可复用同一问卷同一request_id。关闭或截止后即使重试也会先被开放状态检查拦截。

## 统计结构

返回 `total_responses` 与 `questions`。每题含id/title/type/answered；选择题options为选项到次数映射；文本或数字values为当前页有效答案，数字average无回答为null。多选一份答卷可为多个选项贡献次数；跳过或空选填不计入answered。匿名和实名答卷采用相同统计口径，不返回作者以外的身份信息。当前统计由MongoDB聚合计算。GET统计支持page（默认1）和page_size（默认20，1至100），作用于每道填空题；界面每页10条。填空题附带page/page_size/values_total/has_more，翻页可查看全部内容；总答卷数、answered、选项次数、average不受分页影响。旧字段名称保留，但values由全量改为分页返回，旧客户端需要按has_more继续读取。


## 草稿设置与只读预览

PUT `/api/surveys/{id}` 支持携带revision部分修改title、description、deadline、allow_anonymous、allow_repeat、questions。字段类型与创建一致；deadline使用带时区ISO时间或null。只允许作者修改draft，revision必须与数据库一致，成功增加1。可保存questions为空的草稿，发布与预览必须有合法题目。

|POST接口|请求字段|结果|
|---|---|---|
|`/api/surveys/{id}/preview`|可选draft对象|返回作者预览快照，剔除owner_id/created_at|
|`/api/surveys/{id}/preview-next`|可选draft、question_id、value|按正式校验逻辑返回next题目ID或END|
|`/api/surveys/{id}/preview-submit`|可选draft、answers|重新验证路径，返回preview:true、saved:false、path、answered|

draft可包含尚未保存的设置与题目，必须携带当前revision；未传draft则使用已保存问卷。三个接口都要求作者登录，均不写surveys、revision或responses。预览不会放开公开草稿链接。预览成功不代表正式提交，正式提交仍检查发布状态、截止时间和防重约束。
