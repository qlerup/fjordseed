"""A reviewable mount guide for a selected pool; never executes on the host."""
import re
import shlex


def mount_plan(inventory,storage_id,uid=1000,gid=1000):
    row=next((s for s in inventory.get('storages',[]) if s.get('id')==storage_id),None)
    ctid=str(inventory.get('ctid',''))
    if not row or not row.get('online') or row.get('type') not in ('dir','nfs','cifs','btrfs'):
        raise ValueError('Vælg en tilgængelig storagepool med et eksisterende filsystem.')
    source=row.get('path','').rstrip('/')
    if (not re.fullmatch(r'[1-9][0-9]{2,8}',ctid) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}',storage_id)
            or not re.fullmatch(r'/(?:mnt|media|srv)(?:/[A-Za-z0-9_. -]+)+',source) or '..' in source.split('/')):
        raise ValueError('Lagerets mountoplysninger kunne ikke valideres.')
    if not str(uid).isdigit() or not str(gid).isdigit():raise ValueError('Ugyldig appbruger.')
    target='/mnt/fjordhub/'+storage_id
    commands=f'''bash <<'FJORDSEED_STORAGE'
set -euo pipefail
ctid={shlex.quote(ctid)}
disk={shlex.quote(source)}
target={shlex.quote(target)}
uid={int(uid)}
gid={int(gid)}
mountpoint -q "$disk" || {{ echo 'Storagepoolen er ikke monteret'; exit 1; }}
[ "$(readlink -f "$disk")" = "$disk" ] || {{ echo 'Storagepoolens sti må ikke være et link'; exit 1; }}
source="$disk/fjordhub"
[ ! -L "$source" ] || {{ echo 'Mediemappen må ikke være et link'; exit 1; }}
config=$(pct config "$ctid")
if printf '%s\n' "$config" | grep -q '^lxc.idmap:'; then
  echo 'Denne LXC har brugerdefineret UID-map. Tilslut lageret manuelt i Proxmox.'; exit 1
fi
if printf '%s\n' "$config" | grep -q '^unprivileged: 1'; then uid=$((uid+100000)); gid=$((gid+100000)); fi
slot=''
for i in $(seq 0 255); do
  if ! printf '%s\n' "$config" | grep -q "^mp$i:"; then slot="mp$i"; break; fi
done
[ -n "$slot" ] || {{ echo 'Ingen ledige mountpunkter'; exit 1; }}
if printf '%s\n' "$config" | grep -Fq "mp=$target," || printf '%s\n' "$config" | grep -F "mp=$target" | grep -q "$target$"; then
  echo 'Mountpunktet findes allerede. Genindlæs lageroversigten eller kontrollér Proxmox.'; exit 1
fi
pct exec "$ctid" -- sh -c '[ ! -e "$1" ] || {{ [ -d "$1" ] && [ -z "$(ls -A "$1")" ]; }}' sh "$target" || {{ echo 'Målmappen indeholder allerede filer'; exit 1; }}
mkdir -p -- "$source"
if [ ! -e "$source/fjordseed" ] && [ ! -L "$source/fjordseed" ]; then install -d -m 0775 -o "$uid" -g "$gid" "$source/fjordseed"; fi
cp -- "/etc/pve/lxc/$ctid.conf" "/root/fjordseed-mount-$ctid-$(date +%Y%m%d-%H%M%S).conf"
pct set "$ctid" "-$slot" "$source,mp=$target,backup=0"
if pct exec "$ctid" -- mountpoint -q "$target"; then
  echo 'Lageret er tilsluttet. Genindlæs lageroversigten i Fjordseed.'
else
  echo 'Mountet er gemt. Genstart LXC, når igangværende uploads/afspilninger er afsluttet:'
  echo "pct reboot $ctid"
fi
FJORDSEED_STORAGE'''
    return {'ctid':ctid,'storage_id':storage_id,'path':target+'/fjordseed','commands':commands,
            'message':'Kør kommandoen i Proxmox Shell. Den deler lageret med FjordHubs LXC. Følg resultatet og genindlæs derefter lageroversigten.'}
