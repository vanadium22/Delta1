# script_making 项目交接

更新日期：2026-10-15。状态：已建立 Git 同步与后续开发约定，业务实现待开发。

## 位置与分支

- 家里用户原目录：`P:\project\swhy\Delta1\project\script_making`。
- 原始材料位于上述目录的 `materials`，目前有 3 份 Excel、1 份旧 Python 脚本和 1 份本地说明，均保持本机私有。
- 本次独立开发工作目录：`P:\project\swhy\Delta1\script-making-worktree`，避免混入原仓库其他未提交工作。
- 公司目录：`D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard\script_making`。
- Git 仓库：`https://github.com/vanadium22/Delta1.git`。
- 开发分支：`codex/script-making`；公司统一分支：`codex/company-apps`。

## 本次接入范围

1. 新增 README.md、AGENTS.md、本交接文件、.gitignore 与 materials/README.md，使公司 pull 后即可看到项目目录和后续规则。
2. 原材料没有移动、改写或上传。materials 下除 README.md 外全部忽略；原始脚本含硬编码登录信息、本机设置及内部业务标识，因此留作本地参考，未来复用需先整理配置与信息。
3. 当前没有启动脚本、依赖安装流程、业务数据下载或报表功能；不能宣称原脚本已适配公司环境。没有运行原脚本或访问 Wind、共享盘和业务接口。
4. 每次后续功能在开发分支完成验证、提交推送后，还需汇总并发布到公司分支。仅创建本地文件、仅提交未推送、仅推送开发分支均不会自动出现在公司 pull 结果中。

## 验证记录

本次只涉及目录与同步文档。核验项目忽略规则、明确的提交文件清单、文档链接及命令语法，并比较 5 份原始材料接入前后的 SHA256。最终汇总与远端发布记录以公司分支根目录 COMPANY_SYNC.md 为准。业务功能尚未实现，不运行业务测试或真实接口验证。

## 后续对话可用提示词

```text
请继续开发 Delta1 仓库中的 script_making 项目。

家里原项目目录：P:\project\swhy\Delta1\project\script_making
公司项目目录：D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard\script_making
开发分支：codex/script-making
公司统一分支：codex/company-apps

先读取 script_making/PROJECT_HANDOFF.md、AGENTS.md、README.md 和适用的根目录规则，
核对实际仓库根目录、worktree、分支和未提交工作，不回退或覆盖已有内容。
materials 为本地参考材料，原脚本含硬编码登录信息；复用前先移出凭据和本机配置。
本次代码、适当测试和交接说明验证后提交推送到开发分支，再将本次已验证提交
汇总、验证并推送到 codex/company-apps，保留其他模块，更新 COMPANY_SYNC.md。
公司始终在统一分支执行一次 git pull --ff-only 更新所有已发布项目。
仅提交本次代码、无真实数据的模板和说明；不提交原始材料、真实数据或本机配置，
不强推，不使用 reset/clean 覆盖工作。完成后报告公司提交号、验证结果和更新方法。

我的本次需求是：
【填写具体功能】
```
