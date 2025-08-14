# run_gpt_duel.py (class-based)
import argparse, asyncio, os, json, re
from openai import AsyncOpenAI
from typing import Dict, Any, List, Optional, Tuple
from sandbox.model import MapData
from sandbox.game import Game
from sandbox.render import Renderer
from sandbox.prompts import BLUE_PERSONA, RED_PERSONA
from sandbox.agents import HeuristicAgent, RandomAgent

# ====== CLI Orchestrator Refactor ======
class DuelRunner:
    """
    Class-based orchestrator for the duel game.
    Keeps state like map/game/renderer/history in one place,
    and exposes a simple .run() entrypoint.
    """
    # —— 给 LLM 的 env 解释（放进 system prompt） ——
    ENV_NOTE = (
        "说明：env 表示地区环境/地利系数，数值越高防守越稳固。"
        "进攻示意公式：守方估值 = 兵力 * env * 随机值；攻防估值严格= 兵力 * env；上下左右相邻才可进攻，否则无效。兵力不足时可调兵，但调兵会产生随机损耗。"
        "全部地区为7*7 按上下左右为相邻，编号为：\n"
        "00 01 02 03 04 05 06  \n"
        "07 08 09 10 11 12 13 \n"
        "14 15 16 17 18 19 20 \n"
        "21 22 23 24 25 26 27 \n"
        "28 29 30 31 32 33 34 \n"
        "35 36 37 38 39 40 41 \n"
        "42 43 44 45 46 47 48 \n"
    )

    def __init__(self, args):
        self.args = args
        self.gmap = MapData.load(args.map)
        self.game = Game(self.gmap, blue=None, red=None, max_rounds=args.rounds, seed=42, human_mode="none")
        self.renderer = Renderer(grid_cols=args.cols)
        # 保存最近行动（蓝/红）用于上下文
        self.history = {}
        self.last_events_text: str = ""
        self.last_events = ""
    # ---------- Context formatting ----------
    @staticmethod
    def _format_side_view(snap: dict, side: int) -> str:
        """
        只展示：
          - 己方：全部可见
          - 中立：与己方任意一格“邻接”的中立，且必须有 troops/env（并展示「与我方邻接 id」）
          - 对方：与己方任意一格“邻接”的敌方，且必须有 troops/env（并展示「与我方邻接 id」）
        """

        def _as_int(x):
            try:
                return int(str(x))
            except Exception:
                return None

        # ① 收集己方格与它们的邻居；同时建立「被邻接方 -> 我方邻接 id 列表」的映射
        self_ids = set(snap.get("self", {}).keys())
        my_adj = set()
        my_adj_map = {}  # rid -> [my_ids...]
        for oid, oinfo in snap.get("self", {}).items():
            for nb in oinfo.get("neighbors", []):
                nb_i = _as_int(nb)
                if nb_i is None:
                    continue
                my_adj.add(nb_i)
                my_adj_map.setdefault(nb_i, []).append(_as_int(oid))

        # ② 行格式化
        def line_simple(rid: int, troops, env) -> str:
            return f"id:{rid:02d} T:{troops} env:{env}"

        def line_with_neighbors(rid: int, troops, env) -> str:
            adj_list = sorted([i for i in (my_adj_map.get(rid) or []) if i is not None])
            adj_txt = " ".join(f"{i:02d}" for i in adj_list) if adj_list else "--"
            return f"id:{rid:02d} T:{troops} env:{env} neighbors: {adj_txt}"

        # ③ 己方
        mine_rows = []
        for rid in sorted(self_ids):
            info = snap["self"][rid]
            mine_rows.append(line_simple(rid, info.get("troops", "--"), info.get("env", "--")))

        # ④ 中立（仅邻接 & 有数值）
        adj_neu = []
        for rid, info in snap.get("neutral_enemy_partial", {}).items():
            rid_i = _as_int(rid)
            if rid_i is None:
                continue
            if info.get("owner", -1) == 0 and rid_i in my_adj:
                if "troops" in info and "env" in info:
                    adj_neu.append(line_with_neighbors(rid_i, info["troops"], info["env"]))

        # ⑤ 敌方（仅邻接 & 有数值）
        adj_enemy = []
        for rid, info in snap.get("neutral_enemy_partial", {}).items():
            rid_i = _as_int(rid)
            if rid_i is None:
                continue
            owner = info.get("owner", -1)
            if owner in (1, 2) and owner != side and rid_i in my_adj:
                if "troops" in info and "env" in info:
                    adj_enemy.append(line_with_neighbors(rid_i, info["troops"], info["env"]))

        parts = []
        parts.append("己方（可见）：\n" + (" | ".join(mine_rows) if mine_rows else "(none)"))
        parts.append("中立（仅邻接）：\n" + (" | ".join(sorted(adj_neu)) if adj_neu else "(none)"))
        parts.append("对方（仅邻接）：\n" + (" | ".join(sorted(adj_enemy)) if adj_enemy else "(none)"))
        return "\n".join(parts)
    # ---------- OpenAI call ----------
    @staticmethod
    async def _call_openai(model: str, messages: List[Dict[str,str]]) -> str:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("未设置 OPENAI_API_KEY 环境变量")
        client = AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=1,
        )
        return resp.choices[0].message.content or ""

    def _sanitize_jsonish(self,s: str) -> str:
        s = s.replace("：", ":").replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
        s = re.sub(r"\bNone\b", "null", s)
        s = re.sub(r"\bTrue\b", "true", s)
        s = re.sub(r"\bFalse\b", "false", s)
        # 去尾逗号
        s = re.sub(r",\s*([}\]])", r"\1", s)
        # 仅当冒号后**不是引号**时，才去掉前导 0（避免破坏 "02" 这种字符串）
        s = re.sub(r'(:\s*)(?!")0+([0-9]+)(\s*[,\}\]])', r"\1\2\3", s)
        return s
    def system_prompt(self,side_label,user_prompt,step):
        PERSONA=BLUE_PERSONA if side_label=="蓝方" else RED_PERSONA
        sys_prompt = (
            f"你是{side_label}指挥官。你正处于两军交战中，只有占领全部大陆才算最终胜利。进攻区域成功后，两片区域都能获得一定兵力提升。每一轮可以进行两次连续行动。只能进行 调用(调兵) 与 进攻\n"
            + self.ENV_NOTE + "\n"
            "严格输出如下两段，且第二段必须是合法JSON：\n"
            "[思考决策]: 根据人设和行为偏好，分析当前局势和行动，给出行动的推论和原因。\n"
            "[行动json]: {\"调用\":{\"调离\":{\"<id>\":数量,...},\"调往\":\"<id>\"},\"进攻\":{\"进攻方id\":[\"<己方id>\"...],\"防守方id\":\"<id>\"}}\n"
            "要求：所有字段必须与示例一致，id和兵力必须为数字类型；如：{\"调用\":{\"调离\":{\"23\":120,\"29\":100},\"调往\":22},\"进攻\":{\"进攻方id\":[19,27],\"防守方id\":20}} 若无进攻或无调动请填 {\"调用\":null,\"进攻\":null}}。\n"
            "不要输出多余段落、不要表格、不要 markdown 标题。"
            + PERSONA
            + f"\n当前为本轮第{step}次行动:"
        )
        return [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ]
    async def ask_nano(self, model: str, side_label: str, user_prompt: str, turn: int,step:int) -> Dict[str, Any]:
        sys_prompt=self.system_prompt(side_label,user_prompt,step)
        text = await self._call_openai(model, sys_prompt)
        print(text)
        # 写日志
        import pathlib
        logdir = pathlib.Path("logs"); logdir.mkdir(exist_ok=True)
        fname = logdir / f"llm_raw_round_{turn}_{'blue' if '蓝' in side_label else 'red'}.txt"
        fname.write_text(text, encoding="utf-8")
        # 抓取 JSON 片段（宽容）
        text = text or ""
        m = re.search(r'\[行动json\]\s*[:：]\s*(.*)', text, re.I | re.S)
        if not m:
            print(f"匹配json失败，原回复：{text}")
            return {"raw": text,"action":{},"had_json": False}
        blob = self._sanitize_jsonish(m.group(1))
        action = json.loads(blob)
        return {"raw": text, "action": action, "had_json": True}
    # ---------- Parse action ----------
    def analysis_json(self,text):
        m = re.search(r'\[行动json\]\s*[:：]\s*(.*)', text, re.I | re.S)
        if not m:
            print(f"匹配json失败，原回复：{text}")
            return {"raw": text, "action": {}, "had_json": False}
        blob = self._sanitize_jsonish(m.group(1))
        action = json.loads(blob)
        return {"raw": text, "action": action, "had_json": True}
    # ---------- Round helpers ----------
    def _ctx_for_side(self, snap: dict, side: int) -> str:
        history = "\n".join([f"{k}:{v}" for k, v in list(self.history.items())[-3:]])
        return ("历史行动（简表）:\n" +history+ ("\n\n上回合自然事件:\n" + self.last_events_text if self.last_events_text else "") +
                (f"\n\n当前（{'蓝方' if side==1 else '红方'}视角):\n" + self._format_side_view(snap, side)))

    async def _step_ai(self, side: int, agent_kind: str, model: str, turn: int,step:int) -> Dict[str, Any]:
        snap = self.game.map.visible_snapshot(side)
        # pre-turn panel
        self.renderer.draw_map_dual(snap)
        ctx = self._ctx_for_side(snap, side)
        if agent_kind in ("heuristic", "random"):
            prompt = self.system_prompt("蓝方" if side == 1 else "红方", ctx, step)
            print("\t".join([prompt[0]["content"], prompt[1]["content"]]))
            agent = HeuristicAgent(side) if agent_kind == "heuristic" else RandomAgent(side)
            decision = agent.select_action(snap, self.game.rng) or {}
            print(f"\n[{'蓝方' if side==1 else '红方'}-启发式行动json]:", decision)
        elif agent_kind == "nano":
            out = await self.ask_nano(model, "蓝方" if side==1 else "红方", ctx, turn,step)
            decision=out["action"]
            print(f"\n[{'蓝方' if side==1 else '红方'}-行动json]:", decision)
        elif agent_kind == "net":
            prompt=self.system_prompt("蓝方" if side==1 else "红方",ctx,step)
            sanitize="\n".join([prompt[0]["content"],prompt[1]["content"]])
            text=input(f"当前局势：{sanitize}\n请输入模型回答").strip().lower()
            result_json=self.analysis_json("[行动json]:"+text)
            decision = result_json["action"]
        # 执行
        res = self.game.execute_decision(side, decision)
        self.history[f"轮次{turn}"].setdefault("蓝方" if side == 1 else "红方", []).append(" ".join([res]))
        print(self.history)
        self.game.map.prt_troops()
        return decision

    async def run(self):
        # 开局双视图
        snap_b = self.game.map.visible_snapshot(1)
        snap_r = self.game.map.visible_snapshot(2)
        self.renderer.draw_map_dual(snap_r,snap_b)

        for turn in range(1, self.args.rounds + 1):
            self.history[f"轮次{turn}"]={}
            print(f"\n—— 回合 {turn}：蓝方 ——")
            await self._step_ai(1, self.args.blue, self.args.blue_model, turn,1)
            await self._step_ai(1, self.args.blue, self.args.blue_model, turn,2)

            if self.args.pause:
                s = input("输入 n 回车继续，或 q 退出 > ").strip().lower()
                if s == "q": return None
            print(f"\n—— 回合 {turn}：红方 ——")
            await self._step_ai(2, self.args.red, self.args.red_model, turn,1)
            await self._step_ai(2, self.args.red, self.args.red_model, turn,2)
            # —— 回合末：自然事件（应用 + 打印），并纳入下一轮上下文 ——
            self.last_events_text=self.game.map.ptr_events(self.game.rng)
            # 回合暂停
            if self.args.pause:
                s = input("输入 n 回车继续，或 q 退出 > ").strip().lower()
                if s == "q": break
            # 胜负检查 + 重绘
            snap_b = self.game.map.visible_snapshot(1)
            snap_r = self.game.map.visible_snapshot(2)
            self.renderer.draw_map_dual(snap_b, snap_r)
            if self.game.side_done(1):
                print("\n蓝方胜")
            if self.game.side_done(2):
                print("\n红方胜")

def build_argparser():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default="data/sample_map_50.json")
    ap.add_argument("--rounds", type=int, default=20)
    ap.add_argument("--cols", type=int, default=10)
    ap.add_argument("--blue", choices=["heuristic","random","nano","net"], default="heuristic")
    ap.add_argument("--red",  choices=["heuristic","random","nano","net"], default="heuristic")
    ap.add_argument("--blue-model", default="gpt-5-nano")
    ap.add_argument("--red-model",  default="gpt-5-nano")
    ap.add_argument("--pause", action="store_true", help="每回合等待输入 'n' 继续")
    return ap


async def main_async(args=None):
    if args is None:
        args = build_argparser().parse_args()
    runner = DuelRunner(args)
    await runner.run()


def main():
    asyncio.run(main_async())


if __name__ == "__main__":
    main()