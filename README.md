# Multi-Agent Ops Analyst —— 企业级多智能体运营分析助手

基于 LangGraph 构建的多智能体协作系统，支持自然语言驱动的 SQL 查询、RAG 规则检索、循环自我修正和人工中断恢复，并通过 SSE 实时推送分析报告。

## ✨ 核心特性

- 🧠 多节点智能协作：Router（路由）→ Executor（并行执行）→ Validator（循环校验）→ Summarizer（报告生成）
- 🔄 闭环自我修正：SQL 执行失败或结果为空时，Validator 节点自动触发重试（最多 2 次），并携带修正后的查询重新执行
- 📚 RAG 增强分析：并行检索 ChromaDB 中的运营规则文档，与 SQL 结果融合生成更全面的分析报告
- 🚦 人工中断恢复（HITL）：当系统连续重试仍无法解决问题时，自动挂起等待人工指令，支持任务恢复
- 📡 实时流式响应：通过 SSE 向用户推送"路由分析中 → 执行查询中 → 校验中 → 生成报告中"的完整执行轨迹
- 💾 状态持久化：使用 SqliteSaver 保存每个任务的完整执行状态，服务重启后仍可恢复

## 🛠️ 技术栈

核心框架：FastAPI + Uvicorn
Agent 编排：LangGraph (StateGraph, Command, SqliteSaver)
向量数据库：ChromaDB（本地持久化）
结构化数据：SQLite
流式传输：SSE (sse-starlette)
嵌入模型：sentence-transformers/all-MiniLM-L6-v2
配置管理：python-dotenv

## 🏗️ 系统架构图

用户问题
   ↓
Router 节点：判断意图（SQL / RAG / BOTH）
   ↓
Executor 节点：并行执行 SQL 查询 + RAG 检索
   ↓
Validator 节点：校验 SQL 结果是否有效
  - 有效 → 进入 Summarizer
  - 无效 且 重试 < 2 → 修正 SQL，跳回 Executor
  - 无效 且 重试 = 2 → 挂起，等待人工介入
   ↓
Summarizer 节点：融合 SQL + RAG 生成报告
   ↓
SSE 流式推送最终报告

## 📁 项目结构

multi-agent-ops-analyst/
├── agents/
│   └── graph.py            # LangGraph 状态图定义
├── api/
│   └── routes.py           # FastAPI 路由（/invoke, /stream, /resume）
├── tools/
│   ├── sql_tool.py         # SQL 执行工具（@tool 封装）
│   └── rag_tool.py         # ChromaDB 检索工具
├── models/
│   └── state.py            # Pydantic 状态模型
├── db/
│   └── init_db.py          # SQLite 初始化与模拟数据生成
├── data/
│   └── docs/               # RAG 知识库文档（运营规则）
├── config.py               # 环境变量配置
├── main.py                 # FastAPI 启动入口
├── requirements.txt        # 依赖清单
└── .env.example            # 环境变量模板

## 🚀 快速启动

1. 克隆项目

git clone https://github.com/你的用户名/multi-agent-ops-analyst.git
cd multi-agent-ops-analyst

2. 安装依赖

pip install -r requirements.txt

3. 配置环境变量

复制 .env.example 为 .env，填入你的 API Key：
OPENAI_API_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
OPENAI_BASE_URL=https://api.deepseek.com/v1

4. 初始化数据库（自动生成模拟数据）

python -c "from db.init_db import seed_data; seed_data()"

5. 启动服务

python main.py

6. 测试 API

访问 http://localhost:8080/docs 查看 Swagger 文档。

## 📖 API 使用示例

1. 发起分析任务
curl -X POST http://localhost:8080/api/v1/invoke -H "Content-Type: application/json" -d '{"question": "智能手机产品线最近三个月的营收趋势如何？"}'
返回示例：
{
  "thread_id": "abc-123-def-456",
  "status": "processing"
}

2. 查看实时分析进度（SSE 流式）
curl http://localhost:8080/api/v1/stream/abc-123-def-456
实时推送示例：
data: {"event": "router", "content": "正在分析问题意图..."}
data: {"event": "executor", "content": "正在并行查询数据库..."}
data: {"event": "validator", "content": "校验通过 ✅"}
data: {"event": "summarizer", "content": "📊 智能手机产品线营收趋势：..."}
data: [DONE]

3. 人工中断恢复（HITL）
当系统挂起时：
curl -X POST http://localhost:8080/api/v1/resume/abc-123-def-456 -H "Content-Type: application/json" -d '{"instruction": "忽略错误，直接生成报告"}'

## 📖 使用示例

1.智能手机产品线最近三个月的日营收趋势如何？帮我看看有没有明显的波动或异常。（展示“SQL 查询 + 趋势分析”能力）


## 🎯 核心难点与设计决策

SQL 查询失败时如何自动恢复？

Validator 节点捕获异常，retry_count 递增，通过 Command(goto="Executor") 跳转回执行节点。

如何防止无限循环？

设置 max_retries=2，耗尽后挂起等待人工指令。

RAG 和 SQL 谁先执行？

并行执行（asyncio.gather），互不阻塞。

服务重启后任务状态丢失？

SqliteSaver 持久化 State，通过 thread_id 恢复。

## 🧪 模拟数据说明

项目启动时会自动在 SQLite 中生成 60 条运营数据，覆盖 3 个产品线（智能手机、笔记本电脑、平板电脑），时间跨度为最近 3 个月，包含：日期、产品线、营收、成本、活跃用户数。
