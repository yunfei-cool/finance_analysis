# -*- coding: utf-8 -*-
"""
ETF Rotation Strategy for Futu PC Strategy Editor (Python)
- Single file, paste and run.
- Uses only Python standard library.
"""
from __future__ import division
import math
import datetime
import statistics


# ===================== 参数区（可直接修改） =====================
ETF_LIST = [
    "HK.02800", "HK.03033", "HK.02828", "HK.03188", "HK.03068",
    "HK.03190", "HK.03001", "HK.03191", "HK.03015", "HK.03069",
]

REBALANCE_FREQ = "W"  # "W"=每周一次, "N"=每N个交易日
REBALANCE_N_DAYS = 5
TOP_N = 3
WEIGHT_MODE = "EQUAL"  # "EQUAL" 或 "RISK_PARITY"

MIN_CASH_BUFFER = 0.05
MAX_WEIGHT_SINGLE = 0.50
MIN_TRADE_VALUE = 2000
TURNOVER_LIMIT = 0.60

COST_GATE = True
MAX_COST_RATE = 0.003  # 0.30%

LOT_SIZE_DEFAULT = 100
PRICE_BPS = 5

DRY_RUN = True  # True=只输出建议订单；False=自动下模拟单

# 因子权重
W_MOM_20 = 0.25
W_MOM_60 = 0.25
W_MOM_120 = 0.25
W_VOL_20 = 0.15
W_LIQ_20 = 0.10

# 交易成本参数（港股ETF，可按手册调整）
COMMISSION_RATE = 0.0003
MIN_COMMISSION = 3
PLATFORM_FEE_PER_ORDER = 15
SETTLEMENT_FEE_RATE = 0.00002  # 按手册可调整
STAMP_DUTY_RATE = 0.0  # ETF默认0
OTHER_FEE_RATE = 0.00002
OTHER_FEE_MIN = 0
OTHER_FEE_MAX = 100

# ===================== API 适配层 =====================

def resolve(self, candidates):
    for name in candidates:
        fn = getattr(self, name, None)
        if callable(fn):
            return fn
        fn = globals().get(name)
        if callable(fn):
            return fn
    return None


def _log(self, msg):
    fn = resolve(self, ["show_variable", "log", "print", "alert"])
    if fn:
        try:
            return fn(msg)
        except Exception:
            return print(msg)
    return print(msg)


def _show(self, name, value):
    fn = resolve(self, ["show_variable", "log", "print", "alert"])
    if fn:
        try:
            return fn({name: value})
        except Exception:
            return fn(f"{name}: {value}")
    return print(f"{name}: {value}")


def _get_universe(self):
    candidates = ["get_universe", "get_stock_pool", "get_market_watch", "get_universe_list"]
    fn = resolve(self, candidates)
    if fn:
        try:
            data = fn(1) if fn.__code__.co_argcount >= 1 else fn()
            if data:
                return list(data)
        except Exception as exc:
            _log(self, f"读取运行标的组1失败：{exc}")
    return list(ETF_LIST)


def _get_history(self, code, count, ktype="K_DAY"):
    candidates = [
        "history_kline", "get_history_kline", "request_history_kline",
        "kline", "get_kline", "get_market_data",
    ]
    fn = resolve(self, candidates)
    if not fn:
        raise RuntimeError("未找到历史K线函数，请检查API手册（history_kline/get_history_kline/request_history_kline/kline）")
    try:
        return fn(code, count, ktype)
    except Exception:
        return fn(code, count)


def _extract_column(data, name):
    if data is None:
        return None
    if isinstance(data, dict):
        return data.get(name)
    try:
        return data[name]
    except Exception:
        pass
    try:
        return getattr(data, name)
    except Exception:
        return None


def _get_current_price(self, code):
    fn = resolve(self, ["current_price", "get_current_price", "get_price"])
    if not fn:
        raise RuntimeError("未找到当前价函数，请检查API手册（current_price/get_current_price/get_price）")
    try:
        return fn(code)
    except Exception:
        return fn(code, price_type="ALL")


def _get_order_book(self, code):
    fn = resolve(self, ["order_book", "get_order_book"])
    if not fn:
        return None
    try:
        return fn(code)
    except Exception:
        return None


