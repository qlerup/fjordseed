"""Bounded, private time series; account credit and physical traffic stay separate."""
from contextlib import closing
import json
import logging
import math
import os
import sqlite3
import time
from tracker_providers import ACCOUNT_REFRESH_SECONDS

FIELDS=('ratio','credited_uploaded','credited_downloaded','real_uploaded','real_downloaded','seedbonus')
RETENTION=30*86400
INTERVAL=ACCOUNT_REFRESH_SECONDS


class TrackerHistory:
    def __init__(self,path):
        self.path=path
        fd=os.open(path,os.O_CREAT|os.O_WRONLY,0o600);os.close(fd)
        path.chmod(0o600)
        try:
            with closing(self.connect()) as db, db:
                db.execute('CREATE TABLE IF NOT EXISTS samples (scope TEXT NOT NULL, bucket INTEGER NOT NULL, at REAL NOT NULL, data TEXT NOT NULL, PRIMARY KEY(scope,bucket))')
        except sqlite3.Error:
            # Optional charts must not prevent the seedbox from starting.
            logging.getLogger(__name__).exception('Chart history database could not be opened')

    def connect(self):
        return sqlite3.connect(self.path,timeout=5)

    def record(self,scope,values,now=None):
        now=time.time() if now is None else now
        clean={key:value for key,value in values.items() if key in FIELDS
               and type(value) in (int,float) and math.isfinite(value) and value>=0}
        if not clean:return
        bucket=int(now//INTERVAL)
        with closing(self.connect()) as db, db:
            previous=db.execute('SELECT bucket,at,data FROM samples WHERE scope=? ORDER BY bucket DESC LIMIT 1',(scope,)).fetchone()
            if previous:
                if now<previous[1]:return  # Do not overwrite newer samples after clock jitter.
                old=json.loads(previous[2])
                for key in ('real_uploaded','real_downloaded'):
                    if key in clean and key in old and (clean[key]<old[key] or previous[0]==bucket and old.get(key+'_reset')):
                        clean[key+'_reset']=True
            db.execute('INSERT INTO samples VALUES (?,?,?,?) ON CONFLICT(scope,bucket) DO UPDATE SET at=excluded.at,data=excluded.data',
                       (scope,bucket,now,json.dumps(clean,allow_nan=False)))
            db.execute('DELETE FROM samples WHERE at<?',(now-RETENTION,))

    def clear(self,scope):
        with closing(self.connect()) as db, db:
            db.execute('DELETE FROM samples WHERE scope=?',(scope,))

    def changes(self,scope,now=None):
        """Keep the latest 60 changed observations per metric, with original dates."""
        now=time.time() if now is None else now
        with closing(self.connect()) as db:
            rows=db.execute('SELECT at,data FROM samples WHERE scope=? AND at>=? AND at<=? ORDER BY at',
                            (scope,now-RETENTION,now)).fetchall()
        points=[{'at':at,**json.loads(data)} for at,data in rows]
        # Each metric is sparse independently: an upload change must not add a ratio point.
        result={}
        for field in FIELDS:
            previous=None;events=[]
            for i,point in enumerate(points):
                value=point.get(field)
                if value is None:continue
                if value!=previous or point.get(field+'_reset'):
                    events.append(i)
                previous=value
            for i in events[-60:]:
                item=result.setdefault(i,{'at':points[i]['at']})
                item[field]=points[i][field]
                if points[i].get(field+'_reset'):item[field+'_reset']=True
        return [result[i] for i in sorted(result)]

    def samples(self,scope,days,now=None):
        now=time.time() if now is None else now
        with closing(self.connect()) as db:
            rows=db.execute('SELECT at,data FROM samples WHERE scope=? AND at>=? AND at<=? ORDER BY at',
                            (scope,now-days*86400,now)).fetchall()
        points=[{'at':at,**json.loads(data)} for at,data in rows]
        for i,point in enumerate(points):
            if i and point['at']-points[i-1]['at']>3*INTERVAL:point['gap_before']=True
        if len(points)<=480:return points
        # Preserve extrema and resets, rather than hiding ratio dips with averages.
        selected={0,len(points)-1}
        for start in range(0,len(points),math.ceil(len(points)/48)):
            indices=range(start,min(len(points),start+math.ceil(len(points)/48)))
            for field in FIELDS:
                valid=[i for i in indices if field in points[i]]
                if valid:
                    selected.add(min(valid,key=lambda i:points[i][field]))
                    selected.add(max(valid,key=lambda i:points[i][field]))
            for i in indices:
                if any(points[i].get(key+'_reset') for key in ('real_uploaded','real_downloaded')):selected.add(i)
        result=[];previous=-1
        for i in sorted(selected):
            point=points[i]
            if any(p.get('gap_before') for p in points[previous+1:i+1]):point['gap_before']=True
            result.append(point);previous=i
        return result
