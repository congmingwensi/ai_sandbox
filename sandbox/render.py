from __future__ import annotations
from typing import Dict, Set, Iterable, Tuple
import shutil
try:
    import colorama
    from colorama import Fore, Style
    colorama.init(autoreset=False, convert=True, strip=False)
except Exception:
    class _Dummy: RESET_ALL = ""
    class _DFore:
        LIGHTBLUE_EX=""; LIGHTRED_EX=""; LIGHTBLACK_EX=""; LIGHTYELLOW_EX=""
    Fore=_DFore(); Style=_Dummy()

RESET = Style.RESET_ALL
FG_BLUE = Fore.LIGHTBLUE_EX
FG_RED  = Fore.LIGHTRED_EX
FG_GREY = Fore.LIGHTBLACK_EX
FG_YELLOW = Fore.LIGHTYELLOW_EX

BOX_H = "─"; BOX_V = "│"
BOX_TL = "┌"; BOX_TR = "┐"; BOX_BL = "└"; BOX_BR = "┘"
BOX_TM = "┬"; BOX_BM = "┴"; BOX_LM = "├"; BOX_RM = "┤"; BOX_MM = "┼"

class Renderer:
    def __init__(self, grid_cols: int = 10):
        self.grid_cols = grid_cols

    def _fg_by_owner(self, owner: int) -> str:
        if owner == 1: return FG_BLUE
        if owner == 2: return FG_RED
        return FG_GREY

    def draw_side_panel(self, snap: dict, side: int):
        """
        只用“自己可见的信息”画一个小表：
          - 己方：全部可见
          - 中立：仅邻接（且有 troops/env）
          - 对方：仅邻接（且有 troops/env）
        颜色：蓝/红/灰（没有依赖你项目里的配色工具，走 ANSI；若你的旧配色更好看，可把 _c() 改成你自己的着色函数）
        """
        # 小着色（若你已有 color 辅助，改这里即可）
        C = {
            "blue": "\x1b[38;5;39m",
            "red": "\x1b[38;5;203m",
            "gray": "\x1b[38;5;246m",
            "yel": "\x1b[38;5;185m",
            "reset": "\x1b[0m",
        }

        def _c(s, name):
            return f"{C.get(name, '')}{s}{C['reset']}"

        # === 计算“与己方相邻”的格子集合（只依赖己方格子的 neighbors） ===
        self_ids = set(snap.get("self", {}).keys())
        adj = set()
        for oid, oinfo in snap.get("self", {}).items():
            for nb in oinfo.get("neighbors", []):
                if nb not in self_ids:
                    adj.add(nb)

        # 组装三类行
        def line(rid, t, e):
            return f"id {rid:02d} | T {t:<4} | env {e}"

        mine = []
        for rid in sorted(snap.get("self", {}).keys()):
            info = snap["self"][rid]
            mine.append(line(rid, info["troops"], info["env"]))

        adj_neu, adj_enemy = [], []
        for rid, info in snap.get("neutral_enemy_partial", {}).items():
            owner = info.get("owner", -1)
            has_vals = ("troops" in info and "env" in info)
            if rid in adj and has_vals:
                if owner == 0:
                    adj_neu.append(line(rid, info["troops"], info["env"]))
                elif owner in (1, 2) and owner != side:
                    adj_enemy.append(line(rid, info["troops"], info["env"]))

        # 打印
        title = _c("蓝方视角", "blue") if side == 1 else _c("红方视角", "red")
        print(_c("─" * 80, "gray"), flush=True)
        print(f"{title}  （只显示己方可见 / 邻接信息）", flush=True)
        print(_c("─" * 80, "gray"), flush=True)

        print(_c("己方（可见）：", "yel"), flush=True)
        print("\n".join(mine) if mine else _c("(none)", "gray"), flush=True)
        print("", end="", flush=True)

        print(_c("中立（仅邻接）：", "yel"), flush=True)
        print("\n".join(sorted(adj_neu)) if adj_neu else _c("(none)", "gray"), flush=True)
        print("", end="", flush=True)

        print(_c("对方（仅邻接，且可见才有数值）：", "yel"), flush=True)
        print("\n".join(sorted(adj_enemy)) if adj_enemy else _c("(none)", "gray"), flush=True)
        print(_c("─" * 80, "gray"), flush=True)

    def _auto_cols(self, snap: dict) -> int:
        """根据格子总数自动推断列数（方阵优先），失败则返回 self.grid_cols。"""
        n = len(snap.get("all", {}))
        if n <= 0:
            return max(1, getattr(self, "grid_cols", 10))
        import math
        s = int(round(math.sqrt(n)))
        if s * s == n:
            return s  # 49 -> 7
        # 不是完美平方：若当前 cols 能整除就用当前，否则选最接近的因子
        cols = getattr(self, "grid_cols", 10)
        if n % cols == 0:
            return cols
        # 找到最接近 sqrt(n) 的因子
        best = cols
        gap = n
        for c in range(3, min(n, 20)):  # 粗略找下
            if n % c == 0 and abs(c - math.sqrt(n)) < gap:
                best, gap = c, abs(c - math.sqrt(n))
        return best
    def draw_map_dual(self, *snaps):
        def _merge_for_grid_union(snaps_seq: Iterable[Dict]) -> Dict:
            all_ids: Dict[int, Dict] = {}
            merged = {"all": {}, "self": {}, "neutral_enemy_partial": {}}
            # all：后写覆盖前写，维持“最新快照”优先；如需改成首次优先，用 setdefault
            for s in snaps_seq:
                for rid, info in s.get("all", {}).items():
                    all_ids[rid] = info
            # self：拥有即全量，首次优先（避免不同侧覆盖）
            for s in snaps_seq:
                for rid, info in s.get("self", {}).items():
                    if rid not in merged["self"]:
                        merged["self"][rid] = {
                            "owner": info.get("owner"),
                            "troops": info.get("troops"),
                            "env": info.get("env"),
                            "area": info.get("area"),
                            "neighbors": info.get("neighbors", [])
                        }
            # partial：self 没有时再补；若提供 troops/env 则并入，否则只保留 owner 供上色
            def add_partial(src: Dict):
                for rid, info in src.get("neutral_enemy_partial", {}).items():
                    if rid in merged["self"]:
                        continue
                    if "troops" in info and "env" in info:
                        merged["neutral_enemy_partial"][rid] = {
                            k: info.get(k)
                            for k in ("owner", "troops", "env", "area", "neighbors")
                            if k in info
                        }
                    else:
                        merged["neutral_enemy_partial"].setdefault(
                            rid, {"owner": info.get("owner")}
                        )
            for s in snaps_seq:
                add_partial(s)
            merged["all"] = all_ids
            return merged

        def stat_from_union(rid: int, snaps_seq: Iterable[Dict]) -> Tuple[str, str]:
            # 先找任意 snap 的 self
            for s in snaps_seq:
                if rid in s.get("self", {}):
                    x = s["self"][rid]
                    return x.get("troops", "--"), x.get("env", "--")
            # 再找任意 snap 的 partial（必须同时具备 troops/env）
            for s in snaps_seq:
                ne = s.get("neutral_enemy_partial", {}).get(rid, {})
                if "troops" in ne and "env" in ne:
                    return ne["troops"], ne["env"]
            return "--", "--"
        # ---------- 打印：地图概览 ----------
        cols = shutil.get_terminal_size((160, 20)).columns
        print("─" * min(cols, 160))
        print("地图概览（仅显示阵营编号）：")
        merged_for_grid = _merge_for_grid_union(snaps)
        # 用合并后的 all 做概览与分组
        all_sorted = sorted(merged_for_grid["all"].items())
        line = []
        for rid, info in all_sorted:
            color = self._fg_by_owner(info.get("owner"))
            line.append(f"{color}{rid:02d}{RESET}")
        print(" ".join(line))
        # 标注“值得关注”的中立：在任意 snap 的 partial 中标有 owner=0 且有 neighbors
        adj_neutral: Set[int] = set()
        for s in snaps:
            for rid, info in s.get("neutral_enemy_partial", {}).items():
                if info.get("owner", -1) == 0 and "neighbors" in info:
                    adj_neutral.add(rid)
        blue, red, neutral = [], [], []
        for rid, info in all_sorted:
            troops, env = stat_from_union(rid, snaps)
            row = f"id:{rid:02d} T:{troops} env:{env}"
            owner = info.get("owner")
            if owner == 1:
                blue.append(row)
            elif owner == 2:
                red.append(row)
            else:
                if rid in adj_neutral:
                    neutral.append(row)
        print("\n蓝方：")
        for s in blue:
            print(FG_BLUE + s + RESET,end=" | ")
        print("\n红方：")
        for s in red:
            print(FG_RED + s + RESET,end=" | ")
        print("\n中立（仅邻接蓝/红）：",end=" | ")
        for s in neutral:
            print(FG_GREY + s + RESET,end=" | ")
        # ---------- 表格视图 ----------
        print("\n表格视图：")
        self.draw_grid(merged_for_grid)

    def draw_grid(self, snapshot: Dict):
        ids = sorted(snapshot["all"].keys())
        rows = [ids[i:i+self._auto_cols(snapshot)] for i in range(0, len(ids), self._auto_cols(snapshot))]
        cell_w = 10; cell_h = 3
        def top_border():
            s = BOX_TL + (BOX_H * cell_w)
            for _ in range(self._auto_cols(snapshot) - 1): s += BOX_TM + (BOX_H * cell_w)
            s += BOX_TR; print(s)
        def mid_border():
            s = BOX_LM + (BOX_H * cell_w)
            for _ in range(self._auto_cols(snapshot) - 1): s += BOX_MM + (BOX_H * cell_w)
            s += BOX_RM; print(s)
        def bottom_border():
            s = BOX_BL + (BOX_H * cell_w)
            for _ in range(self._auto_cols(snapshot) - 1): s += BOX_BM + (BOX_H * cell_w)
            s += BOX_BR; print(s)
        def cell_lines(rid: int):
            owner = snapshot["all"][rid]["owner"]
            fg = self._fg_by_owner(owner)
            id_line = f"ID {rid:02d}".center(10)
            troops_txt,env_char = "--","--"
            if rid in snapshot["self"]:
                troops_txt = str(snapshot["self"][rid]["troops"])
                env_char = str(snapshot["self"][rid]["env"])
            else:
                ne = snapshot["neutral_enemy_partial"].get(rid, {})
                if "troops" in ne: troops_txt = str(ne["troops"])
                if "env" in ne: env_char = str(ne["env"])
            troops_line = f"T {troops_txt}".center(10)
            owner_line = f"Env {env_char}".center(10)
            # owner_char = {0:"N",1:"B",2:"R"}.get(owner,"?")
            return [fg + id_line + RESET, fg + troops_line + RESET, fg + owner_line + RESET]
        top_border()
        for r, row in enumerate(rows):
            buf = ["" for _ in range(cell_h)]
            for rid in row:
                CL = cell_lines(rid)
                for i in range(cell_h): buf[i] += BOX_V + CL[i]
            if len(row) < self._auto_cols(snapshot):
                for _ in range(self._auto_cols(snapshot) - len(row)):
                    for i in range(cell_h): buf[i] += BOX_V + " " * 10
            for i in range(cell_h):
                buf[i] += BOX_V; print(buf[i])
            if r < len(rows) - 1: mid_border()
            else: bottom_border()

    def report_turn(self, turn: int, side_name: str):
        print(f"\n—— 回合 {turn}：{side_name} 行动 ——")


