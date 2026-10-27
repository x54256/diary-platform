# 读取、预检与确认后入库

在项目根目录执行；使用 Python 3.11：`backend/venv/bin/python`。脚本自行进入 `backend` 加载 `.env`，可在子命令前传入 `--backend-dir`。不打印配置、连接串或认证信息。

## 1. 定位目标与只读导出

```bash
backend/venv/bin/python skills/diary-analyzer/scripts/store_analysis.py find \
  --username x5456 --date 2026-10-27
```

返回用户 ID、候选数、日记 ID、日期、状态、是否已有分析及事件数。`eligible_status` 仅报告状态和分析轮次条件；完整资格由 `export` 再检查。唯一匹配才直接继续，多条匹配请用户选择。UUID 必须用实际查询结果替换：

```bash
backend/venv/bin/python skills/diary-analyzer/scripts/store_analysis.py export \
  --diary-id DIARY_UUID --user-id USER_UUID \
  --output diary-analyses/2026-10-27/来源.json
```

导出结构化事件（含 ID、原标题、正文、感受、反思、重要性）、琐事、后续计划、日记日期、上海时区及冻结分析日期、人物关系、来源指纹。人物资料随来源一起校验，不另用其他用户的资料。

完整资格：未删除、归属正确、`organized`、没有任何分析轮次、整理修订与原文一致、未标记脏数据、没有本用户运行中的建图／分析任务或该日记运行中的整理任务。第一版不支持反馈重写、重分析或历史导入。已有建图结果本身不阻止首次分析，保存时不更改它们。

输出文件不覆盖。来源变化后用新的导出文件名，核对稿件与新来源，再生成新入库包。来源文件含私人日记内容，只保存在约定本地目录，不提交到外部服务。

## 2. Markdown 转换

按 [格式协议](markdown-format.md) 生成 `分析稿.md`。先用 `--sources-only` 输出行动来源清单，再完成行动规划。

```bash
backend/venv/bin/python skills/diary-analyzer/scripts/markdown_to_json.py \
  diary-analyses/2026-10-27/分析稿.md \
  --source diary-analyses/2026-10-27/来源.json \
  --output diary-analyses/2026-10-27/分析结果.json
```

转换只依赖 Python 标准库，不连接数据库。转换结果用于检查；保存脚本从 Markdown 重新生成结果，不依赖可以另行修改的分析结果 JSON。

## 3. 只读预检并冻结

```bash
backend/venv/bin/python skills/diary-analyzer/scripts/store_analysis.py prepare \
  --markdown diary-analyses/2026-10-27/分析稿.md \
  --source diary-analyses/2026-10-27/来源.json \
  --output diary-analyses/2026-10-27/入库包-1.json
```

预检重新检查资格、数据库内容和人物资料是否与导出一致，校验 Markdown、来源 ID、连续摘录和推荐日程；返回事件数、行动数及 `confirmation_sha256`。PostgreSQL 读取事务显式设置只读。此步骤不创建任务或分析记录。

向用户交付完整稿、文件链接及保存范围：“准备保存某用户某年某月某日日记的核心分析、认知分析和 N 个行动项；只读预检通过，尚未写库。”必要时统计非空分析条目数补充范围。用户无需操作指纹。

## 4. 核验与正式保存

默认只读：

```bash
backend/venv/bin/python skills/diary-analyzer/scripts/store_analysis.py save \
  diary-analyses/2026-10-27/入库包-1.json
```

用户确认当前整篇最终稿后，使用对应包的实际指纹：

```bash
backend/venv/bin/python skills/diary-analyzer/scripts/store_analysis.py save \
  diary-analyses/2026-10-27/入库包-1.json \
  --write --confirmed-sha256 CONFIRMED_SHA256
```

指纹是完整文件版本绑定，不是授权凭据。必须先取得用户对整篇最终稿的明确确认，才可加 `--write`；不得从默认选项、等待时间或局部确认推定授权。

保存持有用户、日记、整理及事件锁，重新核对资格、来源、人物资料、稿件指纹和当前上海日期。单个事务创建已完成的分析任务、CURRENT 分析轮次和各类分析项，按真实事件 ID 建立关联；调用现有行动项保存服务生成行动及其事件关联；更新日记为 analyzed，刷新关键词索引并将变更的分析语义层标为 PENDING。语义向量由项目后台后续生成。

行动来源精确匹配本条事件建议或日记级建议，不能因为建议文字相同而关联到另一个事件。保存推荐日程，不调用日程同步接口。入库前读回核对；任一环节失败则事务回滚。

首次保存后再次使用原包会因已有分析轮次而停止。源文件或稿件变化须重新预检；来源更新或推荐日期过期时先修订稿件并取得变更后的确认。网络或提交异常后先只读检查目标日记和分析轮次，再决定后续操作，禁止自动重试写入。

## 调用与安装

本 skill 源文件在仓库 `skills/diary-analyzer`。可按路径读取执行；宿主是否支持 `$diary-analyzer` 取决于安装发现路径。仅手动调用由 `agents/openai.yaml` 配置，本实现不自动修改宿主安装目录或创建发现链接。
