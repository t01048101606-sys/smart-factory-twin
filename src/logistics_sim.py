"""물류 · 출하 구역 시뮬레이터 (입고 -> 자재 창고, 완제품 창고 -> AGV -> 출하 도크 -> 트럭).

입고: 자재(냉연강판, 볼트, 도료) 재고가 발주점 아래로 내려가면 입고 트럭이 와서 하역한다 (lot.received).
      재고는 프레스 라인의 공정 완료 이벤트로 줄어든다 (MES BOM 과 같은 단위당 수량).
출하: 프레스 라인의 양품 5개가 모이면 파렛트가 되어 완제품 창고에 쌓이고, AGV가 출하 도크로 옮기고,
      트럭이 싣고 출발한다 (shipment.dispatched). 출하 트럭은 적재함이 가득 차야(파렛트 4개) 출발한다.
      입고 트럭은 짐을 가득 싣고 도착해서 하역하는 만큼 비워지고, 빈 채로 떠난다. 불량(scrap)은 불량 상자에 남고 출하되지 않는다.

위치 상수(LAYOUT)는 3D 장면(tools/make_logistics_scene.py)과 같다. state()는 3D 화면이 그대로 읽는다.
"""
import math

# 위치 상수 (3D 장면과 같다). 단위는 미터에 가깝다. 건물 바닥(도크 바닥)이 y=0 이고, 트럭이 서는 마당은 도크 높이(1.08m, 5톤 트럭 적재함 높이)만큼 낮아서
# 트럭 적재함 바닥이 도크 바닥과 같은 높이가 된다. 그래서 파렛트는 도크에서 트럭으로 높이 변화 없이 수평으로 들어간다 (도크 레벨러가 틈을 잇는다).
# 파렛트 중심 높이 0.3 = 플라스틱 파렛트(0.15)와 박스 높이의 절반쯤이 바닥에 놓인 상태, AGV 가 들면 0.1 올라간다.
LAYOUT = {
    "inbound_x": (-17.0, -5.97),       # 입고 트럭(적재함 6.8m) 중심 x: pos 0 -> 1. 1 에서 뒤끝이 도크 범퍼 바깥면(x=-2.57)에 닿는다
    "out_x": (34.0, 21.52),            # 출하 트럭(적재함 5.5m) 중심 x: pos 0 -> 1 (도크). 1 에서 적재함 뒤끝이 도크 범퍼 바깥면(x=18.77)에 닿는다
    "agv_x": (4.6, 15.6), "agv_z": 0.0, "agv_y": 0.4,
    "rack": [(2.4 + (i % 3) * 2.2, 0.3, -2.6 - (i // 3) * 2.0) for i in range(6)],     # 완제품 창고 칸 (바닥 적재)
    "dock": [(17.4, 0.3, -2.0 + 2.0 * j) for j in range(3)],                          # 출하 도크 칸
    "cargo": [(-1.3 + 2.6 * (k % 2), 0.3, -0.58 + 1.16 * (k // 2)) for k in range(4)],  # 트럭 적재함 칸 (적재함 중심 기준, 폭 2.28m 에 파렛트 2개)
}
MATERIALS = {
    "steel": {"item": "RM-STEEL", "name": "냉연강판", "unit": "KG", "stock": 30.0, "rop": 12.0, "order": 60.0, "supplier": "한국제철"},
    "bolt": {"item": "RM-BOLT", "name": "육각볼트 M8", "unit": "EA", "stock": 150.0, "rop": 60.0, "order": 300.0, "supplier": "대한볼트산업"},
    "paint": {"item": "RM-PAINT", "name": "전착도료", "unit": "L", "stock": 2.0, "rop": 0.8, "order": 4.0, "supplier": "삼성도료"},
}
CONSUME = {"press": ("steel", 0.5), "weld": ("bolt", 4.0), "paint": ("paint", 0.05)}   # 공정 한 번 완료할 때 소비 (MES BOM 과 같음)
PALLET_QTY = 5
IN_CARGO = 12                         # 입고 트럭 적재함의 짐 칸 수 (6열 x 2줄, 3D 장면과 같다)
T = {"in_arrive": 8.0, "unload": 6.0, "in_leave": 6.0, "agv_load": 2.0, "agv_move": 6.0, "agv_unload": 2.0, "agv_return": 6.0,
     "out_arrive": 8.0, "to_truck": 3.0, "out_leave": 8.0}
lerp = lambda a, b, t: a + (b - a) * t


class LogisticsSim:
    def __init__(self):
        self.speed = 1.0
        self.hook = None       # hook(kind, data): received, pallet, dispatched, reset
        self.reset()

    def _h(self, kind, **data):
        if self.hook:
            self.hook(kind, {"sim_t": self.time, **data})

    def reset(self):
        self._h("reset")
        self.time = 0.0
        self.stock = {k: m["stock"] for k, m in MATERIALS.items()}
        self.inbound = {"state": "idle", "t": 0.0}
        self.agv = {"state": "idle", "t": 0.0, "pallet": None}
        self.out = {"state": "idle", "t": 0.0, "wait": 0.0}
        self.open_pieces = []              # 아직 파렛트가 되지 않은 양품 (작업물 번호)
        self.pallets = []                  # {"id", "pieces", "stage", "slot", "prog"}
        self._next_pallet = 1
        self.counts = {"received": 0, "shipped_pallets": 0, "shipped_pcs": 0, "pallets": 0}
        self.manual_request = False

    def set_speed(self, v):
        self.speed = max(0.5, min(8.0, float(v)))

    # ---- 외부에서 들어오는 일 ----
    def consume(self, station):
        k, q = CONSUME[station]
        self.stock[k] = max(0.0, self.stock[k] - q)

    def add_exit(self, piece_id, result):
        """라인 끝에서 나온 작업물. 양품만 파렛트에 담는다."""
        if result != "good":
            return
        self.open_pieces.append(piece_id)
        if len(self.open_pieces) >= PALLET_QTY:
            self._make_pallet(self.open_pieces[:PALLET_QTY])
            self.open_pieces = self.open_pieces[PALLET_QTY:]

    def add_pallet(self, pieces):
        """협동로봇 셀이 쌓아서 마감한 파렛트 (작업물 번호 목록)."""
        if pieces:
            self._make_pallet(list(pieces))

    def flush(self):
        """라인이 멈추면 모자란 수량으로 파렛트를 만든다."""
        if self.open_pieces:
            self._make_pallet(self.open_pieces)
            self.open_pieces = []

    def request_inbound(self):
        self.manual_request = True

    def _make_pallet(self, pieces):
        pid = self._next_pallet
        self._next_pallet += 1
        p = {"id": pid, "pieces": list(pieces), "stage": "wait", "slot": None, "prog": 0.0}
        self.pallets.append(p)
        self.counts["pallets"] += 1
        self._h("pallet", id=pid, pieces=list(pieces))
        self._place_in_rack(p)

    def _free(self, stages, n):
        used = {p["slot"] for p in self.pallets if p["stage"] in stages and p["slot"] is not None}
        return next((i for i in range(n) if i not in used), None)

    def _place_in_rack(self, p):
        s = self._free(("rack", "agv_load"), len(LAYOUT["rack"]))
        if s is not None and p["stage"] == "wait":
            p["stage"], p["slot"] = "rack", s

    # ---- 시간 진행 ----
    def step(self, dt):
        self.time += dt
        self._step_inbound(dt)
        for p in self.pallets:                  # 창고가 가득 차서 기다리던 파렛트
            if p["stage"] == "wait":
                self._place_in_rack(p)
        self._step_agv(dt)
        self._step_out(dt)

    def advance(self, seconds, dt=0.05):
        t = seconds * self.speed
        while t > 1e-9:
            d = min(dt, t)
            self.step(d)
            t -= d

    def _low(self):
        return any(self.stock[k] <= m["rop"] for k, m in MATERIALS.items())

    def _step_inbound(self, dt):
        s = self.inbound
        if s["state"] == "idle":
            if self._low() or self.manual_request:
                self.manual_request = False
                s["state"], s["t"] = "arriving", 0.0
            return
        s["t"] += dt
        if s["state"] == "arriving" and s["t"] >= T["in_arrive"]:
            s["state"], s["t"] = "unloading", 0.0
        elif s["state"] == "unloading" and s["t"] >= T["unload"]:
            for k, m in MATERIALS.items():
                self.stock[k] += m["order"]
                self._h("received", material=k, item=m["item"], qty=m["order"], unit=m["unit"], supplier=m["supplier"])
            self.counts["received"] += 1
            s["state"], s["t"] = "leaving", 0.0
        elif s["state"] == "leaving" and s["t"] >= T["in_leave"]:
            s["state"], s["t"] = "idle", 0.0

    def _step_agv(self, dt):
        a = self.agv
        if a["state"] == "idle":
            cand = next((p for p in self.pallets if p["stage"] == "rack"), None)
            slot = self._free(("agv_unload", "dock", "to_truck"), len(LAYOUT["dock"]))
            if cand and slot is not None:
                a.update(state="loading", t=0.0, pallet=cand, dock=slot)
                cand["stage"], cand["prog"] = "agv_load", 0.0
            return
        a["t"] += dt
        p = a["pallet"]
        if a["state"] == "loading":
            p["prog"] = min(1.0, a["t"] / T["agv_load"])
            if a["t"] >= T["agv_load"]:
                p["stage"], p["slot"] = "agv", None
                a["state"], a["t"] = "moving", 0.0
        elif a["state"] == "moving":
            if a["t"] >= T["agv_move"]:
                a["state"], a["t"] = "unloading", 0.0
                p["stage"], p["prog"], p["slot"] = "agv_unload", 0.0, a["dock"]
        elif a["state"] == "unloading":
            p["prog"] = min(1.0, a["t"] / T["agv_unload"])
            if a["t"] >= T["agv_unload"]:
                p["stage"] = "dock"
                a["state"], a["t"], a["pallet"] = "returning", 0.0, None
        elif a["state"] == "returning" and a["t"] >= T["agv_return"]:
            a["state"], a["t"] = "idle", 0.0

    def _free_truck(self):
        used = {p.get("tslot") for p in self.pallets if p["stage"] in ("to_truck", "truck")}
        return next((i for i in range(len(LAYOUT["cargo"])) if i not in used), None)

    def _step_out(self, dt):
        o = self.out
        docked = [p for p in self.pallets if p["stage"] == "dock"]
        loading = next((p for p in self.pallets if p["stage"] == "to_truck"), None)
        if o["state"] == "idle":
            if docked:
                o["state"], o["t"], o["wait"] = "arriving", 0.0, 0.0
            return
        o["t"] += dt
        if o["state"] == "arriving" and o["t"] >= T["out_arrive"]:
            o["state"], o["t"], o["wait"] = "docked", 0.0, 0.0
        elif o["state"] == "docked":
            if loading:
                loading["prog"] = min(1.0, loading["prog"] + dt / T["to_truck"])
                if loading["prog"] >= 1.0:
                    loading["stage"] = "truck"
                o["wait"] = 0.0
                return
            slot = self._free_truck()
            if docked and slot is not None:
                nxt = docked[0]
                nxt["stage"], nxt["prog"], nxt["tslot"], nxt["dslot"] = "to_truck", 0.0, slot, nxt["slot"]   # 도크 칸은 그대로 기억한다
                return
            loaded = len([p for p in self.pallets if p["stage"] == "truck"])
            if loaded >= len(LAYOUT["cargo"]):            # 가득 차야 출발한다. 모자라면 다음 파렛트가 올 때까지 도크에서 기다린다
                ps = [p for p in self.pallets if p["stage"] == "truck"]
                self.counts["shipped_pallets"] += len(ps)
                self.counts["shipped_pcs"] += sum(len(p["pieces"]) for p in ps)
                self._h("dispatched", pallets=[{"id": p["id"], "pieces": list(p["pieces"])} for p in ps])
                o["state"], o["t"] = "leaving", 0.0
        elif o["state"] == "leaving" and o["t"] >= T["out_leave"]:
            self.pallets = [p for p in self.pallets if p["stage"] != "truck"]
            o["state"], o["t"] = "idle", 0.0

    # ---- 위치와 화면용 상태 ----
    def _truck_x(self):
        o = self.out
        pos = {"idle": 0.0, "arriving": o["t"] / T["out_arrive"], "docked": 1.0, "leaving": 1.0 - o["t"] / T["out_leave"]}[o["state"]]
        return min(1.0, max(0.0, pos)), lerp(LAYOUT["out_x"][0], LAYOUT["out_x"][1], min(1.0, max(0.0, pos)))

    def _agv_pos(self):
        a = self.agv
        if a["state"] == "moving":
            return min(1.0, a["t"] / T["agv_move"])
        if a["state"] == "returning":
            return max(0.0, 1.0 - a["t"] / T["agv_return"])
        return 1.0 if a["state"] == "unloading" else 0.0

    def _pallet_pos(self, p, truck_x, agv_pos):
        ax = lerp(*LAYOUT["agv_x"], agv_pos)
        agv_xyz = (ax, LAYOUT["agv_y"], LAYOUT["agv_z"])
        st = p["stage"]
        if st in ("rack", "wait"):
            return LAYOUT["rack"][p["slot"] if p["slot"] is not None else 0] if st == "rack" else (2.4, 0.3, -7.0)
        if st == "agv_load":
            a, b = LAYOUT["rack"][p["slot"]] if p["slot"] is not None else LAYOUT["rack"][0], (LAYOUT["agv_x"][0], LAYOUT["agv_y"], LAYOUT["agv_z"])
            return tuple(lerp(a[i], b[i], p["prog"]) for i in range(3))
        if st == "agv":
            return agv_xyz
        if st == "agv_unload":
            a, b = (LAYOUT["agv_x"][1], LAYOUT["agv_y"], LAYOUT["agv_z"]), LAYOUT["dock"][p["slot"]]
            return tuple(lerp(a[i], b[i], p["prog"]) for i in range(3))
        if st == "dock":
            return LAYOUT["dock"][p["slot"]]
        c = LAYOUT["cargo"][p["tslot"]] if st in ("to_truck", "truck") else LAYOUT["cargo"][0]
        tgt = (truck_x + c[0], c[1], c[2])
        if st == "to_truck":
            a = LAYOUT["dock"][p.get("dslot", 0)]
            return tuple(lerp(a[i], tgt[i], p["prog"]) for i in range(3))
        return tgt

    def state(self):
        tpos, tx = self._truck_x()
        ipos = {"idle": 0.0, "arriving": self.inbound["t"] / T["in_arrive"], "unloading": 1.0, "leaving": 1.0 - self.inbound["t"] / T["in_leave"]}[self.inbound["state"]]
        apos = self._agv_pos()
        parts = []
        for p in self.pallets:
            x, y, z = self._pallet_pos(p, tx, apos)
            parts.append({"id": p["id"], "stage": p["stage"], "qty": len(p["pieces"]), "pos": [round(x, 3), round(y, 3), round(z, 3)]})
        stock = {k: {"qty": round(self.stock[k], 2), "pct": round(min(1.0, self.stock[k] / (m["stock"] + m["order"])), 3),
                     "level": "low" if self.stock[k] <= m["rop"] else "ok", "unit": m["unit"], "name": m["name"]} for k, m in MATERIALS.items()}
        rack = sum(1 for p in self.pallets if p["stage"] in ("rack", "agv_load"))
        ist, it, ost, ast = self.inbound["state"], self.inbound["t"], self.out["state"], self.agv["state"]
        # 입고: 트럭이 도크에 붙으면(unloading) 뒷문이 열리고, 신축 컨베이어가 1.5초에 걸쳐 트럭 안으로 뻗고, 박스가 흐르고, 끝나기 전 1.5초에 접힌다
        boom = max(0.0, min(1.0, it / 1.5, (T["unload"] - it) / 1.5)) if ist == "unloading" else 0.0
        cartons = []
        for i in range(4):
            ph = ((it - 1.5) * 0.2 + i / 4.0) % 1.0
            flowing = ist == "unloading" and boom > 0.999
            cartons.append({"p": round(ph, 3) if flowing else 0.0, "on": bool(flowing and 0.03 < ph < 0.97)})
        # 입고 트럭 적재량: 도착할 때 가득(1.0), 신축 컨베이어가 펴진 뒤 박스가 흐르는 동안 줄어서 하역이 끝나면 0. 뒷문 쪽 적재 칸부터 비워진다
        if ist in ("arriving",):
            load = 1.0
        elif ist == "unloading":
            load = max(0.0, min(1.0, 1.0 - (it - 1.5) / (T["unload"] - 3.0)))
        else:
            load = 0.0
        n_in = math.ceil(load * IN_CARGO - 1e-9)
        cap = len(LAYOUT["cargo"])
        loaded_out = len([p for p in self.pallets if p["stage"] == "truck"]) if ost in ("docked", "leaving") else 0
        carrying = any(p["stage"] in ("agv_load", "agv", "agv_unload") for p in self.pallets)
        return {
            "time": round(self.time, 1), "speed": self.speed, "stock": stock,
            "inbound": {"state": ist, "truck": round(min(1.0, max(0.0, ipos)), 3), "moving": 1 if ist in ("arriving", "leaving") else 0,
                        "docked": 1 if ist == "unloading" else 0, "door": 1 if ist == "unloading" else 0, "boom": round(boom, 3), "cartons": cartons,
                        "load": round(load, 3), "cargo": [1 if i < n_in else 0 for i in range(IN_CARGO)]},
            "agv": {"state": ast, "pos": round(apos, 3), "moving": 1 if ast in ("moving", "returning") else 0, "lift": 1 if carrying else 0},
            "outbound": {"state": ost, "truck": round(tpos, 3), "moving": 1 if ost in ("arriving", "leaving") else 0, "docked": 1 if ost == "docked" else 0,
                         "loaded": loaded_out, "capacity": cap, "full": 1 if loaded_out >= cap else 0},
            "parts": parts, "counts": {**self.counts, "rack": rack, "open": len(self.open_pieces)},
            "kpi": {"low_stock": [k for k, v in stock.items() if v["level"] == "low"]},
        }
