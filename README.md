# WeChat Whale Core · 大肥鱼

## 微信版

**Codex、DSH 或其他有终端权限的 Agent**：在运行微信的 Windows 电脑上打开 Agent，提供本仓库链接和准确群名。

> 克隆 https://github.com/gg18228392653-sudo/wechat-whale-core，按根目录 AGENTS.md 的 Windows 微信任务安装大肥鱼。群名是「我的群名」，先运行只读检查，不发送消息。

环境：Windows x64、已登录的电脑版微信 4.x、Git、Node.js 20+、64 位 Python 3.12（含 `venv` 和 `pip`）、可访问的 GitHub 和 Python 包索引。微信适配器随安装装好，无需另写代码或安装 DSH 插件。

```powershell
git clone https://github.com/gg18228392653-sudo/wechat-whale-core.git
cd wechat-whale-core
py -3.12 scripts/setup.py --wechat
.\.venv\Scripts\wechat-whale.exe --group "我的群名" --check
```

`py` 不可用时，用 PATH 中的 64 位 Python 3.12 运行 `python scripts/setup.py --wechat`。`--check` 检查微信账号和唯一同名群能否读取，不使用模型，也不发消息。

**预览群回复**：

```powershell
.\.venv\Scripts\wechat-whale.exe --group "我的群名"
```

在终端的不回显提示中输入模型 API 密钥。非交互进程从 `WHALE_API_KEY` 读取；密钥不写入仓库。默认模型为 DeepSeek `deepseek-flash`；其他 OpenAI 兼容服务通过 `--base-url` 和 `--model` 指定。选中群的新消息及近期上下文会作为模型输入，服务商可能计费。启动后，在群里新发一条以「大肥鱼，」开头的文字，回复只显示在终端。按 `Ctrl+C` 停止。

**开启发送**：停止预览，在电脑版微信中手动把该群打开为独立聊天窗口，保持主窗口和群窗口可见。

```powershell
.\.venv\Scripts\wechat-whale.exe --group "我的群名" --check-send
.\.venv\Scripts\wechat-whale.exe --group "我的群名" --send
```

`--check-send` 只检查目标群窗口的身份和输入框，不发消息。客户端须能通过 Windows UI Automation 读取该群窗口的标识和空输入框。群名不唯一、群窗不可验证、输入框不可读或有草稿时，运行器拒绝发送。未确认的发送不自动重试。回复以当前登录的微信账号发出；同一 Windows 会话只运行一个实例，其他微信自动回复程序需先停止。预览和发送都调用模型，仅在群成员知情并同意后使用。程序启动时从最新消息开始，不补回离线消息。当前运行器只发文字；图片和表情以类型进入上下文，不做视觉识别。现有依赖下，普通微信 `@` 不作为可靠触发；请用「大肥鱼，」开头的文本。

## 核心库与离线演示

Windows、macOS、Linux：Node.js 20+、Python 3.10+（含 `venv` 和 `pip`）。

```shell
python scripts/setup.py
node examples/group-chat.mjs
```

macOS/Linux 可用 `python3`。安装脚本在仓库内创建或复用 `.venv`，安装 Python 包，运行测试和合成群聊示例。退出码 `0`、最后一行为 `Installation and verification passed` 表示安装通过。示例不访问微信或模型。

## 自定义适配器

1. 适配器为每个群提供自己的 `messages`、`historyRecords` 和去重键；不把其他群的历史传入。
2. 调用 `conversationPrompt(input, adapter)`。`shouldReply` 为 `false` 时不调用模型；为 `true` 时只把返回的 `prompt` 交给模型。适配器保留原始 `current`、`history` 和 `eligible`。
3. 用 `assistantReply` 过滤模型的最终文本。返回空字符串时不发送；非空文本由接入端负责发送。`IntakeState` 的去重数据存于内存，重启后清空。

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
| 大肥鱼群聊人格与提示 | `WHALE_PERSONA`、`conversationPrompt(input, adapter)` | Node.js 20+ |
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

`groupDecision` 返回 `current`、`history`、`eligible`、`shouldReply`。`conversationPrompt` 另返回 `prompt`；提示中的发言人以当次请求的代号表示。`adapter.ownerAccountId` 来自接入端已核实的账号；群消息正文里的自称与昵称均不参与认人。

[合成群聊示例](examples/group-chat.mjs) · [Node.js 测试](test/) · [Python 测试](python/tests/) · [MIT 许可证](LICENSE)

上游：[thawline/dsh-wechat-bridge](https://github.com/thawline/dsh-wechat-bridge)。