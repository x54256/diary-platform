# 管理端模型管理实施文档与验收标准

> 本文基于 `docs/llm-model-config-design.md` 编写，描述实施顺序、代码改造范围、测试方案和验收标准。需求文档定义“做什么”，本文定义“怎么做、怎么验”。

## 1. 实施目标

把 AI 模型选择从 `.env` 固定配置迁移到管理端：

1. 管理端维护模型清单、调用渠道、渠道支持模型和业务用途模型设置。
2. 日记整理、分析、对话、语音转文字运行时读取 `model_settings`。
3. `.env` 不再提供模型调用兜底；未配置时对应 AI 功能不可用。
4. 通过后端单测和接口测试验证核心规则。

## 2. 实施边界

本次实施包含：

- 数据表与迁移。
- Excel 模型清单初始化入库。
- 管理端模型、渠道、模型设置接口。
- 管理端三个页面。
- 运行时模型选择改造。
- 单测、接口测试和基础前端构建验证。

本次不包含：

- ASR 真实音频测试调用。
- 模型设置历史记录。
- 复杂费用统计。
- 自动推荐模型。
- 自动从远端平台同步模型列表。

## 3. 实施顺序

### 3.1 数据层

新增 SQLAlchemy 模型：

```text
ModelCatalog
ApiChannel
ChannelModel
ModelSetting
```

新增迁移文件：

```text
backend/migrations/013_model_management.sql
```

迁移内容：

1. 创建 `model_catalog`。
2. 创建 `api_channels`。
3. 创建 `channel_models`。
4. 创建 `model_settings`。
5. 添加唯一约束：
   - `channel_models(channel_id, model_id)`
   - `model_settings(setting_key)`
6. 添加必要索引：
   - `model_catalog(model_type, ability_tier, ability_category, enabled)`
   - `channel_models(channel_id, enabled)`
   - `channel_models(model_id, enabled)`

### 3.2 初始化数据

新增初始化模块：

```text
backend/services/model_seed.py
```

职责：

1. 写入 Excel 中 70 个语言模型。
2. 写入 Excel 中 30 个 ASR 模型。
3. 保留 Excel 原始能力分类到 `original_category`。
4. 映射精简能力分类到 `ability_category`。
5. 幂等执行：重复启动不会重复插入。

初始化时只写 `model_catalog`，不自动创建渠道、渠道模型和模型设置。

### 3.3 后端服务层

新增服务模块：

```text
backend/services/model_management.py
backend/services/model_runtime.py
```

`model_management.py` 负责管理端规则：

- 模型 CRUD。
- 渠道 CRUD。
- 渠道模型关系维护。
- 模型设置保存。
- 禁用、删除、清空密钥保护。

`model_runtime.py` 负责运行时解析：

```text
resolve_model_setting(setting_key)
```

返回：

```text
api_base_url
api_key
model_name
protocol
model_type
```

并校验：

1. `model_settings` 存在。
2. `channel_model` 启用。
3. `model_catalog` 启用。
4. `api_channels` 启用。
5. API Key 已配置。
6. 用途、模型类型、协议匹配。

### 3.4 管理端接口

新增路由：

```text
backend/routers/admin_models.py
```

所有接口必须复用 `require_admin` 权限规则。

模型接口：

```text
GET    /api/admin/models
POST   /api/admin/models
GET    /api/admin/models/{model_id}
PATCH  /api/admin/models/{model_id}
DELETE /api/admin/models/{model_id}
```

渠道接口：

```text
GET    /api/admin/channels
POST   /api/admin/channels
GET    /api/admin/channels/{channel_id}
PATCH  /api/admin/channels/{channel_id}
DELETE /api/admin/channels/{channel_id}
POST   /api/admin/channels/{channel_id}/clear-api-key
```

渠道模型接口：

```text
GET   /api/admin/channels/{channel_id}/models
PUT   /api/admin/channels/{channel_id}/models
GET   /api/admin/models/{model_id}/channels
PUT   /api/admin/models/{model_id}/channels
```

