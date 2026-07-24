# 开发约束

## iOS Safari 表单交互

- 移动端的 `input`、`textarea`、`select` 等可编辑控件，实际字号必须不小于 `16px`，避免 iOS Safari 聚焦时自动放大页面。
- 不得通过 `user-scalable=no` 或 `maximum-scale=1` 禁止用户缩放来规避该问题。
- 新增或修改移动端表单后，必须验证 iOS Safari 聚焦输入框时页面不会自动放大。
