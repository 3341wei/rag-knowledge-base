# -*- coding: utf-8 -*-
"""Agent 工具测试，重点覆盖计算器的安全边界。"""
from __future__ import annotations

import re

from backend.services.tools import calculator, get_current_time


def test_calculator_basic():
    assert calculator.invoke({"expression": "3*5+2"}) == "17"
    assert calculator.invoke({"expression": "(1+2)/2"}) == "1.5"
    assert calculator.invoke({"expression": "-3+5"}) == "2"


def test_calculator_rejects_pow_and_calls():
    # 指数运算可能造成 CPU 耗尽，必须拒绝
    assert calculator.invoke({"expression": "9**9**9"}).startswith("计算错误")
    assert calculator.invoke({"expression": "__import__('os').system('ls')"}).startswith(
        "计算错误"
    )
    assert calculator.invoke({"expression": "open('x','w')"}).startswith("计算错误")


def test_calculator_rejects_long_expression():
    assert "过长" in calculator.invoke({"expression": "1+" * 200 + "1"})


def test_calculator_zero_division():
    assert calculator.invoke({"expression": "1/0"}).startswith("计算错误")


def test_current_time_format():
    value = get_current_time.invoke({})
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", value)
