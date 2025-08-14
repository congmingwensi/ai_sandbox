from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Optional, List
import random

@dataclass
class Agent:
    side: int  # 1 蓝方 / 2 红方
    def select_action(self, obs: Dict, rng: random.Random) -> Optional[Dict]:
        raise NotImplementedError

class RandomAgent(Agent):
    """相邻就打，随缘挑一个目标"""
    def select_action(self, obs: Dict, rng: random.Random) -> Optional[Dict]:
        choices: List[tuple[int, List[int]]] = []
        for rid, info in obs["neutral_enemy_partial"].items():
            own_neighbors = []
            for oid, oinfo in obs["self"].items():
                if rid in oinfo["neighbors"]:
                    own_neighbors.append(oid)
            if own_neighbors:
                choices.append((rid, own_neighbors))
        if not choices:
            return None
        rid, attackers = rng.choice(choices)
        return {"进攻": {"进攻方id": attackers, "防守方id": rid}}

class HeuristicAgent(Agent):
    """简易启发式：估算攻守差，优先打得过/值当的相邻格"""
    def __init__(self, side: int):
        self.side = side
        self._recent: List[int] = []   # 防“乒乓”，记忆最近目标

    def select_action(self, obs: Dict, rng: random.Random) -> Optional[Dict]:
        candidates = []
        for rid, info in obs["neutral_enemy_partial"].items():
            own_neighbors: List[int] = []
            for oid, oinfo in obs["self"].items():
                if rid in oinfo["neighbors"]:
                    own_neighbors.append(oid)
            if not own_neighbors:
                continue

            est_attack = sum(obs["self"][oid]["troops"] for oid in own_neighbors)
            if "troops" in info:  # 可见
                est_def = info["troops"] + info["area"] * info["env"]
            else:                 # 不可见的（理论上不会进到这儿，因为我们只给相邻）
                est_def = 20.0

            score = est_attack - est_def + (0.5 if info["owner"] == 2 else 0.0)
            if rid in self._recent:
                score -= 9999  # 最近打过的先别打，避免来回拉扯
            candidates.append((score, -est_def, rid, own_neighbors))

        if not candidates:
            return None
        candidates.sort(reverse=True)

        # 轻随机探索一点，打破平分循环
        pick = candidates[0]
        if rng.random() < 0.10 and len(candidates) > 1:
            pick = rng.choice(candidates[:min(3, len(candidates))])

        _, _, target_rid, attackers = pick
        self._recent.append(target_rid)
        if len(self._recent) > 2:
            self._recent.pop(0)

        return {"进攻": {"进攻方id": attackers, "防守方id": target_rid}}
