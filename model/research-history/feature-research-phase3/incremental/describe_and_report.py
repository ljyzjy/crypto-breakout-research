"""Descriptive reporting only. Does not refit, select, or open account outcomes."""
import json
import numpy as np
import pandas as pd
from run_incremental import HERE,load_cohort,TRAIN_START,TRAIN_END,SCREEN_END,EVAL_END,save_json,save_parquet

VARIABLES={'F1':['r6','residual6'],'F2':['efficiency6','concentration6'],
           'F3':['rv_relative60','range_atr'],'F4':['boundary_distance','outside_fraction5'],
           'F5':['drawdown_atr','recovery_fraction'],'F6':['quote_rvol','count_rvol']}
NAMES={'F1':'方向/残差动量','F2':'路径效率/集中度','F3':'相对波动/幅度风险',
       'F4':'边界距离/外侧接受度','F5':'回撤深度/修复比例','F6':'成交笔数相对活跃度'}

def main():
    results=json.loads((HERE/'incremental_results.json').read_text(encoding='utf-8'))
    cohorts={c:load_cohort(c) for c in ['clock','events']}; rows=[]
    splits={'train':(TRAIN_START,TRAIN_END),'screen':(TRAIN_END,SCREEN_END),'evaluation_features_only':(SCREEN_END,EVAL_END)}
    for group,variables in VARIABLES.items():
        d=cohorts['events' if group in ['F4','F5'] else 'clock']
        for split,(start,end) in splits.items():
            eligible=d.decision_ts.ge(start)&d.decision_ts.lt(end)&d.eligible_decision.fillna(False)&~d.quarantined.fillna(True)
            q=d.loc[eligible]
            for var in variables:
                numeric=pd.to_numeric(q[var],errors='coerce')
                v=numeric.loc[np.isfinite(numeric.to_numpy(float))]
                row={'group':group,'variable':var,'split':split,'eligible_opportunities':len(q),'finite_values':len(v),
                     'coverage':len(v)/len(q),'baseline_control_not_new_discovery':var in ['r6','quote_rvol']}
                row.update({k:float(x) for k,x in {'mean':v.mean(),'std':v.std(),'min':v.min(),'q05':v.quantile(.05),'median':v.median(),'q95':v.quantile(.95),'max':v.max()}.items()})
                rows.append(row)
    save_parquet(HERE/'diagnostics'/'all12-feature-descriptives.parquet',pd.DataFrame(rows))
    save_json(HERE/'diagnostics'/'all12-feature-descriptives.json',{'denominator':'each assigned original cohort, eligible at decision and not then quarantined; no future label mask','rows':rows})
    lines=['十二项特征增量价值检验：本轮结果','',
           '结论：六组均未达到事先冻结的入选规则，本轮不增加任何新特征交易候选。',
           '这是已反复研究过历史数据上的严格时间先后探索；不能称为全新样本外确认。',
           '训练：2025-01-01至03-31；筛选：2025-04-01至06-30。每段末尾65分钟清除，所有目标严格在边界前结束。',
           '最终2025-07-01至2026-04-26的300日只供账户代理评价；本增量模块未读取该段未来标签。','',
           '主检验：30分钟。OLS共同控制自身6小时动量、BTC6小时动量、24小时波动、报价成交额RVOL、UTC时刻及币固定效应。',
           '12项中r6和quoteRVOL本来就是共同控制，新增检验为10个变量、6组假设。',
           '各组同一匹配样本，训练段拟合/缩放；筛选段不重新拟合。按币-日等权损失，7日同步移动块bootstrap 2000次，Holm6校正。','',
           '组别 | 误差相对改善 | 单侧原始p | Holm6 p | 训练条数/天数 | 筛选条数/天数']
    for r in results['groups']:
        t=r['train']['paired'];s=r['screen']['paired']
        lines.append(f"{r['group']} {NAMES[r['group']]} | {r['relative_loss_improvement']*100:+.5f}% | {r['p_raw']:.6f} | {r['p_holm6']:.6f} | {t['records']}/{t['active_days']} | {s['records']}/{s['active_days']}")
    lines += ['', '正数表示预测误差减少；F3预测的是MAE风险，不是方向收益。F3改善1.09405%，原始p约0.026，但六组校正后约0.156，证据不足以升级。',
              '其他五组在这一预定线性增量检验中均无改善。不能据此断言这些变量在一切市场或模型中都无用；能断言的是本轮规则没有支持它们增加到当前策略。',
              'F1训练只有46个有效日，主要来自预先发现的BTC历史零成交量导致连续回归窗口失效；仍达到预设30日/8周/5币最低要求。没有更改连续性规则或按收益补值。',
              '每组baseline/enhanced样本ID完全一致；筛选阶段在已知特征合格及purge之后，30分钟未来标签额外损失均为0。训练期删样见incremental_results.json。','',
              '固定时长标签仅用于诊断：gross=方向对数收益(bp)，成本代理=gross−20bp；该代理未计真实资金费，不等于账户收益。真实账户另计逐次手续费、不利滑点和归档资金费。',
              '15/30/60分钟标签的均值、MFE、MAE及方向/币种/月度细分均保留在diagnostics/*-screen.parquet；它们不改变30分钟主结论。',
              '下面为筛选期配对主样本上的均值描述；并非独立不重叠交易，也未按这些数字选持有周期：',
              '组别 | 周期分钟 | 有效条数 | gross均值bp | 20bp成本代理均值bp | MFE均值bp | MAE均值bp']
    for group in VARIABLES:
        x=pd.read_parquet(HERE/'diagnostics'/f'{group}-screen.parquet')
        for _,r in x.loc[x.stratum.eq('all')].iterrows():
            h=int(r.horizon)
            lines.append(f"{group} | {h} | {int(r.records)} | {r[f'gross_bp_{h}']:.3f} | {r[f'net20bp_proxy_{h}']:.3f} | {r[f'mfe_bp_{h}']:.3f} | {r[f'mae_bp_{h}']:.3f}")
    lines += ['','主要文件：incremental_results.json完整结果；selection.json封存筛选；models/F*-train.json模型参数与时间；matched/逐组匹配；labels/完整标签及无效原因；predictions/account_events.parquet账户事件接口。',
              '现有模拟没有更改；本轮不会因没有入选组而改阈值、换样本、挑15/60分钟或强行构造候选。']
    (HERE/'增量特征检验结果.txt').write_text('\n'.join(lines),encoding='utf-8')
    print('\n'.join(lines[:24]))

if __name__=='__main__':main()
