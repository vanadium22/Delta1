"""Build-only equation rasterization; matplotlib is not a runtime dependency."""
from pathlib import Path
from matplotlib.mathtext import math_to_image
from matplotlib import rc_context

EQUATIONS={
 'A01':r'b=10^4\ln\!\left(\frac{F}{S}\right)\qquad a=\frac{365b}{100T}',
 'A02':r'P=\frac{100}{N}\left[\sum_i I(X_i<X_t)+\frac{1}{2}\sum_i I(X_i=X_t)\right]\qquad Z=\frac{X_t-\mu_{hist}}{s_{hist}}',
 'A03':r'g=X_0-X_{prev}\qquad d=X_\tau-X_0\qquad R=-\frac{d}{g}',
 'A04':r'\mu_{w,\tau}=\frac{\sum_{j\leq\tau} w_jX_j}{\sum_{j\leq\tau}w_j}\qquad D_\tau=X_\tau-\mu_{w,\tau}',
 'A05':r'P_X=\frac{\sum_iw_i\Delta X_i}{\sum_iw_i}\qquad w_i^{VOI}=\min(RVOL_i,3)\max\!\left(\frac{\Delta OI_i}{OI_{i-1}},0\right)',
 'A06':r'Q=\frac{V_t}{OI_{t-1}}\qquad K=\frac{OI_t-OI_{t-1}}{V_t}',
 'A07':r'\epsilon_t=y_t-\alpha-\beta x_t\qquad Z_{\epsilon,t}=\frac{\epsilon_t}{s_{\epsilon,train}}',
 'A08':r'E_k(X)=\frac{X_t-X_{t-k}}{\sum_i|\Delta X_i|}\qquad RV=10^4\sqrt{\sum_i r_i^2}',
 'A09':r'Event_\tau=I(streak_\tau=L)\qquad |Z_\tau|\geq 2,\quad L=3',
 'A10':r'F_{fair}=S\left[1+(r-q)\frac{T}{365}\right]\qquad e=10^4\frac{F-F_{fair}}{S}',
 'A11':r'Candidate_X=-sign(Z_X)\,I(\mathcal{C}_X)\qquad\mathcal{C}_X:\ |Z_X|\geq2,\ RVOL\geq1.5,\ |K|\leq0.05,\ |E_X|\leq0.5,\ stress\leq2',
 'A12':r'Nominal=F m\qquad BasisCash=(F-S)m',
 'B01':r'c=10^4\frac{F_n-F_f}{S}\qquad\ell=10^4\ln\!\left(\frac{F_n}{F_f}\right)\qquad a_{nf}=\frac{365\ell}{100\Delta T}',
 'B04':r'M=\min[\max(-\Delta OI_n,0),\max(\Delta OI_f,0)]\qquad R=\frac{100M}{OI_{n,prev}+OI_{f,prev}}',
 'B05':r'P_X=\frac{\sum_iw_i\Delta X_i}{\sum_iw_i}\qquad w_i=M_i\min(RVOL_{pair,i},3)',
 'B06':r'D_V=\ln\!\left(\frac{RVOL_n}{RVOL_f}\right)\qquad D_{CLV}=\frac{CLV_n-CLV_f}{2}',
 'B10':r'cap=\min\!\left(pV_u,\frac{pV_v}{h},qOI_u,\frac{qOI_v}{h}\right)',
 'C01':r'G=b_u-b_v\qquad G_a=a_u-a_v',
 'C03':r'10^4(R_{F_u,k}-\beta R_{F_v,k})=10^4(R_{S_u,k}-\beta R_{S_v,k})+\Delta_k b_u-\beta\Delta_k b_v',
 'C04':r'\beta=\frac{Cov(r_{S_v},r_{S_u})}{Var(r_{S_v})}\qquad h_\beta=\beta\frac{F_um_u}{F_vm_v}',
 'C05':r'\Delta P=\frac{\sum_iw_{u,i}\Delta X_{u,i}}{\sum_iw_{u,i}}-\frac{\sum_iw_{v,i}\Delta X_{v,i}}{\sum_iw_{v,i}}',
 'C06':r'g_p=100\ln\!\left(\frac{\sum_{m\in S}OI_{p,m,t}}{\sum_{m\in S}OI_{p,m,t-5}}\right)\qquad D_O=g_u-g_v',
 'C07':r'CLV=\frac{2C-H-L}{H-L}\qquad stress=\frac{TRbp_t}{median(TRbp_{hist})}',
}
for dst,src in {'B02':'A02','C02':'A02','B03':'A04','B07':'A08','C08':'A08','B08':'A07','C09':'A07','B09':'A11','C10':'B10'}.items():EQUATIONS[dst]=EQUATIONS[src]
def main():
    dest=Path(__file__).parent/'formula_assets';dest.mkdir(exist_ok=True)
    for theme,color in [('public','#17334f'),('private','#edeff3')]:
        with rc_context({'savefig.transparent':True}):
            for code,eq in EQUATIONS.items():math_to_image('$'+eq+'$',dest/f'{code}_{theme}.png',dpi=160,color=color,format='png')
    print('Built 64 static equation assets; no market data.')
if __name__=='__main__':main()
