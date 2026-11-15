"""Apply fixed-pool hourly ranks and the previous BTC/ETH bar condition."""
import hashlib,json,sys
from collections import Counter
from pathlib import Path
import pandas as pd
H=Path(__file__).resolve().parent;P=H.parent;Q=900_000;DAY=86_400_000
sys.path.insert(0,str(P/'第四十轮_BTC_ETH事前活跃度'))
from market_decisions import classify
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    frozen=json.loads((H/'小块来源冻结哈希.json').read_text(encoding='utf-8'))
    assert sha(H/'冻结研究方案.md')==frozen['plan_sha256']
    assert json.loads((H/'小块算法一致性核验.json').read_text(encoding='utf-8'))['all_checks_pass']
    summary=[]
    for year in (2024,2026):
        out=H/str(year);raw=pd.read_parquet(out/'固定十一币潜在分钟候选.parquet');top=pd.read_parquet(out/'固定十一币已知小时排名.parquet')
        bars=pd.read_parquet(out/'BTC_ETH一分钟合成十五分钟.parquet')
        lookup={(x['symbol'],int(x['open_time'])):x for x in bars.to_dict('records')}
        assert raw.observation_id.is_unique and not top.duplicated(['decision_hour','symbol','side']).any()
        ranks={(int(r.decision_hour),r.symbol,int(r.side)):{'score':float(r.score),'rvol':float(r.rvol),
                'rank':int(r.hourly_rank),'liquidity_rank':int(r.liquidity_rank)} for r in top.itertuples(index=False)}
        qs=sorted(set(map(int,raw.quarter_start)));market={q:classify(q,lookup,set()) for q in qs}
        output=[];counts=Counter()
        for e in raw.to_dict('records'):
            hour=int(e['trigger_minute'])//3_600_000*3_600_000;both=market[int(e['quarter_start'])]
            for side,name in ((1,'long'),(-1,'short')):
                details=ranks.get((hour,e['symbol'],side));eligible=bool(e[name+'_pre_rank'] and details is not None)
                if eligible:e[name+'_spec']=json.dumps({**json.loads(e[name+'_spec']),**details},ensure_ascii=False)
                allowed=both['market_status']=='market_unknown' or (both['market_status']=='allowed' and both['allowed_side']==side)
                e[name+'_known_eligible']=bool(eligible and allowed)
                if not e[name+'_known_eligible']:e[name+'_spec']='null'
            if e['long_known_eligible'] or e['short_known_eligible']:
                e['market_prior_status']=both['market_status'];e['market_allowed_side']=both['allowed_side']
                e['needs_next']=bool((int(e['quarter_end'])+60_000-1)//DAY>int(e['trigger_minute'])//DAY)
                output.append(e);counts[both['market_status']]+=1
            else:counts['filtered_before_tick']+=1
        d=pd.DataFrame(output).sort_values(['trigger_minute','symbol']).reset_index(drop=True)
        assert d.observation_id.is_unique and not d.duplicated(['symbol','quarter_start']).any()
        d.to_parquet(out/'固定十一币双币过滤潜在触价.parquet',index=False)
        result={'year':year,'raw_potential_events':len(raw),'hourly_rank_rows':len(top),'post_hour_and_market_candidates':len(d),
                'candidate_market_statuses':d.market_prior_status.value_counts().to_dict(),'unique_raw_quarters':len(qs),
                'market_quarter_statuses':dict(Counter(v['market_status'] for v in market.values())),
                'source_hashes':{'raw':sha(out/'固定十一币潜在分钟候选.parquet'),'ranks':sha(out/'固定十一币已知小时排名.parquet'),
                                 'market':sha(out/'BTC_ETH一分钟合成十五分钟.parquet'),'candidates':sha(out/'固定十一币双币过滤潜在触价.parquet')},
                'note':'Causal candidate locations only; no inferred tick direction, order or PnL.'}
        (out/'双币过滤候选质量.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');summary.append(result)
        print('FIXED11_46_CANDIDATES',json.dumps(result,ensure_ascii=False),flush=True)
    (H/'跨期双币候选质量.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
if __name__=='__main__':main()
