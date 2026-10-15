# 个人微信接口调研：群内 @ 上下文与指定消息发送

核查日期：2026-10-15（北京时间）。本文记录最初“先查看 GitHub 插件接口”的调研与设计。用户随后授权测试本人测试号：UIA 候选连接失败，本地 OCR 已从其他会话自动找群、读取三条前后文样本并发送一条测试消息，用户确认手机收到。真正 @ 与纯文本对照表明原生提示可提供群级未读证据，正文无法逐条区分。最新结果见 [实机验证与安全审查](WECHAT_VALIDATION.md)。**尚未通过完整验收，未接入券单，没有公司可运行的微信入口。** 券单 App 的现有业务与依赖不变。

## 结论与候选方案

接口层面存在收发能力，但还没有在公司微信上验证可用的完整方案。最关键的缺口是准确识别真正的 @、稳定定位目标群及补齐上下文。**用户已明确没有指定插件，需要我们主动检索 GitHub、官方等渠道的 Python 或其他接口。** 公司微信完整版本未知，不影响本轮调研；以下为候选对比，不表示已选定依赖。

| 候选 | 已查到的能力 | 本项目判断 |
| --- | --- | --- |
| Hello-Mr-Crab/pywechat 内的 pyweixin | Python + Windows UI 自动化；当前 README 声明 4.1.6+，源码有窗口监听、向上读取消息及指定文本发送 | 开源源码可核对，可与 wxauto 一起优先验证；目前所查监听接口未提供准确 @ 名单 |
| wxauto 当前官方产品线 | Windows UI Automation；当前安装文档覆盖微信 4.1；有窗口消息读取、文本发送，Plus 有监听回调 | 若公司是 4.1，可优先做兼容性验证；精确 @ 识别仍待证实 |
| FreeWisdom/wxauto-4.0 社区分支 | 可审阅的 Python 源码包含监听、读取、发送 | README 只声明适配 4.0.5，不推断适配当前所有 4.x；不能与官方当前同名 pip 包混为一谈 |
| lich0821/WeChatFerry | Hook/RPC；群 ID、本人 wxid、消息 XML、接收队列、文本发送 | 2026-07-10 已归档；README 最新适配记录为 3.9.12.51。只作为接口参照，不作为当前默认接入方案 |
| wechaty/python-wechaty | Python 异步 SDK；message 事件、群对象、mention_self、say | API 较完整，但依赖实际 Puppet/网关提供微信连接；SDK 存在不等于当前个人账号可登录 |

