# Data til det nye tracker- og grafkort

Registreret 25. oktober 2026, inden det separate statistikkort på Oversigt blev erstattet af grafkortet. Dataintegrationen og de detaljerede kort under **Trackere** bevares. Redigering af grafkortets indhold er endnu ikke implementeret.

Kortet på Oversigt samler nu de faste kontotal, events og opdateringstid i venstre sektion og grafkarrusellen i højre sektion. På små skærme står sektionerne under hinanden. Kontovælgeren styrer begge sektioner. `trackerDetails()` bruges både her og under Trackere, så felter og formatering holdes ens.

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

`GET /api/trackers/<id>/history?mode=changes` returnerer `account` og `seedbox` med op til 60 ændrede værdier pr. graf, hver med det oprindelige tidspunkt i `at`. Uændrede målinger tilføjer ikke grafpunkter. Historikken gemmes lokalt i SQLite i op til 30 dage med 10 minutters intervaller. Ældre målinger bliver ikke rekonstrueret fra aktuelle totaler. Det ældre API med `days=1|7|30` understøttes stadig, men grafkortet har ingen periodeknapper.

| Graf | Historikfelt | Kilde og omfang |
| --- | --- | --- |
| Ratio | `ratio` | Trackerkontoen |
| Krediteret upload | `credited_uploaded` | Kontoens `stats.uploaded` |
| Krediteret download | `credited_downloaded` | Kontoens `stats.downloaded` |
| Reel upload | `real_uploaded` | qBittorrent, hele denne seedbox |
| Reel download | `real_downloaded` | qBittorrent, hele denne seedbox |

Reel trafik er **ikke fordelt pr. tracker**. Den må ikke præsenteres som kontoens reelle trafik. Historikken markerer huller og nulstillinger af de lokale trafiktællere.

Grafkortets kurve viser den **faktiske totalværdi** for hvert punkt, aldrig forskellen mellem målinger. Y-aksen tilpasses automatisk de viste værdier med lidt luft over og under kurven, så også små ændringer er synlige. Den nedre grænse bliver aldrig negativ. Akseteksten markerer den automatiske skala, og decimalerne tilpasses spændet, så aksemærkerne kan skelnes. X-aksen har plads til 60 ændringer med nyeste til højre; få punkter fylder fra højre, og tidligere punkter flytter mod venstre ved nye ændringer. Dato og klokkeslæt vises ved hover eller tastaturvalg. En faldende ratio bevæger sig ned til sin nye positive værdi. En markeret tællernulstilling afbryder kurven. Der indsættes ikke et opdigtet startpunkt på nul. Det mindre ændringstal ved siden af totalen er kun supplerende information.

De øvrige kontofelter ovenfor hentes aktuelt, men gemmes **ikke** som tidsserier. De kan bruges som faste nøgletal i et kommende redigerbart kort. Grafer for dem kræver først udvidelse af historikopsamlingen.

## Kode at genbruge

- `trackers.py`: validering, kontodata, opdateringer og registrering af kredittal.
- `tracker_providers.py`: understøttede trackere, API-adresser og interval.
- `tracker_history.py`: historikfelter, opbevaring, huller og nulstillinger.
- `static/trackers.js`: `trackerCard`, `trackerBytes` og `trackerNumber`; det detaljerede kort bruges fortsat under Trackere.
- `static/insights.js` og `templates/_insights.html`: grafkort, kontovalg, perioder og karrusel.

Et kommende layoutvalg bør gemme felt-id'er og placeringer, mens kilder, enheder og adgangskontrol fortsat styres af applikationen. Konto- og seedboxdata skal fortsat mærkes tydeligt.