def _get_positions(self):
    fn = resolve(self, ["get_positions", "position_list", "get_position_qty"])
    if not fn:
        raise RuntimeError("未找到持仓函数，请检查API手册（get_positions/position_list/get_position_qty）")
    return fn()


def _get_funds(self):
    fn = resolve(self, ["get_cash", "get_funds", "get_total_asset"])
    if not fn:
        raise RuntimeError("未找到资金函数，请检查API手册（get_cash/get_funds/get_total_asset）")
    return fn()


def _place_order(self, code, qty, price, side):
    candidates = ["place_order", "order", "buy", "sell", "target_position"]
    fn = resolve(self, candidates)
    if not fn:
        raise RuntimeError("未找到下单函数，请检查API手册（place_order/order/buy/sell/target_position）")
    if fn.__name__ in ("buy", "sell"):
        return fn(code, qty, price)
    return fn(code, qty, price, side)


# ===================== 成本模型 =====================

def hk_etf_cost(trade_value, num_orders=1):
    commission = max(trade_value * COMMISSION_RATE, MIN_COMMISSION)
    platform_fee = PLATFORM_FEE_PER_ORDER * num_orders
    settlement_fee = trade_value * SETTLEMENT_FEE_RATE
    stamp_duty = trade_value * STAMP_DUTY_RATE
    other_fee = trade_value * OTHER_FEE_RATE
    other_fee = min(max(other_fee, OTHER_FEE_MIN), OTHER_FEE_MAX)
    total = commission + platform_fee + settlement_fee + stamp_duty + other_fee
    return {
        "commission": commission,
        "platform_fee": platform_fee,
        "settlement_fee": settlement_fee,
        "stamp_duty": stamp_duty,
        "other_fee": other_fee,
        "total": total,
        "rate": total / trade_value if trade_value > 0 else 0,
    }


# ===================== 策略模板函数 =====================

def global_variables(self):
    self.last_rebalance_date = None
    self.last_positions = {}
    self.last_targets = {}
    self.rebalance_counter = 0
    _log(self, "策略初始化完成。")
    _log(self, "本策略仅用于研究与模拟，不构成投资建议。市场有风险，投资需谨慎。")


def custom_indicator(self):
    return


def _winsorize(values, lower=0.05, upper=0.95):
    if not values:
        return values
    sorted_vals = sorted(values)
    n = len(sorted_vals)
    lo = sorted_vals[int(n * lower)]
    hi = sorted_vals[min(int(n * upper), n - 1)]
    return [min(max(v, lo), hi) for v in values]


def _zscore(values):
    if not values:
        return values
    mean_v = statistics.mean(values)
    std_v = statistics.pstdev(values) or 1.0
    return [(v - mean_v) / std_v for v in values]


def _safe_avg(values):
    return sum(values) / len(values) if values else 0


def _is_rebalance_day(self, today):
    if REBALANCE_FREQ == "W":
        return today.weekday() == 0
    if REBALANCE_FREQ == "N":
        return self.rebalance_counter % REBALANCE_N_DAYS == 0
    return False


def _estimate_turnover(current_weights, target_weights):
    turnover = 0
    codes = set(current_weights) | set(target_weights)
    for code in codes:
        turnover += abs(target_weights.get(code, 0) - current_weights.get(code, 0))
    return turnover / 2


def _normalize_weights(weights):
    total = sum(weights.values())
    if total <= 0:
        return weights
    return {k: v / total for k, v in weights.items()}


def _get_lot_size(self, code):
    fn = resolve(self, ["get_lot_size", "lot_size"])
    if fn:
        try:
            size = fn(code)
            if size:
                return int(size)
        except Exception:
            pass
    _log(self, f"未获取到{code}的手数，使用默认{LOT_SIZE_DEFAULT}")
    return LOT_SIZE_DEFAULT


