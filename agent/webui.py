"""
agent/webui.py - 极简 Claude 风格高颜值流式 WebUI 后端服务

功能特性：
1. 彻底实现 H5/前端资源与 Python 业务逻辑解耦 (静态文件独立收归至 agent/web/)。
2. 全流程 Server-Sent Events (SSE) 真实流式输出 (打字机效果、多轮会话)。
3. 提供工作区信息检索、会话管理与流式生成 API。
4. 基于 FastAPI + Uvicorn 驱动。
"""

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, AsyncGenerator, Dict, List, Optional
from pydantic import BaseModel
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# 确保项目根目录在 sys.path 中
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from agent.docx_agent import DocxTemplateAgent
from agent.utils.get_sys_path import get_workspace_path

# 前端静态资源目录
WEB_DIR = Path(__file__).resolve().parent / "web"

app = FastAPI(title="DocxTemplateAgent WebUI API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载前端静态资源
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

# 维护全局 Agent 1 (DocxTemplateAgent) 实例与会话状态
agent_instance: Optional[DocxTemplateAgent] = None
sessions_meta: Dict[str, Dict[str, Any]] = {}


def get_or_create_agent() -> DocxTemplateAgent:
    """获取或初始化 Agent 1: 文档排版与模板引擎智能体"""
    global agent_instance
    if agent_instance is None:
        agent_instance = DocxTemplateAgent()
    return agent_instance


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default_session"


# ==============================================================================
# 1. API 路由
# ==============================================================================
@app.get("/api/info")
async def get_info():
    """获取工作区与工具基本信息"""
    agent = get_or_create_agent()
    tools = [
        {"name": t.name, "description": t.description}
        for t in agent.get_all_tools()
    ]
    return {
        "workspace_path": get_workspace_path(),
        "agent_name": "DocxTemplateAgent (Agent 1: 文档排版与模板引擎智能体)",
        "model": os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        "base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        "tools": tools,
    }


@app.get("/api/sessions")
async def get_sessions():
    """获取所有会话列表"""
    return list(sessions_meta.values())


@app.post("/api/sessions/clear")
async def clear_sessions():
    """清空所有会话"""
    global agent_instance
    sessions_meta.clear()
    agent_instance = None  # 重置 Agent 内存
    return {"status": "ok"}


# 全局默认单轮计算图最大递归步数上限 (防止 25 步过早触发 GraphRecursionError)
DEFAULT_RECURSION_LIMIT = 80


@app.post("/api/chat/stream")
async def chat_stream(request: ChatRequest):
    """
    SSE 流式对话接口：
    实时发送打字机文字流、工具调用事件与最终指标统计
    """
    agent = get_or_create_agent()
    session_id = request.session_id.strip() or "default_session"

    # 更新会话元数据
    if session_id not in sessions_meta:
        sessions_meta[session_id] = {
            "id": session_id,
            "title": request.message[:25] + ("..." if len(request.message) > 25 else ""),
            "created_at": time.time(),
        }

    async def event_generator() -> AsyncGenerator[str, None]:
        start_time = time.time()
        # 显式注入 recursion_limit，避免 LangGraph 默认 25 步导致复杂任务中断
        config = {
            "configurable": {"thread_id": session_id},
            "recursion_limit": DEFAULT_RECURSION_LIMIT,
        }

        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0

        try:
            async for event in agent.astream_events(request.message, config=config):
                event_type = event.get("event")

                # 1. 工具调用开始
                if event_type == "on_tool_start":
                    tool_name = event.get("name", "tool")
                    tool_input = event.get("data", {}).get("input", {})
                    payload = {
                        "type": "tool_start",
                        "tool": tool_name,
                        "input": tool_input,
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

                # 2. 工具调用完成
                elif event_type == "on_tool_end":
                    tool_name = event.get("name", "tool")
                    tool_output = str(event.get("data", {}).get("output", ""))
                    payload = {
                        "type": "tool_end",
                        "tool": tool_name,
                        "output": tool_output,
                    }
                    yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

                # 3. 大模型 Token 实时打字机流
                elif event_type == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        # 仅发送普通文本内容（工具调用参数不作为文本流出）
                        if not getattr(chunk, "tool_call_chunks", None):
                            payload = {
                                "type": "text_delta",
                                "content": str(chunk.content),
                            }
                            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

                # 4. 捕获模型完成时的 Token 统计
                elif event_type == "on_chat_model_end":
                    output = event.get("data", {}).get("output")
                    if output:
                        usage = getattr(output, "usage_metadata", None) or {}
                        p_t = int(usage.get("input_tokens", 0))
                        c_t = int(usage.get("output_tokens", 0))
                        t_t = int(usage.get("total_tokens", p_t + c_t))
                        prompt_tokens += p_t
                        completion_tokens += c_t
                        total_tokens += t_t

            # 执行结束，回传统计指标
            elapsed = round(time.time() - start_time, 2)
            metrics_payload = {
                "type": "metrics",
                "duration": elapsed,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": total_tokens or (prompt_tokens + completion_tokens),
            }
            yield f"data: {json.dumps(metrics_payload, ensure_ascii=False)}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

        except Exception as err:
            err_str = str(err)
            if "Recursion limit" in err_str:
                friendly_msg = (
                    "### 智能体单轮执行步数达到上限 (Recursion Limit 触发)\n\n"
                    "**【问题排查】**：\n"
                    "- 当前任务较为复杂（涉及多轮代码编写、Bash 执行、排版调整等），单轮 LangGraph 计算图步数已达上限。\n"
                    "- 智能体在处理任务时可能进行了多次代码校验与重试。\n\n"
                    "**【优化处理与操作建议】**：\n"
                    "1. 系统已将单轮最大步数从默认的 25 步大幅提高至 **80 步**；\n"
                    "2. **分步下达指令**：建议将复合任务拆解为小目标（如：先下发生成规范空白模板，再指令填充表格与正文）；\n"
                    "3. **开启新会话**：若当前会话中累积了过多长文本历史，建议点击左侧侧边栏「+ 新建对话」开启干净上下文重试。"
                )
            else:
                friendly_msg = f"处理过程中发生异常: {err_str}"

            error_payload = {
                "type": "error",
                "message": friendly_msg,
            }
            yield f"data: {json.dumps(error_payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ==============================================================================
# 2. 前端静态页面路由
# ==============================================================================
@app.get("/", response_class=FileResponse)
async def serve_index():
    index_file = WEB_DIR / "index.html"
    if not index_file.exists():
        return JSONResponse(status_code=404, content={"detail": "WebUI 静态页面 index.html 不存在"})
    return FileResponse(str(index_file))


def start_server(host: str = "127.0.0.1", port: int = 8000):
    """启动 WebUI 服务"""
    print(f"[PaperGenFlow] Claude WebUI 正在启动中: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    start_server()
