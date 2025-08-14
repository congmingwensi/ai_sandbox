# tools/gen_map_7x7.py
import json, random, argparse, pathlib
def build(N=7, M=7, seed=7):
    rng = random.Random(seed)
    def nid(i,j): return i*M+j
    regions = []
    for i in range(N):
        for j in range(M):
            nbs = []
            for di,dj in [(1,0),(-1,0),(0,1),(0,-1)]:  # 只允许 上下左右
                ni, nj = i+di, j+dj
                if 0<=ni<N and 0<=nj<M:
                    nbs.append(nid(ni,nj))
            regions.append({
                "id": nid(i,j),
                "name": f"R{nid(i,j)}",
                "owner": 0,
                "troops": rng.randint(12,30),
                "area": round(rng.uniform(3,6),2),
                "env": round(rng.uniform(0.5,3),2),
                "pos": [float(i), float(j)],
                "neighbors": nbs
            })
    # 起始：蓝(1,1)=8 与 (1,2)=9；红(5,4)=39 与 (5,5)=40
    blue_ids = [8, 9]
    red_ids  = [39, 40]
    base = 100
    for r in regions:
        if r["id"] in blue_ids: r["owner"]=1; r["troops"]=base
        if r["id"] in red_ids:  r["owner"]=2; r["troops"]=base
    return {"regions": regions}
def update(regions,troops_list):
    for r,n in zip(regions["regions"],troops_list):
        r["troops"]=n
    return regions
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="data/sample_map_50.json")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--update",type=bool,help="依次更新地图中每个格子的兵力值（空格分隔整数）")
    args = ap.parse_args()
    if args.update:
        path = pathlib.Path(args.out)
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            for r, n in zip(data["regions"], [
                1, 1, 1, 47, 16, 13, 100,
                29, 32, 101, 1, 58, 11, 60,
                12, 37, 1, 26, 24, 22, 35,
                48, 13, 23, 15, 1, 5, 8,
                1, 6, 3, 28, 17, 40, 33,
                66, 15, 55, 25, 16, 1, 1,
                79, 101, 35, 1, 9, 25, 52
]):
                r["troops"] = n
            for r, n in zip(data["regions"], [
                1, 1, 1, 0, 0, 0, 0,
                1, 1, 1, 1, 0, 1, 0,
                1, 1, 1, 1, 1, 1, 0,
                0, 1, 0, 2, 1, 1, 1,
                1, 1, 1, 2, 2, 2, 0,
                0, 0, 2, 2, 2, 2, 2,
                0, 0, 0, 2, 2, 2, 0
            ]):
                r["owner"] = n

        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"已更新兵力并写入: {path}")
    else:
        data = build(seed=args.seed)
        pathlib.Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"写入: {args.out}")

if __name__ == "__main__":
    main()
