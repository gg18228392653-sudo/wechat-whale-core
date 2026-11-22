# WeChat Whale Core · 大肥鱼

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