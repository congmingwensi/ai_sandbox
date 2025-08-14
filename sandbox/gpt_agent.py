from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from openai import OpenAI

from .agents import Agent


@dataclass
class GPTAgent(Agent):
    """Game agent powered by OpenAI GPT models.

    The agent expects the model to output two blocks in plain text:
    [思考决策]：...  (free-form reasoning)
    [行动json]：{...}  (JSON describing the action)
    """

    model: str = "gpt-5-nano"
    instructions: str = (
        "游戏规则，\n"
        "每次输出返回：决策思考内容， 行动json。\n"
        "格式如下：\n"
        "[思考决策]：<你的分析>\n"
        "[行动json]：<JSON>"
    )
    history: List[Dict[str, Any]] = field(default_factory=list)
    client: OpenAI = field(default_factory=OpenAI)

    def _build_input(self, obs: Dict, events: List[str]) -> str:
        hist_lines = []
        for idx, h in enumerate(self.history[-10:], 1):
            hist_lines.append(
                f"第{idx}轮: 我方={h.get('self')} 对方={h.get('opponent')}"
            )
        hist_text = "\n".join(hist_lines)
        obs_text = json.dumps(obs, ensure_ascii=False)
        evt_text = "\n".join(events)
        return f"{hist_text}\n当前观察: {obs_text}\n事件: {evt_text}\n{self.instructions}"

    def select_action(self, obs: Dict, rng) -> Optional[Dict]:
        prompt = self._build_input(obs, events=[])
        resp = self.client.responses.create(model=self.model, input=prompt)
        text = getattr(resp, "output_text", str(resp))
        match = re.search(r"\[行动json\]：(\{.*\})", text, re.S)
        if not match:
            return None
        try:
            action = json.loads(match.group(1))
        except Exception:
            return None
        self.history.append({"self": action, "opponent": None})
        if len(self.history) > 10:
            self.history = self.history[-10:]
        return action

    def notify_opponent(self, action: Optional[Dict]) -> None:
        if self.history:
            self.history[-1]["opponent"] = action
