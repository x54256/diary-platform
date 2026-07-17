# 语音日记录入功能设计

> 状态：已确认设计  
> 日期：2026-07-17  
> 适用模块：日记录入、Fun-ASR 录音文件识别

## 1. 背景

当前日记录入页只支持手工输入文本。用户希望上传一段或多段录音，由语音识别模型转成文本，并在整批录音全部处理成功后由后台自动创建正式日记。

本功能使用阿里云百炼 `fun-asr` 录音文件识别 HTTP API，不使用 Python SDK。

## 2. 目标

- 支持在现有日记输入框中混合使用手工文字和语音转写文本。
- 支持一次选择任意数量的录音文件，单文件最大 300 MB。
- 同一批次最多并行转写 3 段，其余录音排队。
- 只有整批有效录音全部成功时，后台才创建正式日记。
- 后台保存不依赖页面是否停留、是否轮询或是否模拟点击保存。
- 失败项支持手动重试、删除；整批支持取消。
- 服务重启后能够恢复尚未完成的任务。
- 转写成功后删除原始音频，只保留最终文本。

## 3. 非目标

- 不支持浏览器直接录音。
- 不把音频作为正式日记附件长期保存。
- 不在日记详情页提供音频播放。
- 不增加日记草稿状态。
- 不支持实时流式识别。
- 第一版不启用说话人分离、热词和敏感词过滤。
- 不使用 DashScope Python SDK。
- 不改变无语音场景下现有的手工保存流程。

## 4. 核心概念

### 4.1 语音处理批次

语音处理批次表示一次“原输入文字 + 多段录音”的后台处理任务。

批次不是日记草稿：

- 它不出现在日记列表、日历和搜索结果中。
- 它不能进入 AI 整理或分析。
- 它只保存完成本次后台任务所需的输入快照、音频项状态和最终结果。
- 只有批次全部成功后，系统才创建一条现有 `diaries` 表中的正式日记。

### 4.2 原输入文字

用户点击“开始转写”时，系统固定当前日期和输入框文字。该文本记为 `base_text`。

后台最终保存的 `original_text` 为：

```text
base_text

第 1 段录音转写文本

第 2 段录音转写文本
```

空文本片段不参与拼接，每个非空片段之间插入两个换行符。

### 4.3 日期锁

同一用户、同一日记日期，同一时间只能存在一个已开始处理且未结束的批次。

- 当前日期处理中时，该日期的录入页只读。
- 用户可以返回日记首页，再进入其他日期继续记录。
- 批次完成、取消或过期后释放日期锁。
- 日期锁只限制处理中批次，不改变“一天可以创建多篇正式日记”的现有规则。

## 5. 用户流程

### 5.1 无语音

保持现有逻辑：

1. 用户输入文字。
2. 用户点击“保存”。
3. 前端调用现有 `POST /api/diaries`。
4. 创建正式日记并进入详情页。

### 5.2 语音批次全部成功

1. 用户选择一个或多个音频文件。
2. 页面逐个上传文件到本系统临时目录，展示上传进度。
3. 所有文件上传成功后，“开始转写”按钮可用。
4. 用户点击“开始转写”。
5. 后端固定 `diary_date` 和 `base_text`，批次进入排队状态。
6. 当前日期页面进入只读状态；用户可以返回其他页面。
7. 后端最多并行处理 3 个音频项。
8. 所有有效音频项成功后，后端在事务中创建正式日记。
9. 后端删除临时音频，批次记录创建出的 `diary_id`。
10. 用户仍在页面时，前端轮询到完成状态，更新页面文本并进入日记详情页。
11. 用户已经离开时不影响保存，新日记直接出现在列表和日历中。

### 5.3 存在失败项

1. 任意音频项失败后，批次进入 `PARTIAL_FAILED`。
2. 成功项保存转写文本，但整批文本不写入输入框，也不创建日记。
3. 成功项对应的临时音频立即删除。
4. 失败项临时音频保留 7 天。
5. 用户可以：
   - 手动重试失败项；
   - 删除失败项；
   - 取消整批。
