"""Pure arithmetic with field-level validity. No I/O, forward filling or zero sentinels."""
from dataclasses import dataclass
import math
import statistics as st


@dataclass(frozen=True)
class Value:
    value: float | None
    reasons: tuple = ()

    def __post_init__(self):
        if self.value is not None and (isinstance(self.value, bool) or not math.isfinite(self.value)):
            raise ValueError('Output must be finite or null')
        if self.value is None and not self.reasons:
            raise ValueError('Null needs a reason')

    def __add__(self, other): return calc(lambda a,b:a+b, self, as_value(other))
    def __radd__(self, other): return self + other
    def __sub__(self, other): return calc(lambda a,b:a-b, self, as_value(other))
    def __rsub__(self, other): return as_value(other) - self
    def __mul__(self, other): return calc(lambda a,b:a*b, self, as_value(other))
    def __rmul__(self, other): return self * other
    def __truediv__(self, other):
        other = as_value(other)
        return invalid('DENOM_ZERO') if other.value == 0 and self.value is not None else calc(lambda a,b:a/b,self,other)
    def __rtruediv__(self,other):return as_value(other)/self
    def __neg__(self): return self * -1

    def json(self):
        return dict(value=self.value, status='VALID' if self.value is not None else 'INVALID', reason_codes=list(self.reasons))


def invalid(*reasons): return Value(None, tuple(dict.fromkeys(reasons)))
def as_value(v): return v if isinstance(v,Value) else raw(v)
def raw(v, kind=None):
    if v is None or isinstance(v,bool): return invalid('INPUT_MISSING')
    try: v=float(v)
    except (ValueError,TypeError): return invalid('INPUT_MISSING')
    if not math.isfinite(v): return invalid('INPUT_MISSING')
    if kind=='price' and v<=0: return invalid('PRICE_INVALID')
    if kind=='quantity' and v<0: return invalid('DATA_ANOMALY')
    if kind=='parameter' and v<=0: return invalid('PARAM_INVALID')
    return Value(v)
def failed(values):
    rs=tuple(dict.fromkeys(r for v in values if v.value is None for r in v.reasons))
    return invalid('DEPENDENCY_NULL',*rs) if rs else None
def calc(fn,*values):
    bad=failed(values)
    if bad is not None:return bad
    try:return raw(fn(*(v.value for v in values)))
    except (ValueError,ZeroDivisionError,OverflowError):return invalid('DENOM_ZERO')
def log(v): return calc(math.log,v)
def positive(v,reason='DENOM_ZERO'):
    return invalid(reason) if v.value is not None and v.value<=0 else v
def minimum(*v): return calc(min,*v)
def maximum(*v): return calc(max,*v)
def total(v): return calc(lambda *x:sum(x),*v) if v else invalid('INPUT_MISSING')
def window(seq,i,n,prior=False):
    end=i if prior else i+1
    if end<n:return [invalid('WARMUP')]
    return seq[end-n:end]
def statistic(x,i,n=20):
    hist=window(x,i,n,True);bad=failed([x[i],*hist])
    if bad:return bad,bad
    h=[v.value for v in hist];v=x[i].value
    pct=Value(100*(sum(a<v for a in h)+.5*sum(a==v for a in h))/n)
    sigma=st.stdev(h) if n>1 else 0
    return pct,Value((v-st.mean(h))/sigma) if sigma>0 else invalid('STD_ZERO')
def change(x,i,k=5):
    w=window(x,i,k+1);bad=failed(w)
    return bad if bad else w[-1]-w[0]
def efficiency(x,i,k=5):
    w=window(x,i,k+1);bad=failed(w)
    if bad:return bad
    den=sum(abs(b.value-a.value) for a,b in zip(w,w[1:]))
    return Value((w[-1].value-w[0].value)/den) if den else invalid('FLAT_PATH')
def weighted(deltas,weights):
    bad=failed([*deltas,*weights])
    if bad:return bad
    if any(w.value<0 for w in weights):return invalid('DATA_ANOMALY')
    den=sum(w.value for w in weights)
    return Value(sum(d.value*w.value for d,w in zip(deltas,weights))/den) if den else invalid('NO_WEIGHT')
def advance(x,w,i,k=5):
    xs=window(x,i,k+1);ws=window(w,i,k);bad=failed([*xs,*ws])
    return bad if bad else weighted([b-a for a,b in zip(xs,xs[1:])],ws)
def rvol(v,i,n=20):
    hist=window(v,i,n,True)
    return v[i]/positive(calc(lambda *h:st.median(h),*hist))
