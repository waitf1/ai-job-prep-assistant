# 从零把本项目上传到 GitHub

本教程使用 Windows PowerShell。逐条执行，报错时先停下来，不要使用强制推送。

## 1. 理解基本概念

Git 是本机版本记录工具，GitHub 是远程代码托管网站。`commit` 保存本地版本，`push` 才发送到远程。`.gitignore` 排除私人和生成文件，不删除磁盘文件，也不能消除已经提交的秘密。

## 2. 注册并准备 Git

打开 https://github.com 注册、验证账号，建议启用双重验证。提交作者邮箱可能公开，可在账号 Settings → Emails 获取 GitHub 的 no-reply 邮箱。

PowerShell 执行 `git --version`；显示版本即已安装。否则从 https://git-scm.com/downloads/win 安装 Git for Windows，保留凭据管理器，重开终端。

资源管理器打开项目根目录，在地址栏输入 `powershell` 回车。执行 `Get-Location` 和 `Get-ChildItem`，确认能看到 app、tests、README.md。

## 3. 创建空仓库

GitHub 右上角“+”→ New repository：

- 名称可用 `ai-job-prep-assistant`。
- 简介可用“基于个人资料库的岗位匹配与多轮模拟面试助手”。
- 建议先选 Private，确认后再公开；私有仓库也不能放密钥。
- 不初始化 README、.gitignore 或许可证，本地已有文件。
- Create repository 后复制 HTTPS 仓库地址。

不要把整个文件夹或压缩包拖到网页上传，这可能绕过 Git 忽略规则。

## 4. 建立本地版本记录

本次准备时项目没有 Git 仓库。已初始化时跳过 init。

```powershell
git init -b main
git config user.name "你的展示名称"
git config user.email "从 GitHub 设置复制的 no-reply 邮箱"
```

替换引号中的内容；配置只作用于这个项目。

检查私人文件是否被忽略：

```powershell
git check-ignore .env data/resumes/example.json .local/check.txt 记录.md 分析结果.txt 启动.txt 参考项目/example.py
```

应显示上述路径。检查 `.env.example` 只有占位符。

## 5. 检查并提交

首次明确指定范围：

```powershell
git add .gitignore .env.example .streamlit/config.toml README.md requirements.txt app prompts tests docs
git diff --cached --name-only
git diff --cached --stat
git diff --cached
```

最后一条查看实际内容，空格翻页、q 退出。不应出现 `.env`、data、.venv、.tmp、.local、参考项目、记录.md、分析结果.txt、启动.txt。文档、测试、截图也要检查，不能只看文件名。

若有私人文件，先不要提交。首次提交尚无 HEAD 时，可用 `git rm --cached -- "具体文件路径"` 撤出暂存，保留磁盘文件；目录需要 `-r`，只填写确定的具体目录。更新忽略规则并重查。

```powershell
git commit -m "Initial project release"
```

这一步只创建本地版本。

## 6. 上传

替换下面网址为真实仓库地址：

```powershell
git remote add origin https://github.com/你的用户名/ai-job-prep-assistant.git
git remote -v
git push -u origin main
```

凭据管理器若打开浏览器，登录正确账号授权。不要用模型 API Key 认证 GitHub，不要把访问令牌写进网址。认证失败参考下方官方说明。

刷新仓库页面，应看到代码和 README。

## 7. 核对、公开、放入简历

在网页检查文件和提交内容。下载 ZIP 到另一个目录，确认无私人资料，再按 README 新建环境验证运行，不覆盖原项目。

需要公开时：仓库 Settings → General → Danger Zone → Change repository visibility，选择 Public 并确认提示。这会公开历史，因此必须先确认提交历史没有秘密。

将仓库链接放入简历，在 About 添加简介。如需截图，用虚构或脱敏资料，不展示真实姓名、联系方式、项目保密内容、回答、令牌或账号信息。

没有 LICENSE 不等于已授予任意使用权。选择 MIT 等许可证前，需确认授权意愿和代码来源；本次未替你选择许可证。参考项目未纳入上传范围；若曾复制其代码，仍需核对并保留必要的第三方声明。

## 8. 以后更新

```powershell
git status
git diff
git add README.md
git diff --cached
git commit -m "Update documentation"
git push
```

将 README.md 换成实际改动文件。每次复查，忽略规则不能识别所有隐私。如曾在网页修改远程文件，先 `git pull --ff-only`；有分歧时停下来处理，不用 `--force`。

## 9. 常见错误

- `not a git repository`：确认目录，再初始化。
- `remote origin already exists`：先看 `git remote -v`，确实错误才用 `git remote set-url origin 正确地址`。
- `src refspec main does not match any`：检查是否已经 commit，并用 `git branch --show-current` 看分支。
- 推送被拒绝：检查权限、远程是否已有提交，不强推覆盖。
- 检测出 secret：不绕过保护。若密钥曾被发到远程或分享给别人，先在供应商撤销／轮换，再处理历史。

仅删除当前文件、添加忽略规则或改为私有不能清除历史与他人的副本。密钥暴露应先撤销。

## 官方参考

- [添加本地代码](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github)
- [身份验证](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/about-authentication-to-github)
- [移除敏感数据](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)
