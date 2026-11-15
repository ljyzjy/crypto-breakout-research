"""Attribute strict residual-window unavailability without returns/labels."""
from pathlib import Path
from datetime import datetime,timezone
import sys,json,hashlib
import pandas as pd
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent
sys.path.insert(0,str(ROOT))
import data_io
H=3_600_000;M=60_000
lo=int(pd.Timestamp('2025-01-01',tz='UTC').timestamp()*1000)
hi=int(pd.Timestamp('2026-04-27',tz='UTC').timestamp()*1000)
btc=pd.read_parquet(HERE/'hourly/BTCUSDT.parquet').set_index('ts',drop=False)
old=pd.read_parquet(HERE/'matched_legacy_hours.parquet')
out=[];by_symbol=[]
for symbol,g in old[old.contract.ne('BTCUSDT')].groupby('symbol',sort=True):
    h=pd.read_parquet(HERE/'hourly'/f'{symbol}.parquet').set_index('ts',drop=False)
    ownbad=~np.isfinite(h.hourly_return)
    btcbad=~np.isfinite(btc.hourly_return.reindex(h.index))
    ownn=ownbad.astype(int).rolling(720,min_periods=720).sum().shift(6)
    btcn=btcbad.astype(int).rolling(720,min_periods=720).sum().shift(6)
    pairn=(ownbad|btcbad).astype(int).rolling(720,min_periods=720).sum().shift(6)
    sharedn=(ownbad&btcbad).astype(int).rolling(720,min_periods=720).sum().shift(6)
    ownex=(ownbad&~btcbad).astype(int).rolling(720,min_periods=720).sum().shift(6)
    btcex=(btcbad&~ownbad).astype(int).rolling(720,min_periods=720).sum().shift(6)
    keys=g.ts.to_numpy()
    z=pd.DataFrame({'ts':keys,'symbol':symbol,
       'own_invalid_returns_in_fit':ownn.reindex(keys).to_numpy(),
       'btc_invalid_returns_in_fit':btcn.reindex(keys).to_numpy(),
       'pair_invalid_returns_in_fit':pairn.reindex(keys).to_numpy(),
       'shared_same_hour_invalid_returns_in_fit':sharedn.reindex(keys).to_numpy(),
       'own_only_invalid_hour_count_in_fit':ownex.reindex(keys).to_numpy(),
       'BTC_only_invalid_hour_count_in_fit':btcex.reindex(keys).to_numpy(),
       'new_residual_available':g.new_residual6.notna().to_numpy(),
       'old_residual_available':g.residual_score.notna().to_numpy()})
    z['fit_failure_attribution']=np.select([
        z.pair_invalid_returns_in_fit.isna(),
        z.pair_invalid_returns_in_fit.eq(0),
        z.own_invalid_returns_in_fit.eq(0)&z.btc_invalid_returns_in_fit.gt(0),
        z.own_invalid_returns_in_fit.gt(0)&z.btc_invalid_returns_in_fit.eq(0),
        z.own_invalid_returns_in_fit.gt(0)&z.btc_invalid_returns_in_fit.gt(0)],
        ['insufficient_calendar_window','fit_window_valid','BTC_only','own_coin_only','both'],default='unclassified')
    assert np.array_equal(z.pair_invalid_returns_in_fit.to_numpy(),720-h.regression_pairs.reindex(keys).to_numpy(),equal_nan=True)
    by_symbol.append({'symbol':symbol,'rows':len(z),'fit_attribution':{str(k):int(v) for k,v in z.fit_failure_attribution.value_counts().items()}})
    out.append(z)
out=pd.concat(out,ignore_index=True)
counts={str(k):int(v) for k,v in out.fit_failure_attribution.value_counts().items()}
for cat in ['BTC_only','own_coin_only','both','fit_window_valid','insufficient_calendar_window','unclassified']:
    counts.setdefault(cat,0)
assert sum(counts.get(k,0) for k in ('BTC_only','own_coin_only','both'))==38698

