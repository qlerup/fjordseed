"""Incremental tracker credit, independent of conservative seeding goals."""
from datetime import datetime
import math


def stamp(value):
    try:
        date=datetime.fromisoformat(value.replace('Z','+00:00'))
        return date.timestamp() if date.tzinfo else None
    except (AttributeError,ValueError,OverflowError):return None


def policy(result):
    matches=result.get('matches',[]) if result.get('status')=='matched' else []
    values=[]
    for match in matches:
        created=stamp(match.get('created_at'))
        own=match.get('own_upload') is True
        values.append({'green_until':0 if own else created+86400 if created else None,
            'double_upload':match.get('double_upload'),
            'freeleech':match.get('torrent_freeleech',match.get('freeleech')),
            'global_until':stamp(match.get('global_freeleech_ends_at')) if match.get('global_freeleech') is True else None})
    if not values or any(v!=values[0] for v in values):return {}
    return {**values[0],'checked_at':result.get('checked_at')}


def valid_number(value):
    return type(value) in (int,float) and math.isfinite(value) and value>=0


def accrue(state,uploaded,downloaded,start,end,rules):
    """Keep unresolved samples for ten minutes while the initial API lookup runs.

    Reconstructing a short interval with its first verified flags is explicitly
    estimated. Old intervals are never reclassified with today's flags.
    """
    pending=state.setdefault('pending',[])
    if uploaded or downloaded:pending.append({'start':start,'end':end,'uploaded':uploaded,'downloaded':downloaded})
    up=down=0;remaining=[]
    checked=rules.get('checked_at')
    fresh=valid_number(checked) and 0<=end-checked<=600
    for sample in pending:
        recent=fresh and abs(sample['end']-checked)<=600
        age=end-sample['end']
        a,b=sample['start'],sample['end'];duration=max(b-a,1e-6)
        green=rules.get('green_until');double=rules.get('double_upload');free=rules.get('freeleech')
        if recent and valid_number(green) and type(double) is bool and sample['uploaded']:
            fraction=(float(green>b) if b<=a else max(0,min(1,(min(b,green)-a)/duration)))
            up+=sample['uploaded']*(1-.5*fraction)*(2 if double else 1)
            state['estimated']=state.get('estimated',False) or checked>a or 0<fraction<1
            sample['uploaded']=0
        if recent and type(free) in (int,float) and free in (0,25,50,75,100) and sample['downloaded']:
            global_end=rules.get('global_until')
            global_fraction=(float(global_end>b) if b<=a else max(0,min(1,(min(b,global_end)-a)/duration))) if valid_number(global_end) else 0
            down+=sample['downloaded']*(1-free/100)*(1-global_fraction)
            state['estimated']=state.get('estimated',False) or checked>a or 0<global_fraction<1
            sample['downloaded']=0
        if sample['uploaded'] or sample['downloaded']:
            if age>600:
                for field in ('uploaded','downloaded'):
                    state['unknown_'+field]=state.get('unknown_'+field,0)+sample[field]
            else:remaining.append(sample)
    state['pending']=remaining
    return up,down
