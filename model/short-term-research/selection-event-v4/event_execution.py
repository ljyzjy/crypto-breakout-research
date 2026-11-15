"""Predecessor accounting with sale-triggered vacancy replacement.
No rank-based sale; globals supplied by event_engine; research only.
"""
def simulate_path(start,end,mode,fee=.0005,delay=0,fixture=None,feature_fixture=None):
    assert mode in NAMES and delay in (0,5)
    selector,variant=mode.split('__')
    z=fixture if fixture is not None else prepare(start,end,delay);f=feature_fixture if feature_fixture is not None else features()
    times=z['index'].as_unit('s').asi8;px=z['px'];mk=z['mk'];rates=z['rates'];dynamic=variant=='tiered';mult=1;slip=.0005
    cash=1000.;pos={};cool={};boostcool={};stops=[];guard=0;peak=1000.;equity=1000.;dd=0.;maxdd=0.;mincash=1000.;minratio=1e9;stressdd=0.;maxexp=0.;sumexp=0.;boost_steps=0;held_steps=0
    symbols=z['symbols'];chosen=[];selection=[];skips=[]
    orders=[];trades=[];fund_events=[];issues=[];audit=[];adjustments=[];curve=[[int(times[0]),1000.,0.,0.]];blocked=0
    pending=[int(times[0])+delay*60]*2;last_review=-1
    def lots(p):return [p['core'],*p['boost'].values()]
    def settle(s,layer,lot,i,ts,boundary=False):
        signed=pos[s]['side']*rates[s][i]
        if boundary and signed<=0:return
        amount=lot['qty']*mk[s][i,0]*signed;lot['funding']+=amount
        if amount:fund_events.append(dict(symbol=s,layer=layer,ts=int(ts),side=pos[s]['side'],rate=float(rates[s][i]),payment=float(amount),new_boundary_entry=boundary))
    def close_lot(s,layer,ref,ts,reason,info):
        nonlocal cash
        p=pos[s];lot=p['core'] if layer=='core' else p['boost'].pop(layer);side=p['side'];fill=ref*(1-side*slip);exitfee=lot['qty']*fill*fee
        pricepnl=side*lot['qty']*(fill-lot['fill']);net=pricepnl-lot['entryfee']-exitfee-lot['funding'];cash+=pricepnl-exitfee-lot['funding']
        if layer=='core':cash+=p['margin']
        sc=lot['qty']*(abs(lot['fill']-lot['ref'])+abs(ref-fill))
        trades.append(dict(symbol=s,layer=layer,direction='long' if side==1 else 'short',entry_ts=lot['ts'],exit_ts=int(ts),entry_price=lot['fill'],exit_price=fill,entry_reference=lot['ref'],exit_reference=float(ref),qty=lot['qty'],margin=p['margin'] if layer=='core' else 0.,notional=lot['qty']*lot['fill'],pnl=net,gross_pnl=net+lot['entryfee']+exitfee+sc+lot['funding'],fees=lot['entryfee']+exitfee,slippage=sc,funding=lot['funding'],reason=reason,hold_hours=(ts-lot['ts'])/3600))
        orders.append(dict(action='close',symbol=s,layer=layer,side=-side,ts=int(ts),information_ts=info,price=float(fill),qty=lot['qty'],cash=cash,reason=reason))
        if layer!='core':boostcool[s]=max(boostcool.get(s,0),ts+86400);adjustments.append(dict(ts=int(ts),symbol=s,action='reduce',layer=layer,reason=reason,quantity_multiplier=1+.5*len(p['boost'])))
        return net
    def close_core(s,ref,ts,reason,info):
        nonlocal guard
        for layer in list(pos[s]['boost']):close_lot(s,layer,ref,ts,'core_'+reason,info)
        net=close_lot(s,'core',ref,ts,reason,info);pos.pop(s);cool[s]=math.ceil((ts+21600)/3600)*3600
        pending.append(max(int(times[i])+300,int(ts)))
        if reason in ('gap_stop','stop_loss') and net<0:
            if selector=='delayed_retry':
                mid=pd.Timestamp(ts,unit='s',tz='UTC').normalize();cool[s]=max(cool[s],int((mid+pd.Timedelta(days=7-mid.weekday())).timestamp()))
            stops.append(ts)
            if sum(t>=ts-172800 for t in stops)>=2:guard=max(guard,math.ceil((ts+86400)/3600)*3600)
    def risk_to_stops(i,proposal=None):
        total=0.
        for s,p in pos.items():
            mark=mk[s][max(0,i-1),3]
            for lot in lots(p):total+=lot['qty']*(max(0.,p['side']*(mark-lot['stop']))+abs(lot['stop'])*(fee+slip))
        if proposal:
            qty,fill=proposal;total+=qty*fill*(.04+fee+slip)
        return total
    for i,t in enumerate(times):
        ts=int(t);endts=ts+300;info=ts-delay*60;daily=bool(z['decision'][i]) and (hourly_rotation or info%86400==0)
        pre_equity=equity;pre_dd=dd;pre_core_funding={s:p['core']['funding'] for s,p in pos.items()}
        for s in pos:
            if not z['ok'][s][i] or not np.isfinite(mk[s][i]).all() or not np.isfinite(px[s][i]).all():issues.append(dict(ts=ts,symbol=s,kind='held_data_missing'))
        if issues:break
        for s,p in pos.items():
            settle(s,'core',p['core'],i,ts)
            for layer,lot in p['boost'].items():settle(s,layer,lot,i,ts)
        for s,p in pos.items():
            mark=mk[s][i,0];coll=p['margin']+sum(p['side']*lot['qty']*(mark-lot['fill'])-lot['funding'] for lot in lots(p));ratio=coll/(sum(lot['qty'] for lot in lots(p))*mark);minratio=min(minratio,ratio)
            if ratio<=.07:issues.append(dict(ts=ts,symbol=s,kind='collateral_stress_open',ratio=ratio))
        if issues:break
        for s in list(pos):
            p=pos[s];op=px[s][i,0]
            if px[s][i,4]>0 and p['side']*(op-p['core']['stop'])<=0:close_core(s,op,ts,'gap_stop',info if daily else None);continue
            for layer in list(p['boost']):
                if px[s][i,4]>0 and p['side']*(op-p['boost'][layer]['stop'])<=0:close_lot(s,layer,op,ts,'boost_gap_stop',ts)
        if dynamic and pre_dd>=8:
            for s in list(pos):
                for layer in list(pos[s]['boost']):close_lot(s,layer,px[s][i,0],ts,'account_dd_brake',ts)
        if daily:
            for s in list(pos):
                if (int(z['mom'][s][i])!=pos[s]['side']) and px[s][i,4]>0:close_core(s,px[s][i,0],ts,'timing_exit',info)
        rank_ts=(info//3600)*3600
        row=z['trace'].get(rank_ts)
        if row is not None and pending and min(pending)<=ts:
            held_before=list(pos);opened=[]
            for candidate in row['ranked']:
                s=candidate['symbol']
                if not any(t<=ts for t in pending):break
                quarantine=z.get('quarantine',{}).get(s)
                if quarantine and quarantine['observed_ts']<=info:continue
                side=int(z['mom'][s][i]);margin=float(z['budgets'][s][i]);notional=margin*mult;entryfee=notional*fee
                if s in pos or not side:continue
                if z['avail'][s][i]==2:skips.append(dict(ts=ts,symbol=s,kind='known_missing_mark_excluded'));continue
                if not z['avail'][s][i]:skips.append(dict(ts=ts,symbol=s,kind='no_previous_executable_contract_bar'));continue
                if margin<10:continue
                if ts<cool.get(s,0) or ts<guard:blocked+=1;continue
                if len(pos)>=2 or cash<margin+entryfee:continue
                if z['avail'][s][i]!=1 or not z['ok'][s][i] or not np.isfinite(mk[s][i]).all() or not np.isfinite(px[s][i]).all():issues.append(dict(ts=ts,symbol=s,kind='entry_data_missing'));continue
                if px[s][i,4]<=0:continue
                ref=float(px[s][i,0]);fill=ref*(1+side*slip);qty=notional/fill;cash-=margin+entryfee
                lot=dict(qty=qty,fill=fill,ref=ref,entryfee=entryfee,funding=0.,ts=ts,stop=fill*(1-side*.04))
                pos[s]=dict(side=side,margin=margin,core=lot,boost={});orders.append(dict(action='open',symbol=s,layer='core',side=side,ts=ts,information_ts=info,price=fill,qty=qty,cash=cash,reason='entry'));settle(s,'core',lot,i,ts,True)
                pending.remove(min(pending));opened.append(s)
            if opened or rank_ts!=last_review:
                selection.append({**row,'ranking_date':row['date'],'date':pd.Timestamp(ts,unit='s',tz='UTC').isoformat(),
                    'decision_information_ts':info,'selected':list(pos),'held_before_decision':held_before,
                    'replacements':opened,'decision_type':'initial_or_sale_replacement',
                    'excluded_data':[q for q in z.get('quarantine',{}).values() if q['observed_ts']<=info]})
                last_review=rank_ts
        if issues:break
        if daily and dynamic and info%86400==0:
            for s in symbols:
                if s not in chosen and s not in pos:continue
                stamp=pd.Timestamp(info,unit='s',tz='UTC');row=f[s].loc[stamp].to_dict() if stamp in f[s].index else None;p=pos.get(s);side=p['side'] if p else int(z['mom'][s][i]);target,why=regime(row,side,variant)
                audit_row={k:float(v) if np.isfinite(v) else None for k,v in row.items()} if row is not None else None
                if p is None:
                    audit.append(dict(ts=ts,information_ts=info,symbol=s,side=side,target=target,actual=0.,reasons=['无基础仓位'],features=audit_row,account_dd=pre_dd));continue
                # Downgrades are permitted in the5..8% DD band; new risk is not.
                desired=int(round((target-1)*2))
                for layer in sorted(list(p['boost']),reverse=True):
                    if int(layer[-1])>desired:close_lot(s,layer,px[s][i,0],ts,'daily_regime_reduce',info)
                mark=mk[s][max(0,i-1),3];core=p['core'];profit=p['side']*core['qty']*(mark-core['fill'])-pre_core_funding.get(s,core['funding'])-core['entryfee'];blocked_reasons=[]
                if ts-core['ts']<86400:blocked_reasons.append('基础仓持有不足24小时')
                if profit<=0:blocked_reasons.append('基础仓尚未净浮盈')
                if pre_dd>=5:blocked_reasons.append('账户回撤达到5%，禁止新增杠杆')
                if ts<guard:blocked_reasons.append('基础策略全局保护期')
                if ts<boostcool.get(s,0):blocked_reasons.append('额外仓24小时冷却期')
                risk_at_add=None
                if not blocked_reasons:
                    for n in range(1,desired+1):
                        layer='boost'+str(n)
                        if layer in p['boost']:continue
                        ref=float(px[s][i,0]);fill=ref*(1+p['side']*slip);qty=core['qty']*.5;entryfee=qty*fill*fee;risk_at_add=risk_to_stops(i,(qty,fill))
                        if risk_at_add>.02*pre_equity:blocked_reasons.append('拟加仓后到止损的组合风险超过净值2%');break
                        if px[s][i,4]<=0 or cash<entryfee:blocked_reasons.append('成交量或现金不足');break
                        cash-=entryfee;p['boost'][layer]=dict(qty=qty,fill=fill,ref=ref,entryfee=entryfee,funding=0.,ts=ts,stop=fill*(1-p['side']*.04))
                        orders.append(dict(action='open',symbol=s,layer=layer,side=p['side'],ts=ts,information_ts=info,price=fill,qty=qty,cash=cash,reason='leverage_add',core_age_hours=(ts-core['ts'])/3600,core_net_unrealized=profit,pre_account_dd=pre_dd,stop_risk_pct=100*risk_at_add/pre_equity))
                        settle(s,layer,p['boost'][layer],i,ts,True);adjustments.append(dict(ts=ts,symbol=s,action='add',layer=layer,reason='daily_gate',quantity_multiplier=1+.5*len(p['boost'])))
                audit.append(dict(ts=ts,information_ts=info,symbol=s,side=side,target=target,actual=1+.5*len(p['boost']),reasons=why+blocked_reasons,features=audit_row,account_dd=pre_dd,core_net_unrealized=profit,planned_stop_risk_pct=100*risk_at_add/pre_equity if risk_at_add is not None else None))
        worst=cash
        for s,p in pos.items():
            mark=mk[s][i,2 if p['side']==1 else 1];coll=p['margin']+sum(p['side']*lot['qty']*(mark-lot['fill'])-lot['funding'] for lot in lots(p));worst+=coll;ratio=coll/(sum(lot['qty'] for lot in lots(p))*mark);minratio=min(minratio,ratio)
            if ratio<=.07:issues.append(dict(ts=ts,symbol=s,kind='collateral_stress_intrabar',ratio=ratio))
        stressdd=max(stressdd,100*(1-worst/peak))
        if issues:break
        for s in list(pos):
            p=pos[s];adverse=px[s][i,2 if p['side']==1 else 1]
            if px[s][i,4]>0 and p['side']*(adverse-p['core']['stop'])<=0:
                # When both stops touch, each boost fills at its own tighter stop, otherwise core exit.
                for layer in list(p['boost']):
                    st=p['boost'][layer]['stop'];ref=st if p['side']*(st-p['core']['stop'])>0 else p['core']['stop'];close_lot(s,layer,ref,endts,'core_stop_loss',None)
                close_core(s,p['core']['stop'],endts,'stop_loss',None);continue
            for layer in list(p['boost']):
                if px[s][i,4]>0 and p['side']*(adverse-p['boost'][layer]['stop'])<=0:close_lot(s,layer,p['boost'][layer]['stop'],endts,'boost_stop_loss',None)
        equity=cash+sum(p['margin']+sum(p['side']*lot['qty']*(mk[s][i,3]-lot['fill'])-lot['funding'] for lot in lots(p)) for s,p in pos.items());peak=max(peak,equity);dd=(1-equity/peak)*100;maxdd=max(maxdd,dd);mincash=min(mincash,cash)
        exposure=sum(sum(lot['qty'] for lot in lots(p))*mk[s][i,3] for s,p in pos.items())/equity if equity>0 else 0;sumexp+=exposure;maxexp=max(maxexp,exposure)
        held_steps+=len(pos);boost_steps+=sum(bool(p['boost']) for p in pos.values())
        if endts%3600==0:curve.append([endts,equity,dd,exposure])
    if not issues:
        for s in list(pos):close_core(s,float(px[s][-1,3]),int(times[-1]+300),'window_end',None)
    valid=not issues and not pos;ledger=abs(1000+sum(t['pnl'] for t in trades)-cash) if valid else None
    if valid:
        assert ledger<1e-7 and mincash>=-1e-7
        maxdd=max(maxdd,(1-cash/peak)*100);curve[-1]=[int(times[-1]+300),cash,(1-cash/peak)*100,0.]
    days=(pd.Timestamp(end)-pd.Timestamp(start)).days+1
    return dict(mode=mode,name=NAMES[mode],selector=selector,variant=variant,selection_trace=selection,skipped_entries=skips,universe_size=638,execution_symbols=len(symbols),start=start,end=end,fee=fee,slippage=slip,delay_minutes=delay,elapsed_days=days,initial=1000.,final_equity=cash if valid else None,return_pct=(cash/1000-1)*100 if valid else None,annualized_return_pct=((cash/1000)**(365/days)-1)*100 if valid and days>=365 and cash>0 else None,max_drawdown=maxdd if valid else None,valid_for_comparison=valid,trade_count=len(trades),core_trades=sum(t['layer']=='core' for t in trades),boost_trades=sum(t['layer']!='core' for t in trades),core_pnl=sum(t['pnl'] for t in trades if t['layer']=='core'),boost_pnl=sum(t['pnl'] for t in trades if t['layer']!='core'),long_pnl=sum(t['pnl'] for t in trades if t['direction']=='long'),short_pnl=sum(t['pnl'] for t in trades if t['direction']=='short'),fees=sum(t['fees'] for t in trades),slippage_cost=sum(t['slippage'] for t in trades),funding_cost=sum(t['funding'] for t in trades),gross_pnl=sum(t['gross_pnl'] for t in trades),cash_min=mincash,ledger_error=ledger,minimum_collateral_ratio_pct=minratio*100 if minratio<1e8 else None,intrabar_stress_dd=stressdd,mean_exposure_pct=sumexp/len(times)*100 if valid else None,max_exposure_pct=maxexp*100,boost_held_time_pct=boost_steps/held_steps*100 if held_steps else 0.,data_issues=issues,trades=trades,orders=orders,funding_events=fund_events,leverage_audit=audit,adjustments=adjustments,curve=base.compress_curve(curve),contributions={s:sum(t['pnl'] for t in trades if t['symbol']==s) for s in symbols})
