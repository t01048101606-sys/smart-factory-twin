"""물류 · 출하 구역 시뮬레이터 (입고 -> 자재 창고, 완제품 창고 -> AGV -> 출하 도크 -> 트럭).

입고: 자재(냉연강판, 볼트, 도료) 재고가 발주점 아래로 내려가면 입고 트럭이 와서 하역한다 (lot.received).
      재고는 프레스 라인의 공정 완료 이벤트로 줄어든다 (MES BOM 과 같은 단위당 수량).
출하: 프레스 라인의 양품 5개가 모이면 파렛트가 되어 완제품 창고에 쌓이고, AGV가 출하 도크로 옮기고,
      트럭이 싣고 출발한다 (shipment.dispatched). 불량(scrap)은 불량 상자에 남고 출하되지 않는다.

위치 상수(LAYOUT)는 3D 장면(tools/make_logistics_scene.py)과 같다. state()는 3D 화면이 그대로 읽는다.
"""
import math

LAYOUT = {
    "inbound_x": (-15.0, -5.5),        # 입고 트럭 중심 x: pos 0 -> 1
    "out_x": (33.0, 21.0),             # 출하 트럭 중심 x: pos 0 -> 1 (도크)
    "agv_x": (4.6, 15.6), "agv_z": 0.0, "agv_y": 0.95,
    "rack": [(2.4 + (i % 3) * 2.2, 0.4, -2.6 - (i // 3) * 2.0) for i in range(6)],     # 완제품 창고 칸
    "dock": [(17.4, 0.4, -2.0 + 2.0 * j) for j in range(3)],                          # 출하 도크 칸
    "cargo": [(-1.3 + 2.6 * (k % 2), 1.15, -0.9 + 1.8 * (k // 2)) for k in range(4)],  # 트럭 화물칸 (트럭 중심 기준)
}
MATERIALS = {
    "steel": {"item": "RM-STEEL", "name": "냉연강판", "unit": "KG", "stock": 30.0, "rop": 12.0, "order": 60.0, "supplier": "한국제철"},
    "bolt": {"item": "RM-BOLT", "name": "육각볼트 M8", "unit": "EA", "stock": 150.0, "rop": 60.0, "order": 300.0, "supplier": "대한볼트산업"},
    "paint": {"item": "RM-PAINT", "name": "전착도료", "unit": "L", "stock": 2.0, "rop": 0.8, "order": 4.0, "supplier": "삼성도료"},
}
CONSUME = {"press": ("steel", 0.5), "weld": ("bolt", 4.0), "paint": ("paint", 0.05)}   # 공정 한 번 완료할 때 소비 (MES BOM 과 같음)
PALLET_QTY = 5
T = {"in_arrive": 8.0, "unload": 6.0, "in_leave": 6.0, "agv_load": 2.0, "agv_move": 6.0, "agv_unload": 2.0, "agv_return": 6.0,
     "out_arrive": 8.0, "to_truck": 3.0, "out_wait": 20.0, "out_leave": 8.0}
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
            o["wait"] += dt
            busy = bool(docked) or self.agv["state"] in ("loading", "moving", "unloading") or any(p["stage"] == "rack" for p in self.pallets)
            if loaded and (loaded >= len(LAYOUT["cargo"]) or (not busy and o["wait"] >= T["out_wait"])):
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
            return LAYOUT["rack"][p["slot"] if p["slot"] is not None else 0] if st == "rack" else (2.4, 0.4, -7.0)
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
        return {
            "time": round(self.time, 1), "speed": self.speed, "stock": stock,
            "inbound": {"state": self.inbound["state"], "truck": round(min(1.0, max(0.0, ipos)), 3)},
            "agv": {"state": self.agv["state"], "pos": round(apos, 3)},
            "outbound": {"state": self.out["state"], "truck": round(tpos, 3)},
            "parts": parts, "counts": {**self.counts, "rack": rack, "open": len(self.open_pieces)},
            "kpi": {"low_stock": [k for k, v in stock.items() if v["level"] == "low"]},
        }