def volatility(returns,i,n=30,scale=10000):
    return calc(lambda *r:scale*math.sqrt(sum(x*x for x in r)),*window(returns,i,n))
def returns(prices):
    return [invalid('WARMUP')]+[log(b/a) for a,b in zip(prices,prices[1:])]
def regression(y,x,i,m=30,var_epsilon=1e-20,residual_epsilon=1e-12,scale=10000):
    ys=window(y,i,m,True);xs=window(x,i,m,True);bad=failed([*ys,*xs])
    if bad:return dict(beta=bad,resid=bad,z=bad,r2=bad)
    xx=[v.value for v in xs];yy=[v.value for v in ys]
    vx=st.variance(xx);vy=st.variance(yy)
    if vx<=var_epsilon:
        bad=invalid('REG_DEGENERATE');return dict(beta=bad,resid=bad,z=bad,r2=bad)
    mx,my=st.mean(xx),st.mean(yy)
    cov=sum((a-mx)*(b-my) for a,b in zip(xx,yy))/(m-1)
    beta=cov/vx;alpha=my-beta*mx
    sigma=st.stdev([b-alpha-beta*a for a,b in zip(xx,yy)])
    e=y[i]-alpha-beta*x[i]
    return dict(beta=Value(beta),resid=e*scale,z=e/sigma if sigma>residual_epsilon else invalid('STD_ZERO'),
                r2=Value(cov*cov/vx/vy) if vy>0 else invalid('STD_ZERO'))
def candidate(z,rv,k,e,stress):
    deps=[z,e,*rv,*k,*stress];bad=failed(deps)
    if bad:return bad
    yes=abs(z.value)>=2 and min(v.value for v in rv)>=1.5 and max(abs(v.value) for v in k)<=.05 and abs(e.value)<=.5 and max(v.value for v in stress)<=2
    return Value(-math.copysign(1,z.value) if yes else 0)
def capacity(vu,vv,ou,ov,h,p=.01,q=.001):
    if not 0<=p<=1 or not 0<=q<=1:return invalid('PARAM_INVALID'),invalid('PARAM_INVALID'),invalid('PARAM_INVALID')
    h=positive(h,'BETA_NONPOS');cv=minimum(vu*p,vv*p/h);co=minimum(ou*q,ov*q/h)
    return cv,co,minimum(cv,co)
def basis(f,s,t):
    b=10000*log(f/s)
    a=invalid('PARAM_MISSING') if t is None else invalid('EXPIRED') if t<0 else invalid('DTE_LT5') if t<5 else b*365/(100*t)
    if t is not None and t<0:f=s=invalid('EXPIRED');b=invalid('EXPIRED')
    return dict(points=f-s,B=10000*(f/s-1),b=b,a=a)
def calendar(fn,ff,s,gap,valid_pair=True):
    if not valid_pair or gap is None or gap<=0:
        return {k:invalid('PAIR_MISMATCH') for k in ('cal_points','cal','l','ac')}
    l=10000*log(fn/ff)
    return dict(cal_points=fn-ff,cal=10000*(fn-ff)/s,l=l,ac=l*365/(100*gap))
def cross(u,v,paired=True):
    return dict(G=u['b']-v['b'],Ga=u['a']-v['a']) if paired else dict(G=invalid('PAIR_MISMATCH'),Ga=invalid('PAIR_MISMATCH'))


def minute_grid(day,sessions):
    from datetime import datetime,timedelta
    result=[]
    for s in sessions:
        t=datetime.fromisoformat(day+'T'+s['first_end']);end=datetime.fromisoformat(day+'T'+s['last_end'])
        while t<=end:
            result.append(dict(timestamp=t.isoformat()+'+08:00',trading_date=day,session_id=s['id'],trade_minute_index=len(result)))
            t+=timedelta(minutes=1)
    return result


def confirmation(xs,sessions,n=30,length=3,threshold=2):
    out=[];zs=[];segment=[];count=0;streak=0;lastside=0;validrun=0;previous=None
    for x,session in zip(xs,sessions):
        if session!=previous:segment=[];streak=lastside=validrun=0
        previous=session;segment.append(x);_,z=statistic(segment,len(segment)-1,n);zs.append(z)
        if z.value is None:
            streak=lastside=validrun=0;event=z
        else:
            validrun+=1;side=int(math.copysign(1,z.value)) if abs(z.value)>=threshold else 0
            streak=streak+1 if side and side==lastside else 1 if side else 0;lastside=side
            event=Value(float(streak==length)) if validrun>=length else invalid('WARMUP')
            if event.value==1:count+=1
        out.append((event,Value(count) if event.value is not None else event))
    return out,zs
