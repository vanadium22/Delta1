# 个人微信接口调研：群内 @ 上下文与指定消息发送

核查日期：2026-10-15（北京时间）。本轮响应“先查看 GitHub 插件接口”：交付接口证据、选型限制和接入设计，**尚未实现微信运行入口、监听或发送按钮**。未安装、激活或运行第三方插件，未读取私人聊天、未发送消息。券单 App 的现有业务与依赖不变。

## 结论与候选方案

接口层面存在收发能力，但还没有在公司微信上验证可用的完整方案。最关键的缺口是准确识别真正的 @、稳定定位目标群及补齐上下文。用户尚未给出指定插件仓库与公司微信完整版本号；以下为候选对比，不表示已选定依赖。

| 候选 | 已查到的能力 | 本项目判断 |
| --- | --- | --- |
| wxauto 当前官方产品线 | Windows UI Automation；当前安装文档覆盖微信 4.1；有窗口消息读取、文本发送，Plus 有监听回调 | 若公司是 4.1，可优先做兼容性验证；精确 @ 识别仍待证实 |
| FreeWisdom/wxauto-4.0 社区分支 | 可审阅的 Python 源码包含监听、读取、发送 | README 只声明适配 4.0.5，不推断适配当前所有 4.x；不能与官方当前同名 pip 包混为一谈 |
| lich0821/WeChatFerry | Hook/RPC；群 ID、本人 wxid、消息 XML、接收队列、文本发送 | 2026-07-10 已归档；README 最新适配记录为 3.9.12.51。只作为接口参照，不作为当前默认接入方案 |

依据：[wxauto 安装与版本说明](https://docs.wxauto.org/docs/install.html)、[社区分支固定版 README](https://github.com/FreeWisdom/wxauto-4.0/blob/bd7c5233e79c0a185638a325bf6d30607244dfa8/README.md)、[WeChatFerry 仓库归档状态](https://github.com/lich0821/WeChatFerry)、[其固定版适配记录](https://github.com/lich0821/WeChatFerry/blob/0f5c60a034fcac234cabd000b49c9200defa7f7d/README.MD)。

### wxauto 的版本和分发不能混用

官方当前文档列出免费包 `wxauto4`（Python 3.9–3.12，免费版最新支持客户端 4.1.8.107）和 Plus 包 `wxautox4`（Python 3.9–3.13）。`AddListenChat` 标记为 Plus 功能。券单现用 Python 3.13，免费包不能直接作为已兼容依赖加入；若试验免费版，建议独立 Python 3.12 进程，保留主 App 环境。Plus 的具体客户端小版本仍需现场核验。[安装文档](https://docs.wxauto.org/docs/install.html)、[WeChat 类](https://docs.wxauto.org/docs/class/WeChat.html)。

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

可提交适配器源码、合成测试、无真实账号的配置模板和说明。拟用 `wechat.local.json` 保存正式本机设置，演示配置放 `data/demo/`；正式缓存/待发任务/本地诊断放 `data/live/wechat/`，演示放 `data/demo/wechat/`。这些路径受既有 `*.local.*`、`data/`、`*.jsonl`、`*.sqlite*` 忽略规则覆盖，本轮没有创建真实配置或聊天数据。

账号标识、群标识、聊天正文、附件、插件二进制、登录材料、激活码与本机路径留在本机，不复制进 Git、公共日志或文档。未来新增日志/数据路径时需重新检查忽略规则。公司 pull 只同步源码与说明，不传输微信登录状态、授权或聊天记录。

## 下一步所需信息与验收

接入前需知道：指定插件仓库（若有）、公司 Windows 微信完整版本号，以及使用免费版还是已有 Plus。群身份、本人群昵称/微信 ID、上下文范围在本机配置；没有这些信息时本轮调研仍可完成，但不能宣称正式功能已接通。

后续在明确的测试群验证：普通消息、真正 @ 我、@ 别人、@所有人、引用/手打 @ 文本、重名；前后文不足和持续补齐；群切换、重命名、断线重连及重启去重；指定文本仅发送一次、错误群拒发、发送超时不盲重试；演示完全隔离。随后才评估公司实际使用。当前未执行这些微信验收，也未调用公司 Wind/共享盘。

本轮仅静态核对公共文档、固定源码、GitHub 元数据及本项目接入边界；文档检查与公司发布结果记录于 [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md) 和公司分支根目录 `COMPANY_SYNC.md`。本轮没有 UI 变更，也没有可启动的微信模块。

## 来源版本快照

2026-10-15 通过 GitHub API 读取默认分支 HEAD；源码链接固定到以下提交。网页文档为当天在线版本，未来接入前须复核，不把页面标题、pip 包名和 fork 版本等同。

| 仓库 | 分支 | 核对提交 | API 归档状态 |
| --- | --- | --- | --- |
| cluic/wxauto | main | `05e5a52379c99f401dc512acfdd811b3d701da8b` | false |
| FreeWisdom/wxauto-4.0 | main | `bd7c5233e79c0a185638a325bf6d30607244dfa8` | false |
| lich0821/WeChatFerry | master | `0f5c60a034fcac234cabd000b49c9200defa7f7d` | true |

当前 `cluic/wxauto` 固定版目录包含文档与包元数据，未发现 `wxauto/` 实现目录；因此本报告没有把旧 GitHub 页面当作当前可直接集成的完整源码。WCF 在线文档标题仍为旧版本，接口细节优先与以上固定源码对照。
