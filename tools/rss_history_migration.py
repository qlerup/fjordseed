"""One-time archive ownership transfer. Call with all ledger writers stopped."""
from copy import deepcopy


def transfer(ledger, destination, sources):
    feeds=ledger.setdefault('_rss_upload',{}).setdefault('feeds',{})
    target=feeds.setdefault(destination,{'credited_uploaded':0,'downloads':{}})
    completed=target.setdefault('migrated_sources',[])
    for source in dict.fromkeys(sources):
        if source==destination or source in completed:continue
        original=feeds.get(source,{})
        target['credited_uploaded']+=original.get('credited_uploaded',0)
        target['estimated']=target.get('estimated',False) or original.get('estimated',False)
        for ident,record in original.get('downloads',{}).items():
            downloads=target.setdefault('downloads',{})
            if ident not in downloads:downloads[ident]=deepcopy(record)
            else:
                item=downloads[ident]
                item['credited_uploaded']=item.get('credited_uploaded',0)+record.get('credited_uploaded',0)
                for field in ('uploaded','downloaded','credited_downloaded'):
                    if field in record and field in item:item[field]+=record[field]
                    else:item.pop(field,None)
                item['added_at']=min(item['added_at'],record['added_at'])
                for flag in ('estimated','download_credit_incomplete'):
                    item[flag]=item.get(flag,False) or record.get(flag,False)
        for key,entry in ledger.items():
            if not key.startswith('_') and isinstance(entry,dict) and entry.get('rss_feed_id')==source:
                entry['rss_feed_id']=destination
        # Retain a complete original archive for recovery, but the new feed owns
        # its copy and all subsequent live traffic goes to the destination.
        if source in feeds:feeds[source]['migrated_to']=destination
        completed.append(source)
    return target
