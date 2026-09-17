# Key 申请图文指引目录

本目录存放扶摇 API Key 的**注册/签发流程截图**，由 AI 在用户缺 Key 时通过
`ash_env.py --guide` 自动依次打开（浏览器图片查看），或作为给用户的说明材料。

## 当前内容

| 文件 | 步骤 |
|------|------|
| `01-APIKey管理页-先去登录.png` | 打开管理页，未登录时点【去登录】 |
| `02-填别名-签发APIKey.png` | 【创建 API Key】→ 填别名 → 【签发 API Key】 |
| `03-点复制-把Key发给AI.png` | 点【复制】，把 sk-fuyao- 开头的 Key 粘贴给 AI |

步骤说明集中在 `captions.json`（image / caption 对）——截图更新后只需改这个文件，
`ash_env.py --guide` 会同时打开图片并输出对应说明。

> 截图不要包含任何真实 API Key 内容（示例图中的 Key 已打码）。