模型设置接口：

```text
GET  /api/admin/model-settings
PUT  /api/admin/model-settings
POST /api/admin/model-settings/test
```

辅助枚举接口：

```text
GET /api/admin/model-options
```

返回模型类型、协议、用途、能力梯队、能力分类固定选项。

### 3.5 运行时改造

整理流水线：

- `backend/services/pipeline.py`
- 所有整理节点使用 `resolve_model_setting("organize")`。

分析流水线：

- `backend/services/analysis_pipeline.py`
- 普通分析和反馈重分析使用 `resolve_model_setting("analysis")`。

对话：

- `backend/services/ai.py`
- `AIService.chat()` 使用 `resolve_model_setting("chat")`。

语音转文字：

- `backend/services/fun_asr.py`
- `submit()` 使用 `resolve_model_setting("transcription")`。

`.env` 中模型相关字段不再作为运行时兜底。

### 3.6 前端页面

新增页面：

```text
frontend/pages/admin/models.vue
frontend/pages/admin/channels.vue
frontend/pages/admin/model-settings.vue
```

更新：

```text
frontend/layouts/admin.vue
```

新增菜单：

```text
模型管理
渠道管理
模型设置
```

页面行为：

- 模型管理支持筛选、新增、详情、启用、禁用、删除。
- 渠道管理支持新增、编辑、清空密钥、删除、维护支持模型。
- 模型设置支持四个用途一起保存。
- 模型设置选择链路为：渠道 → 能力梯队 → 能力分类 → 模型。
- 渠道变化后清空模型选择。
- 页面展示未配置原因。

## 4. 关键规则

### 4.1 禁用和删除保护

以下操作必须被后端拒绝：

1. 禁用正在被 `model_settings` 使用的模型。
2. 删除正在被 `model_settings` 使用的模型。
3. 禁用正在被 `model_settings` 使用的渠道。
4. 删除正在被 `model_settings` 使用的渠道。
5. 清空正在被 `model_settings` 使用的渠道 API Key。
6. 禁用或删除正在被 `model_settings` 使用的 `channel_model`。

### 4.2 API Key 安全

1. API Key 加密存储。
2. 查询接口不返回明文。
3. 编辑渠道时 API Key 留空表示不修改。
4. 清空 API Key 必须走独立接口。

### 4.3 用途保存校验

保存 `model_settings` 时必须校验：

| 用途 | 模型类型 | 协议 |
|---|---|---|
| organize | language | openai_chat |
| analysis | language | openai_chat |
| chat | language | openai_chat |
| transcription | asr | dashscope_asr |

同时校验：

- 渠道启用。
- 渠道已配置 API Key。
- 模型启用。
- 渠道模型启用。

## 5. 测试策略

主要通过后端单测和接口测试验收，前端以构建和手工流程验证为辅。

测试占比目标：

```text
70% 后端单测 / 接口测试
20% 运行时 mock 测试
10% 前端构建 / 手工验收
```

### 5.1 数据层测试

测试内容：

1. `channel_id + model_id` 唯一约束生效。
2. `setting_key` 唯一约束生效。
3. 删除渠道时级联删除 `channel_models`，不删除 `model_catalog`。
4. 删除模型时级联删除 `channel_models`。
5. 使用中的模型、渠道、渠道模型不能删除。

### 5.2 初始化测试

测试内容：

1. 初始化后语言模型为 70 条。
2. 初始化后 ASR 模型为 30 条。
3. 重复执行初始化不重复插入。
4. `original_category` 保留 Excel 原始分类。
5. `ability_category` 映射为精简分类。

### 5.3 管理接口测试

测试内容：

1. 非 admin 访问返回 403。
2. 模型列表支持类型、梯队、分类、状态和关键词筛选。
3. 新增自定义模型后默认启用。
4. 渠道创建后 API Key 加密存储。
5. 渠道查询不返回 API Key 明文。
6. API Key 留空更新不覆盖旧密钥。
7. 清空 API Key 受使用中保护。
8. 批量维护渠道模型关系能正确新增、更新、禁用。
9. 模型设置保存校验用途、类型和协议。
10. 模型测试接口能构造固定最小语言模型请求。

