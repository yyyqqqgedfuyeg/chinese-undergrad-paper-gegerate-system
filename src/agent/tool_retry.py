"""
tool_retry.py - 独立工具重试与异常反馈机制

功能：
1. 为工具提供自动重试机制（默认最多重试 3 次）。
2. 指数退避 (Exponential Backoff) 延迟。
3. 当重试 3 次均失败时，安全捕获异常，绝不导致 LangGraph 图崩溃；
   而是将结构化错误诊断信息作为 Observation 结果返回给 Agent，促使模型自主反思与纠错。
"""

import functools
import logging
import time
from typing import Any, Callable, Optional

# 配置专用 logger
logger = logging.getLogger("ToolRetry")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("[%(asctime)s] [%(levelname)s] [ToolRetry] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def with_retry(
    max_retries: int = 3,
    initial_delay: float = 0.5,
    backoff_factor: float = 1.5,
    log_errors: bool = True,
) -> Callable:
    """
    通用工具函数重试装饰器。
    
    :param max_retries: 最大重试次数 (默认 3 次)
    :param initial_delay: 首次重试等待秒数
    :param backoff_factor: 延迟递增因子
    :param log_errors: 是否在控制台打印重试与错误日志
    """
    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            current_delay = initial_delay
            last_exception: Optional[Exception] = None

            for attempt in range(1, max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if log_errors:
                        logger.warning(
                            f"工具 [{func.__name__}] 第 {attempt}/{max_retries} 次执行失败: "
                            f"{type(e).__name__}: {str(e)}"
                        )

                    if attempt < max_retries:
                        time.sleep(current_delay)
                        current_delay *= backoff_factor

            # 达到最大重试次数后仍然失败，组织结构化错误回传给 Agent
            error_report = (
                f"【工具执行失败 (已自动重试 {max_retries} 次均未成功)】\n"
                f"- 调用的工具名称: `{func.__name__}`\n"
                f"- 传入的参数: args={args}, kwargs={kwargs}\n"
                f"- 最终异常类型: {type(last_exception).__name__}\n"
                f"- 详细错误信息: {str(last_exception)}\n"
                f"【智能体纠错指引】: 请仔细分析上述报错原因（例如检查目标文件或路径是否存在、参数格式是否符合规范等），调整参数或采取备用策略后重新决策。"
            )
            if log_errors:
                logger.error(f"工具 [{func.__name__}] 已达最大重试上限，将错误报告安全交还 Agent 处理。")

            return error_report

        return wrapper

    return decorator


if __name__ == "__main__":
    # 单元测试：测试重试机制与错误回传
    @with_retry(max_retries=3, initial_delay=0.1)
    def flaky_tool(target: str) -> str:
        if target != "success":
            raise ValueError(f"目标 '{target}' 非法，模拟执行异常！")
        return f"执行成功: {target}"

    print("--- 测试 1: 正常执行 ---")
    print(flaky_tool("success"))

    print("\n--- 测试 2: 触发 3 次重试并捕获返回错误信息 ---")
    err_res = flaky_tool("invalid_param")
    print("返回给 Agent 的结果:")
    print(err_res)