6. 重试或删除后，只要剩余音频项至少有一项成功且全部为成功状态，后台立即创建正式日记。
7. 如果删除后不存在任何成功音频项，则取消批次，不因 `base_text` 单独触发自动保存。

### 5.4 取消整批

取消时：

- 不创建日记。
- 删除所有临时音频。
- 终止尚未提交给 Fun-ASR 的排队项。
- 对已经提交给 Fun-ASR 的任务停止本地轮询；如果提供方任务仍在执行，其结果不再使用。
- 返回 `base_text` 和 `diary_date`，供当前页面恢复原输入。
- 释放日期锁。

### 5.5 失败批次过期

- 失败音频保留 7 天供用户重试。
- 超过 7 天后，批次进入 `EXPIRED`。
- 删除临时音频、转写文本和原输入文字等敏感业务数据，仅保留必要的任务审计字段。
- 释放日期锁。

其他清理规则：

- 未点击“开始转写”的 `COLLECTING` 批次超过 24 小时后删除文件和批次。
- `COMPLETED`、`CANCELLED`、`EXPIRED` 批次只保留不含正文的任务元数据 30 天，之后物理删除。
- 正式日记创建成功后，正文以 `diaries.original_text` 为唯一正式存储；批次中的 `base_text` 和音频项转写文本随临时文件一起清除。

## 6. 页面设计

### 6.1 正常录入状态

现有输入框底部增加“添加语音”入口，下面展示临时音频卡片：

- 文件名；
- 文件大小；
- 上传进度；
- 上传成功状态；
- 删除按钮。

全部文件上传成功后显示“开始转写（N）”。

### 6.2 当前日期处理中

- 保留顶部返回按钮。
- 不增加“切换日期”按钮。
- 日期、输入框和语音上传入口只读。
- 显示“该日期正在后台生成日记，其他日期不受影响”。
- 显示每个音频项的排队、转写和成功状态。
- 返回页面不会取消后台任务。

### 6.3 部分失败

- 顶部明确提示“尚未写入正文，也没有创建正式日记”。
- 成功项显示成功状态和只读文本预览。
- 失败项显示错误摘要、重试和删除按钮。
- 提供“重试失败项”和“取消整批并恢复原输入”。
- 页面说明失败音频保留 7 天。

### 6.4 后台保存成功

- 后台创建日记成功后，批次已持有 `diary_id`。
- 页面仍打开时根据 `diary_id` 读取正式日记，同步最终文本状态，再使用替换导航进入 `/diary/{diary_id}`。
- 页面不调用现有日记创建接口，不模拟点击保存，不重复提交正文。

### 6.5 页面状态获取

第一版采用轮询，不使用 WebSocket：

- 处理中：每 2 秒查询一次。
- 页面不可见时：暂停轮询。
- 页面恢复可见时：立即查询一次。
- 批次进入终态后停止轮询。
- 轮询只负责展示，后台任务和正式日记创建不依赖轮询。

## 7. 文件规则

### 7.1 文件限制

- 单文件最大 300 MB，即 `314572800` 字节。
- 页面不限制文件数量。
- 产品不额外限制音频时长；Fun-ASR 自身最大支持 12 小时，超过后按模型失败处理。
- 支持格式：`aac`、`amr`、`avi`、`flac`、`flv`、`m4a`、`mkv`、`mov`、`mp3`、`mp4`、`mpeg`、`ogg`、`opus`、`wav`、`webm`、`wma`、`wmv`。
- 后端同时校验扩展名、Content-Type 和实际文件大小；扩展名与 Content-Type 仅用于快速拒绝，Fun-ASR 识别结果是最终格式判定依据。

### 7.2 上传策略

- 文件选择后立即上传到本系统服务器，不消耗模型额度。
- 每个文件独立请求，避免多文件总大小导致单次请求过大。
- 上传使用流式分块写入临时目录，不把整个 300 MB 文件读入内存。
- 上传前和写入过程中检查剩余磁盘空间。
- 磁盘空间不足返回 `507 Insufficient Storage`。
- 页面数量不设上限，但磁盘容量是硬性安全边界。

