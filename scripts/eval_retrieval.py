# -*- coding: utf-8 -*-
"""检索效果评测：量化「向量检索 → 混合检索 → 混合检索+Rerank」的命中率提升。

用法（在项目根目录）：
    python scripts/eval_retrieval.py
    python eval_retrieval.py        # 根目录兼容入口，等价

原理：
- 准备一组问答对，每个问题标注「正确答案所在切片的独特关键词」作为黄金标准
- 分别用三种检索方法取 Top-K，判断正确切片是否命中
- 对比命中率，量化每一步检索优化的增量价值

注意：评测会真实调用 Embedding 与 Rerank 接口，需要可用的 API Key 与已建好的索引。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services.retrieval import hybrid_search, retrieve  # noqa: E402
from backend.services.vectorstore import get_vectorstore  # noqa: E402

# 评测集：(问题, 正确答案所在切片的独特关键词)
CASES = [
    # 产品手册
    ("X100 音箱保修几年？", "保修期为 2 年"),
    ("智能门锁 L200 支持哪几种解锁方式？", "指纹、密码、人脸"),
    ("客服热线电话是多少？", "400-888-1234"),
    ("产品无理由退换货的期限是多久？", "7 天内支持无理由退换货"),
    # 员工手册：请假/报销/福利
    ("员工请假需要提前几天申请？", "员工请假需提前 3 天"),
    ("年假每年有几天？", "年假每年 10 天"),
    ("出差报销需要多久内提交？", "出差结束后 7 个工作日内"),
    ("婚假有几天？", "婚假 3 天"),
    ("公积金缴纳比例是多少？", "公积金缴纳比例为 12%"),
    ("周末加班工资怎么算？", "1.5 倍工资"),
    ("上班时间是几点到几点？", "9:00"),
    ("迟到超过 10 分钟扣多少钱？", "扣 50 元"),
    ("办公电脑必须安装什么软件？", "杀毒软件"),
    ("违规泄露数据会怎么处理？", "严重违纪"),
    # 技术开发规范
    ("Python 代码要遵循什么规范？", "PEP 8"),
    ("代码提交前需要做什么？", "单元测试"),
    ("Git 提交信息格式是什么？", "feat: 新增登录接口"),
    # 人事管理制度
    ("试用期一般是多久？", "试用期一般为 3 个月"),
    ("年度绩效 S 档有什么奖励？", "3 个月年终奖"),
    ("公司每年培训预算是多少？", "2000 元培训预算"),
    ("技术岗位有几个职级？", "T1-T6"),
    # 财务报销细则
    ("报销单需要在多久内提交？", "30 天内提交"),
    ("一线城市住宿标准是多少？", "500 元/晚"),
    ("出差餐补一线城市每天多少？", "100 元/天"),
    ("发票抬头是什么？", "星辰科技有限公司"),
    # 信息安全管理办法
    ("系统密码至少多少位？", "10 位"),
    ("数据分为几个等级？", "四个等级"),
    ("密码需要多久更换一次？", "90 天"),
    # 客户服务规范
    ("在线客服响应时间多久？", "30 秒"),
    ("客户投诉多久闭环？", "48 小时"),
    ("维修周期一般多久？", "15 个工作日"),
]


def hit(docs, gold: str) -> bool:
    """判断检索结果里是否有片段包含黄金关键词。"""
    return any(gold in d.page_content for d in docs)


def main() -> None:
    vs = get_vectorstore()
    top = 3

    def vector_search(q: str, k: int):
        """基线：纯向量检索 Top-K。"""
        return vs.as_retriever(search_kwargs={"k": k}).invoke(q)

    def hybrid_no_rerank(q: str, k: int):
        """混合检索（向量 + BM25 + RRF），但不加 Rerank。"""
        return hybrid_search(q, vectorstore=vs)[:k]

    def hybrid_with_rerank(q: str, k: int):
        """完整链路：混合检索粗召回 + Rerank 精排。"""
        return [d for d, _ in retrieve(q)[:k]]

    methods = [
        ("向量检索（V1 基线）", vector_search),
        ("混合检索（无 Rerank）", hybrid_no_rerank),
        ("混合检索 + Rerank（V2）", hybrid_with_rerank),
    ]

    print(f"评测集规模：{len(CASES)} 个问题")
    print(f"知识库切片数：{len(vs.get()['documents'])} 个\n")

    for name, method in methods:
        top1_hits = 0
        top3_hits = 0
        for q, gold in CASES:
            docs = method(q, top)
            if docs and hit([docs[0]], gold):
                top1_hits += 1
            if hit(docs, gold):
                top3_hits += 1
        print(f"{name}")
        print(f"    Top-1 命中率：{top1_hits}/{len(CASES)} = {top1_hits / len(CASES) * 100:.1f}%")
        print(f"    Top-3 命中率：{top3_hits}/{len(CASES)} = {top3_hits / len(CASES) * 100:.1f}%\n")


if __name__ == "__main__":
    main()
