#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
================================================================================
БЭКТЕСТ СТРАТЕГИИ "МАНИПУЛЯЦИЯ НА ЧАСЕ" (Pifagor) — откаты по Фибоначчи
================================================================================
Стратегия (по описанию автора + уточнениям пользователя):

  ИМПУЛЬС: два последовательных бара в одну сторону, которые НЕ откатились
           друг к другу более чем на 50% (по фибе). Т.е. два сильных бара подряд.
           - импульс ВВЕРХ: два бычьих движения, low->high растёт.
           - works для шорта зеркально (импульс вниз).

  ФИБА: натягивается на импульс.
        - импульс вверх: уровень 1.0 = начало (low первого бара, точка A),
          уровень 0.0 = вершина (high второго бара, точка B).
        - откаты считаются вниз от B к A: 0.236 / 0.382 / 0.5 / 0.618 / 0.786.

  ВХОД: сразу выставляем 3 ЛИМИТНЫХ ордера на 0.382, 0.5, 0.618 (вход по тренду —
        в продолжение импульса, т.е. на импульсе вверх это ЛОНГИ на откате вниз).

  СТОП: на начале импульса — уровень 1.0 (точка A). Для всех ордеров общий.

  ЦЕЛИ (таблица автора, "глубина коррекции -> цель"):
        вошли по 0.382  -> цель 0.236
        вошли по 0.5    -> цель 0.382   (расширенная 0.236)
        вошли по 0.618  -> цель 0.5     (расширенная 0.382)
        + правило пользователя: "если цена ходила до 0.5 — закрываем на 0.236".

  ПЕРЕСТРОЙКА: если отката до 0.382 НЕ было, а цена обновила экстремум (перехай),
        импульс продлился -> фиба перестраивается по новому экстремуму, ордера
        переставляются. (неисполненные лимитки отменяются и ставятся заново.)

  ПЕРЕЗАПУСК: как только ЛЮБОЙ ордер отработал (профит или стоп) — снова ищем
        2 бара без коррекции >50% и всё заново.

  Меряем: матожидание/сделку (net of fees), winrate, PF, t-stat, in/out-of-sample,
          устойчивость к параметрам. winrate тут НЕ главное — главное матожидание.
