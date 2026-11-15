"""Serialization adapter around the frozen experiment runner.

Fresh NumPy calculations can yield int64 counts. Convert only container/scalar
types for JSON output; do not change the frozen engine, rules or metric formulas.
"""
import numpy as np
import study

original_metric=study.metric
def plain(value):
    if isinstance(value,np.generic):return value.item()
    if isinstance(value,dict):return {k:plain(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [plain(v) for v in value]
    return value
def serializable_metric(result):return plain(original_metric(result))

if __name__=='__main__':
    study.metric=serializable_metric
    study.run()