### 7.3 临时存储

- 默认路径：`/app/data/transcriptions`。
- 该目录必须挂载持久化卷。
- 文件名使用服务端生成的 UUID，不使用用户原文件名作为磁盘路径。
- 原文件名只保存为展示信息。
- 禁止路径穿越和任意路径读取。

## 8. Fun-ASR HTTP API 对接

### 8.1 选择 HTTP API 的原因

- 项目已有 `httpx`，无需引入 `dashscope`。
- `httpx.AsyncClient` 与 FastAPI 异步任务模型一致。
- Python SDK 的 `async_call`、`fetch`、`wait` 是同步调用，直接使用会阻塞事件循环。
- SDK 不消除文件 URL、任务持久化、轮询、重试和清理等核心复杂度。
- HTTP 方式可以完整控制请求头、超时、错误响应和请求日志。

### 8.2 服务封装

新增 `FunAsrService`，只承担提供方协议适配：

```text
submit(file_url, parameters) -> provider_task_id
query(provider_task_id) -> provider_status/result_url/error
fetch_result(result_url) -> transcript_text/metadata
```

业务批次、并发、重试、日期锁和日记创建不放入该服务。

### 8.3 提交任务

```http
POST https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1/services/audio/asr/transcription
Authorization: Bearer {DASHSCOPE_API_KEY}
Content-Type: application/json
X-DashScope-Async: enable
```

请求体：

```json
{
  "model": "fun-asr",
  "input": {
    "file_urls": [
      "http://公网地址/diary/api/transcription-files/{token}"
    ]
  },
  "parameters": {
    "channel_id": [0],
    "language_hints": ["zh"],
    "diarization_enabled": false
  }
}
```

单个 Fun-ASR 请求只包含一个文件 URL。

### 8.4 查询任务

```http
GET https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/api/v1/tasks/{provider_task_id}
Authorization: Bearer {DASHSCOPE_API_KEY}
```

提供方状态映射：

| Fun-ASR 状态 | 本地音频项状态 |
|---|---|
| `PENDING` | `SUBMITTED` |
| `RUNNING` | `RUNNING` |
| `SUCCEEDED` | 下载结果后转为 `SUCCEEDED` |
| `FAILED` | `FAILED` |

查询结果中的 `transcription_url` 只有 24 小时有效。查询到成功后必须立即下载并解析结果，不能把该 URL 作为长期数据保存。

### 8.5 结果解析

从结果 JSON 中按音轨顺序读取：

```text
transcripts[].text
```

本功能默认只请求 `channel_id: [0]`。多个非空 `text` 使用换行拼接。

如果最终文本为空，则将音频项标记为失败，错误码使用本地 `NO_SPEECH_TEXT`，不参与自动保存。

### 8.6 超时和重试

- 提交请求连接超时：10 秒；读取超时：30 秒。
- 查询请求连接超时：10 秒；读取超时：30 秒。
- 结果文件下载读取超时：120 秒。
- 查询请求和结果下载发生网络错误或 HTTP `429/5xx` 时，使用指数退避重试，最多 3 次。
- 提交请求只有在连接尚未建立时才允许自动重试。提交后发生读取超时无法判断提供方是否已经受理，必须标记为 `FAILED/SUBMIT_RESULT_UNKNOWN`，不能自动再次提交，避免重复计费。
- 进程在 `SUBMITTING` 状态退出且尚未持久化 `provider_task_id` 时，同样无法证明提供方未受理；启动恢复时必须标记为 `FAILED/SUBMIT_RESULT_UNKNOWN`，由用户明确触发重试。
- 提交接口明确返回 `429/5xx` 时允许按响应状态自动重试，最多 3 次。
- 业务失败、格式错误和 `4xx` 参数错误不自动重复消耗额度。
- 用户点击重试时复用保留的失败音频，生成新的下载令牌和新的提供方任务 ID。
- 每次重试增加 `retry_count`，历史错误摘要保留在日志中。

