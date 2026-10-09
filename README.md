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

Efter valg af magnetlink eller torrentfil angives stop-ratio og filhandling i et separat trin, inden torrenten starter. qBittorrent gemmer reglerne pr. torrent og stopper selv ved den valgte ratio eller 48 timers seeding, også efter en genstart. Standardhandlingen bevarer filerne. Automatisk sletning skal vælges aktivt og fjerner både torrenten og dens downloadede filer. Stop-ratio under 1 bliver hævet til 1. Automatisk stop sker ved den valgte ratio eller 48 timers seeding. Eksisterende torrents bevarer deres mål og filhandling; Green-korrektionen kan tilpasse den underliggende qBittorrent-grænse.

Ved manuel tilføjelse vises også forventet tracker-ratio efter fuldt download: upload / (registreret download + torrentstørrelse × (1 − freeleech/100)). Størrelsen læses fra torrentfilen (v1/v2) eller et eksakt tracker-match for magnetlinks. 100 % freeleech tæller som 0 ekstra download; delvis freeleech reducerer det tilsvarende. Ukendt freeleech regnes forsigtigt som almindelig download og markeres. Kontotal skal være tilgængelige og højst ti minutter gamle. Ved manglende tracker-match kan en eksplicit valgt konto bruges med filens størrelse og ukendt freeleech. Ratio ≤ 0,5 viser en advarsel, men blokerer ikke download. Beregningen medregner hverken fremtidig upload, andre aktive downloads eller eventuelle senere ændringer af trackerfordele. Dobbelt upload tæller først ved faktisk upload. Den forventede kontoratio er adskilt fra qBittorrents stop-ratio pr. torrent.

## Trackerkonti

Tilføj NordicBytes under Trackere med en API-nøgle, der må læse kontodata. Downloads viser trackerens samlede upload, download, ratio, buffer, seeding, bonuspoint og advarsler pr. konto. Disse tal kan afvige fra qBittorrents lokale tal og ratio. Kontodata hentes i baggrunden højst hvert femte minut samt efter ændring af opsætningen. Ved udfald vises senest hentede tal med tidspunkt og fejlstatus. Nøgler lagres i /data/trackers.json med rettigheder 0600, returneres aldrig til browseren og deles ikke med qBittorrent-containeren. Redigering med tomt nøglefelt bevarer den eksisterende nøgle. Fjernelse af tracker berører ikke torrents eller filer. Andre udbydere kræver en separat API-integration.

## Fordele pr. torrent

