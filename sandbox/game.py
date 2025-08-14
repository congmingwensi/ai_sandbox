
from __future__ import annotations
from typing import Optional, List, Dict, Any, Tuple, Union
import random, json, sys
from .model import MapData
from .render import Renderer

class Game:
    def __init__(self, gmap: MapData, blue, red, max_rounds: int = 60, seed: int = 0, human_mode: str = "none",enable_events: bool = True):
        self.map = gmap
        self.blue = blue
        self.red = red
        self.max_rounds = max_rounds
        self.rng = random.Random(seed)
        assert human_mode in ("none","blue","red","both")
        self.human_mode = human_mode
        self.enable_events = enable_events
        self.file=open(f"decision.txt","a+")

    def side_done(self, side: int) -> bool:
        owners = [r.owner for r in self.map.regions.values()]
        return (2 not in owners) if side == 1 else (1 not in owners)
    def human_take_action(self, side: int):
        snapshot = self.map.visible_snapshot(side=side)
        print("\n==== 视野快照 JSON（可复制给网页端 AI） ====")
        print(json.dumps(snapshot, ensure_ascii=False, indent=2))
        print("请输入指令：'skip' | 'attack <id>' | 单行JSON（含 调用/进攻 ）：", end="", flush=True)
        line = sys.stdin.readline().strip()
        if not line: return None
        if line.startswith("{"):
            try: return json.loads(line)
            except Exception:
                print("JSON 解析失败，视为 skip"); return None
        if line.lower().startswith("attack"):
            try:
                target = int(line.split()[1])
                return {"进攻": {"进攻方id": [], "防守方id": target}}
            except Exception:
                print("解析失败，视为 skip"); return None
        if line.lower() == "skip": return None
        return None

    def execute_decision(self, side: int, decision: Dict[str, Any]):
        def report_action(actor_side: int, target_id: int, success: bool, attack_power: float, defense: float):
            side = "蓝方" if actor_side == 1 else "红方"
            outcome = "成功" if success else "失败"
            outcome = f"{side} 进攻 区域 {target_id} | 攻 {attack_power:.1f} vs 守 {defense:.1f} → {outcome}"
            print(outcome)
            return outcome
        self.file.write(json.dumps(decision, ensure_ascii=False)+"\n")
        self.file.flush()
        self.last_events = ""
        call = decision.get("调用")
        if call and isinstance(call, dict):
            move_from = call.get("调离", {})
            move_to = call.get("调往", None)
            if isinstance(move_from, dict) and isinstance(move_to, (int, str)):
                res = self.map.redeploy(side, {int(k): int(v) for k, v in move_from.items()}, int(move_to))
                message=f"调兵→ {res.get('to')} +{res.get('moved', 0)}(lost {res.get('lost', 0)}) 来自 {res.get('sources', [])}"
                print(message)
                self.last_events+=message
            else:return f"{json.dumps(decision,ensure_ascii=False)} 解析json失败,调离方不为字典或调往方不为int"

        atk = decision.get("进攻") if isinstance(decision, dict) else None
        if atk and isinstance(atk, dict):
            target = int(atk.get("防守方id",""))
            attacker_ids = atk.get("进攻方id", [])
            attacker_ids = [int(x) for x in attacker_ids] if attacker_ids else None
            # —— 关键：必须相邻（上下左右），且属于当前方 ——
            if attacker_ids is not None:
                adj_ok = any((rid in self.map.regions[target].neighbors and self.map.regions[rid].owner == side) for rid in attacker_ids)
                if not adj_ok:
                    return self.last_events+f"防守方id {target} 相邻id为:{self.map.regions[target].neighbors },与{'蓝' if side == 1 else '红'}方进攻方id{attacker_ids}均不相邻，无法进攻"
            res=self.map.attack_possible(side, target, self.rng, attacker_ids)
            if isinstance(res,str): return res
            else:
                self.map.execute_attack(side, target, attacker_ids,res)
                ok, atk, dfn=res
                outcome=report_action(side, target, ok, atk, dfn)
                return self.last_events+outcome
        else:
            return self.last_events

    def turn_step(
        self,
        side: int,
        renderer: Optional[Renderer] = None,
        return_decision: bool = False,
    ) -> Union[int, Tuple[int, Optional[Dict[str, Any]]]]:
        if (self.human_mode == "both") or (self.human_mode == "blue" and side == 1) or (self.human_mode == "red" and side == 2):
            decision = self.human_take_action(side)
        else:
            agent = self.blue if side == 1 else self.red
            obs = self.map.visible_snapshot(side=side)
            decision = agent.select_action(obs, self.rng)

        if decision is None:
            if renderer: print("无指令/跳过。")
        else:
            res = self.execute_decision(side, decision)
            if res:
                ok, atk, dfn, target = res
                if renderer: renderer.report_action(side, target, ok, atk, dfn)
            else:
                if renderer: print("无有效进攻指令。")

        if self.side_done(side=1):
            winner = 1
        elif self.side_done(side=2):
            winner = 2
        else:
            winner = 0
        if return_decision:
            return winner, decision
        return winner
