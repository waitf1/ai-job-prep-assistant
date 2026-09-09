# 第一阶段 MVP 说明

## 目标

第一阶段只完成最小闭环：

```text
输入简历文本 + 输入岗位 JD -> 调用 OneAI/OneAPI -> 输出岗位匹配分析
```

本阶段暂不实现：

- PDF / Word 文档解析；
- RAG 个人资料库；
- Agent 工作流；
- Tool Calling；
- 模拟面试。

这些能力会在后续阶段逐步加入。

## 当前已包含的模块

```text
app/
├── config.py                 # 从环境变量读取模型配置
├── main.py                   # Streamlit 页面入口
├── llm/
│   └── client.py             # OneAI / OneAPI 兼容模型调用封装
└── services/
    └── match_analyzer.py     # 岗位匹配分析服务

prompts/
├── job_match_system.txt      # 系统角色和分析规则
└── job_match_user.txt        # 用户输入模板
```

## 运行前配置

复制 `.env.example` 为 `.env`，然后填写真实配置：

```env
LLM_BASE_URL=https://your-oneai-domain.example.com/v1
LLM_API_KEY=your_api_key_here
LLM_MODEL=qwen-plus
LLM_TEMPERATURE=0.2
```

注意：

- `.env` 中包含真实 API Key，不要提交到仓库；
- `LLM_BASE_URL` 应该是 OneAI / OneAPI 的 OpenAI-compatible 地址；
- `LLM_BASE_URL` 不是本项目 Streamlit 页面地址，不能填写 `http://localhost:8501/v1` 或 `http://你的电脑IP:8501/v1`；
- 如果是自建 OneAPI，地址通常类似 `http://服务器IP:3000/v1`；如果是平台服务，请使用平台提供的 API Base URL；
- `LLM_MODEL` 可以后续更换为不同模型。
- 如果直接调用阿里云百炼 / DashScope 的 OpenAI 兼容接口，`LLM_BASE_URL` 通常为 `https://dashscope.aliyuncs.com/compatible-mode/v1`，`LLM_API_KEY` 需要填写模型服务页面生成的 API Key，不是阿里云 AccessKey ID / AccessKey Secret。

## 安装依赖

建议使用项目独立虚拟环境，不要直接安装到 Anaconda `base` 环境。

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

如果已经在 `base` 环境里安装过依赖并出现冲突，可以先不用处理 `base` 环境，后续运行本项目时只使用 `.venv` 即可。

不建议直接执行：

```bash
pip install -r requirements.txt
```

除非你已经确认当前终端处于项目专用虚拟环境中。

## 启动方式

在项目根目录运行：

```bash
streamlit run app/main.py
```

启动后在页面中粘贴：

- 简历内容；
- 岗位 JD；

点击“开始分析”即可看到大模型生成的岗位匹配分析。

## 本阶段验证重点

需要确认：

- OneAI / OneAPI 是否能正常调用；
- Prompt 输出是否结构清晰；
- 模型是否能准确识别岗位要求；
- 模型是否能基于简历内容给出具体建议；
- 模型是否存在明显胡编。
- 模型是否能区分“当前可直接写进简历”和“完成补充项目后才能写”的内容。

## 下一阶段方向

第一阶段跑通后，下一步加入文档解析：

- 支持上传 PDF；
- 支持上传 docx；
- 支持上传 txt / md；
- 将解析出的文本用于当前岗位匹配分析。

文档解析完成后，再进入 RAG 阶段。
