# 多租户 Guest Mode 访客机器人

基于 Python 3.11 + aiogram 3.28.2 的多租户 Guest Mode Bot 托管系统。管理主 Bot 负责创建/绑定租户 Bot、Token 轮换和状态刷新；租户 Bot 负责处理自己的 `guest_message`，并通过 `answerGuestQuery` 自动回复模板。

## 功能

- 管理主 Bot：`/start`、`/createbot`、`/addtoken`、`/mybots`、`/refreshbot`
- Managed Bots：通过 Telegram 官方流程创建受管理子 Bot，并自动获取 token
- 多租户 Runner：每个租户 Bot 独立 polling，默认监听 `guest_message`
- 租户 Bot 自管理：`/start` 菜单按钮可新增、查看、预览、编辑、删除、设默认、启停和测试模板
- 模板能力：关键词、精确匹配、模糊匹配、默认模板、权重随机、图片、URL 按钮
- Token 加密：使用 `cryptography.Fernet` 加密保存 Bot Token
- 手动 `/addtoken` 会尽量删除包含 token 的用户消息；推荐优先使用 `/createbot`
- 数据库：SQLite + SQLAlchemy 2.0 async，预留 Alembic 迁移

## 配置

复制配置模板：

```bash
cp .env.example .env
```

生成 `FERNET_KEY`：

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`.env` 必填项：

```env
MASTER_BOT_TOKEN=主BotToken
FERNET_KEY=上面生成的密钥
DATABASE_URL=sqlite+aiosqlite:///./data/guest_bot.db
ADMIN_IDS=你的Telegram数字ID
```

兼容旧配置：如果暂时没有 `MASTER_BOT_TOKEN`，代码会读取 `BOT_TOKEN`。

## 安装与运行

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python main.py
```

启动后确认日志：

```text
管理主 Bot 已启动: @xxx can_manage_bots=True
```

如果 `can_manage_bots` 不是 `True`，需要先在 BotFather MiniApp 为主 Bot 开启 Bot Management。

## 使用流程

1. 对主 Bot 发送 `/createbot`，打开返回的 Telegram 官方链接创建租户 Bot。
2. 创建成功后，主 Bot 自动获取并加密保存租户 Bot Token。
3. 打开 `https://t.me/Botfather?startapp`，选择租户 Bot，进入 `Bot Settings`，打开 `Guest Chat Mode`。
4. 打开租户 Bot 发送 `/start`，使用按钮新增模板；也可以继续用命令添加模板：

```text
/addtemplate @tenant_bot =广告 | 广告标题 | <b>广告文案</b> | https://image.jpg | [{"text":"联系","url":"https://example.com"}]
```

5. 在任意群组输入：

```text
@tenant_bot 广告
```

租户 Bot 会通过 Guest Mode 自动回复匹配模板。

## 模板命令格式

```text
/addtemplate @bot 关键词 | 标题 | 文案 | 图片URL | 按钮JSON
```

- `=广告`：精确匹配
- `~广告`：模糊匹配
- `广告`：默认模糊匹配
- 图片 URL 可省略
- 按钮 JSON 可省略
- 同一个关键词可以添加多个模板；Guest Mode 命中多个模板时会按权重随机选择一个回复
- 调整随机权重：`/edittemplate <template_id> weight 5`

## 富媒体与能力边界

- 文案使用 HTML parse mode，可直接写 `<b>加粗</b>`、普通 emoji、会员 emoji 文本。
- 在 Telegram 客户端给文字设置“超链接”会自动保留为 HTML 链接。
- 也兼容常见 Markdown 链接写法：`[限时免费搜索](https://t.me/kuai?start=a_ATC98L)`。
- Telegram 自定义 emoji 可使用 HTML：`<tg-emoji emoji-id="5368324170671202286">👍</tg-emoji>`。
- 图片必须是公网可访问的 HTTPS URL。
- Inline Keyboard 支持文本和 URL 按钮；Telegram Bot API 不支持自定义按钮颜色，按钮颜色由客户端主题决定。
- 按钮 JSON 示例：

```json
[{"text":"联系我","url":"https://example.com"}]
```

- 多行按钮 JSON 示例：

```json
[[{"text":"官网","url":"https://example.com"}],[{"text":"频道","url":"https://t.me/example"}]]
```

## 管理命令

- `/mybots`：查看自己的租户 Bot
- `/tenantstatus @bot`：查看租户运行状态、Guest 支持状态和模板数量
- `/refreshbot @bot`：刷新 Guest 状态并重启租户 Bot polling
- `/seedtemplates @bot`：为空租户写入 `广告`、`推广`、`你好` 测试模板
- `/mytemplates @bot`：查看模板
- `/edittemplate <template_id> <field> <value>`：编辑模板字段
- `/deltemplate <template_id>`：删除模板
- `/setdefault <template_id>`：设置默认模板
- `/rotatetoken @bot`：轮换 Managed Bot Token
- `/admin_tenants`：管理员查看全部租户
- `/admin_reload`：管理员重载租户 Runner
- `/admin_disable <tenant_id>`：管理员停用租户

## 租户 Bot 菜单

租户 Bot 收到 `/start` 后会显示按钮菜单：

- `新增模板`：分步输入关键词、匹配模式、标题、文案、图片和按钮。
- `查看模板`：列出模板，并提供预览、编辑、删除、设默认、启用/停用按钮。
- `测试关键词`：按 Guest Mode 匹配规则测试关键词会命中哪个模板；也可用 `/test 广告`。
- `写入测试模板`：为空 Bot 写入 `广告`、`推广`、`你好` 示例。
- `刷新 Guest 状态`：读取当前 Bot 的 `supports_guest_queries`，确认 Guest Chat Mode 是否生效。
- `打开 BotFather 设置`：进入 Mini App，选择 Bot → `Bot Settings` → `Guest Chat Mode` → 打开。

## 离线检查

不调用 Telegram API 的本地 smoke 检查：

```bash
python scripts/smoke_check.py
```

部署前/部署后检查数据库状态：

```bash
python scripts/runtime_check.py
```

如需调用 Telegram `getMe` 验证主 Bot 和租户 Bot 的 Guest 能力：

```bash
python scripts/runtime_check.py --telegram
```

## Docker 运行

功能测试稳定后可使用 Docker。SQLite 数据会挂载到 `./data`：

```bash
docker compose pull
docker compose up -d
docker compose logs -f
```

### GitHub 自动构建镜像

仓库推送到 `main` 后，GitHub Actions 会自动构建并推送多架构镜像到 GHCR：

- `ghcr.io/lookoupai/telegram_guest_bot:latest`
- `ghcr.io/lookoupai/telegram_guest_bot:sha-<commit>`
- 发布 tag 时还会生成对应版本 tag
