"""Read-only cleanup forecast based on allocated blocks and the worker's policies."""
import math
import time


def number(value):
    return type(value) in (int,float) and math.isfinite(value) and value>=0


def forecast(row, source, now):
    def result(state, message, at=None):
        return dict(state=state,message=message,release_at=at)
    if not row:
        return result('unknown','Afventer en aktuel status fra FjordSeed.')
    if not number(row.get('progress')) or row['progress']<1:
        return result('downloading','Downloader stadig; frigivelse beregnes efter download.')
    converted=source.get('converted')
    if converted and not source.get('published'):
        return result('processing','Afventer konvertering og en kontrolleret kopi i biblioteket.')
    if not converted and row.get('share_limit_action')!='RemoveWithContent':
        return result('retained','Beholdes i biblioteket; flytningen frigiver ikke plads på denne disk.')
    if row.get('state') not in ('uploading','stalledUP','forcedUP'):
        return result('paused','Seeding er sat på pause eller i kø; tidspunkt kan ikke beregnes.')
    reached=row.get('seeding_requirement_met') if converted else row.get('seeding_goal_reached')
    if reached:
        if not converted and row.get('waiting_for_downloaders'):
            return result('waiting','Målet er nået; venter på aktive downloadere eller kontrol af upload.')
        if not converted and row.get('seeding_auto_extended'):
            return result('extended','Målet er nået; automatisk seeding er forlænget, fordi der stadig er efterspørgsel.')
        return result('soon','Forventes frigivet ved næste automatiske oprydning.')
    minutes=row.get('seeding_time_limit')
    limit=row.get('required_seeding_seconds') if converted else minutes*60 if number(minutes) else None
    if not converted and row.get('ratio_only'):
        return result('ratio','Afventer ratio '+str(row.get('ratio_limit',1))+'; tidspunkt afhænger af upload.')
    seeded=row.get('seeding_time')
    if not number(limit) or not number(seeded):
        return result('unknown','Tidspunkt kan ikke beregnes ud fra den aktuelle seedingstatus.')
    return result('estimated','Ved fortsat seeding; kan ske tidligere ved opnået ratio og senere ved forlænget seeding.',
                  now+max(0,limit-seeded))


def schedule(sources, runtime, now=None):
    now=time.time() if now is None else now
    if not sources:
        return dict(items=[],count=0,scheduled_bytes=0,available=True)
    try:
        rows=runtime.rpc('status',{}).get('torrents',[])
        if not isinstance(rows,list):raise ValueError()
        available=True
    except Exception:
        rows=[];available=False
    by_hash={r.get(key):r for r in rows for key in ('hash','infohash_v1','infohash_v2') if r.get(key)}
    items=[]
    for source in sources:
        row=next((by_hash[h] for h in source.get('hashes',[]) if h in by_hash),None)
        item=dict(name=row.get('name') if row else source['stage'].rsplit('/',1)[-1],
                  bytes=source['bytes'],reclaimable_bytes=source['reclaimable_bytes'],
                  **forecast(row,source,now))
        if item['state']=='retained':item['reclaimable_bytes']=0
        items.append(item)
    items.sort(key=lambda item:(item['state']!='soon',item['release_at'] is None,item['release_at'] or 0,-item['bytes']))
    return dict(items=items[:10],count=len(items),available=available,
                scheduled_bytes=sum(i['reclaimable_bytes'] for i in items if i['state'] in ('soon','estimated')))
