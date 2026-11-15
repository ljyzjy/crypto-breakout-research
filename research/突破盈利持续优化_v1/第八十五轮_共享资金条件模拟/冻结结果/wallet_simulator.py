"""Known-path wallet accounting with precommitted signal-time risk sizing."""
from decimal import Decimal, localcontext

D = Decimal
FEE = D('.0005')
SLIP = D('.0005')


def simulate(records, lev, reverse_ties=False, initial=D('1000')):
    assert lev in (10, 20)
    assert len({r['observation_id'] for r in records}) == len(records)
    order = {obs: i for i, obs in enumerate(sorted((r['observation_id'] for r in records), reverse=reverse_ties))}
    schedule = []
    for r in records:
        obs = r['observation_id']
        assert r['reference_ts'] >= r['decision_ts'] + 1000 and r['entry_ts'] >= r['reference_ts'] + 1000
        assert r['exit_ts'] >= r['exit_signal_ts'] + 5000 and r['entry_ts'] <= r['exit_ts']
        schedule.extend([(r['reference_ts'], 0, order[obs], 0, 'reference', r, None),
                         (r['entry_ts'], 1, order[obs], 0, 'entry', r, None),
                         (r['exit_ts'], 3, order[obs], 0, 'exit', r, None)])
        for i, event in enumerate(r['funding_events']):
            assert r['entry_ts'] <= event['settlement_ts'] <= r['exit_ts']
            schedule.append((event['settlement_ts'], 2, order[obs], i, 'funding', r, event))
    schedule.sort(key=lambda z: z[:4])
    with localcontext() as ctx:
        ctx.prec = 42
        wallet, locked, peak, max_dd = D(initial), D(0), D(initial), D(0)
        pending, active, outcomes, journal = {}, {}, {}, []
        max_active = 0

        def snapshot(ts, typ, obs, status):
            nonlocal peak, max_dd, max_active
            max_active = max(max_active, len(active))
            peak = max(peak, wallet)
            if peak > 0:
                max_dd = max(max_dd, (peak - wallet) / peak)
            journal.append({'ts': ts, 'event': typ, 'observation_id': obs, 'status': status,
                            'wallet': wallet, 'locked_margin': locked,
                            'pending_reserve': sum((v['reserve'] for v in pending.values()), D(0)),
                            'planned_open_risk': sum((v['planned_risk'] for v in [*pending.values(), *active.values()]), D(0))})

        for ts, _, _, _, typ, r, payload in schedule:
            obs = r['observation_id']
            if typ == 'reference':
                assert obs not in pending and obs not in active and obs not in outcomes
                side, ref, stop = D(r['side']), D(str(r['reference'])), D(str(r['stop']))
                estimate_entry = ref * (1 + side * SLIP)
                estimate_stop = stop * (1 - side * SLIP)
                loss_per_unit = side * (estimate_entry - estimate_stop) + FEE * (estimate_entry + estimate_stop)
                assert estimate_entry > 0 and estimate_stop > 0 and loss_per_unit > 0
                other_reserve = sum((v['reserve'] for v in pending.values()), D(0))
                prior_risk = sum((v['planned_risk'] for v in [*pending.values(), *active.values()]), D(0))
                free = max(D(0), wallet - locked - other_reserve)
                risk_budget = max(D(0), min(wallet * D('.005'), wallet * D('.01') - prior_risk))
                margin_per_unit = estimate_entry / D(lev) + FEE * estimate_entry
                # Ignore only arithmetic residue, not a real exchange lot-size rule.
                quantity = D(0) if risk_budget <= abs(wallet) * D('1e-18') or free <= abs(wallet) * D('1e-18') else min(risk_budget / loss_per_unit, free / margin_per_unit)
                if quantity <= 0:
                    outcomes[obs] = {'status': 'signal_rejected_budget_or_funds', 'quantity': D(0), 'net_pnl': D(0)}
                    snapshot(ts, typ, obs, 'signal_rejected_budget_or_funds')
                    continue
                pending[obs] = {'quantity': quantity, 'reserve': quantity * margin_per_unit,
                                'planned_risk': quantity * loss_per_unit, 'unit_planned_loss': loss_per_unit,
                                'reference_wallet': wallet, 'estimated_entry': estimate_entry}
                snapshot(ts, typ, obs, 'reserved')
            elif typ == 'entry':
                if obs not in pending:
                    continue
                order_ = pending.pop(obs)
                qty, actual = order_['quantity'], D(str(r['entry_fill']))
                margin, open_fee = qty * actual / D(lev), qty * actual * FEE
                remaining_pending = sum((v['reserve'] for v in pending.values()), D(0))
                free = wallet - locked - remaining_pending
                if margin + open_fee > free + D('1e-25'):
                    outcomes[obs] = {'status': 'entry_rejected_insufficient_margin', 'quantity': qty, 'net_pnl': D(0), **order_}
                    snapshot(ts, typ, obs, 'entry_rejected_insufficient_margin')
                    continue
                wallet -= open_fee
                locked += margin
                active[obs] = {**order_, 'margin': margin, 'open_fee': open_fee, 'funding_paid': D(0)}
                snapshot(ts, typ, obs, 'filled')
            elif typ == 'funding':
                if obs not in active:
                    continue
                position = active[obs]
                charge = D(str(payload['charge'])) * position['quantity'] * D(str(r['entry_fill']))
                wallet -= charge
                position['funding_paid'] += charge
                snapshot(ts, typ, obs, 'funding_applied')
            else:
                if obs not in active:
                    continue
                position = active.pop(obs)
                qty, side = position['quantity'], D(r['side'])
                entry, exit_ = D(str(r['entry_fill'])), D(str(r['exit_fill']))
                closing_change = qty * (side * (exit_ - entry) - exit_ * FEE)
                wallet += closing_change
                locked -= position['margin']
                net_pnl = closing_change - position['open_fee'] - position['funding_paid']
                assert abs(net_pnl - qty * entry * D(str(r['unit_net']))) < D('1e-8')
                outcomes[obs] = {'status': 'closed', **position, 'net_pnl': net_pnl}
                snapshot(ts, typ, obs, 'closed')
        assert not pending and not active and abs(locked) < D('1e-20') and len(outcomes) == len(records)
        values = [x['net_pnl'] for x in outcomes.values() if x['status'] == 'closed']
        positive = sum((x for x in values if x > 0), D(0))
        negative = -sum((x for x in values if x < 0), D(0))
        assert abs(wallet - D(initial) - sum(values, D(0))) < D('1e-8')
        summary = {'initial_wallet': D(initial), 'final_wallet': wallet, 'net_pnl': wallet - D(initial),
                   'net_return_pct': (wallet / D(initial) - 1) * 100, 'known_opportunities': len(records),
                   'simulated_trades': len(values), 'net_wins': sum(x > 0 for x in values),
                   'net_win_rate_pct': D(100) * sum(x > 0 for x in values) / len(values) if values else None,
                   'profit_factor': positive / negative if negative else None,
                   'realized_wallet_drawdown_pct': max_dd * 100,
                   'rejected_signals': sum(x['status'] != 'closed' for x in outcomes.values()),
                   'maximum_open_positions': max_active, 'reverse_ties': reverse_ties}
        return summary, outcomes, journal
