# 个人微信候选：实机验证与安全审查

验证日期：2026-10-15。用户授权测试本人已登录的测试号及指定测试群，目标是**自动找到目标群、识别真正的 @ 本人、读取前后文、发送指定消息**；验证可行后再接入券单。本次仅交付验证记录，券单运行代码、依赖和业务口径未变。

## 当前结论

**还没有通过完整验收、可直接推荐给公司运行的插件。** pyweixin 与 wxauto 社区版的 UIA 连接在本机失败；本地 OCR 已能截图并准确识别完整测试群标题，但原项目存在区域适配及发送目标校验缺陷，需要独立适配和进一步实测。

本次测试微信为 **4.1.15.13**，Python **3.13.9**，不代表公司环境。用户在测试途中表示有事，稍后再配合发送真正 @ 样本及提供可操作桌面；因此自动找群、@/上下文和真实发送暂停。**发送尝试为 0，未启动常驻监听、未读取聊天数据库或提取密钥、未修改微信进程内存。**

后续优先继续**可审阅、仅在本机处理的 OCR 适配验证**，因为它已越过本机的控件树障碍；这不是“现成 OCR 机器人已通过验收”的结论。若必须可靠区分真正 @ 与手打 @ 文本，OCR 正文匹配本身不够，必须另有可验证证据；不能为追求可用而把文字候选改称准确识别。

## 实际执行结果

| 检查 | 实际结果 | 能说明什么 |
| --- | --- | --- |
| pyweixin 导入及只读连接 | 固定源码可导入；`Tools.get_weixin_hwnd()` 返回 0；`Navigator.connect_weixin()` 抛出 `NotFoundError` | 用户手动打开测试群后仍无可用 UIA 连接，未执行拉消息或发送 |
| Windows UIA 元素 | 微信只暴露 Qt 外层与渲染 Pane，没有可用聊天列表/输入框 | 这是当前账号与客户端组合的现场结果，不能断言所有账号或所有 4.x 都不可用 |
| wxauto 社区版连接 | `wxauto4.ui.WeChatMainWnd()` 报“未找到微信窗口” | 特意绕过高层构造函数的删除更新目录行为；没有启动监听 |
| 小漓项目的本地视觉后端 | `PrintWindow` 截图成功；本地 PP-OCRv5 能从完整标题区域准确读出指定测试群及人数 | 截图/标题识别可用；没有取得结构化群 ID 或消息 @ 名单 |
| 视觉后端原始默认区域 | `connect()` 成功，但 `read_title()` 截掉群名前部 | 默认区域按作者显示环境标定，不适配本机当前布局；“已连接”不等于识别正确 |
| 自动搜索目标群 | 前台焦点核验失败时停止；随后微信不可见，用户暂停现场配合 | 尚未完成从其他会话自动找到指定群的验收，不能把预先打开的群算作自动找群成功 |
| 真 @、前文、后文 | 尚未收到并核验约定测试样本 | 未验证；空白画面/未执行不能作为“没有 @”结论 |
| 指定文本发送 | 0 次真实发送尝试 | 未验证，未声称接口成功、送达或已读 |