依据：[wxauto 安装与版本说明](https://docs.wxauto.org/docs/install.html)、[社区分支固定版 README](https://github.com/FreeWisdom/wxauto-4.0/blob/bd7c5233e79c0a185638a325bf6d30607244dfa8/README.md)、[WeChatFerry 仓库归档状态](https://github.com/lich0821/WeChatFerry)、[其固定版适配记录](https://github.com/lich0821/WeChatFerry/blob/0f5c60a034fcac234cabd000b49c9200defa7f7d/README.MD)。

### 腾讯官方接口的适用范围

本轮检索没有找到腾讯公开提供的、供个人微信账号直接读取任意现有群消息并自动发送消息的 Python/HTTP 接口。这是本轮检索结论，不是对所有内部或未公开接口的断言。

核实到的腾讯官方资料分别面向公众号和企业微信群：[公众号 API](https://cloud.tencent.com/document/product/1301/100187) 的账号主体是公众号；[企业微信群机器人配置](https://cloud.tencent.cn/document/product/1551/84530) 描述通过 webhook 让企业微信群接收腾讯云通知，标题中的“接收消息”不是读取群成员聊天记录。依据这些资料，不能把这些能力当成现有个人微信群的读写接口。Python 可以调用 HTTP，但语言封装不会改变接口服务对象。

本轮未成功直读微信开发者站的“接收普通消息”和企微 `99110` 页面，因此这里仅依据可读取的腾讯云官方文档界定上述能力，不引用第三方转载来宣称已完整审计腾讯接口目录。若未来将业务迁到企业微信，需要另查具体群类型、消息回调及历史获取能力，不能直接套用个人群设计。

### 补充 Python 候选：pyweixin 与 Wechaty

`Hello-Mr-Crab/pywechat` 当前主要维护 `src/pyweixin`，README 声明微信 4.1.6+、Python 3.10+；旧 `pywechat` 与新版不能混用。固定源码核对到：

| pyweixin 接口 | 当前实现语义 |
| --- | --- |
| `Messages.pull_messages(friend, number, ...)` | 通过 UI 向上滚动读取消息；返回发送人、内容、类型等，仍受客户端能显示的记录限制 |
| `Monitor.listen_on_chat(dialog_window, duration, ...)` | 按 UI runtime ID 轮询，**持续时间结束后返回汇总字典**，不是逐条实时回调；群发送人拆分需要群成员信息 |
| `Messages.send_messages_to_friend(friend, messages, at_members=..., ...)` | 可指定好友或群、文本列表及群昵称形式的 @；签名返回 `None`，不能把无异常返回当送达回执 |

所查 `WeChatAuto.py` 未见 `mention_self` / `atuserlist` / 独立 `at_only` 接口；旧文章中的“被 @ 自动回复”不能作为新版精确 @ 能力的依据。实现实时前后文需另外组织事件流、缓存和去重，并验证群身份及 @ 证据。适配器要控制窗口关闭和媒体保存参数，避免直接照抄默认行为。[固定版 README](https://github.com/Hello-Mr-Crab/pywechat/blob/8589baa049bb91d3a500602c167f07b2f8397a13/README.md)、[实际源码](https://github.com/Hello-Mr-Crab/pywechat/blob/8589baa049bb91d3a500602c167f07b2f8397a13/src/pyweixin/WeChatAuto.py)。

Wechaty 的 Python 源码有 `message.room()`、`await message.mention_self()`、`await message.say(text, mention_ids=...)`。`mention_self()` 检查本人 ID 是否在底层返回的 `payload.mention_ids`；没有名单时返回 False，因此需要验证底层提供了名单，不能把缺失数据当“肯定没 @”。接入通常还需可用的 Puppet Service/网关、地址与 token；当前服务商可用性、成本和公司账号登录未验证。[Python SDK](https://github.com/wechaty/python-wechaty)、[消息源码](https://github.com/wechaty/python-wechaty/blob/a69851c448e2c845f807b62e12185d8dd9a06bec/src/wechaty/user/message.py)、[Puppet Service 客户端](https://github.com/wechaty/python-wechaty-puppet-service)。

针对本项目的判断：若优先本机、可审阅的 Python 实现，先验证 `pyweixin` 与 wxauto 的客户端兼容性和 UI 消息结构；若必须基于真实成员 ID 准确识别 @，则需证明底层能提供名单，不能用正文匹配凑成“已实现”。Wechaty 可作后一条路线的候选，前提是先验证连接提供方。现阶段不指定采购或安装任何方案。

### wxauto 的版本和分发不能混用

官方安装文档列出免费包 `wxauto4`（页面标注 Python 3.9–3.12，客户端上限 4.1.8.107）和 Plus 包 `wxautox4`（Python 3.9–3.13）。但后续核对 PyPI **wxauto4 41.1.7 已提供 cp313 wheel、元数据为 `>=3.9,<3.14`**，与页面有差异；不能继续断言没有 Python 3.13 包，也不能由包存在推断已兼容本机微信。`AddListenChat` 在官网标记为 Plus 功能。试验继续使用独立环境，实际运行兼容性和分发安全性见验证记录，不能直接加入券单依赖。[安装文档](https://docs.wxauto.org/docs/install.html)、[WeChat 类](https://docs.wxauto.org/docs/class/WeChat.html)、[41.1.7 元数据](https://pypi.org/pypi/wxauto4/41.1.7/json)。

旧 GitHub README 的使用声明与当前 Plus 分发条款不同。当前 Plus 条款涉及组织内部工作流、设备数及凭证分发边界；具体采购和授权以所选产品记录为准。本轮没有购买、复制插件或凭证，也没有判断任意 fork 的公司使用授权。[旧仓库 README](https://github.com/cluic/wxauto/blob/05e5a52379c99f401dc512acfdd811b3d701da8b/README.md)、[当前 Plus 条款](https://docs.wxauto.org/legal/commercial-license.html)。

## 接口对应与容易误判的地方

以下是已核对的第三方接口签名，不是 Delta1 已实现接口或可直接运行的完整程序。

| 需求 | wxauto 当前文档 | WeChatFerry 固定版源码 |
| --- | --- | --- |
| 选群/身份 | `ChatWith(who, exact=True)`、`ChatInfo()` | `get_self_wxid()`；事件的 `roomid`、`sender` |
| 收取新消息 | Plus `AddListenChat(nickname, callback)`，回调 `(msg, chat)` | `enable_receiving_msg()` 后 `get_msg(block=True)`；空队列会抛 `queue.Empty` |
| 读取已有消息 | `GetAllMessage()`：当前聊天窗口内的消息 | `query_sql(db, sql)` 提供数据库查询能力，未提供已核实的通用“@ 前后 N 条”接口 |
| 判断 @ 我 | 所查当前 Message 文档未公开按本人 wxid 验证 @ 的接口，不能假设存在 `is_at` | `msg.is_at(self_wxid)`；还需审查其实现边界 |
| 发指定文本 | `SendMsg(msg, who, clear=True, at=None, exact=True)` 返回 `WxResponse` | `send_text(msg, receiver, aters='')` 返回整数，**0 为接口成功** |

依据：[wxauto Chat](https://docs.wxauto.org/docs/class/Chat.html)、[WeChat](https://docs.wxauto.org/docs/class/WeChat.html)、[Message](https://docs.wxauto.org/docs/class/Message.html)、[WCF client.py](https://github.com/lich0821/WeChatFerry/blob/0f5c60a034fcac234cabd000b49c9200defa7f7d/clients/python/wcferry/client.py)、[WCF wxmsg.py](https://github.com/lich0821/WeChatFerry/blob/0f5c60a034fcac234cabd000b49c9200defa7f7d/clients/python/wcferry/wxmsg.py)。

1. **真 @ 与文字提及。** WCF 的 `is_at` 在 XML 的 `atuserlist` 中用正则搜索 wxid，且从正文排除“@所有人”等文字；它不是严格解析后逐项比较。后续适配应解析名单并精确匹配完整 ID，分别记录直接 @、@所有人、普通文字提及和无法判断。UI 方案若只能得到“@昵称”，应标为候选，不自动认定为准确命中；同名、改名、引用旧消息都要验证。
2. **窗口消息不等于全部历史。** wxauto 的 `GetAllMessage()` 文档只承诺当前窗口消息；`id` 是会随 UI 切换变化的 ID，`hash` 也可能重复。因此不能承诺启动前任意日期历史，不能仅按正文或 hash 去重。社区分支另有 `GetNewMessage()`，不能把该分支方法当作当前官方免费版保证。
3. **上下文需要自行组织。** 前文来自已读取的窗口/本地缓存，后文必须等待后续事件到达。数据库查询也不能取得尚未发生的消息。若历史未覆盖、监听中断或窗口丢失，必须显示缺口。
4. **发送目标和结果。** wxauto 子窗口的 `who`、`exact` 参数无效，必须先核验绑定窗口；同名群仅靠精确名称仍不足以消歧。WCF 使用 roomid，群 @ 使用 wxid 列表；普通正文里写“@姓名”不能替代结构化参数。接口返回成功不等于对方已收到或已读，超时不代表一定没发出。

社区源码依据：[wx.py](https://github.com/FreeWisdom/wxauto-4.0/blob/bd7c5233e79c0a185638a325bf6d30607244dfa8/wxauto4/wx.py)、[消息基类](https://github.com/FreeWisdom/wxauto-4.0/blob/bd7c5233e79c0a185638a325bf6d30607244dfa8/wxauto4/msgs/base.py)、[发送实现](https://github.com/FreeWisdom/wxauto-4.0/blob/bd7c5233e79c0a185638a325bf6d30607244dfa8/wxauto4/ui/chatbox.py)。

## Delta1 接入设计建议（待实现）

保持 Python + PySide6。微信适配器独立运行，通过本机通信向 App 提供消息事件和发送结果；只有用户配置并启动时连接微信。正式/演示分别使用真实适配器和合成事件，演示进程不得初始化微信客户端。任何群消息都是数据，不能作为程序指令执行，也不据此自动修改券单库存、价格、费率或成交判断。

建议数据流：指定群 → 接收并校验群身份 → 本地有界缓存 → @ 命中与上下文记录 → App 展示。发送由独立的指定内容任务触发，不因收到 @ 自动生成或发送回复。

| 本项目拟提供的操作 | 约束 |
| --- | --- |
| 启动/停止指定群监听 | 本机配置允许的群；保存适配器版本、账号/群绑定与启动时间；暂停/断线显式显示 |
| 列出 @ 与上下文 | 保存命中依据、前后实际条数、消息来源及缺口；按群隔离；支持后文到达后更新 |
| 发送指定文本 | 固定目标群和用户指定内容；任务 ID 防重复；错误、未知结果与接口成功分开显示；未知结果不自动重试 |

建议初始窗口为前 10 条、后 10 条、后文最长等待 120 秒，全部可配置，**不是已确认业务口径或现有默认值**。首次命中就展示现有上下文，随后持续补后文；到时不足则显示实际数量。计数建议按消息条数，包括非文本占位，时间分隔符不计数。多次 @ 各自保存命中 ID，共用缓存但不吞掉相同正文的合法重复消息。

重连后先识别覆盖缺口并去重，再继续监听；只能拿到 UI ID 时按窗口会话范围使用，不能声称跨重启永久唯一。真实时间取不到时分别记录本机观察时间与未知的发送时间。不得把“当前只读到这些”显示为“群内完整记录”。

现有行业联系表仍只提供询券线索。照片暂读的群名/人名尚未核对，不应自动升级为收发配置；发送也不代表对方接受需求。未来若需要在指定消息中 @ 交易员，须另外核对真实成员映射。

### 本地与 Git 边界

可提交适配器源码、合成测试、无真实账号的配置模板和说明。拟用 `wechat.local.json` 保存正式本机设置，演示配置放 `data/demo/`；正式缓存/待发任务/本地诊断放 `data/live/wechat/`，演示放 `data/demo/wechat/`。这些路径受既有 `*.local.*`、`data/`、`*.jsonl`、`*.sqlite*` 忽略规则覆盖。后续独立验证材料保存在忽略的 `data/wechat_probe/`；没有创建正式微信配置。

账号标识、群标识、聊天正文、附件、插件二进制、登录材料、激活码与本机路径留在本机，不复制进 Git、公共日志或文档。未来新增日志/数据路径时需重新检查忽略规则。公司 pull 只同步源码与说明，不传输微信登录状态、授权或聊天记录。

## 下一步所需信息与验收

后续先核对公司 Windows 微信完整版本号，再依据本报告选定并锁定候选；用户已经明确没有指定插件，不应反复要求用户寻找仓库。只有选择 Plus 路线时再核对对应授权。群身份、本人群昵称/微信 ID、上下文范围在本机配置；没有这些信息时本轮调研仍可完成，但不能宣称正式功能已接通。

后续在明确的测试群验证：普通消息、真正 @ 我、@ 别人、@所有人、引用/手打 @ 文本、重名；前后文不足和持续补齐；群切换、重命名、断线重连及重启去重；指定文本仅发送一次、错误群拒发、发送超时不盲重试；演示完全隔离。随后才评估公司实际使用。目前仅完成验证记录中的连接/标题检查与安全缺陷复现，上述收发验收尚未完成；用户表示稍后再配合现场测试，未调用公司 Wind/共享盘。

最初调研仅静态核对公共文档、固定源码、GitHub 元数据及本项目接入边界；后续实机与安全结果另见 [WECHAT_VALIDATION.md](WECHAT_VALIDATION.md)。文档检查与公司发布结果记录于 [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md) 和公司分支根目录 `COMPANY_SYNC.md`。券单没有 UI 变更，也没有可启动的微信模块。

## 来源版本快照

2026-10-15 通过 GitHub API 读取默认分支 HEAD；源码链接固定到以下提交。网页文档为当天在线版本，未来接入前须复核，不把页面标题、pip 包名和 fork 版本等同。

| 仓库 | 分支 | 核对提交 | API 归档状态 |
| --- | --- | --- | --- |
| cluic/wxauto | main | `05e5a52379c99f401dc512acfdd811b3d701da8b` | false |
| FreeWisdom/wxauto-4.0 | main | `bd7c5233e79c0a185638a325bf6d30607244dfa8` | false |
| lich0821/WeChatFerry | master | `0f5c60a034fcac234cabd000b49c9200defa7f7d` | true |
| Hello-Mr-Crab/pywechat | main | `8589baa049bb91d3a500602c167f07b2f8397a13` | false |
| wechaty/python-wechaty | main | `a69851c448e2c845f807b62e12185d8dd9a06bec` | false |

当前 `cluic/wxauto` 固定版目录包含文档与包元数据，未发现 `wxauto/` 实现目录；因此本报告没有把旧 GitHub 页面当作当前可直接集成的完整源码。WCF 在线文档标题仍为旧版本，接口细节优先与以上固定源码对照。