## 9. 临时文件下载接口

### 9.1 地址

```http
GET /diary/api/transcription-files/{token}
```

该接口由 Fun-ASR 服务器访问，不能要求用户 JWT。

### 9.2 安全规则

- 令牌使用至少 256 位安全随机数。
- 数据库只保存令牌哈希，不保存明文。
- 令牌只对应一个音频项。
- 令牌仅在音频项真正获得并发槽、准备提交 Fun-ASR 时生成。
- 令牌最长有效 24 小时；任务终止或音频删除时立即失效。
- 接口只允许 `GET` 和 `HEAD`。
- 禁止目录列表、路径参数和任意文件名访问。
- 访问日志不得记录完整令牌。
- Nginx 对该下载 location 关闭访问日志，避免默认日志记录完整 URL 令牌。

### 9.3 大文件传输

300 MB 文件不通过 Python 循环传输。推荐流程：

1. FastAPI 校验令牌、音频项状态和文件存在性。
2. FastAPI 返回 `X-Accel-Redirect`。
3. Nginx 内部 location 读取持久化目录中的文件。
4. 外部请求不能直接访问内部 location。

该方式降低 Python 进程内存和连接占用，并由 Nginx 处理 Range 请求。

HTTP 可以满足 Fun-ASR 的协议要求，但录音属于隐私数据，生产环境迁移到 HTTPS 时不需要改变业务接口。

## 10. 数据模型

### 10.1 `transcription_batches`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | 批次 ID |
| `user_id` | UUID FK | 所属用户 |
| `diary_date` | DATE NULL | 开始转写时固定的日记日期；收集文件阶段为空 |
| `base_text` | TEXT NULL | 开始转写时的输入文字；终态清理后为空 |
| `status` | VARCHAR(30) | 批次状态 |
| `diary_id` | UUID FK NULL | 后台创建的正式日记 ID |
| `error_message` | TEXT NULL | 批次级错误摘要 |
| `started_at` | TIMESTAMP NULL | 开始处理时间 |
| `completed_at` | TIMESTAMP NULL | 完成时间 |
| `expires_at` | TIMESTAMP NULL | 失败批次过期时间 |
| `created_at` | TIMESTAMP | 创建时间 |
| `updated_at` | TIMESTAMP | 更新时间 |

批次状态：

| 状态 | 含义 |
|---|---|
| `COLLECTING` | 文件上传阶段，尚未消耗模型额度 |
| `QUEUED` | 已点击开始转写，等待本地并发槽 |
| `PROCESSING` | 至少一个音频项已提交或运行中 |
| `PARTIAL_FAILED` | 所有项已结束且至少一个失败 |
| `FINALIZING` | 正在事务内创建正式日记 |
| `COMPLETED` | 正式日记已创建 |
| `CANCELLED` | 用户取消 |
| `EXPIRED` | 失败批次超过保留期 |

约束和索引：

```sql
CREATE UNIQUE INDEX uq_transcription_batch_diary
ON transcription_batches (diary_id)
WHERE diary_id IS NOT NULL;

CREATE UNIQUE INDEX uq_transcription_active_user_date
ON transcription_batches (user_id, diary_date)
WHERE status IN ('QUEUED', 'PROCESSING', 'PARTIAL_FAILED', 'FINALIZING');
```

另建索引：

```sql
INDEX (user_id, diary_date, created_at DESC)
INDEX (status, updated_at)
INDEX (expires_at) WHERE status = 'PARTIAL_FAILED'
```

### 10.2 `transcription_items`

