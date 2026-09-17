# Key 申请图文指引目录

把扶摇 API Key 的**注册 / 登录 / 签发页面截图**（png 或 jpg，按步骤命名，如
`01-登录页.png`、`02-APIKey管理.png`、`03-签发.png`）放入本目录。

之后 AI 助手在用户缺少 Key 时会运行：

```bash
python scripts/ash_env.py --guide     # 依次打开本目录下的截图
python scripts/ash_env.py --open-admin  # 直接拉起 https://fuyao.aicubes.cn/admin/
```

无截图时 `--guide` 会提示目录为空，不影响流程（`--open-admin` 拉起官网 + 文字步骤引导）。

> 截图不要包含任何真实 API Key 内容（截图仅用于指引页面布局）。
