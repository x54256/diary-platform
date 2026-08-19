# 开发约束

## iOS Safari 表单交互

- 移动端的 `input`、`textarea`、`select` 等可编辑控件，实际字号必须不小于 `16px`，避免 iOS Safari 聚焦时自动放大页面。
- 不得通过 `user-scalable=no` 或 `maximum-scale=1` 禁止用户缩放来规避该问题。
- 新增或修改移动端表单后，必须验证 iOS Safari 聚焦输入框时页面不会自动放大。

## 后端调试与数据库排查

- `backend/.venv` 使用 Python 3.13，与项目当前 SQLAlchemy 版本不兼容。运行后端调试脚本时使用 `backend/venv/bin/python`（Python 3.11）。
- `Settings.Config.env_file = ".env"` 按命令工作目录解析。需要加载 `backend/.env` 时，在 `backend` 目录执行脚本。
- 远程数据库连接在沙箱内出现 `Operation not permitted` 时，先确认操作是只读查询，再按权限流程申请网络访问；不得将该错误直接判断为数据库服务故障。
- 使用原生 SQL 查询 `diary_events.body` 时，返回值可能是 JSON 字符串。统计或遍历前必须先判断类型，并在字符串类型时执行 `json.loads`，避免把字符数误认为数组元素数。
- 调试输出不得打印 `.env`、数据库连接串、账号、密码、密钥或其他认证信息。
