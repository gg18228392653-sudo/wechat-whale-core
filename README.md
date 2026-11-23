# WeChat Whale Core · 大肥鱼

## 微信版

### Codex、DSH 和其他 Agent

Agent 操作清单见 [AGENTS.md](AGENTS.md)。在运行微信的 Windows 电脑上提交一条任务，替换引号内的目标名称。

> 克隆 https://github.com/gg18228392653-sudo/wechat-whale-core，按仓库根目录 AGENTS.md 安装 Windows 微信版。我要群聊，群名是「我的群名」。先执行 `--check`。

> 克隆 https://github.com/gg18228392653-sudo/wechat-whale-core，按仓库根目录 AGENTS.md 安装 Windows 微信版。我要私聊，联系人备注是「我的联系人」。先执行 `--check`。

### 安装

环境要求为 Windows x64、已登录的电脑版微信 4.x、Git、Node.js 20+、64 位 Python 3.12（含 `venv` 和 `pip`）、可访问的 GitHub 和 Python 包索引。安装包含微信适配器和模型接口。

```powershell
git clone https://github.com/gg18228392653-sudo/wechat-whale-core.git
cd wechat-whale-core
py -3.12 scripts/setup.py --wechat
```

64 位 Python 3.12 已在 PATH 中时，也可执行 `python scripts/setup.py --wechat`。已有旧版时，先停止运行中的大肥鱼，在原仓库执行 `git pull --ff-only`，再运行安装命令更新启动器。

### 群聊与私聊命令

| 模式 | 群聊 | 私聊 |
| --- | --- | --- |
| 只读自检 | `.\.venv\Scripts\wechat-whale.exe --group "我的群名" --check` | `.\.venv\Scripts\wechat-whale.exe --contact "我的联系人" --check` |
| 回复预览 | `.\.venv\Scripts\wechat-whale.exe --group "我的群名"` | `.\.venv\Scripts\wechat-whale.exe --contact "我的联系人"` |
| 发送前检查 | `.\.venv\Scripts\wechat-whale.exe --group "我的群名" --check-send` | `.\.venv\Scripts\wechat-whale.exe --contact "我的联系人" --check-send` |
| 正式发送 | `.\.venv\Scripts\wechat-whale.exe --group "我的群名" --send` | `.\.venv\Scripts\wechat-whale.exe --contact "我的联系人" --send` |

1. 先执行只读自检。群聊指定准确群名，私聊指定一位联系人的准确备注或昵称。同名联系人用唯一备注或稳定账号标识区分。两种检查模式均不调用模型或发送微信消息。
2. 预览和正式发送均使用模型。默认模型是 DeepSeek `deepseek-flash`。其他 OpenAI 兼容服务使用 `--base-url` 和 `--model`。密钥从本机终端的不回显提示或 `WHALE_API_KEY` 输入。目标会话的新消息和近期上下文会交给所配的模型服务，经聊天参与者同意后开启。
3. 预览中，群成员发送以「大肥鱼，」开头的新文本，或指定联系人向登录账号发一条新私聊。两种模式都从启动时的消息位置开始，登录账号自己发的消息不会触发回复。终端显示预览，`Ctrl+C` 停止。
4. 正式发送前停止预览，在电脑版微信中把目标会话打开为独立聊天窗口。保持主窗口和目标窗口可见、输入框为空，通过发送前检查后执行正式发送。发送使用当前登录账号，未确认的发送不会自动重试。

一个 Windows 桌面会话运行一个实例，每次指定一个群或一位联系人。停止当前实例后可切换。文字回复可发送，图片和表情以类型进入上下文。客户端需向 Windows UI Automation 提供可校验的目标窗口标识和可读的输入框。

## 核心库与离线演示

Windows、macOS、Linux：Node.js 20+、Python 3.10+（含 `venv` 和 `pip`）。

```shell
python scripts/setup.py
node examples/group-chat.mjs
```

