# Shared gateway verification — 2026-10-13

FjordSeed can select a FjordVPN gateway as well as a dedicated torrent profile.
It joins the same VPN namespace and leases a separate non-symmetric TCP/UDP
NAT-PMP port. HTTPS/Minecraft retain the first port. No torrent proxy, new rate
limit, Docker socket, capability or WireGuard credential is added to qBittorrent.

## Evidence

- 353 FjordSeed Python tests and 114 FjordVPN Python tests passed.
- Unit tests cover protocol/port/lifetime validation, renewal, port conflicts,
  failure closure, reserved-port protection, marked firewall cleanup, foreign
  ownership, unchanged speed settings and public-port reporting.
- A scoped desktop/mobile browser test covers both profile choices, public
  port display, persisted selection, stop and legacy TCP-profile rejection.
- The production-source Docker image built successfully.
- A disposable actual qBittorrent worker ran as UID/GID 1000 with a read-only
  root filesystem, all capabilities dropped and no-new-privileges. Its API
  confirmed tun0 binding, disabled UPnP, distinct listen/announce ports, zero
  download/upload limits and disabled alternative-speed mode.
- A receiver using the separate Seedbox VPN's public exit downloaded a complete
  256 KiB synthetic fixture through the gateway's extra port using plaintext
  TCP, required encrypted TCP and uTP/UDP. File hashes matched.
- Actual qBittorrent also downloaded a second 256 KiB fixture from a seeder on
  that other VPN exit. The file hash matched. These fixtures had no trackers.
- Simulated unhealthy VPN status stopped qBittorrent. Healthy status restored
  it with a newly leased public port. The underlying real VPN was kept running;
  this checks the independent supervisor gate, not an actual tunnel outage.
- Minecraft status continued returning Paper 1.16.5 during the public tests.
  Real production qBittorrent/VPN container start times remained unchanged;
  temporary mappings, firewall rules and containers were removed afterwards.

The initial same-port proxy experiment was rejected: it hid peer IPs and its
public UDP test failed. Direct extra-port testing succeeded from another VPN
exit and preserved that peer's public IP. An attempt from the same home uplink
produced misleading UDP results. A browser request from the second VPN exit
received Cloudflare HTTP 403, so website validation is done independently of
that torrent client; it is not used to claim a change in web routing.

## Limits and rollout

Tests establish real transfers and protection gates, not maximum throughput or
zero latency under every workload. Shared applications contend for the same VPN
capacity. Existing speed settings are preserved. A full physical tunnel outage
and long private-tracker seeding remain normal operational checks.

Update FjordVPN first for secret-free gateway discovery, then FjordSeed. Select
Gateway and save only when ready to restart the torrent client; files, resume
data and RSS settings are retained. Keep the old Seedbox profile for rollback.
Failure to obtain/renew matching TCP/UDP mappings blocks qBittorrent. Cleanup
addresses only its explicit private port, never private port zero or the first
gateway mapping. Marked firewall ownership is persisted for retry after errors.

The pre-existing broad browser script currently stops at its stale RSS ratio
step (the default keep-files mode hides that field). It was left unchanged;
the shared-gateway browser check is separate and passes.