| 字段 | 类型 | 说明 |
|---|---|---|
| `id` | UUID PK | 音频项 ID |
| `batch_id` | UUID FK | 所属批次，删除批次时级联删除 |
| `sort_order` | INTEGER | 用户选择顺序 |
| `original_filename` | VARCHAR(255) | 展示用原文件名 |
| `content_type` | VARCHAR(100) | 上传 Content-Type |
| `file_size` | BIGINT | 实际文件大小 |
| `storage_path` | TEXT NULL | 服务端内部路径 |
| `status` | VARCHAR(30) | 音频项状态 |
| `provider_task_id` | VARCHAR(100) NULL | Fun-ASR 任务 ID |
| `access_token_hash` | VARCHAR(128) NULL | 下载令牌哈希 |
| `access_expires_at` | TIMESTAMP NULL | 下载令牌过期时间 |
| `transcript_text` | TEXT NULL | 成功转写文本 |
| `provider_request_id` | VARCHAR(100) NULL | 提供方请求 ID |
| `error_code` | VARCHAR(100) NULL | 错误码 |
| `error_message` | TEXT NULL | 用户可理解的错误摘要 |
| `retry_count` | INTEGER | 手动重试次数，默认 0 |
| `created_at` | TIMESTAMP | 创建时间 |
| `updated_at` | TIMESTAMP | 更新时间 |

音频项状态：

```text
UPLOADING
UPLOADED
QUEUED
SUBMITTING
SUBMITTED
RUNNING
SUCCEEDED
FAILED
DELETED
```

约束和索引：

```sql
UNIQUE (batch_id, sort_order)
UNIQUE (provider_task_id) WHERE provider_task_id IS NOT NULL
INDEX (batch_id, status, sort_order)
INDEX (status, updated_at)
```

## 11. 正式日记创建的一致性

### 11.1 创建条件

同时满足以下条件才允许创建正式日记：

- 批次状态为 `PROCESSING` 或 `PARTIAL_FAILED`；
- 不存在排队、提交中或运行中的音频项；
- 不存在失败音频项；
- 至少存在一个成功音频项；
- `diary_id` 为空。

### 11.2 原子事务

最终化必须在单个数据库事务内完成：

1. 使用 `SELECT ... FOR UPDATE` 锁定批次记录。
2. 重新检查全部创建条件。
3. 按 `sort_order` 读取成功文本。
4. 拼接 `base_text` 和转写文本。
5. 创建 `Diary(status=saved)`。
6. 将新日记 ID 写入批次 `diary_id`。
7. 清除批次 `base_text` 及音频项 `transcript_text`，正式正文只保存在日记中。
8. 将批次改为 `COMPLETED`。
9. 提交事务。

临时文件删除发生在事务提交之后。删除失败只记录告警并由清理任务再次处理，不能回滚已经创建的正式日记。

该设计保证：

- 页面重复轮询不会重复创建日记；
- 多个后台协程同时发现完成状态不会重复创建日记；
- 服务在创建过程中重启后可以根据 `diary_id` 恢复；
- 文件清理失败不影响业务结果。

## 12. 后台调度与重启恢复

### 12.1 并发模型

- 应用级 Fun-ASR 并发上限为 3。
- 并发单位是单个音频项，不是批次。
- 多个日期、多个批次共享同一个并发池。
- 批次内音频项允许并行完成，但最终正文始终按 `sort_order` 排序。

### 12.2 调度循环

后台调度器负责：

- 获取 `QUEUED` 音频项；
- 申请并发槽；
- 生成临时下载令牌；
- 提交 Fun-ASR；
- 周期查询提供方状态；
- 下载成功结果；
- 更新本地状态；
- 判断批次是否可以最终化。

调度器更新音频项或最终化批次前，必须在事务内重新锁定并检查批次状态。批次已变为 `CANCELLED` 或 `EXPIRED` 时，丢弃迟到的提供方结果，不再写入转写文本或创建日记。

### 12.3 启动恢复

应用启动时执行：

