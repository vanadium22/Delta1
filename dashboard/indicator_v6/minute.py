"""Session-aware minute calculation; cumulative state retains the morning."""
from .core import *


def compute(rows,grid,t,gap,previous=None,previous_t=None):
    values=[];xs={k:[] for k in ('b','a','cal','l','ac')};wf=[];wb=[]
    segments={};rf_all=[];rn_all=[];rs_all=[]
    for i,meta in enumerate(grid):
        row=rows.get(meta['timestamp'],{})
        f,n,s=(raw(row.get(k),'price') for k in ('F','N','S'))
        if t is not None and t<0:f=invalid('EXPIRED')
        if t is not None and gap is not None and t-gap<0:n=invalid('EXPIRED')
        vf,vn=(raw(row.get(k),'quantity') for k in ('V','VN'))
        d={**basis(f,s,t),**calendar(n,f,s,gap)}
        if not row:
            d={k:invalid('WINDOW_GAP','INPUT_MISSING') for k in d}
            vf=vn=invalid('WINDOW_GAP','INPUT_MISSING')
        for key in xs:xs[key].append(d[key])
        wf.append(vf);wb.append(minimum(vf,vn))
        for key,x in xs.items():
            w=wf if key in ('b','a') else wb
            tag='c' if key=='cal' else key
            d['center_'+tag]=weighted(x,w)
            d['D_'+tag]=x[-1]-d['center_'+tag]
        for key in ('b','a'):
            old=(previous or {}).get(key,invalid('INPUT_MISSING'))
            d['gap_'+key]=xs[key][0]-old;d['intra_'+key]=xs[key][-1]-xs[key][0]
            threshold=2 if key=='b' else 2*365/(100*t) if t is not None and t>=5 else None
            g=d['gap_'+key]
            d['repair_'+key]=failed([g,d['intra_'+key]]) or (invalid('GAP_SMALL') if threshold is None or abs(g.value)<threshold else -d['intra_'+key]/g)
        session=meta['session_id'];seg=segments.setdefault(session,dict(F=[],N=[],S=[],cal=[],a=[],ac=[]))
        for key,val in [('F',f),('N',n),('S',s),('cal',d['cal']),('a',d['a']),('ac',d['ac'])]:seg[key].append(val)
        rf,rn,rs=(returns(seg[k]) for k in ('F','N','S'));j=len(rf)-1
        for prefix,y,x in [('A',rf,rs),('B',rn,rf)]:
            reg=regression(y,x,j)
            d[prefix+'_minbeta']=reg['beta'];d[prefix+'_resid']=reg['resid'];d[prefix+'_resid_z']=reg['z']
        d['A_rv30']=volatility(rf,j);d['B_rv30']=volatility([a-b for a,b in zip(rn,rf)],j)
        for key,target in [('cal','B_c_rv30'),('a','A_arv30'),('ac','B_acrv30')]:
            x=seg[key];delta=[invalid('WARMUP')]+[b-a for a,b in zip(x,x[1:])]
            d[target]=volatility(delta,j,30,1)
        values.append(d)
    sessions=[r['session_id'] for r in grid]
    for key,x in xs.items():
        tag='c' if key=='cal' else key
        events,zs=confirmation(x,sessions)
        for i,((event,count),z) in enumerate(zip(events,zs)):
            values[i]['event_'+tag]=event;values[i]['count_'+tag]=count;values[i]['z_'+tag]=z
        valid=all(v.value is not None for v in x)
        final=events[-1][1] if events else invalid('WARMUP')
        # Expected length comes from the configured grid, not a literal 240.
        daily=final if valid else invalid('INCOMPLETE_DAY',*tuple(dict.fromkeys(r for v in x for r in v.reasons)))
        for d in values:d['events_'+tag]=daily
    return values
