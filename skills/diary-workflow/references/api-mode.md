# 云端接口模式

四阶段继续使用原脚本和逐阶段整稿确认流程。数据访问由环境变量选择：`DIARY_DATA_MODE=db`（默认）直接访问数据库，`DIARY_DATA_MODE=api` 调用应用接口。接口失败时停止并报告错误，不自动切回数据库或旧本地来源。

## 服务端配置

在应用后端环境变量中设置：

```dotenv
SKILL_API_TOKEN=随机固定Token
SKILL_API_USERNAME=x5456
```

Token 使用 `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` 生成，服务端与云端配置同一个值。Token 只绑定 `SKILL_API_USERNAME` 指定用户；留空时接口关闭。更换配置并重启服务即可轮换 Token。

部署需要包含本次后端代码和 `skills/` 目录。仓库 Dockerfile 已包含 Skill 文件，Nginx 的 Skill 接口超时已覆盖同步向量生成。使用 Compose 时将 `SKILL_API_TOKEN`、`SKILL_API_USERNAME` 加到容器环境变量；只修改宿主机 `.env` 不会自动传给容器。接口不提供数据库迁移写入，所需固定迁移在服务端按原说明执行。

## 云端配置

在云端任务执行环境配置：

```dotenv
DIARY_DATA_MODE=api
DIARY_API_BASE_URL=https://应用域名/diary/api
DIARY_API_TOKEN=与服务端相同的Token
```

`DIARY_API_BASE_URL` 包含 `/diary/api`，不包含 `/skills`。每次请求携带 `Authorization: Bearer <Token>`。认证信息仅通过环境变量读取，不写入稿件、入库包、交接记录或命令参数，不打印。

云端使用 Python 3.11 或更新版本。各 Skill 文档中的 `backend/venv/bin/python` 在 API 模式统一替换为 `python3`，其余脚本路径和参数保持原样；无需创建后端虚拟环境、安装数据库驱动或配置数据库连接。

开始时确认接口地址、模式及 Token 是否已配置，只报告存在与否。不得输出 Token 值。

```bash
python3 skills/diary-workflow/scripts/status.py --username x5456 --date YYYY-MM-DD
```

同日多篇时仍由用户选择日记 ID。选定后各阶段固定使用该 ID。接口回执中的数据库来源仍标记 `origin=database`，表示数据权威来源；HTTP 是传输方式。

要点阶段使用以下只读命令核实向量服务地址、模型及详情外发范围，再按已有授权规则处理：

```bash
python3 skills/diary-event-points/scripts/store_points.py embedding-config
```

## 四阶段操作

- **整理**：`export_people.py` 与 `store_diary.py find/export/prepare/save` 自动通过接口定位、读取人物与原文、预检和保存。
- **要点**：`export_events.py find/export`、`store_points.py schema/embedding-config/prepare/save/status` 自动通过接口操作。向量由应用服务端执行，沿用原任务、租约、检查点及失败恢复。
- **关系**：`workflow.py find/prepare/verify/prepare-storage/save/storage-status/schema` 通过接口读取和保存；`redundancy.py prepare` 从接口获取完整历史关系上下文。批次阅读、关系判断、稿件编辑、冗余判定及 finalize 继续在云端本地完成。
- **分析**：`store_analysis.py find/export/prepare/save` 通过接口读取来源与人物、核验并保存已确认稿；不会启动应用后台 AI 分析。
- **补充要点**：`supplement_points.py prepare/save/status` 同样支持接口模式，仅追加原运行缺失事件。

命令默认只读，正式保存仍须显式 `--write --confirmed-sha256 已确认指纹`。保存会上传来源、稿件及必要的澄清记录内容；服务端独立解析并检查文件指纹、目标用户、当前数据库版本和保存资格。入库包中的云端路径只用于绑定稿件身份，服务端从本次上传内容核验，不读取云端路径对应的服务器文件。

来源快照、当前稿、包及交接记录仍写到各 Skill 规定的本地目录。续接需要保留或恢复这些文件；接口模式不额外同步整个工作目录。

## 失败恢复

网络超时、认证失败或保存回执丢失时，不将本地预检当作保存完成，不盲目重复写入。

1. 使用 `status.py --diary-id ...` 核对当前阶段。整理与分析若已完成，继续下一阶段；来源冲突先处理冲突。
2. 要点使用 `store_points.py status 入库包.json` 查询原任务；失败或中断时按原包、原确认指纹恢复，沿用已保存的检查点。
3. 关系使用 `workflow.py storage-status 入库包.json --username x5456` 核对原发布回执。
4. 补充要点使用 `supplement_points.py status 入库包.json` 核对。
5. 稿件、来源或配置变化时按对应 Skill 重新预检；内容或保存范围变化后重新确认。

本地 `db` 模式仍使用 `backend/venv/bin/python` 和现有数据库权限流程。