### 5.4 运行时 mock 测试

通过 mock HTTP 客户端或 mock 适配器验证请求构造，不依赖真实外部模型。

测试内容：

1. 整理读取 `organize` 设置。
2. 分析读取 `analysis` 设置。
3. 对话读取 `chat` 设置。
4. 语音转文字读取 `transcription` 设置。
5. 实际模型名使用 `model_catalog.model_name`。
6. API 地址使用 `api_channels.api_base_url`。
7. API Key 使用解密后的 `api_key_encrypted`。
8. 未配置模型设置时返回明确错误。
9. 渠道禁用、模型禁用、渠道模型禁用、API Key 缺失时返回明确错误。

### 5.5 前端验证

自动验证：

```text
npm run build
```

手工验证：

1. 管理端菜单显示模型管理、渠道管理、模型设置。
2. 模型管理筛选、新增、启用、禁用、删除可用。
3. 渠道管理新增、编辑、清空密钥、维护支持模型可用。
4. 模型设置四个用途可以一起保存。
5. 渠道变化后模型选择被清空。
6. 未配置原因能在页面展示。

## 6. 验收标准

### 6.1 功能验收

通过标准：

1. 管理端可以维护模型清单。
2. 管理端可以维护 API 渠道。
3. 管理端可以维护渠道支持模型。
4. 管理端可以为整理、分析、对话、语音转文字分别选择模型。
5. 模型设置保存后无需重启即可生效。
6. 未配置模型设置时，对应 AI 功能不可用并返回明确错误。
7. 语言模型测试调用可用，且保存不依赖测试结果。

### 6.2 安全验收

通过标准：

1. API Key 不以明文落库。
2. API Key 不通过查询接口返回。
3. 清空 API Key 受使用中保护。
4. 非 admin 无法访问管理端模型接口。
5. 删除、禁用操作不会破坏当前运行配置。

### 6.3 数据验收

通过标准：

1. 初始化模型数量正确：70 个语言模型、30 个 ASR 模型。
2. 初始化可重复执行且不重复插入。
3. 模型、渠道、渠道模型、模型设置外键关系正确。
4. 删除渠道不删除模型清单。
5. 删除模型会删除相关渠道模型关系，但不会影响使用中的模型设置。

### 6.4 运行时验收

通过标准：

1. 整理、分析、对话、语音转文字分别读取对应 `model_settings`。
2. 实际请求使用 `model_name`。
3. 实际请求使用渠道配置的 API 地址和 API Key。
4. `.env` 中模型字段不再作为运行时兜底。
5. 配置缺失、禁用、密钥缺失时失败信息明确。

### 6.5 测试验收

通过标准：

1. 后端单测通过。
2. 管理端接口测试通过。
3. 运行时 mock 测试通过。
4. 前端构建通过。
5. 手工验收清单完成。

## 7. 建议测试文件

后端：

```text
backend/tests/test_model_seed.py
backend/tests/test_admin_models.py
backend/tests/test_model_runtime.py
backend/tests/test_model_management_rules.py
```

前端：

```text
以构建检查和手工验收为主；如后续引入页面测试，再补管理端表单交互测试。
```

## 8. 实施完成检查清单

```text
[ ] 数据表和迁移完成
[ ] 模型初始化完成
[ ] 管理接口完成
[ ] 运行时解析服务完成
[ ] 整理流水线接入 model_settings
[ ] 分析流水线接入 model_settings
[ ] 对话接口接入 model_settings
[ ] 语音转文字接入 model_settings
[ ] 管理端三个页面完成
[ ] 后端单测通过
[ ] 接口测试通过
[ ] 运行时 mock 测试通过
[ ] 前端构建通过
[ ] 手工验收通过
```
