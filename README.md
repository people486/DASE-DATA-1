# 基于 MongoDB 的问卷系统

一个支持问卷创建、条件跳转、答案校验和结果统计的在线问卷系统。前端使用HTML、CSS和JavaScript，后端使用Python与PyMongo，业务数据存储于MongoDB。

## 主要功能

- 用户注册、登录及本人问卷管理。
- 创建、发布和关闭问卷，设置说明、截止时间、匿名权限及重复填写权限。
- 支持单选、多选、文本填空和数字填空四种题型。
- 支持必答、选择数量、文本长度、数字范围及整数校验。
- 通过可视化表单配置单选、多选和数字跳转，支持规则排序，保留高级JSON编辑。
- 草稿基本设置可修改，显示保存状态；离开未保存草稿和删除被引用题目时有确认。
- 发布前可试填未保存草稿，使用正式校验与跳转逻辑，不保存答卷。
- 支持多人填写、匿名提交、重复提交限制及请求重试去重。
- 使用MongoDB聚合提供整卷和单题统计，选项以条形图展示，填空答案分页浏览；数字平均值始终根据全部有效答案计算。

## 技术结构

|部分|实现|
|---|---|
|前端|HTML、CSS、原生JavaScript|
|HTTP服务|Python ThreadingHTTPServer|
|数据库|MongoDB|
|数据库驱动|PyMongo|
|测试|Python unittest、真实MongoDB及HTTP接口测试|

MongoDB分为users、sessions、surveys和responses四个集合。题目及跳转规则嵌入问卷文档，答卷单独保存。集合验证器与索引定义见`survey/storage.py`。

## 环境要求

- Python 3.10及以上。
- MongoDB Community Server 5.0及以上（统计使用 `$getField`）。
- Python依赖见`requirements.txt`。

已验证环境为Python 3.12.14、MongoDB 8.3.11。仓库不包含运行环境、已安装依赖或数据库数据文件。

## 安装依赖

在项目根目录执行：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

以下命令以Windows PowerShell为例。Linux或macOS下，将`.\.venv\Scripts\python.exe`替换为`./.venv/bin/python`，环境变量使用对应Shell的设置方式。

## 数据库连接与启动

### 连接已有MongoDB

例如，MongoDB已运行在本机27017端口：

```powershell
$env:MONGO_URI='mongodb://127.0.0.1:27017/'
.\.venv\Scripts\python.exe run_local.py
```

系统默认使用`lab4_survey`数据库，可通过`MONGO_DB`环境变量调整。

### 自动启动独立本地MongoDB

将MongoDB的bin目录加入PATH后执行：

```powershell
.\.venv\Scripts\python.exe run_local.py
```

也可以通过`MONGOD_EXE`指定可执行文件路径：

```powershell
$env:MONGOD_EXE='C:\Program Files\MongoDB\Server\8.3\bin\mongod.exe'
.\.venv\Scripts\python.exe run_local.py
```

路径须与实际安装位置一致。未设置`MONGO_URI`时，脚本默认连接`127.0.0.1:27019`；无法连接时尝试启动本地MongoDB，数据和日志分别保存到`.mongo/data`与`.mongo/mongod.log`。

Web默认地址为 http://127.0.0.1:5000 。设置`PORT`可调整Web端口。`.env.example`提供配置变量示例，程序不会自动加载`.env`文件。统一使用`run_local.py`启动，以保持数据库配置一致。

Web服务和MongoDB是独立进程，停止Web服务后，MongoDB可能仍在运行。`MONGO_DATA_DIR`可选地指定独立MongoDB的数据根目录，默认是项目下的`.mongo`。

## 演示数据

在与启动服务相同的数据库配置下执行：

```powershell
.\.venv\Scripts\python.exe tools/seed_demo.py
```

|账号|角色|密码|
|---|---|---|
|demo_owner|问卷创建者|DemoPass123!|
|demo_filler|问卷填写者|DemoPass123!|

脚本创建一份示例问卷和三份答卷，重复执行不会清空已有数据。初始年龄答案为20和40，有效回答数为2、平均值为30；另一份答卷跳过年龄题。演示账号仅用于本地功能验证。

## 使用流程

1. 注册并登录，创建问卷并填写基本设置。
2. 添加题目，设置必答、选项、校验条件及跳转规则。
3. 先添加全部题目，再编辑较早的题目设置跳转目标；点击“应用到草稿”后统一“保存草稿”。试填预览确认后保存并发布，通过`/survey/问卷ID`链接访问问卷。
4. 填写者登录后按顺序回答，系统根据规则跳转并检查答案。
5. 提交完成后，创建者可查看整卷或单题统计，也可关闭问卷。

跳转仅支持后续题目或`END`，多条规则按顺序取首条命中结果。被跳过的题目不执行必答检查，提交时后端重新计算答题路径。配置示例见`docs/API说明.md`。

匿名填写需要登录，匿名答卷不向问卷创建者展示账号；系统仍保存用于防重的身份摘要。统计按答卷计数，跳过题及空选填不计入该题有效回答数。已发布问卷的题目暂不支持直接修改。

## 自动测试

在与启动服务相同的数据库配置下执行：

```powershell
.\.venv\Scripts\python.exe tools/run_tests.py
```

测试覆盖问卷创建、题目编辑、跳转、校验、提交、统计、权限、会话、截止时间及并发约束，共23组。测试使用随机`lab4_test_`前缀数据库，结束后仅删除本次测试库，不清空演示数据。

执行记录写入`docs/test-output.txt`与`docs/test-result.json`。



## 项目目录

```text
app.py                HTTP接口与会话检查
run_local.py          启动入口与数据库连接检查
requirements.txt      Python依赖
.env.example          配置示例
survey/
  storage.py          MongoDB验证器与索引
  service.py          账号、问卷、提交和统计
  logic.py            题目校验与条件跳转
static/               前端网页、样式和交互
tests/                自动测试
tools/                演示数据、测试记录与基线工具
docs/                 设计、API、测试、AI使用说明及可编辑Word报告
```

## 项目文档

- [系统与数据库设计](docs/设计说明.md)：系统说明、MongoDB设计、索引、关键逻辑和要求核对。
- [API说明](docs/API说明.md)：接口和题目配置示例。
- [测试用例](docs/测试用例.md)：步骤、输入、输出及实际结果。
- [AI使用说明](docs/AI使用日志.md)：工具、提示来源、方案、调整及设计复盘。
- [项目完成报告](docs/项目完成报告.docx)：可下载编辑的Word文档。
- [第二阶段维护说明](docs/第二阶段维护说明.md)：版本、数据兼容及回归测试安排。
