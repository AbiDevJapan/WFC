"""Compare first-event frequencies with exact integrated Weibull hazards.

Run with a modest number of seeds first. All class/rate parameters in the
sample configuration are illustrative, not empirically fitted statistics.
"""
from __future__ import annotations

import argparse
import math
from dataclasses import asdict
from pathlib import Path

from .advanced import AgeDependentEvolvingWorld
from .hazards import load_temporal_profile
from .schema import ContractError, WorldState, load_world


def main() -> None:
    parser=argparse.ArgumentParser(description='Check first-event Monte Carlo calibration')
    parser.add_argument('world_file',type=Path)
    parser.add_argument('--temporal-profile',type=Path,required=True)
    parser.add_argument('--object-id',default='box_001')
    parser.add_argument('--days',nargs='+',type=float,default=[7,30,90])
    parser.add_argument('--trials',type=int,default=1000)
    args=parser.parse_args()
    try:
        if args.trials < 100 or any(not math.isfinite(t) or t <= 0 for t in args.days):
            raise ContractError('require >=100 trials and positive, finite horizons')
        origin=load_world(args.world_file)
        profile=load_temporal_profile(args.temporal_profile)
        selected=next((o for o in origin.objects if o.object_uid==args.object_id),None)
        if selected is None:
            raise ContractError('object ID is not present in initial world')
        mini_data=asdict(origin)
        mini_data['objects']=[asdict(selected)]
        mini=WorldState.parse(mini_data)
        horizons=sorted(set(args.days))
        counts={h:0 for h in horizons}
        for seed in range(args.trials):
            payload=asdict(mini)
            payload['objects']=list(payload['objects'])
            payload['history_seed']=seed
            engine=AgeDependentEvolvingWorld(WorldState.parse(payload),profile)
            history=engine.events_up_to(max(horizons))
            first=history[0].time_days if history else math.inf
            for h in horizons:
                if first <= h:
                    counts[h]+=1
        print(f'First event of {args.object_id}; {args.trials} seeded histories')
        print('Days  Expected P  Observed P  |diff|    95% Monte-Carlo margin')
        for h in horizons:
            total=sum(profile.cumulative_hazard(selected,e,0,h)
                      for e in ('move','remove','replace','modify'))
            expected=-math.expm1(-total)
            observed=counts[h]/args.trials
            margin=1.96*math.sqrt(expected*(1-expected)/args.trials)
            print(f'{h:4g}    {expected:8.3%}    {observed:8.3%}   '
                  f'{abs(observed-expected):7.3%}     +/- {margin:.3%}')
    except (ContractError,OSError,ValueError) as err:
        parser.exit(1,f'HAZARD TEST ERROR: {err}\n')


if __name__=='__main__':
    main()