Næste i torrentdialogen læser filens info-hash og navn (eller magnetlinkets btih/btmh), og viser opslaget ved seed-indstillingerne. Der foretages aldrig kald til announce-URLer fra filen. NordicBytes ignorerer de testede hash-filterparametre, så appen laver et afgrænset navneopslag og kræver et eksakt info-hash-match. Rene v2-filer bruger SHA-256; hybridfiler understøtter begge hashes. Manglende match eller API-adgang vises som ukendte fordele og blokerer ikke download. Opslag kører i baggrunden, caches fem minutter og begrænses til 50 resultater pr. side og tre sider pr. navnevariant. Torrentkort slås også op automatisk, når deres navn og hash er kendt. Featured-torrents behandles som 100 % freeleech og dobbelt upload efter [NordicBytes-definitionen i Prowlarr](https://github.com/Prowlarr/Indexers/blob/master/definitions/v11/nordicbytes.yml). Badgefordele som Double upload ændrer ikke den lokale ratio. Green-reglen nedenfor korrigerer stop-ratioen for halv uploadkredit.

## RSS-feeds og adskilte downloads

Downloads viser manuelt tilføjede torrents. RSS-feeds har sin egen oversigt over feeds og deres torrents. Begge viser fremdrift, procent, resterende tid og hastigheder. RSS-torrents beholder deres oprindelse, selv hvis feedet fjernes.

Hvert feed har en undermappe i den downloadplacering, der blev valgt i FjordHub, en stop-ratio og valg mellem at bevare filer eller automatisk slette torrent og filer. Tom mappe bruger hovedmappen. Et valgfrit titelfilter følger qBittorrents RSS-matchregler. Nye feeds er på pause; aktivér automatisk download for at hente matchende poster, inklusive eksisterende poster i feedet. Indstillingsændringer gælder nye downloads. Fjernelse af et feed bevarer eksisterende torrents og filer.

qBittorrents indbyggede RSS-motor henter feeds og torrents gennem VPN-forbindelsen og gemmer seeding-reglerne pr. torrent. FjordSeed henter ikke RSS-adresser fra administrationscontaineren. RSS starter først, når reglerne er synkroniseret og VPN-kontrollen er bestået. Feed-adresser kan indeholde passkeys og gemmes med rettigheder 0600; de returneres ikke til browseren. Tomt adressefelt ved redigering bevarer den gemte adresse.

RSS-feeds oprettes og redigeres i en modal. Med en gemt, verificeret aktiv NordicBytes-API-nøgle kan et feed kræve 100 % Freeleech, Double upload, Featured, Internal og Refundable. Alle valgte badges skal være bekræftet for samme info-hash hos den valgte tracker; delvis freeleech opfylder ikke 100 %-kravet. Uden aktiv API-adgang skjules valgene. Eksisterende krav bevares ved API-fejl, og automatisk download blokeres, indtil adgangen er aktiv igen. Badgekontrol understøttes aktuelt kun for NordicBytes-feeds.

Feeds med badgekrav har deres native downloadregel slået fra. En separat kontrol henter kun torrentmetadata inde i VPN-containeren, slår det eksakte hash op hos trackeren og tilføjer først den verificerede torrent med feedets mappe, tag og seeding-regler. Ukendte, manglende eller forældede fordele starter ingen download. Afviste poster kontrolleres igen senere. Feeds uden badgekrav beholder qBittorrents almindelige RSS-download. Tracker-API-nøgler bliver i administrationscontaineren. Historik og afventende metadata ligger under `DATA_DIR/qbit/rss-*`; bevar dem ved backup. Ved en tvetydig fejl under tilføjelse registreres forsøget for at undgå gentagne downloads; kontrollér klienten før manuel gentagelse.

Ved rollback til en version uden badgekontrol skal feeds med badgekrav først sættes på pause, da ældre versioner ikke forstår kravene.

RSS-feeds kan også kræve et minimum af downloadere (leechere), fra 0 til 1000000. 0 betyder intet minimum; 50 kræver mindst 50 leechere hos den valgte tracker. Kravet kan bruges alene eller sammen med badges. Antallet skal være bekræftet for samme info-hash ved et opslag under 30 sekunder gammelt. Manglende tal eller API-fejl blokerer download. Trackeren opdaterer tallene via klienternes announces, så de er senest registrerede tal. Kravet gælder ved start og stopper ikke en igangværende torrent, hvis antallet falder.

Manuelt stop og fjernelse er altid muligt efter bekræftelse. Hvis torrenten hverken har krediteret ratio mindst 1:1 eller 48 timers aktiv seeding, vises en advarsel med den aktuelle ratio og tid. Den manuelle advarsel afhænger ikke af den valgte automatiske stop-ratio. Serveren genkontrollerer tallene ved handlingen og kræver eksplicit bekræftelse ved tidligt stop. Torrentkortene viser seedingtid og ratio. qBittorrents gemte seedingtid bruges på tværs af genstarter. Eksisterende torrents får tidsgrænsen 2880 minutter med deres eksisterende filhandling bevaret og stop-ratio hævet til mindst 1.


## Green-upload og redigering af ratio

Ratio-knappen kan ændre stopmålet og valget mellem at beholde eller slette filerne på en eksisterende torrent uden genstart. Det aktuelle valg vises i dialogen, og manuel pause ophæves ikke. Hvis målet allerede er nået, advarer dialogen om, at automatisk sletning kan ske ved gemning. API-kald uden filhandling bevarer den eksisterende handling. Målet eller 48 timers seeding kan stadig udløse automatisk stop/sletning.

Et eksakt NordicBytes-match bruger trackerens tidszoneangivne `created_at`, ikke tidspunktet for lokal tilføjelse. Green-perioden regnes konservativt som 24 timer plus 30 minutters buffer. Upload i perioden tæller halvt, senere upload tæller fuldt. Et mål på 1 kræver dermed lokal ratio 2, hvis al upload sker i perioden. Ved blandet upload bruges `uploadkredit = uploadet i alt - Green-upload / 2`. Tidligere Green-upload får aldrig ekstra kredit ved udløb. Uploadkredit og krediteret ratio vises separat fra de faktiske uploadbytes. Verificerbare egne uploads er undtaget; anonyme uploadere kan ikke identificeres sikkert og behandles konservativt.

Arbejdsklienten registrerer uploadtælleren mindst hvert 10. sekund og tilpasser qBittorrents native ratio-grænse til det valgte kreditmål. Et interval over udløbstidspunktet regnes helt til halv kredit, så den kan seede en smule ekstra. Regnskab og brugerens mål gemmes atomisk under `DATA_DIR/qbit/green-credit.json` med en proceslås. Denne fil skal med i backup. Ved eksisterende torrents kan historiske uploadbytes ikke fordeles præcist; hvis de kan være uploadet i Green-perioden, regnes de forsigtigt til halv kredit og markeres som et estimat. Torrents tilføjet efter perioden får fuld kredit.

Datoer hentes også i baggrunden for RSS-torrents uden en åben browser. Gemte trackerfordele behøver kun et ekstra opslag ved migrering fra en version uden oprettelsesdato. API-nøglen deles ikke med arbejdsklienten. Mens et opslag afventer, er målet konservativt fordoblet. Uden en konfigureret API-konto kan Green ikke dokumenteres, og normal ratio anvendes. Med en API-konto, men uden verificerbar dato, bevares det konservativt fordoblede mål og markeres i visningen. Mislykkede/ukendte opslag prøves igen efter opslagscachens fem minutter; et verificeret resultat fryses fortsat. Green-regnskabet beregner stopmålet pr. torrent, ikke trackerens samlede kontoratio eller andre bonusmultiplikatorer. Bufferen forlænger ikke trackerens faktiske freeleech-periode.
