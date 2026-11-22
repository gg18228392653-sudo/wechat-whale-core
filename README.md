# WeChat Whale Core · 大肥鱼

## 安装与运行

将[仓库链接](https://github.com/gg18228392653-sudo/wechat-whale-core)交给有终端权限的 Agent，并附上这句话：

> 克隆这个仓库，按根目录的 AGENTS.md 安装，运行自检，并报告结果。

环境：Git、Node.js 20+、Python 3.10+（含 `venv`、`pip`），以及可访问的 GitHub 和 Python 包索引。安装会下载 Pillow 和 Python 构建依赖。

```shell
git clone https://github.com/gg18228392653-sudo/wechat-whale-core.git
cd wechat-whale-core
python scripts/setup.py
```

Windows 也可用 `py -3 scripts/setup.py`；macOS/Linux 用 `python3 scripts/setup.py`。脚本在仓库内创建或复用 `.venv`，安装 Python 包和 Pillow，运行两套测试和群聊示例。退出码为 `0`、最后一行为 `Installation and verification passed` 表示安装通过。Node 部分没有第三方依赖。pip 以隔离模式运行，不读取用户级配置或 `PIP_*` 环境变量。

安装后可单独运行：

```shell
node examples/group-chat.mjs
node --test
```

示例输入三条合成群消息，前两条是同一人的问话和补充，第三条在和别人说话。输出 `eligible: ["1", "2"]`，重复提交同一批次返回 `duplicate`。示例不调用模型或微信；显示的回复是固定样例。

## 接入群聊

本仓库提供群聊核心，不含微信登录、微信收发、客户端自动化或模型服务。真实微信接入需要另备适配器，演示和测试不需要账号或 API 密钥。

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