================================================================================
"""
import os, sys, time, json, ssl
import urllib.request, urllib.error
from dataclasses import dataclass
import numpy as np
import pandas as pd

# ── SSL (как в первом скрипте: certifi + авто-фолбэк при подмене серта) ──
try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL_CTX = ssl.create_default_context()
_SSL_CTX_INSECURE = ssl.create_default_context()
_SSL_CTX_INSECURE.check_hostname = False
_SSL_CTX_INSECURE.verify_mode = ssl.CERT_NONE

# ──────────────────────────────────────────────────────────────────────────────
# КОНФИГ
# ──────────────────────────────────────────────────────────────────────────────
SYMBOL        = "BTCUSDT"
INTERVAL      = "1h"
MONTHS_BACK   = 24
DATA_SOURCE   = "cex"        # "cex" (Binance->Bybit) | "hyperliquid"
HL_COIN       = "BTC"
DATA_CSV      = None
USE_SYNTHETIC = False

# --- параметры стратегии ---
IMPULSE_NO_RETRACE = 0.50    # импульс: бары не откатились друг к другу > этого (50%)
ATR_PERIOD    = 14           # период ATR для фильтра силы бара
ATR_MULT      = 0.0          # фильтр №1a: каждый бар импульса >= ATR_MULT*ATR. 0.0 = выкл (как было)
MIN_BAR_PCT   = 0.7          # фильтр №1b: каждый бар импульса >= 0.7% движения. ГЛАВНЫЙ фильтр шума (25%->75-88% окон, сессия 21.06.2026)
TREND_EMA     = 0            # фильтр №2 (ОПЦИОНАЛЬНЫЙ): тренд по EMA. ВЫКЛ по умолчанию — почти не добавляет (88% окон и без него, сделок больше). EMA200 проверена, +0.112% vs +0.104%, но лишний параметр. Сессия 21.06.2026
FIB_ENTRIES   = [0.382, 0.5, 0.618]     # уровни лимитных ордеров
FIB_TARGETS   = {0.382: 0.236, 0.5: 0.382, 0.618: 0.5}  # вход -> цель (таблица автора)
STOP_FIB      = 0.9          # стоп: 0.9 от импульса (не 1.0 — урезает крупные убытки, +0.034% эксп. по всей сетке, сессия 21.06.2026)
RULE_05_TO_0236 = True       # "если ходила до 0.5 — закрываем на 0.236"
MAX_WAIT_BARS = 48           # сколько баров ждём отработки/перестройки, иначе сброс сетапа
ALLOW_SHORT   = True         # торговать и импульсы вниз (шорты)

# --- издержки ---
FEE_PCT       = 0.04
SLIPPAGE_PCT  = 0.02

OOS_FRACTION  = 0.40
OUTDIR        = os.path.dirname(os.path.abspath(__file__))

# ──────────────────────────────────────────────────────────────────────────────
# ЗАГРУЗКА ДАННЫХ (с фолбэком и SSL-фиксом)
# ──────────────────────────────────────────────────────────────────────────────
BINANCE_HOSTS = ["https://api.binance.com","https://data-api.binance.vision",
                 "https://api1.binance.com","https://api2.binance.com","https://api3.binance.com"]
_insecure_warned = False
def _open(req, timeout):
    global _insecure_warned
    try:
        return urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX)
    except urllib.error.URLError as e:
        is_cert = isinstance(getattr(e,"reason",None), ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(e)
        if is_cert:
            if not _insecure_warned:
                print("  (i) SSL-серт не проверился (антивирус/прокси). Загружаю публичные данные без проверки серта.")
                _insecure_warned = True
            return urllib.request.urlopen(req, timeout=timeout, context=_SSL_CTX_INSECURE)
        raise
def _get(url, timeout=20):
    return json.loads(_open(urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"}), timeout).read())

def fetch_binance(symbol, interval, months):
    ms=3600_000; end=int(time.time()*1000); start=end-months*30*24*ms
    for host in BINANCE_HOSTS:
        rows=[]; cur=start; ok=True
        print(f"Binance: {host} ...")
        while cur<end:
            try: data=_get(f"{host}/api/v3/klines?symbol={symbol}&interval={interval}&startTime={cur}&limit=1000")
            except Exception as e: print(f"  ! {e}"); ok=False; break
            if not data: break
            rows+=data; cur=data[-1][0]+ms; print(f"  ...{len(rows)}",end="\r"); time.sleep(0.15)
        print()
        if ok and rows:
            df=pd.DataFrame(rows,columns=["time","open","high","low","close","volume","ct","qav","tr","tb","tq","ig"])
            df=df[["time","open","high","low","close","volume"]].copy()
            for c in ["open","high","low","close","volume"]: df[c]=df[c].astype(float)
            df["time"]=pd.to_datetime(df["time"],unit="ms")
            return df.drop_duplicates("time").reset_index(drop=True)
    return None

def fetch_bybit(symbol, interval_min, months):
    ms=60_000; step=int(interval_min)*ms; end=int(time.time()*1000); start=end-months*30*24*3600_000
    rows=[]; cur=start; print("Bybit ...")
    while cur<end:
        try: r=_get(f"https://api.bybit.com/v5/market/kline?category=spot&symbol={symbol}&interval={interval_min}&start={cur}&limit=1000")
        except Exception as e: print(f"  ! {e}"); return None
        lst=r.get("result",{}).get("list",[])
        if not lst: break
        lst=sorted(lst,key=lambda x:int(x[0]))
        for k in lst: rows.append([int(k[0]),float(k[1]),float(k[2]),float(k[3]),float(k[4]),float(k[5])])
        cur=int(lst[-1][0])+step; print(f"  ...{len(rows)}",end="\r"); time.sleep(0.15)
    print()
    if not rows: return None
    df=pd.DataFrame(rows,columns=["time","open","high","low","close","volume"])
    df["time"]=pd.to_datetime(df["time"],unit="ms")
    return df.drop_duplicates("time").reset_index(drop=True)

HL_MS={"1m":60_000,"5m":300_000,"15m":900_000,"30m":1_800_000,"1h":3_600_000,"4h":14_400_000,"1d":86_400_000}
def fetch_hl(coin, interval, months):
    url="https://api.hyperliquid.xyz/info"; step=HL_MS.get(interval,3_600_000)
    end=int(time.time()*1000); start=end-months*30*24*3600_000; win=5000*step
    rows={}; cur=start; print(f"Hyperliquid {coin} ...")
    while cur<end:
        body=json.dumps({"type":"candleSnapshot","req":{"coin":coin,"interval":interval,"startTime":cur,"endTime":min(cur+win,end)}}).encode()
        req=urllib.request.Request(url,data=body,headers={"User-Agent":"Mozilla/5.0","Content-Type":"application/json"})
        try: data=json.loads(_open(req,20).read())
        except Exception as e: print(f"  ! {e}"); return None
        if not data: cur+=win; continue
        for k in data: t=int(k["t"]); rows[t]=[t,float(k["o"]),float(k["h"]),float(k["l"]),float(k["c"]),float(k["v"])]
        cur=max(int(k["t"]) for k in data)+step; print(f"  ...{len(rows)}",end="\r"); time.sleep(0.12)
    print()
    if not rows: return None
    df=pd.DataFrame(sorted(rows.values()),columns=["time","open","high","low","close","volume"])
    df["time"]=pd.to_datetime(df["time"],unit="ms")
    return df.reset_index(drop=True)

def load_csv(p):
    df=pd.read_csv(p); df.columns=[c.lower() for c in df.columns]
    df["time"]=pd.to_datetime(df["time"])
    for c in ["open","high","low","close"]: df[c]=df[c].astype(float)
    if "volume" not in df: df["volume"]=0.0
    return df.sort_values("time").reset_index(drop=True)

def make_synthetic(n=24*400, seed=7):
    """Синтетика для проверки КОДА (не для выводов). С выраженными импульсами и откатами."""
    rng=np.random.default_rng(seed)
    price=[30000.0]; trend=0.0
    for i in range(n):
        if rng.random()<0.05: trend=rng.normal(0,0.004)   # иногда задаём импульсный дрейф
        price.append(price[-1]*(1+rng.normal(trend,0.008)))
    price=np.array(price[1:])
    o=price.copy(); c=np.roll(price,-1); c[-1]=price[-1]
    hi=np.maximum(o,c)*(1+np.abs(rng.normal(0,0.003,n)))
    lo=np.minimum(o,c)*(1-np.abs(rng.normal(0,0.003,n)))
    t=pd.date_range("2024-01-01",periods=n,freq="h")
    return pd.DataFrame({"time":t,"open":o,"high":hi,"low":lo,"close":c,"volume":rng.uniform(1,50,n)})

def get_data():
    if USE_SYNTHETIC:
        print(">>> СИНТЕТИКА — метрики ничего не доказывают про реальный эдж."); return make_synthetic(), True
    if DATA_CSV: return load_csv(DATA_CSV), False
    tag=HL_COIN if DATA_SOURCE=="hyperliquid" else SYMBOL
    cache=os.path.join(OUTDIR,f"{tag}_{INTERVAL}_{MONTHS_BACK}m_{DATA_SOURCE}.csv")
    if os.path.exists(cache):
        print(f"Кэш: {cache}"); return load_csv(cache), False
    df=None
    if DATA_SOURCE=="hyperliquid":
        df=fetch_hl(HL_COIN,INTERVAL,MONTHS_BACK)
        if df is None or df.empty:
            print(">>> HL пусто, резерв CEX"); df=fetch_binance(SYMBOL,INTERVAL,MONTHS_BACK) or fetch_bybit(SYMBOL,"60",MONTHS_BACK)
    else:
        df=fetch_binance(SYMBOL,INTERVAL,MONTHS_BACK)
        if df is None or df.empty:
            im={"1h":"60","4h":"240","1d":"D","15m":"15","30m":"30"}.get(INTERVAL,"60")
            df=fetch_bybit(SYMBOL,im,MONTHS_BACK)
    if df is None or df.empty:
        print("\n!!! Данные не скачались. Включи VPN / смени DATA_SOURCE / задай DATA_CSV."); sys.exit(1)
    df.to_csv(cache,index=False); print(f"Сохранил кэш: {cache}")
    return df, False

# ──────────────────────────────────────────────────────────────────────────────
# СТРАТЕГИЯ
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class Trade:
    side:str; entry_i:int; entry:float; stop:float; target:float; entry_fib:float
    exit_i:int=None; exit:float=None; outcome:str=None; ret_pct:float=None

def detect_impulse(o,h,l,c,i,no_retrace=IMPULSE_NO_RETRACE,atr=None,atr_mult=0.0,min_bar_pct=0.0):
    """
    V2 «ДВА ЧИСТЫХ БАРА» (логика пользователя, 21.06.2026).
    Импульс по двум барам i-1, i.

    Идея: фибу натягиваем на ПЕРВЫЙ бар (low->high). Второй бар считается
    "чистым продолжением", если он НЕ скорректировал первый внутрь себя
    глубже уровня no_retrace (по умолчанию 50%). Корректировкой считается
    заход ТЕНИ второго бара (его low для long / high для short) на уровень
    no_retrace первого бара ИЛИ глубже.

      LONG  (оба бара бычьи, второй обновляет хай):
        уровень = low1 + (1-no_retrace)*range1   # при 0.5 это середина бара 1
        чисто, если low2 > уровень  (касание/ниже = откат => отвергаем).
      SHORT — зеркально:
        уровень = high1 - (1-no_retrace)*range1
        чисто, если high2 < уровень.

    ФИЛЬТР №1 (сила бара, ATR): если atr_mult>0 и передан массив atr,
    дополнительно требуем, чтобы ДИАПАЗОН КАЖДОГО из двух баров был
    >= atr_mult * atr[i-1] (ATR на момент НАЧАЛА импульса, без look-ahead).
    Отсекает мелкие "импульсы" из шума/боковика. atr_mult=0 => фильтр выкл.

    Возвращает (side, A, B) или None. A=Фибо 1.0 (начало импульса), B=Фибо 0.0.
    """
    if i<1: return None
    # фильтр силы бара №1a (ATR, относительный)
    if atr_mult>0.0:
        if atr is None or np.isnan(atr[i-1]) or atr[i-1]<=0:
            return None
        need = atr_mult*atr[i-1]
        if (h[i-1]-l[i-1]) < need or (h[i]-l[i]) < need:
            return None
    # фильтр силы бара №1b (абсолютный, % движения цены): оба бара >= порога
    if min_bar_pct>0.0:
        p1=(h[i-1]-l[i-1])/o[i-1]*100.0
        p2=(h[i]-l[i])/o[i]*100.0
        if p1 < min_bar_pct or p2 < min_bar_pct:
            return None
    # --- LONG: два бычьих бара ---
    bull1 = c[i-1] > o[i-1]
    bull2 = c[i]   > o[i]
    if bull1 and bull2 and h[i] > h[i-1]:
        rng1 = h[i-1]-l[i-1]
        if rng1>0:
            # уровень no_retrace, отсчитанный ВВЕРХ от low первого бара
            lvl = l[i-1] + (1.0-no_retrace)*rng1   # no_retrace=0.5 -> середина бара1
            # бар 2 чист, если его нижняя тень держится ВЫШЕ уровня (строго)
            if l[i] > lvl:
                A=l[i-1]; B=h[i]
                if B>A: return ("long",A,B)
    # --- SHORT: два медвежьих бара ---
    if ALLOW_SHORT:
        bear1 = c[i-1] < o[i-1]
        bear2 = c[i]   < o[i]
        if bear1 and bear2 and l[i] < l[i-1]:
            rng1 = h[i-1]-l[i-1]
            if rng1>0:
                lvl = h[i-1] - (1.0-no_retrace)*rng1   # уровень вниз от high первого бара
                # бар 2 чист, если его верхняя тень держится НИЖЕ уровня (строго)
                if h[i] < lvl:
                    A=h[i-1]; B=l[i]
                    if A>B: return ("short",A,B)
    return None

def compute_atr(h,l,c,period=ATR_PERIOD):
    """ATR простым SMA от True Range. atr[i] использует бары ВКЛЮЧАЯ i
    (на момент закрытия бара i он известен). В detect_impulse берём atr[i-1] —
    значение, доступное ДО появления второго бара импульса. Без look-ahead."""
    n=len(c); tr=np.zeros(n)
    for k in range(1,n):
        tr[k]=max(h[k]-l[k], abs(h[k]-c[k-1]), abs(l[k]-c[k-1]))
    atr=np.full(n,np.nan)
    for k in range(period,n):
        atr[k]=tr[k-period+1:k+1].mean()
    return atr

def fib_price(A,B,level,side):
    """Цена уровня фибы. side long: B=вершина(0.0), A=низ(1.0). retrace вниз от B."""
    if side=="long":
        return B - (B-A)*level
    else:  # short: B=низ(0.0), A=верх(1.0). retrace вверх от B
        return B + (A-B)*level

def run(df, no_retrace=IMPULSE_NO_RETRACE, fee=FEE_PCT, slip=SLIPPAGE_PCT,
        rule_05=RULE_05_TO_0236, max_wait=MAX_WAIT_BARS, atr_mult=ATR_MULT, min_bar_pct=MIN_BAR_PCT,
        stop_fib=STOP_FIB, trend_ema=TREND_EMA):
    o=df["open"].values; h=df["high"].values; l=df["low"].values; c=df["close"].values
    n=len(df); cost=(fee+slip)/100.0
    atr = compute_atr(h,l,c,ATR_PERIOD) if atr_mult>0.0 else None
    # EMA для фильтра тренда (считаем по close, без look-ahead: на баре i знаем ema[i])
    ema = pd.Series(c).ewm(span=trend_ema, adjust=False).mean().values if trend_ema>0 else None
    trades=[]
    i=2
    while i<n:
        imp=detect_impulse(o,h,l,c,i,no_retrace,atr,atr_mult,min_bar_pct)
        if imp is None:
            i+=1; continue
        side,A,B=imp
        # фильтр №2: вход только в сторону тренда (EMA на момент НАЧАЛА импульса, бар i-1)
        if ema is not None and not np.isnan(ema[i-1]):
            up = c[i-1] > ema[i-1]
            if (side=="long" and not up) or (side=="short" and up):
                i+=1; continue
        # уровни входа/стопа
        entries={lv:fib_price(A,B,lv,side) for lv in FIB_ENTRIES}
        stop=fib_price(A,B,stop_fib,side)
        filled={}             # lv -> entry_i (исполненные лимитки)
        reached_05=False
        setup_done=False
        j=i+1
        wait=0
        while j<n and not setup_done:
            hj,lj=h[j],l[j]
            # --- перестройка при перехае/перелое, если ещё НЕ было входа ---
            if not filled:
                if side=="long" and hj>B:
                    # импульс продлился вверх -> новый B, фиба заново
                    B=hj; entries={lv:fib_price(A,B,lv,side) for lv in FIB_ENTRIES}; stop=fib_price(A,B,stop_fib,side)
                    wait=0; j+=1; continue
                if side=="short" and lj<B:
                    B=lj; entries={lv:fib_price(A,B,lv,side) for lv in FIB_ENTRIES}; stop=fib_price(A,B,stop_fib,side)
                    wait=0; j+=1; continue
            # --- проверка срабатывания лимиток (касание уровня внутри бара) ---
            for lv in FIB_ENTRIES:
                if lv in filled: continue
                px=entries[lv]
                touched = (lj<=px<=hj)
                if touched: filled[lv]=j
            # отметка достижения 0.5 (для правила закрытия на 0.236)
            p05=fib_price(A,B,0.5,side)
            if side=="long" and lj<=p05: reached_05=True
            if side=="short" and hj>=p05: reached_05=True
            # --- если есть открытые позиции, проверяем стоп/цель для каждой ---
            if filled:
                # стоп общий
                stop_hit = (lj<=stop) if side=="long" else (hj>=stop)
                # обрабатываем каждый исполненный ордер
                done_levels=[]
                for lv,ei in filled.items():
                    tgt_lv=FIB_TARGETS[lv]
                    if rule_05 and reached_05:
                        tgt_lv=0.236   # правило: ходила до 0.5 -> цель 0.236
                    tgt=fib_price(A,B,tgt_lv,side)
                    tgt_hit = (hj>=tgt) if side=="long" else (lj<=tgt)
                    if stop_hit and tgt_hit:
                        _close(trades,side,ei,entries[lv],stop,stop,lv,j,"stop",cost); done_levels.append(lv)
                    elif stop_hit:
                        _close(trades,side,ei,entries[lv],stop,stop,lv,j,"stop",cost); done_levels.append(lv)
                    elif tgt_hit:
                        _close(trades,side,ei,entries[lv],stop,tgt,lv,j,"target",cost); done_levels.append(lv)
                for lv in done_levels: del filled[lv]
                # как только ВСЕ позиции закрыты И хотя бы одна была — перезапуск поиска
                if done_levels and not filled:
                    setup_done=True; i=j+1; break
                if stop_hit and not filled:
                    setup_done=True; i=j+1; break
            wait+=1
            if wait>=max_wait:
                # сетап протух (не дождались) — сбрасываем; закрываем что осталось по close
                for lv,ei in list(filled.items()):
                    _close(trades,side,ei,entries[lv],stop,c[j],lv,j,"timeout",cost)
                setup_done=True; i=j+1; break
            j+=1
        if not setup_done:
            i+=1
    return trades

def _close(trades,side,entry_i,entry,stop,exit_px,fib,exit_i,outcome,cost):
    gross=(exit_px-entry)/entry if side=="long" else (entry-exit_px)/entry
    ret=(gross-2*cost)*100.0
    trades.append(Trade(side=side,entry_i=entry_i,entry=entry,stop=stop,target=exit_px,
                        entry_fib=fib,exit_i=exit_i,exit=exit_px,outcome=outcome,ret_pct=ret))

# ──────────────────────────────────────────────────────────────────────────────
# МЕТРИКИ
# ──────────────────────────────────────────────────────────────────────────────
def metrics(trades,label=""):
    if not trades: return {"label":label,"n":0}
    r=np.array([t.ret_pct for t in trades]); w=r[r>0]; ls=r[r<=0]
    eq=np.cumsum(r); dd=eq-np.maximum.accumulate(eq); n=len(r)
    pf=w.sum()/(-ls.sum()) if ls.sum()<0 else float("inf")
    ts=r.mean()/(r.std(ddof=1)/np.sqrt(n)) if n>1 and r.std()>0 else 0
    return {"label":label,"n":n,"winrate_%":round(len(w)/n*100,1),
            "expectancy_%_per_trade":round(r.mean(),4),
            "avg_win_%":round(w.mean(),3) if len(w) else 0,
            "avg_loss_%":round(ls.mean(),3) if len(ls) else 0,
            "profit_factor":round(pf,2) if pf!=float("inf") else "inf",
            "total_return_%":round(eq[-1],2),"max_drawdown_%":round(dd.min(),2),
            "t_stat":round(ts,2),"_eq":eq}

def show(m):
    if m.get("n",0)==0: print(f"[{m['label']}] сделок нет."); return
    print(f"\n┌─ {m['label']} "+"─"*(46-len(m['label'])))
    print(f"│ Сделок:               {m['n']}")
    print(f"│ Winrate:              {m['winrate_%']}%")
    print(f"│ МАТОЖИДАНИЕ/сделку:   {m['expectancy_%_per_trade']}%  <-- главное (net fees)")
    print(f"│ Сред. выигрыш:        {m['avg_win_%']}%")
    print(f"│ Сред. проигрыш:       {m['avg_loss_%']}%")
    print(f"│ Profit factor:        {m['profit_factor']}")
    print(f"│ Итог доходность:      {m['total_return_%']}%")
    print(f"│ Макс. просадка:       {m['max_drawdown_%']}%")
    print(f"│ t-stat:               {m['t_stat']}  (|t|>2 ≈ значимо)")
    print("└"+"─"*48)

# ──────────────────────────────────────────────────────────────────────────────
def main():
    df,is_synth=get_data()
    print(f"Свечей: {len(df)} ({df['time'].iloc[0]} .. {df['time'].iloc[-1]})")
    split=int(len(df)*(1-OOS_FRACTION))
    df_is=df.iloc[:split].reset_index(drop=True); df_oos=df.iloc[split:].reset_index(drop=True)
    print(f"IN-SAMPLE {len(df_is)} | OUT-OF-SAMPLE {len(df_oos)}")

    print("\n"+"="*60); print("СТРАТЕГИЯ ПИФАГОРА (фиб-откат) — базовые параметры")
    print(f"  импульс: 2 бара, откат<{IMPULSE_NO_RETRACE*100:.0f}%; входы {FIB_ENTRIES}; стоп {STOP_FIB}")
    print(f"  издержки≈{2*(FEE_PCT+SLIPPAGE_PCT):.2f}%/сделку; шорты={ALLOW_SHORT}"); print("="*60)

    m_is=metrics(run(df_is),"IN-SAMPLE"); m_oos=metrics(run(df_oos),"OUT-OF-SAMPLE")
    show(m_is); show(m_oos)

    print("\n"+"="*60); print("УСТОЙЧИВОСТЬ К ПАРАМЕТРАМ (OUT-OF-SAMPLE)"); print("="*60)
    grid=[]
    for nr in [0.4,0.5,0.6]:
        for mw in [24,48,72]:
            tr=run(df_oos,no_retrace=nr,max_wait=mw); mm=metrics(tr)
            if mm.get("n",0)>0: grid.append((nr,mw,mm["n"],mm["expectancy_%_per_trade"],mm["t_stat"],mm["profit_factor"]))
    gdf=pd.DataFrame(grid,columns=["no_retrace","max_wait","trades","expectancy_%","t_stat","PF"])
    print("\n"+gdf.to_string(index=False))
    pos=(gdf["expectancy_%"]>0).sum()
    print(f"\nПоложительное матожидание: {pos}/{len(gdf)} комбинаций")
    print(f"Статзначимых (|t|>2): {(gdf['t_stat'].abs()>2).sum()}")

    rp=os.path.join(OUTDIR,"pifagor_report.txt")
    with open(rp,"w") as f:
        f.write("PIFAGOR FIB STRATEGY — BACKTEST\n")
        f.write(f"data: {'SYNTHETIC' if is_synth else SYMBOL+' '+INTERVAL+' '+DATA_SOURCE}\n")
        f.write(f"candles: {len(df)} ({df['time'].iloc[0]}..{df['time'].iloc[-1]})\n\n")
        for m in (m_is,m_oos):
            f.write(f"--- {m['label']} ---\n")
            for k,v in m.items():
                if not k.startswith("_") and k!="label": f.write(f"  {k}: {v}\n")
            f.write("\n")
        f.write("ROBUSTNESS (OOS):\n"+gdf.to_string(index=False)+f"\n\npositive expectancy {pos}/{len(gdf)}\n")
    print(f"\nОтчёт: {rp}")

    try:
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        fig,ax=plt.subplots(1,2,figsize=(13,4.5))
        for m,a in zip((m_is,m_oos),ax):
            if m.get("n",0)>0:
                a.plot(m["_eq"],lw=1.4); a.axhline(0,color="gray",ls="--",lw=.8)
                a.set_title(f"{m['label']} (n={m['n']}, exp={m['expectancy_%_per_trade']}%)")
                a.set_xlabel("сделка"); a.set_ylabel("эквити, %"); a.grid(alpha=.3)
        ttl="SYNTHETIC — не доказательство" if is_synth else f"{SYMBOL} {INTERVAL} {DATA_SOURCE}"
        fig.suptitle(f"Pifagor Fib — equity | {ttl}"); fig.tight_layout()
        ip=os.path.join(OUTDIR,"pifagor_equity.png"); fig.savefig(ip,dpi=110); print(f"График: {ip}")
    except Exception as e: print(f"(график не построен: {e})")

    print("\n"+"="*60); print("КАК ЧИТАТЬ:")
    print("""  ЭДЖ ЕСТЬ если: матожидание>0 на OOS + |t|>2 + плюс на большинстве
  комбинаций сетки + достаточно сделок. Иначе — эджа нет/подгонка.
  Даже плюс в бэктесте != прибыль в реале (проскальзывание, режим рынка).""")

if __name__=="__main__":
    main()
