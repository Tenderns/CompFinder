# CompFinder · 以图寻物

本地运行的纯图片检索应用。每个款式拥有一个名称、一个展示图片集和一个识别图片集。上传同一物体的多个角度照片，通过外观寻找相似款式，再浏览对应的展示图片。

项目从空图库启动，不导入 `ytst` 的商品、料号、图纸或任何旧业务数据。图片检索编码方案参考 `ytst`，运行时使用独立的模型、SQLite 数据库和图片目录。

## 本地启动

环境：Windows、Python 3.11+、Node.js 22.12+。首次安装需要网络下载依赖；模型就绪后，图片处理和搜索均在本机执行。

```powershell
cd E:\work\KJ\CompFinder
.\scripts\setup.ps1
.\scripts\start.ps1
```

也可以双击 `setup.cmd` 完成首次安装，再双击 `start.cmd` 启动。浏览器打开 **http://127.0.0.1:8010**。关闭启动窗口或按 Ctrl+C 停止服务。

### 图片模型

使用 Meta 的 DINOv3 ViT-S/16（[onnx-community/dinov3-vits16-pretrain-lvd1689m-ONNX](https://huggingface.co/onnx-community/dinov3-vits16-pretrain-lvd1689m-ONNX) 的 fp32 导出），输入 448×448。模型由两个文件组成，安装脚本下载到 `data/models/dinov3-vits16/`，逐个校验 SHA-256：

- `model.onnx`：计算图，约 135 KB。
- `model.onnx_data`：权重，约 86 MB；文件名不能改，计算图按这个名字读取权重。

下载不了 Hugging Face 时：

```powershell
# 使用镜像
$env:HF_ENDPOINT = "https://hf-mirror.com"; .\scripts\setup.ps1
# 或手动下载上面两个文件（仓库 onnx 目录下）放进同一个文件夹
.\scripts\setup.ps1 -ModelSource D:\models\dinov3
```

如果下载提示需要授权，先在 Hugging Face 页面同意许可，再设置 `$env:HF_TOKEN` 后重试。只接受这两个指定文件，校验不通过不会复制。

模型文件受 [DINOv3 License](https://huggingface.co/facebook/dinov3-vits16-pretrain-lvd1689m) 约束：允许商用，但禁止军事等用途；把模型随软件分发给他人时需附带许可文本。正式商用前建议由法务确认。

从旧版（DINOv2-small）升级：重新运行 `setup.ps1` 下载新模型，再启动服务。已有识别图会在后台按新模型重新建立索引，顶栏显示剩余张数，完成前这些款式暂时搜不到。旧的 `data/models/dinov2-small.onnx` 可以删除。

单张图片的计算量约为旧模型的 4 倍，建索引和搜索都会相应变慢。

## 建立图库

在“图库管理”新建款式，分别上传两套照片：

| 集合 | 用途 | 搜索与详情页 | 管理页 |
|---|---|---|---|
| 展示图片集 | 封面和图片浏览 | 展示 | 上传、预览、删除、排序、设置封面 |
| 识别图片集 | 图片向量检索 | 不展示、不返回参考图地址 | 上传、预览、删除、索引状态 |

每个款式还可以填写款式信息，全部可以留空：

- **参数**：名称/内容成对填写，如原厂料号、本体长度、额定电压。
- **视觉信息**：AI 识别出的分类结果，按 ytst 轻触开关规范 v1.1 的字段填写，如安装方式、按压方向、本体轮廓、脚数。
- **备注**：自由文本。

在款式编辑窗口的“款式信息”页签中填写，或随批量导入一起写入（见下文）；搜索结果的对比视图和“我的图库”详情中会显示，并可点击“编辑”直接修改。卡片上显示前两项，图库查找同时匹配名称和款式信息。款式信息不参与图片相似度计算。

集合间不会自动复制。展示图不生成向量。相同图片可主动分别加入两套集合，同一集合内按解码后的图片内容去重。图片方向校正后以无损 PNG 保存，并生成列表缩略图。

至少一张展示图和一张索引成功的识别图，款式才出现在普通图库和搜索候选中。缺图时保存草稿。识别图在后台逐张建立索引，退出重启后继续；失败可在管理页重试。删除立即取消图片的读取及检索资格；封面和展示顺序的更改不会重建索引。

识别集建议加入清楚、完整的不同角度实拍照片。查询集的各张照片应属于同一物体。

## 按文件夹批量导入

```text
待导入图库/
├─ 款式A/
│  ├─ 款式信息.json   （可选）
│  ├─ 展示图/
│  │  └─ 正面.jpg
│  └─ 识别图/
│     ├─ 实拍1.jpg
│     └─ 实拍2.jpg
└─ 款式B/
   ├─ 展示图/
   └─ 识别图/
```

可参考 `examples/导入示例`，将自己的图片放入对应目录。目录占位文件 `.gitkeep` 会作为非图片跳过。

在“批量导入”选择最外层文件夹，检查预览，点击开始导入。支持选择单款文件夹。子目录固定命名“展示图”和“识别图”，图片直接放在其内，不嵌套更多目录。

- 支持 JPG、PNG、WebP；每张最多 20 MB、4000 万像素、宽高至少 24 像素；不接受动画。
- 一批最多 20000 个文件；按照千款以内的图库设计。
- 已有同名款式跳过，不覆盖或合并；后续补图请打开该款式。
- 无效目录、损坏图片及重复文件列出明细，其他图片继续导入。
- 缺少一套图片的款式保存草稿；空文件夹本身不会被浏览器上传。
- 上传期间保持页面打开；中断后已保存图片仍在，可从最近导入记录打开款式补图。

### 款式信息文件

每个款式文件夹里可以放一个 `款式信息.json`，与“展示图”“识别图”并列。导入页右侧可以下载示例文件，内容与 `examples/导入示例/款式A/款式信息.json` 相同：

```json
{
  "参数": { "原厂料号": "TS-6606", "额定电压": "12V DC" },
  "视觉信息": { "安装方式": "插件", "按压方向": "顶按", "本体轮廓": "方形", "脚数": 4 },
  "备注": "可以不写"
}
```

- 三部分都可以省略，`examples/导入示例/款式B` 只写了视觉信息。视觉信息的字段名和取值建议按 ytst 规范 v1.1（AI 通过 MCP 写入时强制检查，文件导入不强制）。
- 内容可以是文字、数字或列表；列表用顿号合并，如 `["疑似硅胶按头", "双动作结构"]` 显示为“疑似硅胶按头、双动作结构”；`true`/`false` 显示为“是/否”；`null` 的项不导入。
- 参数和视觉信息也可以写成 `[{"name": "按柄颜色", "value": "黑色"}]`，与接口格式相同。
- 用 UTF-8 编码保存（Windows 记事本默认即可），注意文件名不要变成 `款式信息.json.txt`。
- 已有同名款式时，图片仍然跳过，但款式信息会按文件**整体替换**，预览中显示为“更新款式信息”。所以只放 `款式信息.json` 的文件夹也能导入，用来给已有款式批量补信息。
- 格式错误、空文件或位置不对的信息文件会列在无效文件中，不影响图片导入。

## 以图搜图

一次添加 1～6 张照片，可点击选择、拖入页面任意位置或 Ctrl+V 粘贴。添加、移除或框选后自动搜索，无需再点按钮。点击查询图片可框选目标：拖动画框，拖动框内移动位置，单击空白处恢复整图；框选窗口中 ← → 切换照片，Enter 完成。完全相同的查询内容只参与一次。

结果按相似度排名。点击结果打开对比视图，左侧是查询图片及各角度得分，右侧是该款式的展示图：← → 切换展示图，↑ ↓ 切换款式，Esc 关闭。展示图和“我的图库”中的图片都可以“用这张图搜索”。切换页面后查询图片和结果保留。界面跟随系统浅色/深色模式。

采用 DINOv3 ViT-S/16 本地特征、白边裁剪及等比例补边，输入 448×448。特征为 CLS 与图块均值拼接（跳过 4 个 register token）。每张查询图与每款全部识别图计算余弦相似度，取该查询图的最佳参考得分，再平均各查询图得分。每款只返回一次，默认取前 12 款。显示的相似度是余弦分数乘以 100，不是型号确认概率，也没有“同款”自动判定阈值。

查询文件仅在当次请求中处理，不写入图库或搜索历史。数据库持久化识别图片向量，使用 NumPy 精确搜索。模型/预处理版本变化后旧向量失效并重新排队。

## 数据与接口

默认数据目录为 `data/`：`compfinder.db`、`images/`、`models/`。停止服务后备份整个 `data/` 可保留图库。数据库和图片不提交版本库。

环境变量：

- `COMPFINDER_DATA_DIR`：自定义数据目录。
- `COMPFINDER_MODEL_PATH`：自定义 `model.onnx` 位置，`model.onnx_data` 须在同一目录。
- `HF_ENDPOINT`、`HF_TOKEN`：仅安装脚本下载模型时使用，分别指定镜像地址和访问令牌。
- `COMPFINDER_TOKEN`：自定义访问令牌（至少 16 个字符）；不设置时使用 `data/access-token.txt`。

网页、接口和接口文档都需要网页登录令牌，持有者拥有全部权限；MCP 使用单独的、可限定工具的 MCP 令牌（见下文）。普通浏览与管理是工作流分区，不是多用户授权系统。

接口文档：`http://127.0.0.1:8010/docs`（需先在网页登录）。

| 接口 | 作用 |
|---|---|
| `POST /api/search` | multipart 重复 `files` 字段；`crops` 为等长 JSON 数组，未框选使用 null；`limit` 默认 12（界面使用 24）。响应含 `items`（每项 `similarity` 与按去重查询排列的 `scores`）、`queryIndex`（每个上传文件对应的去重查询序号）、`queryCount`、`elapsedMs` |
| `GET /api/styles`、`/api/styles/{id}` | 仅可检索款式、展示图及款式信息 `info`；`q` 同时匹配名称和款式信息 |
| `GET /api/images/{id}` | 仅展示图片，`thumbnail=true` 返回缩略图 |
| `/api/admin/styles` | 创建、读取、改名、排序、封面、款式信息和删除；`PATCH` 的 `info` 为 `{params: [{name, value}], visual: [{name, value}], notes}`，整体替换，空行自动去除 |
| `POST /api/admin/styles/{id}/images` | `role` 指定 display 或 recognition，`file` 上传一张图片 |
| `/api/admin/images/{id}` | 管理预览或删除图片 |
| `/api/admin/imports` | 清单预览、任务创建、逐文件上传、完成与最近记录；请求体为 `{paths, infos}`，`infos` 以相对路径为键、`款式信息.json` 的文本为值 |
| `GET /api/admin/index`、`POST /api/admin/index/retry` | 图片索引状态和失败重试 |
| `POST /api/uploads` | 上传一张图片暂存 1 小时，返回 `upload:<id>`，供 MCP 工具引用；网页登录令牌或任一启用的 MCP 令牌均可调用 |
| `/api/admin/tokens` | MCP 令牌增删改查：`GET` 列表（含工具目录）、`POST` 新建 `{name, tools, secret?}`、`PATCH /{id}` 修改 `{name?, tools?, secret?, enabled?}`、`DELETE /{id}` |
| `/api/auth/login`、`/logout`、`/status` | 网页登录（设置 Cookie）、退出、登录状态 |
| `POST /mcp` | MCP 接口，见“AI 建档（MCP）” |

普通接口不返回识别图片 ID、文件名或地址。普通图片接口对识别图返回 404。图片目录没有挂载为公共静态目录。图片 ID 不复用、文件不改写，因此图片响应带长期私有缓存头。

## 访问令牌与公网访问

令牌分两种：

- **网页登录令牌**：登录网页和调用接口用，拥有全部权限。首次启动自动生成，保存在 `data/access-token.txt`，启动窗口也会显示；也可以用环境变量 `COMPFINDER_TOKEN` 自己指定。
- **MCP 令牌**：给 AI 客户端用，在网页“AI 接入”页管理，见“AI 建档（MCP）”。

网页登录令牌的用法：

- 网页：第一次打开会要求输入令牌，之后 30 天内这个浏览器免登录（Cookie）；右上角可以退出。
- 接口和脚本：请求头带 `Authorization: Bearer <令牌>`。`scripts/evaluate.py` 会自动读取令牌文件。
- 换令牌：改 `data/access-token.txt`（或环境变量）后重启，所有浏览器需要重新登录。

默认只允许本机访问。要让其他电脑或公网访问：

```powershell
.\scripts\start.ps1 -Public
```

服务会监听所有网卡的 8010 端口。Windows 第一次会弹出防火墙提示，需要允许；公网访问还需要路由器端口转发，或者部署在有公网地址的服务器上。

**公网一定要套 HTTPS。** 直接用 HTTP，令牌会在网络上明文传输。推荐在同一台机器上用 [Caddy](https://caddyserver.com/) 做反向代理，它会自动申请证书。这时服务保持默认本机监听即可，不需要 `-Public`：

```text
# Caddyfile
compfinder.example.com {
    reverse_proxy 127.0.0.1:8010
}
```

## AI 建档（MCP）

`/mcp` 是标准 MCP 接口（Streamable HTTP，无状态），用请求头 `Authorization: Bearer <MCP 令牌>` 认证。AI 可以以图搜图、读取商品网页、查看图片、新建款式、加图和写款式信息，不能删除。

### MCP 令牌

在网页“AI 接入”页管理，支持增删改查：

- **新建**：填名称，勾选可用工具（可一键选“全部”或“只读”），令牌留空则自动生成。
- **查看和复制**：令牌默认打码，可显示、复制；还能直接复制带令牌的 Claude Code 命令和 JSON 配置。
- **修改**：改名称、可用工具或令牌本身（手填或随机生成，至少 24 个字符）。改令牌后旧令牌立即失效。
- **停用 / 启用、删除**：停用或删除后，使用它的 AI 客户端立刻无法连接。
- 每个令牌显示创建时间和最近使用时间。

权限按工具控制：AI 用 `tools/list` 只能看到这个令牌允许的工具，调用其他工具会被拒绝。网页登录令牌不能用于 MCP；MCP 令牌也不能访问网页和其他接口，只能额外调用 `/api/uploads` 暂存图片。

令牌保存在数据库 `mcp_tokens` 表中。为了能再次复制，令牌以原文保存，校验时按哈希匹配；请像对待 `data/` 里的其他数据一样保护数据库文件。

| 工具 | 作用 |
|---|---|
| `search_by_image` | 1～6 张图片以图搜图，返回候选、相似度、款式信息和前 4 名封面缩略图 |
| `read_page` | 读取公开网页的标题、正文和图片地址（含页面脚本里的商品图） |
| `preview_image` | 查看图片（可带框选），确认是否同款、怎么框选 |
| `visual_taxonomy` | ytst 轻触开关规范 v1.1 的视觉字段和可选值 |
| `list_styles`、`get_style` | 查找款式、查看详情和缩略图 |
| `create_style` | 新建款式，可同时写参数、视觉信息和备注 |
| `add_images` | 按链接加展示图或识别图，每次 1～20 张，可框选，逐张返回结果 |
| `update_style_info` | 只替换传入的部分（visual、params、notes） |
| `library_status` | 款式数和索引进度 |

图片来源可以是：公网 `http(s)` 链接（服务器去下载，不允许访问内网和本机地址）、`data:image/...;base64,...`，或先 `POST /api/uploads` 上传得到的 `upload:<id>`。

视觉信息通过 MCP 写入时，字段名和取值必须符合 ytst 规范 v1.1（`backend/compfinder/tactile_taxonomy_v1_1.json`，复制自 ytst），不符合会报错并列出可选值。网页编辑和文件导入不做强制。

连接方式（把地址和令牌换成自己的；“AI 接入”页可以直接复制前两种）：

```powershell
# Claude Code
claude mcp add --transport http compfinder https://compfinder.example.com/mcp --header "Authorization: Bearer <MCP 令牌>"
```

```json
// Cursor 等支持 HTTP 和请求头的客户端（mcp.json）
{ "mcpServers": { "compfinder": { "url": "https://compfinder.example.com/mcp", "headers": { "Authorization": "Bearer <MCP 令牌>" } } } }
```

```json
// Claude Desktop 等只支持本地进程的客户端，用 mcp-remote 转接（需要 Node.js）
{ "mcpServers": { "compfinder": { "command": "npx", "args": ["-y", "mcp-remote", "https://compfinder.example.com/mcp", "--header", "Authorization: Bearer <MCP 令牌>"] } } }
```

claude.ai 网页版的自定义连接器要求 OAuth 登录，目前不支持这种固定令牌。

### 建档技能（Skill）

`skills/compfinder-library/SKILL.md` 教 AI 按固定流程建档：

- 给一张图片：先以图搜图查重，再按规范识别视觉信息；这张图作为展示图，同时上网找同款图片，核对、框选后作为识别图，最后建立款式。
- 给一个商品网址：读取页面里的型号、参数和图片，主图作为展示图，其余同款图片和搜到的图作为识别图，最后建立款式。

安装：

- Claude Code：把 `skills/compfinder-library` 文件夹复制到 `~/.claude/skills/`（所有项目可用），或复制到项目的 `.claude/skills/`。
- Claude Desktop / claude.ai：把这个文件夹压缩成 zip，在设置的技能（Skills）页面上传。

找同款图片需要 AI 客户端自带网页搜索；没有网页搜索时，只能使用页面里自带的图片。AI 建的档案会在备注里注明来源和“AI 建档，待人工复核”，建议定期在网页上复核。

## 开发与验证

```powershell
# 后端开发，单进程运行（后台索引队列每实例一个）
.\.venv\Scripts\python.exe -m uvicorn compfinder.api:app --host 127.0.0.1 --port 8010
# 另一个终端运行前端
cd frontend
npm run dev
# 访问 http://127.0.0.1:5180
```

```powershell
.\.venv\Scripts\python.exe -m pytest backend/tests -q
cd frontend
npm test
npm run build
```

测试说明及真实照片评估方法见 [docs/validation.md](docs/validation.md)。