- `QUEUED`：重新进入调度队列；
- `SUBMITTING` 且没有 `provider_task_id`：标记为 `FAILED/SUBMIT_RESULT_UNKNOWN`，禁止自动重新提交；
- `SUBMITTED/RUNNING`：使用已有 `provider_task_id` 恢复查询；
- `FINALIZING` 且 `diary_id` 为空：重新执行最终化事务；
- `COMPLETED`：补偿清理残留文件；
- `PARTIAL_FAILED`：保持可重试状态；
- 过期批次：执行过期清理。

## 13. 本系统 API 设计

所有批次管理接口都要求用户 JWT，并校验资源属于当前用户。临时文件下载接口除外。

### 13.1 创建上传批次

```http
POST /api/transcription-batches
```

该接口不创建日记、不保存输入框文字、不锁定日期。返回批次 ID，状态为 `COLLECTING`。

### 13.2 上传音频项

```http
POST /api/transcription-batches/{batch_id}/items
Content-Type: multipart/form-data
```

字段：

- `file`：单个音频文件；
- `sort_order`：用户选择顺序。

### 13.3 删除未开始音频项

```http
DELETE /api/transcription-batches/{batch_id}/items/{item_id}
```

只允许删除 `UPLOADED` 或 `FAILED` 项。删除失败项后立即重新判断是否可以最终化。

### 13.4 开始转写

```http
POST /api/transcription-batches/{batch_id}/start
```

请求：

```json
{
  "diary_date": "2026-07-17",
  "base_text": "今天上午完成了项目汇报。"
}
```

规则：

- 至少存在一个 `UPLOADED` 音频项；
- 不存在上传中的项目；
- 获取同用户、同日期的处理锁；
- 状态改为 `QUEUED` 后立即返回 `202 Accepted`；
- 后台继续执行，不保持长 HTTP 连接。

### 13.5 查询批次

```http
GET /api/transcription-batches/{batch_id}
```

返回批次、音频项和 `diary_id`。完成后前端通过现有日记详情接口读取正式正文。

### 13.6 查询日期活动批次

```http
GET /api/transcription-batches/active?diary_date=2026-07-17
```

进入录入页时调用，用于判断当前日期是否只读并恢复任务展示。

### 13.7 重试失败项

```http
POST /api/transcription-batches/{batch_id}/items/{item_id}/retry
```

规则：

- 只允许 `FAILED`；
- 必须仍在 7 天保留期内；
- 临时文件必须存在；
- 清除当前提供方错误和任务 ID；
- `retry_count + 1`；
- 音频项重新进入 `QUEUED`，批次从 `PARTIAL_FAILED` 切回 `PROCESSING`。

### 13.8 重试全部失败项

```http
POST /api/transcription-batches/{batch_id}/retry-failed
```

一次把所有可重试失败项放回队列。

### 13.9 取消批次

```http
POST /api/transcription-batches/{batch_id}/cancel
```

返回：

```json
{
  "diary_date": "2026-07-17",
  "base_text": "今天上午完成了项目汇报。",
  "status": "CANCELLED"
}
```

服务端先构造响应，再清除数据库中的 `base_text` 和音频项转写文本；取消后的批次只保留不含正文的任务元数据。

取消操作使用事务锁定批次并原子写入 `CANCELLED`。已经进入 `FINALIZING` 且正式日记事务已开始的批次不允许取消；接口返回 `409`，前端随后查询批次并进入已创建的日记。该约束避免“取消成功”和“正式日记创建成功”同时发生。

### 13.10 临时文件下载

```http
GET /api/transcription-files/{token}
```

该接口不接受用户 JWT，只校验高强度随机令牌。

## 14. 统一响应状态

前端主要依据以下字段渲染：

```json
{
  "id": "batch-uuid",
  "diary_date": "2026-07-17",
  "status": "PROCESSING",
  "diary_id": null,
  "items": [
    {
      "id": "item-uuid",
      "sort_order": 0,
      "filename": "voice.m4a",
      "file_size": 123456,
      "status": "RUNNING",
      "transcript_preview": null,
      "error_code": null,
      "error_message": null,
      "retry_count": 0
    }
  ]
}
```

服务端不得返回：

