"""回归测试：`/技能名` 斜杠命令。

- 解析开头的 `/name`，正文剥离命令
- 未知技能不当作命令
- 技能提示只进「给模型看的 content」，不进 display_text（对话里仍显示用户原文）
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api import helpers as helpers_mod
from app.core.registry import registry


def main():
    known = set(registry.skills.keys())
    print("已加载技能:", sorted(known))
    assert known, "应至少加载一个技能"

    name = min(known)

    # 1. 正常命令
    parsed, rest = helpers_mod.split_skill_command(f"/{name} 帮我分析这份财报", known)
    assert parsed == name, f"应解析出 {name}，实际 {parsed}"
    assert rest == "帮我分析这份财报", f"正文应剥离命令，实际 {rest!r}"

    # 2. 未知技能 → 不当作命令，原样透传
    parsed2, rest2 = helpers_mod.split_skill_command("/nosuchskill 你好", known)
    assert parsed2 is None and rest2 == "/nosuchskill 你好"

    # 3. 普通消息
    parsed3, rest3 = helpers_mod.split_skill_command("你好", known)
    assert parsed3 is None and rest3 == "你好"

    # 4. 提示只进 content，display_text 保持用户原文
    ctx = helpers_mod.skill_command_context(name)
    assert name in ctx
    msg = helpers_mod.build_user_message("帮我分析", [], [], ctx)
    assert msg["display_text"] == "帮我分析", "display_text 不应含技能提示"
    assert msg["content"].startswith("【用户指定技能"), "content 应以技能提示开头"
    assert "帮我分析" in msg["content"]

    # 5. 只有命令、没有正文时，指令必须给出可行动作
    bare = helpers_mod.skill_command_context(name, has_body=False)
    assert "禁止只回答" in bare, "空正文时缺少行动要求"
    assert "用 ask 询问用户" in bare
    body_msg = helpers_mod.build_user_message("", [], [], bare)
    assert "意图见上方技能指令" in body_msg["content"]

    print("示例 content 开头:", msg["content"][:80].replace("\n", " "))
    print("\nALL PASS: 斜杠技能命令解析与注入正确")
    raise SystemExit(0)


if __name__ == "__main__":
    main()
