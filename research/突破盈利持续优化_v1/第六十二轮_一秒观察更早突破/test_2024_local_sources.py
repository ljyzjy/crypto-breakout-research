"""Compare local ZIP extraction with previously audited risk-engine caches."""
import json
from pathlib import Path
import settle_2024_local_sources as local

H, P, ROOT = local.H, local.P, local.ROOT


def main():
    manifests = [P / '第四十六轮_固定十一加密币跨时段/2024/逐笔分批/动态池风险档案核验清单.json',
                 P / '第四十七轮_一次重新突破确认/2024重试分批/动态池风险档案核验清单.json',
                 P / '第五十一轮_缩短市价入场延迟/2024一秒入场分批/动态池风险档案核验清单.json']
    trusted = set()
    for path in manifests:
        for x in json.loads(path.read_text(encoding='utf-8')):
            if x.get('status') == 'verified':
                trusted.add((x['kind'], x['contract'], x['month'], x['sha256']))
    cache = ROOT / 'work/point_in_time_universe33/risk_fixed11_cross46'
    available = []
    for path in cache.glob('*.json'):
        item = json.loads(path.read_text(encoding='utf-8'))
        key = (item.get('kind'), item.get('contract'), item.get('month'), item.get('sha256'))
        if item.get('status') == 'verified' and item.get('rows') and key in trusted and local.source(*key[:3]).is_file():
            available.append((path, item))
    checked = []
    for kind in ('markPriceKlines', 'fundingRate'):
        path, old = next((p, x) for p, x in available if x['kind'] == kind and x['contract'] == 'BTCUSDT' and x['month'] == '2024-01')
        source = local.source(kind, old['contract'], old['month'])
        assert local.sha(source) == old['sha256']
        times = [int(x['ts']) for x in old['rows']] if kind == 'markPriceKlines' else []
        new = local.extract_local(kind, old['contract'], old['month'], times, source, old['sha256'])
        assert new == old
        checked.append({'kind': kind, 'contract': old['contract'], 'month': old['month'], 'rows': len(old['rows']),
                        'source_sha256': old['sha256'], 'prior_cache_sha256': local.sha(path)})
    result = {'all_checks_pass': True, 'samples': checked,
              'settlement_code_sha256': local.sha(H / 'settle_2024_local_sources.py'),
              'test_code_sha256': local.sha(Path(__file__)), 'plan_sha256': local.sha(H / '2024本地风险结算方案.md'),
              'trusted_manifest_sha256': {str(p): local.sha(p) for p in manifests},
              'note': 'Both local source ZIPs and exact output rows match previously verified public risk caches.'}
    (H / '2024本地风险读取对照核验.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('OBS62_LOCAL_RISK_PARITY', len(checked), flush=True)


if __name__ == '__main__':
    main()
