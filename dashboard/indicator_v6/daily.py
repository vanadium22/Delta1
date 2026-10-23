"""Daily edition-six calculation on a specific contract or fixed pair's calendar."""
from datetime import date
from .core import *


def single(rows,days,expiry,multiplier):
    cols={k:[raw(r.get(k),'quantity' if k in ('volume','oi') else 'price') for r in rows]
          for k in ('open','high','low','close','spot','volume','oi')}
    for i,row in enumerate(rows):
        for key in cols:
            if (key=='spot' and row.get('_spot_missing')) or (key!='spot' and row.get('_missing_row')):
                cols[key][i]=invalid('WINDOW_GAP','INPUT_MISSING')
    f,s,v,oi=(cols[k] for k in ('close','spot','volume','oi'))
    out=[];tr=[];w=[];wo=[];bs=[];aa=[]
    rf,rs=returns(f),returns(s)
    for i,day in enumerate(days):
        t=(date.fromisoformat(expiry)-date.fromisoformat(day)).days if expiry else None
        d=basis(f[i],s[i],t);bs.append(d['b']);aa.append(d['a'])
        previous=oi[i-1] if i else invalid('WARMUP');doi=oi[i]-previous
        d.update(T=t,volume=v[i],oi=oi[i],oi_prev=previous,close=f[i],spot=s[i],rF=rf[i],rS=rs[i],doi=doi)
        d['Q']=v[i]/positive(previous);d['K']=doi/positive(v[i])
        if doi.value is not None and v[i].value is not None and abs(doi.value)>v[i].value:d['K']=invalid('DATA_ANOMALY')
        d['rvol']=rvol(v,i)
        wo.append(maximum(doi,Value(0)));w.append(minimum(d['rvol'],Value(3))*maximum(doi/positive(previous),Value(0)))
        o,h,l,c=(cols[k][i] for k in ('open','high','low','close'))
        ohlc_bad=failed([o,h,l,c])
        if not ohlc_bad and (h.value<max(o.value,c.value) or l.value>min(o.value,c.value) or h.value<l.value):ohlc_bad=invalid('DATA_ANOMALY')
        d['clv']=ohlc_bad or ((2*c-h-l)/positive(h-l,'OHLC_FLAT'))
        cp=f[i-1] if i else invalid('WARMUP')
        tr.append(ohlc_bad or 10000*maximum(h-l,calc(abs,h-cp),calc(abs,l-cp))/cp)
        d['stress']=tr[i]/positive(calc(lambda *x:st.median(x),*window(tr,i,20,True)))
        for key,x in [('b',bs),('a',aa)]:
            d[key+'_pct'],d[key+'_z']=statistic(x,i)
            d[key+'_d5']=change(x,i);d[key+'_E']=efficiency(x,i)
            d['P' if key=='b' else 'Pa']=advance(x,wo,i)
            d['C1' if key=='b' else 'Wa']=advance(x,w,i)
            d['C2' if key=='b' else 'candidate_a']=candidate(d[key+'_z'],[d['rvol']],[d['K']],d[key+'_E'],[d['stress']])
        # Model parameters are explicit fixed research scenarios, never inferred market rates.
        d['fair']=s[i]*(1+(.02-.03)*t/365) if t is not None else invalid('PARAM_MISSING')
        d['fair']=positive(d['fair'],'PRICE_INVALID')
        d['fair_dev']=10000*(f[i]-d['fair'])/s[i]
        d['fair_space']=calc(abs,d['fair_dev'])-5
        d['space_short']=d['fair_dev']-5;d['space_long']=-d['fair_dev']-5
        for target,base in [('annual_model_gap','fair_dev'),('annual_space','fair_space'),('annual_short','space_short'),('annual_long','space_long')]:
            d[target]=invalid('PARAM_MISSING') if t is None else invalid('DTE_LT5') if t<5 else d[base]*365/(100*t)
        mult=raw(multiplier,'parameter') if multiplier is not None else invalid('PARAM_MISSING')
        d['nominal']=f[i]*mult/10000;d['basis_cash']=(f[i]-s[i])*mult
        out.append(d)
    return out


def pair(near,far,days,expiry_n,expiry_f,same_root=True):
    gap=(date.fromisoformat(expiry_f)-date.fromisoformat(expiry_n)).days if expiry_n and expiry_f else None
    xs={k:[] for k in ('cal','l','ac')};vol=[];weights=[];out=[]
    for i,(n,f) in enumerate(zip(near,far)):
        d=calendar(n['close'],f['close'],f['spot'],gap,same_root)
        if n['T'] is not None and n['T']<0 or f['T'] is not None and f['T']<0:
            d={k:invalid('EXPIRED') for k in d}
        for key in xs:xs[key].append(d[key])
        dn,df=n['doi'],f['doi'];den=n['oi_prev']+f['oi_prev']
        d['M']=minimum(maximum(-dn,Value(0)),maximum(df,Value(0)))
        d['R']=100*d['M']/positive(den);d['N']=100*(dn+df)/positive(den)
        vol.append(n['volume']+f['volume'])
        d['share_diff']=100*(f['volume']/positive(vol[-1])-f['oi_prev']/positive(den))
        weights.append(d['M']*minimum(rvol(vol,i),Value(3)))
        d['C3_weight5']=total(window(weights,i,5))
        for key,x in xs.items():
            d[key+'_pct'],d[key+'_z']=statistic(x,i)
            d[key+'_d5']=change(x,i);d[key+'_E']=efficiency(x,i)
            d[{'cal':'C3','l':'P_l','ac':'P_ac'}[key]]=advance(x,weights,i)
            d['candidate_'+key]=candidate(d[key+'_z'],[n['rvol'],f['rvol']],[n['K'],f['K']],d[key+'_E'],[n['stress'],f['stress']])
        d['B_rvol_diff']=log(positive(n['rvol'])/positive(f['rvol']));d['B_clv']=(n['clv']-f['clv'])/2
        cv,co,cap=capacity(n['volume'],f['volume'],n['oi'],f['oi'],Value(1))
        d.update(B_volume_cap=cv,B_cap=cap,B_integer=calc(math.floor,cap))
        out.append(d)
    return out