bad_hours=btc.loc[(btc.ts>=lo-32*24*H)&(btc.ts<hi)&~btc.hour_valid.fillna(False)].copy()
raw=data_io.load_minutes('BTCUSDT',start_ms=int(bad_hours.ts.min()-H),end_ms=int(bad_hours.ts.max()))
minute_sources=[]
for t in bad_hours.ts:
    minute=raw[(raw.ts>=t-H)&(raw.ts<t)]
    bad=minute[(minute.volume<=0)|(minute.quote_volume<=0)|~np.isfinite(minute[['open','high','low','close','volume','quote_volume']]).all(axis=1)]
    minute_sources.append({'hour_close_ms':int(t),'hour_close_utc':pd.Timestamp(t,unit='ms',tz='UTC').isoformat(),
        'observed_minutes':len(minute),'zero_or_invalid_minutes':len(bad),
        'minute_records':[{'open_ms':int(r.ts),'open_utc':pd.Timestamp(r.ts,unit='ms',tz='UTC').isoformat(),
            'volume':float(r.volume),'quote_volume':float(r.quote_volume),'trade_count':int(r.trade_count)} for r in bad.itertuples()]})

def intervals(ms_values,step=H):
    values=sorted(set(map(int,ms_values)))
    if not values:return []
    groups=[];a=last=values[0]
    for v in values[1:]:
        if v-last!=step:groups.append((a,last));a=v
        last=v
    groups.append((a,last))
    return [{'start_utc':pd.Timestamp(a,unit='ms',tz='UTC').isoformat(),
             'last_included_utc':pd.Timestamp(b,unit='ms',tz='UTC').isoformat(),
             'points':int((b-a)//step+1)} for a,b in groups]

dates=pd.date_range('2025-01-01','2026-04-26',tz='UTC')
mask=pd.read_parquet(ROOT/'matched_samples/F1-mask.parquet')
mask['day']=pd.to_datetime(mask.decision_ts,unit='ms',utc=True).dt.floor('D')
has_f1=mask.groupby('day').included.any().reindex(dates,fill_value=False)
out['day']=pd.to_datetime(out.ts,unit='ms',utc=True).dt.floor('D')
has_res=out.groupby('day').new_residual_available.any().reindex(dates,fill_value=False)
common_btc=btc.hourly_return.isna().astype(int).rolling(720,min_periods=720).sum().shift(6)
btc_blocked=btc.loc[(btc.ts>=lo)&(btc.ts<hi)&common_btc.gt(0),'ts']
recent_btc=btc.hourly_return.isna().astype(int).rolling(6,min_periods=6).sum()
btc_recent_bad=btc.loc[(btc.ts>=lo)&(btc.ts<hi)&recent_btc.gt(0),'ts']
bad_return_hours=btc.loc[(btc.ts>=lo)&(btc.ts<hi)&btc.hourly_return.isna(),'ts']
blank_dates=[str(x.date()) for x in dates[~has_f1]]
summary={'utc':datetime.now(timezone.utc).isoformat(),'rows_non_btc_exact_old_index':len(out),
  'fit_failure_total':38698,'fit_failure_attribution_counts':counts,
  'residual_missing_total':int((~out.new_residual_available).sum()),
  'additional_missing_with_valid_fit':int((~out.new_residual_available&out.fit_failure_attribution.eq('fit_window_valid')).sum()),
  'btc_invalid_closed_hours':minute_sources,
  'btc_invalid_closed_hours_count':len(minute_sources),
  'btc_source_zero_or_invalid_minute_count':sum(x['zero_or_invalid_minutes'] for x in minute_sources),
  'both_bad_fit_rows_with_shared_same_invalid_hour':int((out.fit_failure_attribution.eq('both')&out.shared_same_hour_invalid_returns_in_fit.gt(0)).sum()),
  'both_bad_fit_rows_without_shared_same_invalid_hour':int((out.fit_failure_attribution.eq('both')&out.shared_same_hour_invalid_returns_in_fit.eq(0)).sum()),
  'btc_invalid_hourly_returns_utc':[pd.Timestamp(t,unit='ms',tz='UTC').isoformat() for t in bad_return_hours],
  'btc_reference_fit_unavailable_hour_count':len(btc_blocked),
  'btc_reference_fit_unavailable_intervals':intervals(btc_blocked),
  'btc_recent6_unavailable_intervals':intervals(btc_recent_bad),
  'F1_clock_active_days':int(has_f1.sum()),'F1_clock_blank_days':int((~has_f1).sum()),
  'F1_clock_blank_day_dates':blank_dates,
  'F1_clock_blank_day_intervals':intervals(dates[~has_f1].as_unit('ms').asi8,24*H),
  'all_non_btc_legacy_residual_blank_days':int((~has_res).sum()),
  'all_non_btc_legacy_residual_blank_day_dates':[str(x.date()) for x in dates[~has_res]],
  'by_symbol':by_symbol,
  'interpretation':['Rows classified both contain some invalid BTC and some invalid own-coin hourly returns inside the fit window; these are overlapping causes, not additive economic loss contributions.',
   'Four invalid BTC closed hours are source zero-volume observations, not absent minute records; each also invalidates the next hourly close-to-close return.',
   'A single invalid return fails a strict720-hour window for up to720 successive future fit positions after the fixed6-hour delay. This shared reference issue can disable residuals across all coins simultaneously.',
   'BTC-only fit failures are zero in this panel: every observation with an invalid BTC fit window also has an invalid own-coin fit window. Repairing BTC alone would not restore those rows under unchanged own-coin validity. The common blank periods reflect shared validity failures, not an exclusively BTC-attributable effect.',
   'No rule has been relaxed. This diagnoses data-validity propagation, not factor profitability or an exchange outage cause.'],
  'outcomes_read':False,'features_rebuilt':False,
  'source_manifest_sha256':hashlib.sha256((ROOT/'data/manifest.json').read_bytes()).hexdigest()}
(HERE/'residual_missing_btc_attribution.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
out.to_parquet(HERE/'residual_missing_btc_attribution.parquet',index=False)
lines=['残差缺失：BTC共同参考归因','本次只读数据和特征，未修改规则或重建分片，未计算未来收益。',
 f'旧非BTC资格小时{len(out):,}，残差缺失{summary["residual_missing_total"]:,}。其中拟合窗口失效38,698行，另252行是拟合有效但近期窗口无效。',
 '拟合失效分解：仅BTC无效 '+str(counts.get('BTC_only',0))+'；仅本币无效 '+str(counts.get('own_coin_only',0))+'；两者均有无效 '+str(counts.get('both',0))+'。',
 '两者均有无效是重叠原因，不能把两种影响简单加总，也不是亏损归因。',
 'BTC的无效完整小时（按收盘UTC）：']
for h in minute_sources:
    lines.append(h['hour_close_utc']+f'：存在{h["observed_minutes"]}条分钟记录，其中{h["zero_or_invalid_minutes"]}条零量/无效；源分钟为'+', '.join(r['open_utc'] for r in h['minute_records']))
lines += ['这些源记录的volume、quote_volume及trade_count为0，未以填值制造交易；不能仅据归档断言停机的原因。',
 '小时收盘价被有效性规则设为NA后，当小时及下一小时的close-to-close收益都不可用；严格720个有效配对小时因此在固定6小时隔离之后传播约30日。',
 f'父代理F1共同样本在481日中仅{int(has_f1.sum())}日有观测，{int((~has_f1).sum())}个完整日全池空白；旧非BTC资格小时的残差全缺日也为{int((~has_res).sum())}日。',
 '全池完整空白日期区间：']
for r in summary['F1_clock_blank_day_intervals']:lines.append(r['start_utc']+' 至 '+r['last_included_utc']+'（'+str(r['points'])+'日）')
lines += ['BTC-only失效为0：所有BTC拟合窗口无效的观测，其本币窗口也有无效。仅修BTC不会使这些行恢复。不能将34,029行作为BTC独立造成的排他影响。',
 '上述“两者”行中有共同同一无效收益小时的行数为'+str(summary['both_bad_fit_rows_with_shared_same_invalid_hour'])+'；没有同一无效小时、只分别在不同小时失效的行数为'+str(summary['both_bad_fit_rows_without_shared_same_invalid_hour'])+'。',
 '因此剩余缺失不能只解释为个别小币流动性不足，应区分跨币共享时段的有效性失效与个币额外缺失。BTC可揭示共同禁用区间，但不是唯一原因。',
 '如以后考虑区别“无交易但收盘仍可观察”和“价格数据不可用”，须独立登记新的有效性定义并审计；本轮没有采取这种变更，更没有依收益调整。',
 '详细逐币、逐小时、BTC受影响区间见residual_missing_btc_attribution.json/parquet。']
(HERE/'BTC共同参考缺失归因.txt').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps({k:summary[k] for k in ['fit_failure_attribution_counts','btc_invalid_closed_hours','btc_reference_fit_unavailable_intervals','F1_clock_blank_day_intervals']},ensure_ascii=True))
