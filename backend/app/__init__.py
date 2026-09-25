"""Weister 后端应用包。

金融投研智能体 · 多智能体协作的自动化估值建模系统。

分层结构：
    core/        Tool / Skill / Agent 注册表
    tools/       原子能力（解析、抽取、计算、估值）
    skills/      SKILL.md 技能说明书
    agents/      ReAct 智能体定义与执行器
    orchestrator.py   图编排与专家团调度
    api.py       HTTP 接口与 SSE 流
"""