def cross_pair(u,v,days,expiry_u,expiry_v,m_u=300,m_v=200,valid_pair=True):
    xs={k:[] for k in ('G','Ga')};out=[]
    yf=[r['rF'] for r in u];xf=[r['rF'] for r in v]
    ys=[r['rS'] for r in u];xx=[r['rS'] for r in v]
    fr=[a-b for a,b in zip(yf,xf)];gd=[];gad=[]
    for i,(a,b) in enumerate(zip(u,v)):
        paired=bool(valid_pair and expiry_u and expiry_v and expiry_u==expiry_v)
        d=cross(a,b,paired)
        for key in xs:xs[key].append(d[key])
        for key,x in xs.items():
            d[key+'_pct'],d[key+'_z']=statistic(x,i)
            d[key+'_d5']=change(x,i);d[key+'_E']=efficiency(x,i)
            d['candidate_'+key]=candidate(d[key+'_z'],[a['rvol'],b['rvol']],[a['K'],b['K']],d[key+'_E'],[a['stress'],b['stress']])
        gd.append(xs['G'][i]-xs['G'][i-1] if i else invalid('WARMUP'))
        gad.append(xs['Ga'][i]-xs['Ga'][i-1] if i else invalid('WARMUP'))
        d['C_vol20']=volatility(fr,i,20);d['C_Gvol20']=volatility(gd,i,20,1);d['C_Gavol20']=volatility(gad,i,20,1)
        index=regression(ys,xx,i,60);d['index_beta']=index['beta'];d['index_r2']=index['r2']
        d['h_equal']=a['close']*raw(m_u,'parameter')/(b['close']*raw(m_v,'parameter'))
        d['h_beta']=positive(index['beta'],'BETA_NONPOS')*d['h_equal']
        d['integer_residual']=positive(index['beta'],'BETA_NONPOS')-1/(2*d['h_equal'])
        reg=regression(yf,xf,i,60);d.update(C_regbeta=reg['beta'],C_resid=reg['resid'],C_resid_z=reg['z'])
        def ret(rows,key):
            w=window([r[key] for r in rows],i,6);bad=failed(w)
            return bad if bad else 10000*log(w[-1]/w[0])
        fu,fv,su,sv=ret(u,'close'),ret(v,'close'),ret(u,'spot'),ret(v,'spot')
        d['fret5']=fu-fv;d['sret5']=su-sv
        d['weighted_futures5']=fu-index['beta']*fv;d['weighted_spot5']=su-index['beta']*sv
        d['weighted_basis5']=(fu-su)-index['beta']*(fv-sv)
        # Annual attribution is explicitly restored per endpoint, not delta Ga.
        restored=[r['Ga']*(100*u[j]['T']/365) if u[j]['T'] is not None else invalid('PARAM_MISSING') for j,r in enumerate(out+[d])]
        d['restored_basis5']=change(restored,i)
        d.update(C1=a['C1'],IC_C1=b['C1'],C4=a['C1']-b['C1'],C_Wu=a['Wa'],C_Wv=b['Wa'],C_Wa=a['Wa']-b['Wa'],
                 clv_diff=(a['clv']-b['clv'])/2,stress=a['stress'],IC_stress=b['stress'],rvol_diff=log(positive(a['rvol'])/positive(b['rvol'])))
        cv,co,cap=capacity(a['volume'],b['volume'],a['oi'],b['oi'],d['h_beta'])
        d.update(capV_A=cv,capOI_A=co,C6=cap,C6_B=d['h_beta']*cap)
        if not paired:d={k:invalid('PAIR_MISMATCH') for k in d}
        out.append(d)
    return out


def collection_growth(day,i,days,root,contracts,raw_rows):
    selected=[s for s,r in contracts.items() if s.startswith(root) and r['listing']<=day<=r['expiry']]
    def oi_at(stamp):return total([raw(raw_rows.get((s,stamp),{}).get('oi'),'quantity') for s in selected])
    now=oi_at(day)
    if i<5:return now,invalid('WARMUP'),selected
    if any(contracts[s]['expiry']<=day for s in selected):return now,invalid('EXPIRED'),selected
    if any(contracts[s]['listing']>days[i-5] for s in selected):return now,invalid('WINDOW_GAP'),selected
    return now,100*log(positive(now)/positive(oi_at(days[i-5]))),selected
