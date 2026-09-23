"""
agent/agent.py - 基于 LangGraph 的通用可继承 ReAct 智能体基类 (BaseReActAgent)

核心特性：
1. 面向对象可继承架构：支持子类覆盖系统提示词 (inner_sys_prompt)、扩展状态结构 (AgentState)、注册专用工具与技能。
2. 运行指标全程监控：内置总运行时间 (total_duration_seconds)、Token 消耗统计 (prompt_tokens / completion_tokens / total_tokens)。
3. 工作区环境自动注入：自动引入 utils.get_sys_path 定位项目根路径，并在 System Prompt 中进行环境与落盘约束。
4. 复合技能包 (Skill) 与工具 (Tool) 自动挂载：支持动态注册与指令合流。
5. 原生 DeepSeek 接入与 LangGraph ReAct 闭环：基于 StateGraph、ToolNode、tools_condition 打造标准思考-行动-观察环路。
"""

import operator
import os
import time
from dataclasses import dataclass, field
from typing import (
    Annotated,
    Any,
    AsyncGenerator,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Type,
    Union,
)
from typing_extensions import TypedDict
from dotenv import find_dotenv, load_dotenv

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.tools import BaseTool, tool
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode, tools_condition

# 优先查找并加载项目根目录 .env
load_dotenv(find_dotenv())

# 安全导入相对模块或独立模块
try:
    from .utils.get_sys_path import get_workspace_path, get_workspace_prompt
except ImportError:
    try:
        from utils.get_sys_path import get_workspace_path, get_workspace_prompt
    except ImportError:
        # 兜底函数
        def get_workspace_path() -> str:
            return os.getcwd()
        def get_workspace_prompt() -> str:
            return f"### 【系统运行环境】\n当前工作区根目录: `{os.getcwd()}`"


# ==============================================================================
# 1. 基础状态定义 (AgentState 带运行时间与 Token 统计)
# ==============================================================================
class AgentState(TypedDict):
    """
    智能体通用基础状态。
    包含：
    - messages: 对话消息流（LangGraph 自动增量追加机制 add_messages）
    - total_tokens: 累计消耗总 Token 数 (operator.add 累加)
    - prompt_tokens: 累计输入/提示词 Token 数 (operator.add 累加)
    - completion_tokens: 累计模型生成 Token 数 (operator.add 累加)
    - total_duration_seconds: 本轮调用的总墙钟耗时（秒）
    """
    messages: Annotated[Sequence[BaseMessage], add_messages]
    total_tokens: Annotated[int, operator.add]
    prompt_tokens: Annotated[int, operator.add]
    completion_tokens: Annotated[int, operator.add]
    total_duration_seconds: float


# ==============================================================================
# 2. 技能包抽象 (Skill)
# ==============================================================================
@dataclass
class Skill:
    """
    复合技能包 (Skill) 抽象：
    - name: 技能名称
    - description: 技能功能描述
    - instructions: 执行此技能时的专属规范与指引（自动注入 System Prompt）
    - tools: 该技能下包含的一个或多个底层工具（BaseTool 或 Callable）
    """
    name: str
    description: str
    instructions: str = ""
    tools: List[Union[BaseTool, Callable[..., Any]]] = field(default_factory=list)

    def __post_init__(self):
        converted_tools: List[BaseTool] = []
        for t in self.tools:
            if isinstance(t, BaseTool):
                converted_tools.append(t)
            elif callable(t):
                converted_tools.append(tool(t))
            else:
                raise TypeError(f"Skill 工具必须为 BaseTool 或 Callable，收到: {type(t)}")
        self.tools = converted_tools


