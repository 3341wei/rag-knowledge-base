# -*- coding: utf-8 -*-
"""Agent 可调用的工具。

来源收集采用 LangChain 的 `content_and_artifact` 机制：
工具返回 (给模型看的文本, 结构化 artifact)，artifact 会随 ToolMessage
进入本次 run 的事件流。它是状态机内部的数据，天然按请求隔离，
因此不需要全局变量，也不依赖 ContextVar 在线程池中的传播。
"""
from __future__ import annotations

import ast
import operator
from datetime import datetime

from langchain_core.tools import tool

from backend.services.rag import build_sources
from backend.services.retrieval import retrieve

# ---- 计算器安全求值：只允许数字、括号与 + - * / ----
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_MAX_EXPRESSION_LENGTH = 200
_MAX_RESULT = 1e12


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        result = _BIN_OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
        if abs(result) > _MAX_RESULT:
            raise ValueError("计算结果过大")
        return result
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        value = _eval_node(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    raise ValueError("表达式包含不支持的运算")


@tool(response_format="content_and_artifact")
def search_knowledge_base(question: str) -> tuple[str, list[dict]]:
    """在公司知识库中检索相关信息。当用户询问公司制度（请假/福利/考勤）、
    产品信息、技术规范等内部知识时，必须调用此工具。"""
    top = retrieve(question)
    if not top:
        return "知识库中暂无相关信息。", []

    text = "\n\n".join(
        f"[来源:{d.metadata.get('source', '未知')}]\n{d.page_content}"
        for d, _ in top
    )
    return text, build_sources(top)


@tool
def calculator(expression: str) -> str:
    """计算一个算术表达式，例如 "3*5+2"。仅支持数字与 + - * / ( ) 运算。
    当用户需要数学计算时调用。"""
    expression = expression.strip()
    if len(expression) > _MAX_EXPRESSION_LENGTH:
        return "错误：表达式过长"
    try:
        tree = ast.parse(expression, mode="eval")
        result = _eval_node(tree)
        if result.is_integer():
            return str(int(result))
        return str(round(result, 6))
    except ZeroDivisionError:
        return "计算错误：除数不能为 0"
    except (SyntaxError, ValueError) as exc:
        return f"计算错误：{exc}"


@tool
def get_current_time() -> str:
    """获取当前日期和时间。当用户问「现在几点」「今天几号」时调用。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


TOOLS = [search_knowledge_base, calculator, get_current_time]
TOOL_NAMES = {t.name for t in TOOLS}