def handle_data(self):
    today = datetime.date.today()
    if self.last_rebalance_date == today:
        return

    self.rebalance_counter += 1
    if not _is_rebalance_day(self, today):
        return

    universe = _get_universe(self)
    _log(self, f"调仓日：{today}，候选ETF数量：{len(universe)}")

    factors = {}
    for code in universe:
        try:
            data = _get_history(self, code, 160)
        except Exception as exc:
            _log(self, f"{code} 历史K线获取失败：{exc}")
            continue
        close = _extract_column(data, "close")
        volume = _extract_column(data, "volume")
        turnover = _extract_column(data, "turnover")
        if close is None or len(close) < 130:
            _log(self, f"{code} K线不足，剔除")
            continue
        idx = -2
        if len(close) + idx <= 0:
            continue
        try:
            price_now = float(close[idx])
        except Exception:
            continue
        if price_now <= 0:
            continue
        if turnover:
            liq = _safe_avg([float(x) for x in turnover[-22:-2]])
        elif volume:
            liq = _safe_avg([float(x) for x in volume[-22:-2]])
        else:
            liq = 0
        if liq <= 0:
            _log(self, f"{code} 成交量/额过低，剔除")
            continue
        mom_20 = price_now / float(close[idx - 20]) - 1
        mom_60 = price_now / float(close[idx - 60]) - 1
        mom_120 = price_now / float(close[idx - 120]) - 1
        rets = []
        for i in range(idx - 20, idx):
            r = float(close[i]) / float(close[i - 1]) - 1
            rets.append(r)
        vol_20 = statistics.pstdev(rets) if rets else 0
        ma_100 = _safe_avg([float(x) for x in close[idx - 100:idx]])
        trend = 1 if price_now > ma_100 else 0
        factors[code] = {
            "mom_20": mom_20,
            "mom_60": mom_60,
            "mom_120": mom_120,
            "vol_20": vol_20,
            "liq_20": liq,
            "trend": trend,
        }

    if not factors:
        _log(self, "无可用ETF，跳过调仓")
        return

    codes = list(factors.keys())
    mom_20_list = [factors[c]["mom_20"] for c in codes]
    mom_60_list = [factors[c]["mom_60"] for c in codes]
    mom_120_list = [factors[c]["mom_120"] for c in codes]
    vol_20_list = [factors[c]["vol_20"] for c in codes]
    liq_20_list = [factors[c]["liq_20"] for c in codes]

    mom_20_z = _zscore(_winsorize(mom_20_list))
    mom_60_z = _zscore(_winsorize(mom_60_list))
    mom_120_z = _zscore(_winsorize(mom_120_list))
    vol_20_z = _zscore(_winsorize(vol_20_list))
    liq_20_z = _zscore(_winsorize(liq_20_list))

    scores = {}
    for i, code in enumerate(codes):
        if factors[code]["trend"] == 0:
            continue
        score = (
            W_MOM_20 * mom_20_z[i]
            + W_MOM_60 * mom_60_z[i]
            + W_MOM_120 * mom_120_z[i]
            - W_VOL_20 * vol_20_z[i]
            + W_LIQ_20 * liq_20_z[i]
        )
        scores[code] = score

    if not scores:
        _log(self, "趋势过滤后无可用ETF，跳过调仓")
        return

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    top = ranked[:TOP_N]
    _log(self, f"Top{TOP_N} ETF: {top}")

    target_weights = {}
    if WEIGHT_MODE == "RISK_PARITY":
        inv_vol = {}
        for code, _ in top:
            vol = max(factors[code]["vol_20"], 1e-6)
            inv_vol[code] = 1.0 / vol
        target_weights = _normalize_weights(inv_vol)
    else:
        w = 1.0 / len(top)
        target_weights = {code: w for code, _ in top}

    for code in list(target_weights.keys()):
        target_weights[code] = min(target_weights[code], MAX_WEIGHT_SINGLE)
    target_weights = _normalize_weights(target_weights)

    positions = _get_positions(self)
    current_weights = {}
    current_value = 0
    cash = 0
    total_asset = 0

    try:
        funds = _get_funds(self)
        if isinstance(funds, dict):
            cash = float(funds.get("cash", 0))
            total_asset = float(funds.get("total_asset", funds.get("total", 0)))
        else:
            cash = float(getattr(funds, "cash", 0))
            total_asset = float(getattr(funds, "total_asset", getattr(funds, "total", 0)))
    except Exception as exc:
        _log(self, f"资金获取失败：{exc}")

    pos_list = []
    if isinstance(positions, dict):
        for code, qty in positions.items():
            pos_list.append((code, qty))
    else:
        try:
            pos_list = [(p.code, p.qty) for p in positions]
        except Exception:
            pass

    for code, qty in pos_list:
        try:
            price = _get_current_price(self, code)
        except Exception:
            continue
        value = float(price) * float(qty)
        current_value += value
        current_weights[code] = value

    if total_asset <= 0:
        total_asset = current_value + cash

    current_weights = {k: v / total_asset for k, v in current_weights.items()} if total_asset > 0 else {}

    turnover = _estimate_turnover(current_weights, target_weights)
    if turnover > TURNOVER_LIMIT:
        _log(self, f"预计换手{turnover:.2%}超过限制{TURNOVER_LIMIT:.2%}，跳过调仓")
        return

    trade_value_est = turnover * total_asset
    est_cost = hk_etf_cost(trade_value_est, num_orders=len(top))
    if COST_GATE and est_cost["rate"] > MAX_COST_RATE:
        _log(self, f"预计费用{est_cost['rate']:.2%}超过阈值，跳过调仓")
        return

    target_values = {code: total_asset * w for code, w in target_weights.items()}

    orders = []
    for code, qty in pos_list:
        target_val = target_values.get(code, 0)
        try:
            price = float(_get_current_price(self, code))
        except Exception:
            continue
        target_qty = int(target_val / price)
        lot_size = _get_lot_size(self, code)
        target_qty = (target_qty // lot_size) * lot_size
        delta_qty = target_qty - int(qty)
        if delta_qty < 0:
            orders.append((code, "SELL", abs(delta_qty), price, "reduce"))

    for code, target_val in target_values.items():
        try:
            price = float(_get_current_price(self, code))
        except Exception:
            continue
        target_qty = int(target_val / price)
        lot_size = _get_lot_size(self, code)
        target_qty = (target_qty // lot_size) * lot_size
        current_qty = 0
        for p_code, qty in pos_list:
            if p_code == code:
                current_qty = int(qty)
                break
        delta_qty = target_qty - current_qty
        if delta_qty > 0:
            orders.append((code, "BUY", delta_qty, price, "increase"))

    final_orders = []
    for code, side, qty, price, reason in orders:
        trade_value = qty * price
        if trade_value < MIN_TRADE_VALUE:
            continue
        ob = _get_order_book(self, code)
        limit_price = price
        if ob and isinstance(ob, dict):
            if side == "BUY":
                limit_price = ob.get("ask1", price)
            else:
                limit_price = ob.get("bid1", price)
        else:
            adj = price * PRICE_BPS / 10000
            limit_price = price + adj if side == "BUY" else max(price - adj, 0.01)
        cost = hk_etf_cost(trade_value, num_orders=1)
        final_orders.append({
            "code": code,
            "side": side,
            "qty": qty,
            "limit_price": limit_price,
            "est_cost": cost,
            "reason": reason,
        })

    cash_after = cash - sum(o["qty"] * o["limit_price"] for o in final_orders if o["side"] == "BUY")
    cash_ratio = cash_after / total_asset if total_asset > 0 else 0

    _show(self, "TopETF", top)
    _show(self, "Turnover", turnover)
    _show(self, "EstCostRate", est_cost["rate"])
    _show(self, "CashRatioAfter", cash_ratio)
    _log(self, f"订单列表：{final_orders}")

    if cash_ratio < MIN_CASH_BUFFER:
        _log(self, f"现金比例{cash_ratio:.2%}低于阈值，跳过调仓")
        return

    if DRY_RUN:
        _log(self, "DRY_RUN 模式，仅输出建议订单。")
    else:
        for od in final_orders:
            try:
                _place_order(self, od["code"], od["qty"], od["limit_price"], od["side"])
            except Exception as exc:
                _log(self, f"下单失败 {od['code']}：{exc}")

    self.last_rebalance_date = today
    self.last_positions = current_weights
    self.last_targets = target_weights

    _log(self, "本策略仅用于研究与模拟，不构成投资建议。市场有风险，投资需谨慎。")