- `storage_path`；
- 下载令牌及其哈希；
- 完整提供方响应；
- API Key。

## 15. 错误处理

| 场景 | HTTP/状态 | 用户提示 |
|---|---|---|
| 文件超过 300 MB | `413` | 单个音频不能超过 300 MB |
| 格式不支持 | `415` | 不支持该音频格式 |
| 磁盘空间不足 | `507` | 服务器存储空间不足，请稍后再试 |
| 同日期已有处理中批次 | `409` | 该日期正在生成日记 |
| 批次已开始后重复开始 | `409` | 当前批次已经开始处理 |
| 音频仍在上传 | `409` | 请等待全部音频上传完成 |
| Fun-ASR 限流 | 音频项保持排队或失败 | 服务繁忙，可稍后重试 |
| Fun-ASR 无法下载文件 | `FAILED` | 语音文件读取失败，请重试 |
| 识别结果为空 | `FAILED` | 未识别到有效语音 |
| 失败项已过期 | `410` | 语音已过期，请重新上传 |
| 批次不存在或不属于用户 | `404` | 任务不存在 |

错误日志必须记录本地批次 ID、音频项 ID、提供方任务 ID和请求 ID，不记录 API Key、下载令牌和完整日记文本。

## 16. 配置项

```env
DASHSCOPE_API_KEY=
DASHSCOPE_WORKSPACE_ID=
DASHSCOPE_REGION=cn-beijing
TRANSCRIPTION_PUBLIC_BASE_URL=http://public-host
TRANSCRIPTION_STORAGE_PATH=/app/data/transcriptions
TRANSCRIPTION_MAX_FILE_SIZE=314572800
TRANSCRIPTION_MAX_CONCURRENCY=3
TRANSCRIPTION_FAILED_RETENTION_DAYS=7
TRANSCRIPTION_DOWNLOAD_TOKEN_HOURS=24
```

`TRANSCRIPTION_PUBLIC_BASE_URL` 必须从阿里云公网可访问，不能使用 `localhost`、`127.0.0.1` 或内网地址。

## 17. Nginx 与部署调整

### 17.1 上传限制

当前 Nginx：

```nginx
client_max_body_size 100m;
```

需调整为：

```nginx
client_max_body_size 320m;
```

### 17.2 超时

上传接口单独配置足够的读取和发送超时，避免影响普通 API。普通日记接口继续使用现有超时策略。

### 17.3 内部文件 location

新增仅供 `X-Accel-Redirect` 使用的内部 location，映射持久化音频目录。该 location 不允许外部直接访问。

### 17.4 持久化卷

容器必须把宿主机或 Docker Volume 挂载到：

```text
/app/data/transcriptions
```

没有持久化卷时，容器重启恢复只剩数据库状态，音频文件会丢失，不满足已确认需求。

## 18. 代码结构建议

```text
backend/
├── models/transcription.py
├── schemas/transcription.py
├── routers/transcriptions.py
├── services/fun_asr.py
├── services/transcription_tasks.py
└── migrations/011_voice_transcription.sql

frontend/
├── components/VoiceUploadPanel.vue
├── components/VoiceTranscriptionItem.vue
├── composables/useVoiceTranscription.ts
└── pages/diary/new.vue
```

职责：

- `fun_asr.py`：只封装阿里云 HTTP 协议。
- `transcription_tasks.py`：批次调度、并发、轮询、恢复、最终化和清理。
- `transcriptions.py`：鉴权、输入校验和 REST 接口。
- `useVoiceTranscription.ts`：前端上传、轮询和页面状态协调。

## 19. 测试设计

### 19.1 后端单元测试

