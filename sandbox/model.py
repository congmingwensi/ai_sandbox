from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
import json, math, random
from collections import deque

@dataclass
class Region:
    id: int
    name: str
    owner: int  # 0 neutral, 1 blue, 2 red
    troops: int
    area: float
    env: float   # 0~1
    pos: Tuple[float, float]
    neighbors: List[int] = field(default_factory=list)

    def distance_to(self, other: 'Region') -> float:
        return math.dist(self.pos, other.pos)

@dataclass
class MapData:
    regions: Dict[int, Region]

    def __init__(self, regions: Dict[int, Region]):
        self.regions = regions
        self.fortify_cd = {}

    @staticmethod
    def load(path: str) -> 'MapData':
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        regions = {}
        for r in data["regions"]:
            regions[r["id"]] = Region(
                id=r["id"], name=r["name"], owner=r["owner"], troops=r["troops"],
                area=r["area"], env=r["env"], pos=tuple(r["pos"]), neighbors=r["neighbors"]
            )
        return MapData(regions)

    def shortest_hops(self, src: int, dst: int) -> int:
        if src == dst: return 0
        vis = set([src])
        q = deque([(src,0)])
        while q:
            u,d = q.popleft()
            for v in self.regions[u].neighbors:
                if v in vis: continue
                if v == dst: return d+1
                vis.add(v); q.append((v, d+1))
        return 99999

    def visible_snapshot(self, side: int) -> Dict:
        own_ids = [r.id for r in self.regions.values() if r.owner == side]
        frontier_ids = set()
        for oid in own_ids:
            for nb in self.regions[oid].neighbors:
                if self.regions[nb].owner != side:
                    frontier_ids.add(nb)
        distances = {}
        for a in self.regions:
            distances[a] = {}
            for b in self.regions:
                distances[a][b] = 0.0 if a==b else self.regions[a].distance_to(self.regions[b])

        snapshot = {
            "all": {rid: {"owner": self.regions[rid].owner} for rid in self.regions},
            "distances": distances,
            "self": {},
            "neutral_enemy_partial": {}
        }
        for rid in own_ids:
            r = self.regions[rid]
            snapshot["self"][rid] = {
                "owner": r.owner, "troops": r.troops, "area": r.area, "env": r.env,
                "neighbors": r.neighbors
            }
        for rid, r in self.regions.items():
            if r.owner != side:
                if rid in frontier_ids:
                    snapshot["neutral_enemy_partial"][rid] = {
                        "owner": r.owner, "troops": r.troops, "area": r.area, "env": r.env,
                        "neighbors": r.neighbors
                    }
                else:
                    snapshot["neutral_enemy_partial"][rid] = {"owner": r.owner}
        return snapshot

    def prt_troops(self):
        troops_info= [self.regions[i].troops for i in self.regions]
        owner_info=[self.regions[i].owner for i in self.regions]
        for i in range(0, len(troops_info), 7):
            print(",".join(map(str, troops_info[i:i + 7])))
        for i in range(0, len(owner_info), 7):
            print(",".join(map(str, owner_info[i:i + 7])))
        return troops_info

    def attack_possible(self, attacker_side: int, target_id: int, rng: random.Random, attacker_ids: Optional[List[int]] = None):
        target = self.regions[target_id]
        if target.owner == attacker_side:
            return f"进攻方{attacker_ids},防守方{target_id}为同一方"
        if attacker_ids is None:
            attackers = [self.regions[n] for n in target.neighbors if self.regions[n].owner == attacker_side]
        else:
            attackers = [self.regions[rid] for rid in attacker_ids if rid in target.neighbors and self.regions[rid].owner == attacker_side]
        attack_power = sum(r.troops*r.env for r in attackers)
        luck = rng.uniform(0.8, 1.4)
        defense = target.troops * target.env * luck

        # 🔧 临时固守：若该地有冷却，加成 30% 防御（可调）
        if getattr(self, "fortify_cd", None) and self.fortify_cd.get(target_id, 0) > 0:
            defense *= 1.50
        return (attack_power > defense, attack_power, defense)

    def execute_attack(self, attacker_side: int, target_id: int, attackers: Optional[List[int]], res) -> Dict:
        """
        结算规则：
          - 守方损耗率 ~ min(1, attack/defense) * KD_ATK
          - 攻方损耗率 ~ min(1, defense/attack) * KD_DEF
          - 攻方损耗按各出战格子的出战兵力占比分摊
          - 若胜利：从幸存进攻方抽取 OCCUPY_RATIO 的兵力作为驻军，转移到目标格
        """
        ok, attack_power, defense = res
        result = {
            "ok": ok,
            "attack": attack_power,
            "defense": defense,
            "attacker_ids": attackers,
            "target": target_id,
        }
        target = self.regions[target_id]
        atk_regions = [self.regions[i] for i in attackers]
        # —— 常量可按手感微调 ——
        OCCUPY_RATIO = 0.25  # 胜利后用于驻军的幸存进攻兵力比例
        MIN_LEFT = 1  # 每格至少保留 1 人
        # —— 计算双方损耗率（按强弱比） ——
        rate_def_lost = min(1.0, attack_power / defense)
        rate_atk_lost = min(1.0, defense / attack_power)
        # —— 记录进攻方出战兵力（用于分摊损耗 & 驻军） ——
        atk_init = [r.troops for r in atk_regions]
        atk_total_init = sum(atk_init)
        # —— 守方损耗（按目标格原兵力比例计算，落地到 troops） ——
        def_lost = int(round(target.troops * rate_def_lost))
        target.troops = max(MIN_LEFT, target.troops - def_lost)
        # —— 进攻方总损耗，按出战占比分摊到各格 ——
        atk_total_lost = int(round(atk_total_init * rate_atk_lost))
        # 按比例分配，末尾用“差额法”补齐四舍五入误差
        distributed = 0
        for idx, r in enumerate(atk_regions):
            if idx < len(atk_regions) - 1:
                loss_i = int(round(atk_total_lost * (atk_init[idx] / atk_total_init)))
                distributed += loss_i
            else:
                loss_i = max(0, atk_total_lost - distributed)  # 补差
            r.troops = max(MIN_LEFT, r.troops - loss_i)
        # —— 是否攻下目标 ——
        victory = bool(ok) or (attack_power >= defense)
        # —— 设置加固冷却（守军或新占领方） ——
        self.fortify_cd[target_id] = 2
        garrison = 0
        if victory:
            # 从幸存进攻方抽取驻军
            atk_survivors = sum(r.troops for r in atk_regions)
            garrison = max(MIN_LEFT, int(round(atk_survivors * OCCUPY_RATIO)))
            # 从各进攻格按幸存占比分摊抽调
            if atk_survivors > 0 and garrison > 0:
                pulled = 0
                for idx, r in enumerate(atk_regions):
                    if idx < len(atk_regions) - 1:
                        take_i = int(round(garrison * (r.troops / atk_survivors)))
                        take_i = min(take_i, max(0, r.troops - MIN_LEFT))
                        pulled += take_i
                    else:
                        # 最后一个补齐；同时保证至少留 1
                        take_i = min(max(0, garrison - pulled), max(0, r.troops - MIN_LEFT))
                    r.troops -= take_i
                    target.troops += take_i
            target.owner = attacker_side
        # —— 返回更详细的结算（便于上层记录/展示） ——
        result.update({
            "defender_lost": def_lost,
            "attacker_lost": atk_total_lost,
            "garrison": garrison,
            "target_owner_after": target.owner,
            "target_troops_after": target.troops,
        })
        return result

    def redeploy(self, side: int, move_from: Dict[int,int], move_to: int) -> Dict:
        BASE_LEAK = 0.02
        LOSS_PER_HOP = 0.07
        if move_to not in self.regions or self.regions[move_to].owner != side:
            return {"ok": False, "moved": 0, "to": move_to, "sources": [], "lost": 0}
        moved_total, lost_total = 0, 0
        valid_sources = []
        for sid, amt in move_from.items():
            r = self.regions.get(int(sid))
            if not r or r.owner != side: continue
            amt = max(0, int(amt))
            if amt <= 0 or r.troops <= 1: continue
            take = min(amt, r.troops - 1)
            if take <= 0: continue
            r.troops -= take
            hops = self.shortest_hops(int(sid), move_to)
            if hops >= 99999:
                lost = take; deliver = 0
            else:
                loss_ratio = BASE_LEAK + LOSS_PER_HOP * hops
                loss_ratio = max(0.0, min(0.95, loss_ratio))
                lost = int(round(take * loss_ratio))
                deliver = max(0, take - lost)
            self.regions[move_to].troops += deliver
            moved_total += deliver; lost_total += lost; valid_sources.append(int(sid))
        return {"ok": True, "moved": moved_total, "lost": lost_total, "to": move_to, "sources": valid_sources}

    def apply_natural_events(self, rng) -> list[dict]:
        """
        为地图上每个格子抽取 1 个自然事件，按事件倍率调整兵力。
        返回 changes: [{id, name, desc, delta}]，并在 self.regions[*].troops 上落地。
        规则：
          - 占领区用 EVENTS_OWNED；若该格子邻接中立(owner=0)，可改用 EVENTS_NEUTRAL_ADJ 以柔和波动
          - 波动结果四舍五入为整数；最少保留 1 兵；delta=0 的也返回（便于排序/展示时可过滤）
        """
        EVENTS_OWNED = [
            {"name": "丰收", "desc": "本季收成远超往年，军粮充盈，士气振奋。", "mult": (1.10, 1.30), "weight": 5},
            {"name": "征募顺利", "desc": "各地青年踊跃参军，补员顺畅，战力上升。", "mult": (1.05, 1.40), "weight": 4},
            {"name": "治安安定", "desc": "地方秩序良好，后勤运转高效，驻军稳定增编。", "mult": (1.05, 1.20),"weight": 3},
            {"name": "商贸繁荣", "desc": "商队络绎，物资富集，军需保障及时充足。", "mult": (1.05, 1.18), "weight": 3},
            {"name": "矿脉发现", "desc": "意外发现金属矿，军械产能提振，士气亦随之高涨。", "mult": (1.08, 1.25),"weight": 2},
            {"name": "宗教节日", "desc": "大型祭典凝聚民心，士兵精神面貌焕然一新。", "mult": (1.02, 1.12),"weight": 2},
            {"name": "边境贸易", "desc": "边民互市兴盛，补给链条更为通畅。", "mult": (1.03, 1.20), "weight": 2},
            {"name": "疫病", "desc": "疫症在营中蔓延，战斗力下滑，不得不隔离治疗。", "mult": (0.55, 0.95),"weight": 1},
            {"name": "饥荒", "desc": "歉收与屯粮失败叠加，口粮短缺导致大批逃散。", "mult": (0.70, 0.92), "weight": 1},
            {"name": "洪涝", "desc": "河水暴涨冲毁屯田，补给线受阻。", "mult": (0.88, 0.96), "weight": 1},
            {"name": "贪腐横行", "desc": "军饷被层层克扣，军心涣散，兵员流失。", "mult": (0.80, 0.95), "weight": 1},
            {"name": "边境冲突", "desc": "零星摩擦不断，消耗了不少守军与物资。", "mult": (0.85, 0.97), "weight": 1},
            {"name": "军械短缺", "desc": "兵工生产受阻，武备匮乏，训练效果打折。", "mult": (0.78, 0.92), "weight": 1},
        ]
        EVENTS_NEUTRAL_ADJ = [
            {"name": "风调雨顺", "desc": "时令得宜，庄稼茁壮，民生安定。", "mult": (1.01, 1.15), "weight": 6},
            {"name": "小有收成", "desc": "收成尚可，粮食有余，村社活力增强。", "mult": (1.01, 1.24), "weight": 5},
            {"name": "赶集热闹", "desc": "集市繁荣，手工业活跃，愿从军者略增。", "mult": (1.02, 1.12), "weight": 4},
            {"name": "新人投靠", "desc": "附近民兵主动靠拢，愿受整编，提供线报与劳力。", "mult": (1.02, 1.20),
             "weight": 3},
            {"name": "丰年祭典", "desc": "乡民合力办节，邻里相助，治安稳定。", "mult": (1.01, 1.18), "weight": 3},
            {"name": "水源充沛", "desc": "地下水位回升，灌溉改善，歉情缓解。", "mult": (1.01, 1.15), "weight": 2},

            {"name": "民心浮动", "desc": "谣言与不安蔓延，部分青壮选择观望。", "mult": (0.80, 0.99), "weight": 2},
            {"name": "土匪扰乱", "desc": "盗匪出没洗劫乡里，秩序动荡，青壮流失。", "mult": (0.85, 0.98), "weight": 2},
            {"name": "旱情蔓延", "desc": "雨水失时，地力衰减，春耕乏力。", "mult": (0.88, 0.98), "weight": 1},
            {"name": "灾情波动", "desc": "疫疠偶发、山火走水等不利因素交替出现。", "mult": (0.80, 0.98), "weight": 1},
            {"name": "谣言四起", "desc": "对外势力存疑，民众抗拒征募与输送。", "mult": (0.90, 0.99), "weight": 1},
        ]
        def weighted_pick(evts):
            total = sum(e["weight"] for e in evts)
            t = rng.uniform(0, total)
            acc = 0.0
            for e in evts:
                acc += e["weight"]
                if t <= acc:
                    return e
            return evts[-1]
        changes = []
        for rid, r in self.regions.items():
            # 选择事件池
            pool = EVENTS_OWNED
            if r.owner == 0:
                pool = EVENTS_NEUTRAL_ADJ

            evt = weighted_pick(pool)
            mult_lo, mult_hi = evt["mult"]
            factor = rng.uniform(mult_lo, mult_hi)
            before = int(r.troops)
            after = max(1, int(round(before * factor)))  # 至少留 1 兵
            delta = after - before
            r.troops = after
            changes.append({
                "id": rid,
                "name": evt["name"],
                "desc": evt["desc"],
                "delta": delta,
                "factor": round(factor, 3),
                "owner": r.owner,
            })
        return changes
    def ptr_events(self,rng):
        changes = self.apply_natural_events(rng)
        lines = []
        inc = sorted([c for c in changes if c.get("delta", 0) > 0], key=lambda x: -x["delta"])[:10]
        dec = sorted([c for c in changes if c.get("delta", 0) < 0], key=lambda x: x["delta"])[:5]
        lines.append("自然事件（增前10）：")
        [lines.append(f" + 因{c['desc']} id {c['id']:02d} +{c['delta']}") for c in inc]
        lines.append("\n自然事件（减前5）：")
        [lines.append(f" - 因{c['desc']} id {c['id']:02d} {c['delta']}") for c in dec]
        self.last_events_text = " | ".join(lines)
        print("自然事件：")
        print(self.last_events_text)
        return self.last_events_text
