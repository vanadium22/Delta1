"""Aligned observational indicators; no execution or profit claims."""
import math

import numpy as np
import pandas as pd


def align(left,right):
    if left.empty or right.empty:
        return pd.DataFrame(columns=["event_time","trade_date","session_id","close_left","close_right"])
    columns=["event_time","trade_date","session_id","close"]
    data=left[columns].merge(right[columns],on=columns[:3],suffixes=("_left","_right"))
    return data.dropna(subset=["close_left","close_right"]).sort_values("event_time")


def summarize(near,far,spot,frequency,window=30):
    pair=align(near,far)
    basis=align(near,spot)
    values={"spread":None,"basis_bp":None,"zscore":None,"realized_bp":None,"percentile":None}
    reasons={}
    if len(pair):
        pair["value"]=pair["close_left"]-pair["close_right"]
        values["spread"]=float(pair.iloc[-1]["value"])
        recent=pair
        if frequency!="1d":
            recent=pair[(pair["trade_date"]==pair.iloc[-1]["trade_date"]) & (pair["session_id"]==pair.iloc[-1]["session_id"])]
        if len(recent)>=window+1:
            prior=recent["value"].iloc[-window-1:-1]
            sigma=float(prior.std(ddof=1))
            if sigma>1e-12:
                values["zscore"]=(values["spread"]-float(prior.mean()))/sigma
            else:
                reasons["zscore"]="历史价差无波动"
            values["percentile"]=float((prior<=values["spread"]).mean()*100)
        else:
            reasons["zscore"]=f"需要 {window+1} 条同会话对齐数据，当前 {len(recent)} 条"
    else:
        reasons["spread"]="两腿没有同一时刻/交易日/会话的数据"
        reasons["zscore"]="缺少对齐价差历史"
    if len(basis):
        basis["value"]=np.where(basis["close_right"]!=0,(basis["close_left"]/basis["close_right"]-1)*10000,np.nan)
        basis=basis.dropna(subset=["value"])
        if len(basis):
            values["basis_bp"]=float(basis.iloc[-1]["value"])
    if values["basis_bp"] is None:
        reasons["basis_bp"]="指数与期货缺少同一时刻的有效价格"
    if frequency=="1d":
        reasons["realized_bp"]="短窗实现波动使用分钟或秒级连续数据"
    elif len(near)>=window+1:
        sample=near.tail(window+1)
        duration={"1m":60,"1s":1}[frequency]
        contiguous=(sample["event_time"].diff().iloc[1:].dt.total_seconds()==duration).all()
        same=sample["trade_date"].nunique()==1 and sample["session_id"].nunique()==1
        prices=sample["close"].to_numpy(dtype=float)
        if contiguous and same and np.isfinite(prices).all() and (prices>0).all():
            values["realized_bp"]=float(np.sqrt(np.square(np.diff(np.log(prices))).sum())*10000)
        else:
            reasons["realized_bp"]="窗口有缺口、跨会话或无效价格"
    else:
        reasons["realized_bp"]=f"需要 {window+1} 条连续价格"
    return values,reasons,pair,basis


def executable_spread(near,far,as_of,max_age=30,max_skew=3):
    if near is None or far is None:
        return None,"尚无两腿实时盘口"
    times=[pd.Timestamp(q["observed_at"]) for q in (near,far)]
    ages=[(pd.Timestamp(as_of)-t).total_seconds() for t in times]
    if any(age<0 for age in ages):
        return None,"盘口晚于计算截止时刻"
    if max(ages)>max_age:
        return None,"盘口接收时间已过期"
    if abs((times[0]-times[1]).total_seconds())>max_skew:
        return None,"两腿接收时间偏差过大"
    if times[0].tz_convert("Asia/Shanghai").date()!=times[1].tz_convert("Asia/Shanghai").date():
        return None,"两腿接收日期不同"
    for q in (near,far):
        bid,ask=q.get("bid_price_1"),q.get("ask_price_1")
        if not all(isinstance(v,(int,float)) and math.isfinite(v) and v>0 for v in (bid,ask)) or bid>ask:
            return None,"缺少有效一档盘口"
    return {"buy":near["ask_price_1"]-far["bid_price_1"],"sell":near["bid_price_1"]-far["ask_price_1"],
            "mid":(near["ask_price_1"]+near["bid_price_1"]-far["ask_price_1"]-far["bid_price_1"])/2},"源事件日期未认证，仅为接收时间盘口观测"
