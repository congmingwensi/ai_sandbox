from __future__ import annotations
import asyncio, json
from typing import Dict, Any, List, Optional
from llm_agents.agents import Agent, Runner
from sandbox.model import MapData
from sandbox.render import Renderer
from sandbox.game import Game

def extract_action(decision: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(decision, dict): return None
    out: Dict[str, Any] = {}
    if "调用" in decision and isinstance(decision["调用"], dict):
        mv = decision["调用"]
        move_from = mv.get("调离", {}) or {}
        move_to = mv.get("调往", None)
        if isinstance(move_from, dict) and (isinstance(move_to, int) or isinstance(move_to, str)):
            out["调用"] = {"调离": {str(k): int(v) for k,v in move_from.items()}, "调往": int(move_to)}
    if "进攻" in decision and isinstance(decision["进攻"], dict):
        atk = decision["进攻"]
        attackers = atk.get("进攻方id", [])
        target = atk.get("防守方id", None)
        if target is not None:
            out["进攻"] = {"进攻方id": [int(x) for x in (attackers or [])], "防守方id": int(target)}
    return out if out else None

def snapshot_to_text(snap_b: Dict, snap_r: Dict, history: List[Dict[str, Any]]) -> str:
    def list_side(snap, owner):
        rows = []
        for rid, info in sorted(snap["all"].items()):
            if info["owner"] != owner: continue
            troops = "--"; env = "--"
            if rid in snap["self"]:
                troops = snap["self"][rid]["troops"]; env = snap["self"][rid]["env"]
            else:
                ne = snap["neutral_enemy_partial"].get(rid, {})
                if "troops" in ne and "env" in ne:
                    troops = ne["troops"]; env = ne["env"]
            rows.append(f"id {rid:02d} | T {troops} | env {env}")
        return "\n".join(rows) if rows else "(none)"
    adj_neutral = []
    seen = set()
    for rid, info in snap_b["neutral_enemy_partial"].items():
        if info.get("owner", -1) == 0 and "neighbors" in info: seen.add(rid)
    for rid, info in snap_r["neutral_enemy_partial"].items():
        if info.get("owner", -1) == 0 and "neighbors" in info: seen.add(rid)
    for rid in sorted(seen):
        troops = "--"; env = "--"
        ne = snap_b["neutral_enemy_partial"].get(rid) or snap_r["neutral_enemy_partial"].get(rid) or {}
        if "troops" in ne and "env" in ne:
            troops = ne["troops"]; env = ne["env"]
        adj_neutral.append(f"id {rid:02d} | T {troops} | env {env}")
    adj_neutral_text = "\n".join(adj_neutral) if adj_neutral else "(none)"
    history_txt = json.dumps(history[-10:], ensure_ascii=False, indent=2)
    prompt = (
        "You are a commander in a turn-based sandbox.\n"
        "Return exactly two blocks:\n"
        "[思考决策]: one or two Chinese sentences of your reasoning.\n"
        "[行动json]: a JSON with optional keys 调用 and 进攻.\n\n"
        "最近10轮:\n" + history_txt + "\n\n"
        "蓝方:\n" + list_side(snap_b, 1) + "\n\n"
        "红方:\n" + list_side(snap_r, 2) + "\n\n"
        "中立(邻接蓝/红):\n" + adj_neutral_text + "\n"
    )
    return prompt

async def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--map", default="data/sample_map_50.json")
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--model", default="gpt-5-nano")
    parser.add_argument("--cols", type=int, default=10)
    args = parser.parse_args()

    gmap = MapData.load(args.map)
    game = Game(gmap, blue=None, red=None, max_rounds=args.rounds, seed=42, human_mode="none")
    renderer = Renderer(grid_cols=args.cols)

    a_blue = Agent(name="blue", model=args.model, instructions="你是蓝方指挥官。输出必须包含[思考决策]和[行动json]。")
    a_red  = Agent(name="red",  model=args.model, instructions="你是红方指挥官。输出必须包含[思考决策]和[行动json]。")

    history: List[Dict[str, Any]] = []
    snap_b = game.map.visible_snapshot(1)
    snap_r = game.map.visible_snapshot(2)
    renderer.draw_map_dual(snap_b, snap_r)

    for t in range(1, args.rounds+1):
        print(f"\n—— 回合 {t}：蓝方（LLM）——")
        ctx_b = snapshot_to_text(snap_b, snap_r, history)
        out_b = await Runner.run(a_blue, input=ctx_b)
        act_b = extract_action(out_b.get("action", {})) or {}
        print(out_b.get("raw","").strip()[:600])
        res = game.execute_decision(1, act_b)
        if res:
            ok, atk, dfn, target = res
            renderer.report_action(1, target, ok, atk, dfn)

        print(f"\n—— 回合 {t}：红方（LLM）——")
        snap_b = game.map.visible_snapshot(1); snap_r = game.map.visible_snapshot(2)
        ctx_r = snapshot_to_text(snap_b, snap_r, history)
        out_r = await Runner.run(a_red, input=ctx_r)
        act_r = extract_action(out_r.get("action", {})) or {}
        print(out_r.get("raw","").strip()[:600])
        res = game.execute_decision(2, act_r)
        if res:
            ok, atk, dfn, target = res
            renderer.report_action(2, target, ok, atk, dfn)

        history.append({"轮次": t, "我方": act_b, "对方": act_r})

        snap_b = game.map.visible_snapshot(1); snap_r = game.map.visible_snapshot(2)
        renderer.draw_map_dual(snap_b, snap_r)

        if game.side_done(1): print("\n蓝方获胜"); break
        if game.side_done(2): print("\n红方获胜"); break

if __name__ == "__main__":
    asyncio.run(main())
