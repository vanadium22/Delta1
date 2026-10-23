"""Display coordinates for A-share day sessions; timestamps remain authoritative."""
from bisect import bisect_left,bisect_right
from datetime import datetime,timedelta,timezone
import math

CHINA=timezone(timedelta(hours=8))
SESSIONS=((9*3600+30*60,11*3600+30*60),(13*3600,15*3600))


def session_at(timestamp):
    if not math.isfinite(float(timestamp)): return None
    stamp=datetime.fromtimestamp(float(timestamp),CHINA)
    seconds=stamp.hour*3600+stamp.minute*60+stamp.second+stamp.microsecond/1e6
    for index,(start,end) in enumerate(SESSIONS):
        if start<=seconds<=end: return stamp.date(),index,seconds-start
    return None


class TradingTimeMap:
    """One mapping per chart, shared by all curves, including missing observations.

    Dates come from observed trading dates. Within a day, the two complete
    session clocks preserve missing-bar gaps. Boundaries have one bar's width.
    """
    def __init__(self,timestamps=(),frequency="1m"):
        self.frequency=frequency;self.step={"1d":1.,"1m":60.,"1s":1.}[frequency]
        self.timestamps=sorted({float(t) for t in timestamps if math.isfinite(float(t)) and
            (frequency=="1d" or session_at(t) is not None)})
        self.lookup={};self.boundaries=[];self.positions=[];self.days=[]
        if frequency=="1d":
            self.days=sorted({datetime.fromtimestamp(t,CHINA).date() for t in self.timestamps})
            days={day:i for i,day in enumerate(self.days)}
            self.lookup={t:float(days[datetime.fromtimestamp(t,CHINA).date()]) for t in self.timestamps}
        else:
            self.days=sorted({session_at(t)[0] for t in self.timestamps})
            day_index={day:i for i,day in enumerate(self.days)}
            day_width=14400+2*self.step
            for stamp in self.timestamps:
                day,session,offset=session_at(stamp)
                self.lookup[stamp]=day_index[day]*day_width+session*(7200+self.step)+offset
            origin=min(self.lookup.values(),default=0.)
            self.lookup={t:x-origin for t,x in self.lookup.items()}
            end=max(self.lookup.values(),default=0.)
            for day,index in day_index.items():
                for x,title in ((index*day_width+7200+self.step/2,"午休"),
                                (index*day_width-self.step/2,day.strftime("%m-%d"))):
                    x-=origin
                    if 0<x<end: self.boundaries.append((x,title))
        self.positions=sorted((position,stamp) for stamp,position in self.lookup.items())
        self.xs=[p for p,_ in self.positions]

    def coordinate(self,timestamp):
        return self.lookup.get(float(timestamp))

    def nearest_time(self,position):
        if not self.positions: return None
        index=bisect_left(self.xs,position)
        candidates=self.positions[max(0,index-1):min(len(self.positions),index+1)]
        x,stamp=min(candidates,key=lambda item:abs(item[0]-position))
        if abs(x-position)>self.step*.55: return None
        return stamp

    def label(self,position,full=False):
        stamp=self.nearest_time(position)
        if stamp is None: return "缺数" if full else ""
        fmt="%Y-%m-%d" if self.frequency=="1d" else "%m-%d %H:%M:%S" if full else "%H:%M:%S" if self.frequency=="1s" else "%H:%M"
        return datetime.fromtimestamp(stamp,CHINA).strftime(fmt)

    def ticks(self,left,right,size):
        lo=bisect_left(self.xs,left);hi=bisect_right(self.xs,right)
        visible=self.positions[lo:hi]
        if not visible: return []
        stride=max(1,math.ceil(len(visible)/max(2,int(size/100))))
        return [p for p,_ in visible[::stride]]

    def project(self,xs,ys):
        output_x=[];output_y=[]
        for stamp,value in zip(xs,ys):
            x=self.coordinate(stamp)
            if x is not None: output_x.append(x);output_y.append(value)
        return output_x,output_y