# ==============================================================================
# 3. 可继承 ReAct 智能体基类 (BaseReActAgent)
# ==============================================================================
class BaseReActAgent:
    """
    基于 LangGraph 的可继承 ReAct 智能体基类。
    
    子类继承特性：
    - 可覆盖 inner_sys_prompt: 设定专用人设
    - 可覆盖 state_schema: 替换为继承自 AgentState 的自定义类型
    - 可通过 register_tool / register_skill 扩展工具和技能
    - 可重写 get_system_prompt(state): 拼装自定义业务状态
    - 内置总耗时计算、Token 统计，原生支持 DeepSeek API
    """

    # 默认内部系统提示词 (子类可通过类属性直接覆盖)
    inner_sys_prompt: str = (
        "你是一个具备自主推理与工具调用能力的专业 AI 助手。"
        "遵循 ReAct (Thought -> Action -> Observation) 范式解决复杂问题。"
        "在调用工具前清晰阐述原因，工具执行后综合信息并给出严谨、符合规范的结论。"
    )

    # 默认状态 Schema (子类可覆盖)
    state_schema: Type[Any] = AgentState

    def __init__(
        self,
        inner_sys_prompt: Optional[str] = None,
        llm: Optional[ChatOpenAI] = None,
        tools: Optional[List[Union[BaseTool, Callable[..., Any]]]] = None,
        skills: Optional[List[Skill]] = None,
        checkpointer: Optional[Any] = None,
        enable_memory: bool = True,
        auto_compile: bool = True,
        default_recursion_limit: int = 80,
    ):
        """
        初始化智能体
        :param inner_sys_prompt: 覆盖类级别系统提示词
        :param llm: 语言模型实例（留空则自动读取 .env 的 DeepSeek 配置）
        :param tools: 初始独立工具列表
        :param skills: 初始技能包列表
        :param checkpointer: 状态持久化检查点
        :param enable_memory: 若未传 checkpointer，是否默认启用 MemorySaver
        :param auto_compile: 是否在初始化完毕后立即编译计算图
        :param default_recursion_limit: LangGraph 计算图默认递归深度上限 (默认 80 步，避免 25 步过早截断)
        """
        if inner_sys_prompt is not None:
            self.inner_sys_prompt = inner_sys_prompt

        self.default_recursion_limit = default_recursion_limit
        self.llm = llm or self._create_default_llm()
        self.checkpointer = checkpointer or (MemorySaver() if enable_memory else None)

        self._tools: Dict[str, BaseTool] = {}
        self._skills: Dict[str, Skill] = {}

        if tools:
            for t in tools:
                self.register_tool(t)

        if skills:
            for s in skills:
                self.register_skill(s)

        self.graph = None
        if auto_compile:
            self.compile()

    @staticmethod
    def _create_default_llm() -> ChatOpenAI:
        """从环境变量读取 DeepSeek 配置构建 ChatOpenAI"""
        api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
        model_name = os.getenv("DEEPSEEK_MODEL", "deepseek-flash").strip()

        if not api_key:
            api_key = "MISSING_DEEPSEEK_API_KEY"

        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url=base_url,
            temperature=0.3,
        )

    # --------------------------------------------------------------------------
    # 工具与技能管理
    # --------------------------------------------------------------------------
    def register_tool(self, tool_item: Union[BaseTool, Callable[..., Any]]) -> None:
        """注册单个工具"""
        if isinstance(tool_item, BaseTool):
            self._tools[tool_item.name] = tool_item
        elif callable(tool_item):
            converted = tool(tool_item)
            self._tools[converted.name] = converted
        else:
            raise TypeError(f"工具类型必须为 BaseTool 或 Callable，收到: {type(tool_item)}")

    def register_skill(self, skill: Skill) -> None:
        """注册一个复合技能包，将其指令合流到 Prompt 并绑定工具"""
        if not isinstance(skill, Skill):
            raise TypeError(f"技能必须为 Skill 类型实例，当前为: {type(skill)}")
        self._skills[skill.name] = skill
        for t in skill.tools:
            self.register_tool(t)

    def get_all_tools(self) -> List[BaseTool]:
        """获取已注册的所有工具列表"""
        return list(self._tools.values())

    def get_skills(self) -> List[Skill]:
        """获取已注册的所有技能列表"""
        return list(self._skills.values())

    # --------------------------------------------------------------------------
    # 动态提示词组装 (合流 inner_sys_prompt + get_sys_path + Skills + Tools)
    # --------------------------------------------------------------------------
    def get_system_prompt(self, state: Dict[str, Any]) -> str:
        """
        动态构造注入给 LLM 的系统提示词。
        组合顺序：
        1. inner_sys_prompt 基础人设
        2. 工作区系统路径环境提示 (来自 utils/get_sys_path)
        3. 已挂载技能规范说明 (Skills)
        4. 可用工具清单 (Tools)
        """
        prompt_parts: List[str] = [self.inner_sys_prompt.strip()]

        # 1. 注入工作区路径及环境规范约束
        prompt_parts.append("\n\n" + get_workspace_prompt())

        # 2. 注入挂载的技能说明及操作规范
        skills = self.get_skills()
        if skills:
            skill_lines = ["\n\n### 【已启用的专业技能包 (Skills)】"]
            for s in skills:
                skill_lines.append(f"- **{s.name}**: {s.description}")
                if s.instructions:
                    skill_lines.append(f"  *执行准则与约束*: {s.instructions.strip()}")
            prompt_parts.append("\n".join(skill_lines))

        # 3. 注入可用工具清单说明
        tools = self.get_all_tools()
        if tools:
            tool_names = ", ".join([f"`{t.name}`" for t in tools])
            prompt_parts.append(f"\n\n### 【可用工具集】: {tool_names}")

        return "\n".join(prompt_parts)

    # --------------------------------------------------------------------------
    # LangGraph 节点与图构建
    # --------------------------------------------------------------------------
    def _agent_node(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        智能体决策节点：
        - 组装带有时效性/状态上下文的系统提示词
        - 将其置于消息列表首位
        - 调用绑定工具后的 LLM 进行决策
        - 从 usage_metadata 提取并累加 Token 消耗
        """
        system_content = self.get_system_prompt(state)
        system_msg = SystemMessage(content=system_content)

        raw_messages = list(state.get("messages", []))

        # 确保首位为最新的动态 SystemMessage
        if raw_messages and isinstance(raw_messages[0], SystemMessage):
            call_messages = [system_msg] + raw_messages[1:]
        else:
            call_messages = [system_msg] + raw_messages

        # 绑定可用工具 (若有)
        tools = self.get_all_tools()
        if tools:
            model = self.llm.bind_tools(tools)
        else:
            model = self.llm

        response = model.invoke(call_messages)

        # 统计 Token 消耗
        usage = getattr(response, "usage_metadata", None) or {}
        p_tok = int(usage.get("input_tokens", 0))
        c_tok = int(usage.get("output_tokens", 0))
        t_tok = int(usage.get("total_tokens", p_tok + c_tok))

        return {
            "messages": [response],
            "prompt_tokens": p_tok,
            "completion_tokens": c_tok,
            "total_tokens": t_tok,
        }

    def build_graph(self) -> Any:
        """
        编排 LangGraph 状态图：
        START -> agent -> (tools_condition) -> tools -> agent
                                   |
                                  END
        """
        workflow = StateGraph(self.state_schema)

        # 添加核心推理节点
        workflow.add_node("agent", self._agent_node)

        tools = self.get_all_tools()
        if tools:
            tool_node = ToolNode(tools)
            workflow.add_node("tools", tool_node)

            workflow.add_edge(START, "agent")
            workflow.add_conditional_edges(
                "agent",
                tools_condition,
                {"tools": "tools", END: END},
            )
            workflow.add_edge("tools", "agent")
        else:
            workflow.add_edge(START, "agent")
            workflow.add_edge("agent", END)

        return workflow.compile(checkpointer=self.checkpointer)

    def compile(self) -> None:
        """编译或重新编译图"""
        self.graph = self.build_graph()

    # --------------------------------------------------------------------------
    # 调用与交互入口 (带总耗时计时)
    # --------------------------------------------------------------------------
    def _normalize_input(
        self,
        input_data: Union[str, Dict[str, Any], List[BaseMessage]],
    ) -> Dict[str, Any]:
        """将多种输入类型标准化为带有初始指标的 State 字典"""
        if isinstance(input_data, str):
            state = {"messages": [HumanMessage(content=input_data)]}
        elif isinstance(input_data, list):
            state = {"messages": input_data}
        elif isinstance(input_data, dict):
            state = dict(input_data)
        else:
            raise TypeError(f"不支持的输入数据格式: {type(input_data)}")

        state.setdefault("total_tokens", 0)
        state.setdefault("prompt_tokens", 0)
        state.setdefault("completion_tokens", 0)
        state.setdefault("total_duration_seconds", 0.0)
        return state

    def invoke(
        self,
        input_data: Union[str, Dict[str, Any], List[BaseMessage]],
        config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        同步调用入口：自动计算并注入总执行时间 (total_duration_seconds)
        """
        if self.graph is None:
            self.compile()

        state_input = self._normalize_input(input_data)

        # 确保注入合理 recursion_limit，避免 LangGraph 默认 25 步过早中断
        merged_config = dict(config or {})
        merged_config.setdefault("recursion_limit", self.default_recursion_limit)

        # 启动计时
        start_time = time.time()
        result = self.graph.invoke(state_input, config=merged_config)
        elapsed = round(time.time() - start_time, 3)

        # 记录总耗时
        result["total_duration_seconds"] = elapsed
        return result

    async def astream_events(
        self,
        input_data: Union[str, Dict[str, Any], List[BaseMessage]],
        config: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        异步事件流，供 WebUI 实时捕获 token chunk、tool 调用与状态变化
        """
        if self.graph is None:
            self.compile()

        state_input = self._normalize_input(input_data)

        # 确保注入合理 recursion_limit，避免 LangGraph 默认 25 步过早中断
        merged_config = dict(config or {})
        merged_config.setdefault("recursion_limit", self.default_recursion_limit)

        async for event in self.graph.astream_events(state_input, version="v2", config=merged_config):
            yield event

    @staticmethod
    def get_last_response(state: Dict[str, Any]) -> str:
        """从 State 中提取最后一条 AI 模型的回复正文"""
        messages = state.get("messages", [])
        for msg in reversed(messages):
            if isinstance(msg, AIMessage) and msg.content:
                return str(msg.content)
        return ""


# ==============================================================================
# 4. 子类继承示例
# ==============================================================================
class AcademicPaperAgentState(AgentState):
    """扩展专有状态字段"""
    topic: Optional[str]
    single_source_of_truth: Optional[Dict[str, Any]]


class AcademicPaperAgent(BaseReActAgent):
    """
    毕业论文专用智能体子类示例
    """
    inner_sys_prompt: str = (
        "你是一名中国高校本科毕业设计学术规划与撰写指导专家。"
        "擅长规划结构大纲、检索学术文献、指导规范三线表与架构图表设计。"
    )
    state_schema = AcademicPaperAgentState

    def get_system_prompt(self, state: Dict[str, Any]) -> str:
        base_prompt = super().get_system_prompt(state)
        extra_parts: List[str] = []
        topic = state.get("topic")
        if topic:
            extra_parts.append(f"\n### 【当前正在撰写的论文题目】: {topic}")
        return base_prompt + "".join(extra_parts)


if __name__ == "__main__":
    print("agent/agent.py 模块自测中...")
    test_agent = BaseReActAgent()
    print("Agent 初始化成功！可用系统提示词预览:")
    print("-" * 50)
    print(test_agent.get_system_prompt({}))
    print("-" * 50)