macOS/Linux 可用 `python3`。安装脚本在仓库内创建或复用 `.venv`，安装 Python 包，运行测试和合成群聊示例。退出码 `0`、最后一行为 `Installation and verification passed` 表示安装通过。示例不访问微信或模型。

## Node API

群聊接入按群隔离 `messages`、`historyRecords` 和去重键。调用 `conversationPrompt(input, adapter)`，仅在 `shouldReply` 为 `true` 时把 `prompt` 交给模型。

私聊接入调用 `privatePrompt(input, contactId)`。它只保留登录账号和指定联系人的记录，当前消息由联系人发出时加入 `eligible`，不需要 @ 或群聊唤醒词。

`assistantReply` 过滤模型最终文本；返回空字符串时不发送。`IntakeState` 的去重数据存于内存，重启后清空。

既有 Node 项目可在项目目录直接安装：

```shell
npm install git+https://github.com/gg18228392653-sudo/wechat-whale-core.git
```

```js
import { conversationPrompt } from 'wechat-whale-core'

const { shouldReply, eligible } = conversationPrompt({
  selfId: 'demo-bot',
  messages: [{ id: '1', senderId: 'demo-user', text: '大肥鱼，在吗？', mentions: ['demo-bot'] }],
})
console.log(shouldReply, eligible) // true [ '1' ]

const privateResult = privatePrompt({
  selfId: 'demo-bot',
  messages: [{ id: '2', senderId: 'demo-contact', text: '你好' }],
}, 'demo-contact')
console.log(privateResult.shouldReply, privateResult.eligible) // true [ '2' ]
```

Python 图片接口接收本地文件和输出目录：

```python
from wechat_whale_core.media_normalize import normalize_media

result = normalize_media('input.gif', 'out')
print(result['path'])
```

用 `.venv` 的 Python 运行上述代码即可。支持 PNG、JPEG、GIF、APNG 和 WebP，输出 PNG；多帧动图生成最多六帧的拼图。

## 接口清单

| 模块 | 接口 | 运行环境 |
| --- | --- | --- |
| 群聊接话判断 | `groupDecision(input)` | Node.js 20+ |
| 大肥鱼人格与提示 | `WHALE_PERSONA`、`PRIVATE_PERSONA`、`conversationPrompt(input, adapter)`、`privatePrompt(input, contactId)` | Node.js 20+ |
| 群聊文本过滤 | `assistantReply(message)`、`containsInternalOutput(value)` | Node.js 20+ |
| 按群去重与消息水位 | `IntakeState.accept({ chatId, batchId, sequence })`、`IntakeState.isStale(chatId, sequence)` | Node.js 20+ |
| 混合消息合批 | `wechat_whale_core.conversation_batch.collect_batch` | Python 3.10+ |
| 静态图与动图规范化 | `wechat_whale_core.media_normalize.normalize_media` | Python 3.10+、Pillow |

## 消息结构

| 字段 | 类型 |
| --- | --- |
| `selfId` | 机器人账号在适配层中的标识 |
| `messages`、`historyRecords` | 按时间排列的消息记录 |
| `id`、`senderId` | 消息标识、发言人标识 |
| `text` | 消息正文 |
| `time` | Unix 秒，可省略 |
| `mentions` | 点名对象标识数组，可省略 |
| `quote` | `{ senderId, text }`，可省略 |
| `media` | `{ kind }` 数组，可省略 |

`groupDecision` 返回 `current`、`history`、`eligible`、`shouldReply`。`conversationPrompt` 和 `privatePrompt` 另返回 `prompt`；提示中的发言人以当次请求的代号表示。`adapter.ownerAccountId` 来自接入端已核实的账号；群消息正文里的自称与昵称均不参与认人。

[合成群聊示例](examples/group-chat.mjs) · [Node.js 测试](test/) · [Python 测试](python/tests/) · [MIT 许可证](LICENSE)

上游：[thawline/dsh-wechat-bridge](https://github.com/thawline/dsh-wechat-bridge)。