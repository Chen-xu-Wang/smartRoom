"""给水侧水力模型（任务 1.5 的给水部分，排水侧尚未实现）。

模型
----
- 管段集总阻力：ΔP = K·Q²，K 由参数库"设计流量下的压降"推导（``loss_*_mpa_at_*lps``）。
- 器具出口按孔口处理：Q = Cv·a·√P，a 为住户开度，Cv 取"水效流量 / √试验压力"。
  于是器具出口的等效阻力为 1/(Cv·a)²。
- 混水器具（花洒、洗脸盆、厨房龙头）的冷热两路在混水点汇合。住户调节混水比例
  h = (T_混 − T_冷)/(T_热 − T_冷)，混水阀对压力较高的一路节流，
  所以混水点压力取两路中较低者。
- 多器具同时用水时，共用管段流量叠加，按阻尼迭代求解。

故障通过 ``cv_factor``（器具出口通流能力倍数，<1 表示堵塞）和 ``k_factor``
（管段阻力倍数，>1 表示堵塞）注入；检测算法看不到这两个量。

已知简化：忽略楼内立管在用水时的动压损失、器具安装高度差和开关水瞬态。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt

from .params import Params

MPA_PER_LPS2 = "MPa/(L/s)²"

FIXTURE_CV_PARAM = {
    "SHOWER": "water.fixtures.shower_efficiency_grade2_lps",
    "BASIN": "water.fixtures.faucet_efficiency_grade2_lps",
    "KITCHEN_FAUCET": "water.fixtures.faucet_efficiency_grade2_lps",
    "TOILET": "water.fixtures.toilet_tank_fill_rated_lps",
    "WASHER": "water.fixtures.washer_tap_rated_lps",
}


def _design_flow_lps(param_path: str) -> float:
    """``loss_meter_mpa_at_0p30lps`` → 0.30。"""
    tail = param_path.rsplit("_at_", 1)[1]
    return float(tail.replace("lps", "").replace("p", "."))


@dataclass
class Node:
    code: str
    kind: str
    parents: list[str]
    side: str
    area: str
    fixture: str | None
    k: float  # MPa/(L/s)²


@dataclass
class Chain:
    """器具的一路供水：从入户到混水点（含混水点上游管段），``side`` 为 COLD/HOT。"""
    side: str
    segments: list[str]


@dataclass
class FixturePath:
    fixture: str
    node: str
    trunk: list[str]           # 混水点到器具出口之间的节点（含混水点本身），流过全部流量
    chains: list[Chain]        # 一路（纯冷水器具）或两路（混水器具）
    cv: float                  # L/s/√MPa，开度 1、无故障


@dataclass
class HouseNetwork:
    house_id: str
    nodes: dict[str, Node]
    fixtures: dict[str, FixturePath]
    sensors: list[dict]
    entry_static_mpa: float
    k_factor: dict[str, float] = field(default_factory=dict)
    cv_factor: dict[str, float] = field(default_factory=dict)

    def k(self, code: str) -> float:
        return self.nodes[code].k * self.k_factor.get(code, 1.0)


def build_network(house: dict, params: Params) -> HouseNetwork:
    nodes: dict[str, Node] = {}
    for seg in house["supply_network"]:
        k = 0.0
        if seg["loss_param"]:
            q = _design_flow_lps(seg["loss_param"])
            k = params[seg["loss_param"]] / (q * q)
        nodes[seg["segment_code"]] = Node(seg["segment_code"], seg["kind"], list(seg["parents"]), seg["side"],
                                          seg["area"], seg["fixture"], k)

    test_p = params["water.fixtures.efficiency_test_pressure_mpa"]
    fixtures: dict[str, FixturePath] = {}
    for node in nodes.values():
        if node.kind != "FIXTURE":
            continue
        trunk = [node.code]
        cur = node
        # 沿单一父节点上溯，直到遇到混水点（两个父节点）或入户
        while len(cur.parents) == 1 and nodes[cur.parents[0]].kind == "MIXER":
            cur = nodes[cur.parents[0]]
            trunk.append(cur.code)
        if len(cur.parents) == 2:
            chains = [_chain(nodes, p) for p in cur.parents]
        else:
            chains = [_chain(nodes, cur.parents[0])]
        cv = params[FIXTURE_CV_PARAM[node.fixture]] / sqrt(test_p)
        fixtures[node.fixture] = FixturePath(node.fixture, node.code, trunk, chains, cv)
    return HouseNetwork(house["house_id"], nodes, fixtures, house["sensors"], house["entry_static_pressure_mpa"])


def _chain(nodes: dict[str, Node], start: str) -> Chain:
    segs = []
    cur = nodes[start]
    side = "HOT" if cur.side == "HOT" else "COLD"
    while True:
        segs.append(cur.code)
        if cur.side == "HOT":
            side = "HOT"
        if not cur.parents:
            break
        cur = nodes[cur.parents[0]]
    return Chain(side, segs)


@dataclass
class ActiveUse:
    fixture: str
    open_fraction: float
    hot_fraction: float


@dataclass
class HydraulicState:
    fixture_flow_lps: dict[str, float]
    segment_flow_lps: dict[str, float]
    node_pressure_mpa: dict[str, float]   # 各管段下游端压力
    leak_flow_lps: dict[str, float] = field(default_factory=dict)


def solve(net: HouseNetwork, uses: list[ActiveUse], entry_mpa: float, iterations: int = 60,
          leaks: dict[str, float] | None = None) -> HydraulicState:
    """求解同时用水的器具流量与管段压力。

    ``leaks`` 为 {部件编码: 泄漏孔口系数 c（L/s/√MPa）}：该部件下游端按 Q = c·√P 向外泄漏，
    泄漏流量计入该部件及其全部上游管段（暗漏、软管脱落都用它表示）。
    """
    leaks = {code: c for code, c in (leaks or {}).items() if c > 0}
    if not uses and not leaks:
        pressures = _pressures(net, {}, entry_mpa)
        return HydraulicState({}, {}, pressures)

    flows = {u.fixture: 0.1 for u in uses}
    leak_q = {code: 0.0 for code in leaks}
    seg_flow: dict[str, float] = {}
    for _ in range(iterations):
        seg_flow = _segment_flows(net, uses, flows, leak_q)
        pressures = _pressures(net, seg_flow, entry_mpa)
        max_change = 0.0
        for code, c in leaks.items():
            # 固定其它流量，精确求解本泄漏点：沿上游路径 Σ K_s[(O_s+q)² − O_s²] + (q/c)² = P₀，
            # O_s 为管段上除本泄漏外的流量。大孔口（爆管）时简单阻尼迭代会振荡，这里解二次方程
            q_prev = leak_q[code]
            path = _ancestors_inclusive(net, code)
            p0 = pressures[code] + sum(net.k(s) * (seg_flow[s] ** 2 - (seg_flow[s] - q_prev) ** 2) for s in path)
            a = sum(net.k(s) for s in path) + 1.0 / (c * c)
            b = 2.0 * sum(net.k(s) * (seg_flow[s] - q_prev) for s in path)
            q_new = (-b + sqrt(max(b * b + 4 * a * max(p0, 0.0), 0.0))) / (2 * a)
            q = 0.5 * q_prev + 0.5 * q_new
            max_change = max(max_change, abs(q - q_prev))
            leak_q[code] = q
        for u in uses:
            path = net.fixtures[u.fixture]
            shares = _chain_shares(path, u.hot_fraction)
            # 混水点压力 = 有流量的各路中最低的上游压力（混水阀对高压一路节流）
            p_mix = min(pressures[c.segments[0]] for c, s in zip(path.chains, shares) if s > 0)
            k_trunk = sum(net.k(code) for code in path.trunk)
            cv_eff = path.cv * net.cv_factor.get(path.node, 1.0) * max(u.open_fraction, 1e-3)
            q_new = sqrt(max(p_mix, 0.0) / (k_trunk + 1.0 / (cv_eff * cv_eff)))
            q = 0.5 * flows[u.fixture] + 0.5 * q_new
            max_change = max(max_change, abs(q - flows[u.fixture]))
            flows[u.fixture] = q
        if max_change < 1e-7:
            break
    seg_flow = _segment_flows(net, uses, flows, leak_q)
    return HydraulicState(flows, seg_flow, _pressures(net, seg_flow, entry_mpa), leak_q)


def _ancestors_inclusive(net: HouseNetwork, code: str) -> list[str]:
    out, cur = [], net.nodes[code]
    while True:
        out.append(cur.code)
        if not cur.parents:
            return out
        cur = net.nodes[cur.parents[0]]


def _chain_shares(path: FixturePath, hot_fraction: float) -> list[float]:
    if len(path.chains) == 1:
        return [1.0]
    h = min(max(hot_fraction, 0.0), 1.0)
    return [h if c.side == "HOT" else 1.0 - h for c in path.chains]


def _segment_flows(net: HouseNetwork, uses: list[ActiveUse], flows: dict[str, float],
                   leak_q: dict[str, float] | None = None) -> dict[str, float]:
    seg: dict[str, float] = {}
    for code, q in (leak_q or {}).items():
        cur = net.nodes[code]
        while True:
            seg[cur.code] = seg.get(cur.code, 0.0) + q
            if not cur.parents:
                break
            cur = net.nodes[cur.parents[0]]
    for u in uses:
        path = net.fixtures[u.fixture]
        q = flows[u.fixture]
        for code in path.trunk:
            seg[code] = seg.get(code, 0.0) + q
        for chain, share in zip(path.chains, _chain_shares(path, u.hot_fraction)):
            for code in chain.segments:
                seg[code] = seg.get(code, 0.0) + q * share
    return seg


def _pressures(net: HouseNetwork, seg_flow: dict[str, float], entry_mpa: float) -> dict[str, float]:
    """按拓扑从入户向下游累减压降，得到每个节点下游端压力。混水/器具节点取上游最低压力。"""
    out: dict[str, float] = {}

    def p(code: str) -> float:
        if code in out:
            return out[code]
        node = net.nodes[code]
        upstream = entry_mpa if not node.parents else min(p(par) for par in node.parents)
        q = seg_flow.get(code, 0.0)
        out[code] = upstream - net.k(code) * q * q
        return out[code]

    for code in net.nodes:
        p(code)
    return out
