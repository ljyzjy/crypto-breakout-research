"""Compute the exit-slip break-even for already frozen linear scenarios."""
import hashlib,json
from pathlib import Path
H=Path(__file__).resolve().parent;P=H.parent;R59=P/'第五十九轮_退出滑点压力';R63=P/'第六十三轮_资金费门滑点压力'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    sources=[R59/'退出滑点压力对照.json',R59/'退出滑点压力独立核验.json',R63/'资金费门退出滑点压力.json',R63/'资金费门退出滑点独立核验.json',Path(__file__)]
    assert json.loads(sources[1].read_text(encoding='utf-8'))['all_checks_pass'] and json.loads(sources[3].read_text(encoding='utf-8'))['all_checks_pass']
    out=[]
    for name,path in [('base',sources[0]),('funding_gate',sources[2])]:
        data=json.loads(path.read_text(encoding='utf-8'))['rows']
        for row in data:
            v=row['scenarios'];assert len(v)==3 and [round(x['exit_slippage_pct'],6) for x in v]==[.05,.075,.1]
            slope=(v[1]['mean_net_pct_notional']-v[0]['mean_net_pct_notional'])/(.075-.05)
            assert slope<0 and abs((v[0]['mean_net_pct_notional']+slope*(.1-.05))-v[2]['mean_net_pct_notional'])<1e-10
            zero_slip_net=v[0]['mean_net_pct_notional']-slope*.05;break_even=.05-v[0]['mean_net_pct_notional']/slope
            out.append({'strategy':name,'year':row['year'],'leverage':row['leverage'],'trades':v[0]['trades'],'unknown':v[0]['unknown'],
                'exit_slip_base_pct':.05,'base_mean_net_pct_notional':v[0]['mean_net_pct_notional'],
                'zero_exit_slip_mean_net_pct_notional':zero_slip_net,
                'conditional_break_even_exit_slip_pct':break_even if break_even>=0 else None,
                'negative_break_even_impossible_under_nonnegative_adverse_slip':break_even<0})
    result={'rows':out,'source_sha256':{str(p):sha(p) for p in sources},
            'note':'Ex-post arithmetic with entry, triggers, funding and timestamps frozen; no observed market execution or account results.'}
    (H/'退出滑点盈亏临界.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print('BREAKEVEN65',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