- 单文件上传大小边界：`300 MB` 允许，超过 1 字节拒绝。
- 不支持格式拒绝。
- Fun-ASR 提交请求头和请求体正确。
- 提供方状态映射正确。
- 结果 JSON 正确提取 `transcripts[].text`。
- 空转写结果标记失败。
- 并发槽最多为 3。
- 多音频完成顺序不同，最终文本仍按 `sort_order` 拼接。
- 任意失败时不创建日记。
- 重试成功后自动创建日记。
- 删除失败项后自动创建日记。
- 删除全部音频后不因 `base_text` 自动创建日记。
- 取消批次不创建日记并释放日期锁。
- 失败项 7 天后过期清理。
- 同用户同日期并发开始只允许一个成功。
- 不同日期允许同时处理。
- 最终化被重复调用只创建一条日记。
- 文件删除失败不回滚正式日记。
- 服务重启后各状态恢复正确。
- 用户不能读取、重试或取消其他用户的批次。
- 临时下载令牌错误、过期、失效时拒绝访问。

### 19.2 前端测试

- 上传进度和错误正确展示。
- 全部上传成功前不能开始转写。
- 当前日期处理中页面只读并保留返回按钮。
- 页面返回后重新进入能恢复批次状态。
- 页面不可见时暂停轮询，恢复时立即刷新。
- 部分失败时正文不变化。
- 重试、删除和取消按钮状态正确。
- 完成后使用后端返回的 `diary_id` 进入详情页。
- 完成后前端不再调用 `POST /api/diaries`。

### 19.3 集成验收

1. 输入一段文字并上传两段录音。
2. 点击开始转写后立即返回首页。
3. 进入其他日期创建普通日记，操作不受影响。
4. 等待原批次全部成功。
5. 原日期新增一篇正式日记，正文顺序正确。
6. 重复刷新和重启服务均不会重复创建日记。

失败场景：

1. 上传三段录音，使其中一段转写失败。
2. 确认没有创建正式日记。
3. 确认两段成功文本未写入正文。
4. 手动重试失败项。
5. 全部成功后只创建一篇正式日记。

## 20. 安全与隐私

- API Key 只存在后端环境变量中。
- 用户音频不写入日志。
- 日记正文和转写全文不写入普通应用日志。
- 临时文件下载令牌不写入完整访问日志。
- 转写成功后立即删除原音频。
- 失败音频最多保留 7 天。
- 过期清理同时清除业务文本和临时路径。
- 正式环境应将 HTTP 升级为 HTTPS，避免音频和下载令牌被窃听。

## 21. 备份与恢复

- 正式日记仍按现有备份流程导出和恢复。
- `transcription_batches`、`transcription_items` 和临时音频属于运行期数据，不进入备份包。
- 执行数据库恢复前，必须取消所有非终态语音批次并清理临时音频，避免恢复后的用户数据与旧后台任务交叉。
- 数据库备份恢复不承担语音任务恢复；“服务重启恢复”只针对数据库和持久化卷保持不变的正常部署重启。

## 22. 可观测性

建议记录以下不含正文的指标：

- 批次创建、完成、失败、取消和过期数量；
- 音频项排队时长、转写时长和重试次数；
- 当前队列长度和占用并发数；
- Fun-ASR 错误码分布；
- 临时文件总大小和清理失败数量；
- 自动创建日记成功和幂等拦截次数。

## 23. 实施顺序

1. 新增数据库表、约束和配置。
2. 实现临时文件上传和安全下载接口。
3. 实现 `FunAsrService` HTTP 调用及模拟测试。
4. 实现批次调度、并发、轮询和重启恢复。
5. 实现原子创建正式日记和文件清理。
6. 实现前端上传面板、状态页和轮询。
7. 调整 Nginx 上传限制、内部文件转发和持久化卷。
8. 进行真实单文件联调。
9. 进行多文件、失败重试、页面离开和服务重启验收。

## 24. 官方参考

- [Fun-ASR 录音文件识别 HTTP API](https://help.aliyun.com/zh/model-studio/fun-asr-recorded-speech-recognition-http-api)
- [Fun-ASR Python SDK](https://help.aliyun.com/zh/model-studio/funauidio-asr-recorded-speech-recognition-python-sdk)
- [阿里云百炼语音识别模型与音频规格](https://help.aliyun.com/zh/model-studio/asr-model/)
