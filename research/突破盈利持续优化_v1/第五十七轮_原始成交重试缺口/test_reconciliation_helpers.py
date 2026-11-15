"""Check strict five-second flow boundaries and first directional cross."""
import hashlib,json
from pathlib import Path
import pandas as pd
import check_eth_retests as check
H=Path(__file__).resolve().parent
def main():
    start=60000
    tape=pd.DataFrame([
        {'transact_time':start+100,'price':100.0,'quantity':1.,'is_buyer_maker':'false'},
        {'transact_time':start+1000,'price':101.0,'quantity':1.,'is_buyer_maker':'false'},
        {'transact_time':start+1000,'price':101.0,'quantity':20.,'is_buyer_maker':'false'},
        {'transact_time':start+1001,'price':101.0,'quantity':2.,'is_buyer_maker':'false'},
        {'transact_time':start+5999,'price':100.0,'quantity':3.,'is_buyer_maker':'true'},
        {'transact_time':start+6000,'price':102.0,'quantity':40.,'is_buyer_maker':'true'}])
    event={'trigger_minute':start,'upper':100.5,'lower':99.5}
    cross=check.first(tape,event);assert cross==(start+1000,101.0)
    n,buy,sell=check.flow(tape,cross[0]);assert n==2 and buy==202 and sell==300
    assert check.near(.10000000001,.1) and not check.near(.2,.1)
    out={'all_checks_pass':True,'first_cross_checked':True,'strict_window_excludes_endpoints':True,
         'code_sha256':hashlib.sha256((H/'check_eth_retests.py').read_bytes()).hexdigest(),
         'plan_sha256':hashlib.sha256((H/'核验方案.md').read_bytes()).hexdigest()}
    (H/'重试窗口合成核验.json').write_text(json.dumps(out,ensure_ascii=False,indent=2),encoding='utf-8')
    print('ETH57_HELPER_TEST_PASS',json.dumps(out,ensure_ascii=False),flush=True)
if __name__=='__main__':main()
