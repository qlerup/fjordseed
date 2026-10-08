# FjordSeed

En separat seedbox-app i FjordHub. qBittorrent installeres med appen; FjordVPN
administrerer Proton-profilerne. Ingen torrent starter under installationen.

## Installation

1. Installér/opdatér FjordVPN i FjordHub på samme Docker-vært.
2. Installér FjordSeed fra appkataloget. Vælg appdata og downloads med FjordHubs
   normale lager-/mappevælger. Angiv UID/GID med skriveadgang til downloadmappen.
3. Opret en ny Proton WireGuard-profil med NAT-PMP i FjordVPN. Start profilen
   med **TCP-videresendelse slået fra**. Porten skal bruges af qBittorrent.
4. Åbn FjordSeed, vælg profilen, og tryk **Start seedbox**.
5. Når VPN-status er klar, tilføj magnetlinks eller `.torrent`-filer.

FjordHub-login og administratorrettigheder kræves i en administreret installation.
Adgang kontrolleres løbende hos FjordHub. Standalone: kopiér `.env.example` til
`.env`, angiv absolutte datastier, kør `docker compose up -d --build`, og læs
førstegangsadgangskoden fra `DATA_DIR/initial-login.txt` (brugernavn `admin`).
Åbn `http://SERVER-IP:8099`. FjordVPN skal fortsat køre på samme Docker-vært.

## Netværk og stop

- qBittorrent får **kun** `network_mode: container:<valgt-vpn-id>`; ingen egen
  bridge, host-network, offentlig WebUI-port eller Docker-socket.
- Gluetuns firewall er kill switch. qBittorrent bindes til `tun0`, UPnP slås fra,
  og DNS går til Gluetuns resolver på `127.0.0.1` i VPN-netværket.
- Supervisoren kræver frisk VPN-status, aktivt VPN-netkort, sundhedstjek og en
  tildelt Proton-port før qBittorrent startes. Ved VPN-fejl stoppes processen.
- Porten opdateres i qBittorrent via dens lokale API. VPN-restart eller profilskift
  genopretter qBittorrent-containeren med den rigtige netværksnamespace.
- Ét qBittorrent-instance pr. VPN-profil; profilen kan ikke samtidig bruges som
  FjordVPN TCP-relay. TCP og UDP fra qBittorrent forbliver i VPN-netværket.
- Stoppes FjordSeed, stoppes dens qBittorrent-container. Stop af FjordVPN blokerer
  torrenttrafik. Gemte torrents genoptages, når den valgte VPN bliver klar igen.
- qBittorrents API lytter kun på loopback. FjordSeeds backend udfører en begrænset
  liste af handlinger via Docker exec; der er ingen generel API-proxy.

Panelet viser højst 500 torrents. **Fjern** bevarer altid downloadede filer.
Downloadmappen kan deles med andre apps gennem et fælles mount og passende
filrettigheder. Der ændres ikke rekursivt på ejerskab af eksisterende downloads.
Forbindelsen fra browser til kontrolpanelet er almindelig lokal webtrafik;
VPN-kravet gælder torrentklientens trafik.

## Drift

Appen kræver Docker-socket som FjordVPN og skal behandles som administration af
Docker-værten. Brug et betroet lokalnet eller HTTPS og adgangskontrol. FjordSeed
har ingen Proxmox-adgang og får ikke VPN-profiler eller private nøgler monteret.
Den læser kun en filtreret profiloversigt og VPN-statusfiler.

Backup: `DATA_DIR` og `DOWNLOADS_DIR`. `docker compose down --remove-orphans`
fjerner appens runtime; bind-mounts bevares. Stop seedboxen før rollback.
En igangværende VPN-download kan blive afbrudt kort under opdatering og genoptages
fra de gemte qBittorrent-data.

## Test

`python -m pytest tests -q` og `python tests/browser_check.py`.
`tests/container_check.py` køres i app-imaget med `--network none`; den tester
ægte qBittorrent-konfiguration, portskift og blokering uden VPN, uden downloads.
En rigtig end-to-end-test med Proton kræver en ny brugerleveret VPN-profil.

## Klar til installation

- Build, login, mobil/desktop, VPN-binding, automatisk portskift, stop ved
  manglende VPN og mappeflytning er testet. Før brug med egne downloads:
  kontrollér offentlig VPN-IP, test et lovligt testdownload, stop VPN'en og
  kontrollér at trafikken stopper. Denne Proton-test er endnu ikke udført.
- Opdatér både FjordHub (flytning af lager) og FjordVPN (profilintegration).
  Vælg lager under installation, opret en separat Proton-profil og vælg den i appen.
- Ved fejl: stop FjordSeed, bevar data/downloads og vend tilbage til den
  tidligere appversion. Flytning af lager beholder originalerne ved kopiering.
- Mulige senere forbedringer: kategorier, hastighedsgrænser og søgning i torrents.

Netværksmodellen følger [Gluetuns containerintegration](https://github.com/qdm12/gluetun-wiki/blob/main/setup/connect-a-container-to-gluetun.md).
Klientstyring følger [qBittorrents Web API](https://github.com/qbittorrent/qBittorrent/wiki/WebUI-API-%28qBittorrent-5.0%29).

## Seeding-ratio

Efter valg af magnetlink eller torrentfil angives stop-ratio og filhandling i et separat trin, inden torrenten starter. qBittorrent gemmer reglerne pr. torrent og stopper selv ved den valgte ratio, også efter en genstart. Standardhandlingen bevarer filerne. Automatisk sletning skal vælges aktivt og fjerner både torrenten og dens downloadede filer. Ratio 0 stopper efter afsluttet download. Eksisterende torrents ændres ikke.
