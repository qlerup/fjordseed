# Data til det nye tracker- og grafkort

Registreret 25. oktober 2026, inden det separate statistikkort på Oversigt blev erstattet af grafkortet. Dataintegrationen og de detaljerede kort under **Trackere** bevares. Redigering af grafkortets indhold er endnu ikke implementeret.

## Kontoens aktuelle tal

`GET /api/trackers` leverer konti med `id`, `name`, `provider`, `username`, `status`, `error`, `updated_at`, `stats` og `events`. NordicBytes og Sagmire understøttes gennem de faste API-adresser i `tracker_providers.py`. Kontodata opdateres hvert 10. minut. API-nøgler indgår ikke i det offentlige svar.

| Tidligere kortfelt | Felt i `stats` | Betydning |
| --- | --- | --- |
| Upload | `uploaded` | Trackerens krediterede upload, bytes |
| Download | `downloaded` | Trackerens krediterede download, bytes |
| Ratio | `ratio` | Kontoens ratio |
| Buffer | `buffer` | Trackerens oplyste buffer, bytes |
| Seeding | `seeding` | Antal seedende torrents på kontoen |
| Downloader | `leeching` | Antal downloads på kontoen |
| Shards | `seedbonus` | Trackerens bonuspoint |
| Hit-and-runs | `hit_and_runs` | Trackerens oplyste antal |
| Advarsler | `warnings` | Summen af gyldige `hnr`- og `manual`-advarsler |
| Seeding-størrelse | `seeding_size` | Samlet seedingstørrelse, bytes |
| Uploads | `total_uploads` | Antal uploads til trackeren |

Kortet viste desuden kontonavn, brugernavn, forbindelsesstatus, fejl, sidste opdatering og tracker-events med deres sluttid. Manglende numeriske felter vises som ukendte, ikke som nul. Kontoens tal kan inkludere aktivitet fra andre klienter.

## Eksisterende grafer og historik

`GET /api/trackers/<id>/history?days=1|7|30` returnerer `account` og `seedbox`. Historikken gemmes lokalt i SQLite i op til 30 dage med 10 minutters intervaller. Ældre målinger bliver ikke rekonstrueret fra aktuelle totaler.

| Graf | Historikfelt | Kilde og omfang |
| --- | --- | --- |
| Ratio | `ratio` | Trackerkontoen |
| Krediteret upload | `credited_uploaded` | Kontoens `stats.uploaded` |
| Krediteret download | `credited_downloaded` | Kontoens `stats.downloaded` |
| Reel upload | `real_uploaded` | qBittorrent, hele denne seedbox |
| Reel download | `real_downloaded` | qBittorrent, hele denne seedbox |

Reel trafik er **ikke fordelt pr. tracker**. Den må ikke præsenteres som kontoens reelle trafik. Historikken markerer huller og nulstillinger af de lokale trafiktællere.

Grafkortet viser den aktuelle total til venstre og ændringen fra første måling som kurve. X-aksen dækker hele den valgte periode frem til nu, så en kort historik begynder ved højre kant. Y-aksen viser ændring i datamængde eller ratio med nul som reference. Ved en markeret tællernulstilling afbrydes kurven, og det nye forløb får sit eget nulpunkt. Perioder uden målinger udfyldes ikke med opdigtede værdier.

De øvrige kontofelter ovenfor hentes aktuelt, men gemmes **ikke** som tidsserier. De kan bruges som faste nøgletal i et kommende redigerbart kort. Grafer for dem kræver først udvidelse af historikopsamlingen.

## Kode at genbruge

- `trackers.py`: validering, kontodata, opdateringer og registrering af kredittal.
- `tracker_providers.py`: understøttede trackere, API-adresser og interval.
- `tracker_history.py`: historikfelter, opbevaring, huller og nulstillinger.
- `static/trackers.js`: `trackerCard`, `trackerBytes` og `trackerNumber`; det detaljerede kort bruges fortsat under Trackere.
- `static/insights.js` og `templates/_insights.html`: grafkort, kontovalg, perioder og karrusel.

Et kommende layoutvalg bør gemme felt-id'er og placeringer, mens kilder, enheder og adgangskontrol fortsat styres af applikationen. Konto- og seedboxdata skal fortsat mærkes tydeligt.