上游 pyweixin 也说明存在 UI 树不可见的适配问题，但现场失败原因不能仅凭说明归因到账号类型。[固定版说明](https://github.com/Hello-Mr-Crab/pywechat/blob/8589baa049bb91d3a500602c167f07b2f8397a13/Weixin4.0.md)。

## 安全审查发现

区分三件事：**恶意植入证据、正常但不适合本任务的功能、尚无法审查的范围**。下列发现不把遥测、Hook 或数据库访问一概称作木马，也不作“绝对安全”保证。

| 候选 | 本次检查和发现 | 处理 |
| --- | --- | --- |
| pyweixin | 对 10 个 Python 源文件做 AST/敏感调用检索，复核连接路径；本轮所查路径未发现聊天上传或后台远控代码。依赖包括音频/桌面自动化组件，未逐行审计全部依赖 | 只运行连接探测；UIA 失败，不接入 |
| FreeWisdom/wxauto-4.0 | `WeChat.__init__()` 无条件调用 `delete_update_files()`；该函数删除当前用户微信自动更新目录的子项，监听循环也调用它 | 未执行这个构造函数或删除操作；底层只读连接仍失败，不直接采用 |
| 官方 wxauto4 41.1.7 | 官方 cp313 wheel 中有 15 个 `.pyd`；可读 `param.py` 设置 `TELEMETRY_ENABLED=True`，并列出广告与遥测上报地址及设备指纹盐配置 | 核对分发哈希和病毒扫描；未导入编译核心，未向该接口发请求。没有确定实际上传字段，不能声称上传了聊天，也不能完成源码级排除后门 |
| 官方 wxautox4 41.2.1 | 官方 cp313 wheel 含 20 个 `.pyd`，核心不可完整源码审查；还涉及实际授权与激活 | 仅审查分发结构/哈希并扫描，未激活、购买或运行编译核心；不能把免费包的遥测结论自动套到 Plus |
| wechatauto-replica | `uia_driver.py` 使用 `WriteProcessMemory` 激活 accessibility gate；`db.py` 读取微信内存中的数据库密钥、将密钥缓存为 JSON，并包含尝试其他账号目录的回退路径 | 仅静态审阅。未运行进程修改、密钥提取或数据库路径；这些可见功能不是已证实木马，但范围超出本轮最小视觉验证 |
| 小漓 OCR 项目 | 视觉后端可单独加载；完整机器人另有向配置的 LLM API 发送正文、语音及任务桥功能。源码实际复现了发送忽略目标参数等缺陷，见下文 | 仅加载视觉后端和本地 OCR，不运行机器人主入口、外部 AI、语音或任务桥 |
| WeChatFerry / Python Wechaty | WCF 已归档、固定版适配记录为 3.9.12.51，不能拿该 DLL 在 4.1.15.13 上当作兼容实验；Wechaty SDK 仍需真实可用的 Puppet/网关 | 本次未加载 WCF DLL、未降级微信、未配置或传出登录 token；这两项属于适配/依赖评估，未完成运行测试 |

代码证据：[社区构造函数](https://github.com/FreeWisdom/wxauto-4.0/blob/bd7c5233e79c0a185638a325bf6d30607244dfa8/wxauto4/wx.py)、[社区文件删除实现](https://github.com/FreeWisdom/wxauto-4.0/blob/bd7c5233e79c0a185638a325bf6d30607244dfa8/wxauto4/utils/tools.py)、[replica UI 驱动](https://github.com/fanyuantaier/wechatauto-replica/blob/62503d76a0db069171cb4e42e87090ad285db489/wechatauto/uia_driver.py)、[replica 数据库实现](https://github.com/fanyuantaier/wechatauto-replica/blob/62503d76a0db069171cb4e42e87090ad285db489/wechatauto/db.py)、[小漓视觉实现](https://github.com/wens6515/weixin-wechat-wxauto-ocr-xiaoli/blob/5f4af1da3b0d35518b961f3cbaed4a1063413e18/xiaoli_desktop/wx_backend/visual_backend.py)、[小漓外部模型调用](https://github.com/wens6515/weixin-wechat-wxauto-ocr-xiaoli/blob/5f4af1da3b0d35518b961f3cbaed4a1063413e18/xiaoli_desktop/xiaoli_app/llm_client.py)。官方编译分发依据 [wxauto4 41.1.7](https://pypi.org/project/wxauto4/41.1.7/) 与 [wxautox4 41.2.1](https://pypi.org/project/wxautox4/41.2.1/)，可读配置来自对应 wheel，不能拿旧 GitHub 源码替代该产物。

### 视觉后端的离线缺陷复现

用合成群名和文本，将鼠标、键盘、剪贴板全部替换为测试桩，实际调用固定版实现，复现：

1. `send_text(chat, text)` 没有调用目标群切换；参数 `chat` 不决定发送目标。
2. `_foreground()` 返回 False 时，仍尝试按 Enter 并返回 True。
3. `resolve_chat_coord()` 以双向前缀匹配群名，将“测试群”当作“测试群生产”的候选坐标。

这三项是确定的行为缺陷，不是网络恶意代码判定。测试没有操作真实鼠标/键盘或发送消息。初次测试脚本把预期 False 的字段放进 `all()` 导致断言失败，修正为正确的预期语义后复现通过，没有修改上游实现去迎合结果。

### 扫描与审查的边界

- Windows Defender 的 Antivirus/RealTimeProtection 为 True，签名更新时间 2026-10-15 03:40:04 +08:00。对候选解包内容及测试环境、21 个 OCR wheel、2 个 OCR 模型分别执行定向扫描，均返回退出码 0、未发现威胁；使用禁用自动修复的扫描，未添加排除项、关闭杀毒或更改防火墙。
- 3 个候选/辅助官方 wheel 与 PyPI SHA256 一致；21 个 OCR wheel 逐一与 PyPI 发布哈希比对通过；两个 PP-OCRv5 模型与 RapidOCR 3.9.2 注册表哈希一致。GitHub 源码固定提交并记录下载 SHA256。哈希只证明所下载产物与该来源一致，不证明来源本身可信。
- AST/调用筛查覆盖 pyweixin 10 个文件、社区 wxauto 30 个文件、replica 68 个文件、小漓视觉后端 8 个文件及应用层 22 个文件，解析均通过；敏感调用逐项抽查关键路径。**不是逐行完整审计，也不是整机杀毒结论**，没有逆向全部 `.pyd`/系统组件或审计所有依赖。
- OCR 实机脚本将模型显式指向本地文件，拦截 Python socket 连接，已完成标题探测期间未观察到被拦截的联网尝试。该措施不覆盖本机原生 DLL 的全部网络能力，未做系统级抓包，不能据此保证整个依赖树绝无外联。
- 测试 venv 复用本机基础 Python 包（`--system-site-packages`）；它隔离本次新增依赖，**不是操作系统安全沙箱**。券单正式 Python 环境没有安装这些候选。

## 版本与本地材料

| 来源 | 本次固定版本 |
| --- | --- |
| Hello-Mr-Crab/pywechat | `8589baa049bb91d3a500602c167f07b2f8397a13` |
| FreeWisdom/wxauto-4.0 | `bd7c5233e79c0a185638a325bf6d30607244dfa8` |
| fanyuantaier/wechatauto-replica | `62503d76a0db069171cb4e42e87090ad285db489` |
| wens6515/weixin-wechat-wxauto-ocr-xiaoli | `5f4af1da3b0d35518b961f3cbaed4a1063413e18` |
| 官方包 | wxauto4 `41.1.7`、wxautox4 `41.2.1`、uiautomation `2.0.29` |
| 本地 OCR | RapidOCR `3.9.2`、ONNX Runtime `1.30.0`、PP-OCRv5 mobile |

版本更正：官网安装页仍写免费版 Python 3.9–3.12、客户端上限 4.1.8.107；本轮实际 PyPI 41.1.7 已提供 cp313 wheel、元数据 `>=3.9,<3.14`。因此不能继续把“没有 Python 3.13 包”当作当前结论；存在 wheel 也不代表已经兼容本机微信或完成实测。依据：[官网安装页](https://docs.wxauto.org/docs/install.html)、[该版 PyPI 元数据](https://pypi.org/pypi/wxauto4/41.1.7/json)。

下载文件位于用户规定的下载目录下 `pyweixin-validation/2026-10-15/` 与 `wechat-candidates/2026-10-15/`，逐文件核验并登记本机下载索引。源码解包、两个测试环境、探测脚本、截图、日志与精确哈希清单位于本模块忽略的 `data/wechat_probe/`，**不提交 Git，不随公司 pull 分发**。不把测试群名、账号、聊天内容或本机绝对路径写入公司配置。未启动后台服务、注册开机任务或修改公司设置。

## 恢复测试的顺序

1. 用户回到可交互桌面，微信可见并暂时不操作输入设备；不要求用户事先选择目标群。焦点/窗口不满足时停止动作。
2. 在独立试验中修正缩放区域，主动搜索本机配置的目标群，检查唯一精确匹配及打开后的群标题；相似群、重名群、目标不在当前可见列表必须单独验证。不能仅按第一个搜索结果或缓存坐标发送。
3. 由另一个成员依次发送前文、通过成员菜单真正 @ 测试号的消息、后文。再补普通手打 @、@ 别人、@所有人、引用和同名样本。观察不到结构化证据时保留“文字候选/未知”，不得宣称精确识别通过。
4. 发送仅使用唯一标记的无业务含义测试文本；发送前核验群标题、前台和输入内容，记录尝试，发送后检查本群自身消息。返回 True 不作为送达回执，结果未知时不自动重发。
5. 检查切群后的持续监听、前后文缺口、重启去重、桌面失焦、剪贴板与草稿保护；完整通过后再评估是否接入券单，演示模式不得连接真实微信。公司微信、Wind、共享盘仍需独立现场验证。

当前没有可交付公司的微信运行入口。公司更新与券单启动方式见 [COMPANY_SETUP.md](COMPANY_SETUP.md)；原始接口调研和业务边界见 [WECHAT_INTERFACE_REVIEW.md](WECHAT_INTERFACE_REVIEW.md)。
