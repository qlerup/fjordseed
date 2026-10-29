# Konvertering på en tilsluttet pc

## Kø i pc’ens filoversigt

**Sæt i kø** gemmer valgte biblioteksfiler på serveren. Flere filer behandles
efter hinanden, også efter genstart. Ventende jobs kan fjernes fra køen.
Pc’en foretrækkes, når dens program er online; efter 45 sekunder uden kontakt
kan næste job behandles af serverens installerede GPU-service. Uden en klar
GPU-service bliver køen stående, til pc’en vender tilbage.

Pc’en skal reservere jobbet på serveren, før encoding starter. Et reserveret
eller påbegyndt job skifter ikke maskine ved et forbindelsesudfald. Et job,
der blev sendt til en pc, som forsvandt før reservationen, kan derimod overtages
atomisk af serveren. Når pc’en kommer tilbage, får den ingen besked om at starte
serverens job. Køen fortsætter efter verificering og qBittorrents publicering.

Serveren får kun adgang til arbejdsmapperne. Originaltorrentens flytning til
Seeder og den kontrollerede publicering i Bibliotek går gennem samme forløb
som ved pc-konvertering. Den langsommere server-GPU deler kapacitet med Plex.

FjordSeed kan sende konverteringsarbejdet til Windows-programmet i
[`desktop-converter`](../desktop-converter/README.md). Pc’en kontakter selv
FjordSeed og behøver ingen indgående port. Serveren behøver ingen GPU til denne
tilstand; FFprobe/MKVToolNix til serverens kontrol følger med app-imaget.

## Opsætning

1. Opdatér FjordSeed og pc-programmet fra samme udgivelse.
2. Åbn **Indstillinger → Konvertering** i FjordSeed.
3. Opret et pc-token med et genkendeligt navn. Tokenet vises kun ved oprettelse.
4. Åbn **FjordSeed-forbindelse** i pc-programmet. Indsæt FjordSeed-adressen og
   tokenet, vælg lokal midlertidig plads, og tryk **Forbind og hent jobs**.
5. Pc’en tester faktisk NVENC/HEVC-encoding og melder sig klar.
6. Vælg **En tilsluttet pc** i FjordSeed, slå konvertering til, og gem.
   Vælg derefter konvertering på den manuelle download eller RSS-feedet.

En opdatering aktiverer ikke konvertering, opretter ikke tokens og forbinder ikke
pc’er af sig selv. Der er fortsat separate valg for server-GPU og pc. Valget
gemmes på den enkelte nye download; eksisterende jobs skifter ikke automatisk
maskine, når det globale valg ændres.

## Filernes livscyklus

- Originalen downloades i den normale buffer og bliver dér til seeding.
- Et færdigt, godkendt torrent-filmanifest bliver til et konverteringsjob.
- En pc reserverer jobbet i 180 sekunder og fornyer reservationen hvert 10. sekund.
- Den henter originalfilerne i kontrollerede blokke på højst 8 MiB. Afbrudt
  overførsel genoptages fra sidste gemte blok på samme pc.
- Video konverteres med samme NVEncC-indstillinger som lokal konvertering.
  Andre valgte filer kopieres uændret.
- Resultatet uploades i blokke. En gentaget blok kan kvitteres igen uden at
  fordoble filens indhold. Et færdigt lokalt resultat genbruges efter afbrydelse.
- Serveren retter sporflag og kontrollerer video, HDR/DV/RPU, varighed, lyd,
  undertekster, vedhæftninger og kapitler. Pc’ens egen godkendelse er ikke nok.
- Alle valgte filer skal bestå. Først derefter skrives den normale
  konverteringskvittering, og den færdige mappe publiceres atomisk til den
  biblioteksplacering, der blev gemt for downloadet.
- Originalen slettes fortsat først efter **både** godkendt/publiceret konvertering
  **og** reel ratio mindst 1:1 **eller** 49 timers aktiv seeding.
- Efter serverens kvittering rydder pc’en sin egen midlertidige UUID-jobmappe.
  Ved fejl beholdes cache og originale serverfiler til genoptagelse/undersøgelse.

Hvis en pc forsvinder, udløber reservationen, og et andet tilsluttet program kan
overtage. En gammel reservation kan ikke uploade eller publicere bagefter.
Fejlede konverteringer kan genstartes fra downloadens detaljer.

## Adgang og afgrænsning

Pc-tokens er tilfældige, individuelle og gemmes kun som SHA-256 på serveren.
De giver adgang til tildelte konverteringsjobs, ikke browser-login,
trackercredentials, vilkårlige filstier eller almindelige app-indstillinger.
Tilbagekald adgang i Konvertering-fanen. På Windows gemmes tokenet med DPAPI,
knyttet til den aktuelle Windows-bruger. Det indgår ikke i logs eller Git.

Brug HTTPS til forbindelser over internettet; HTTP er beregnet til et betroet
lokalnet. Klienten følger ikke redirects med sit token og bruger ikke miljøets
HTTP-proxy. Serveren vælger alle filstier ud fra det betroede jobmanifest.
Klienten kan kun angive filindeks og interval, aldrig en kilde- eller målsti.

Filadgang og validering kører i en helper med skriveadgang til de kendte
`.incomplete`-mapper og læseadgang til RPC. Den har ingen netværksadgang,
Docker-socket eller GPU, har read-only systemdisk, kører som PUID/PGID og er
begrænset til 1 GiB RAM og 2 CPU-kerner. Højst to lange valideringer optager
samtidig appens HTTP-tråde. Serveren kontrollerer uploadstørrelse og filblokke.

## Worker-API, version 1

Alle worker-kald kræver `Authorization: Bearer fsw_…`. Jobkald kræver desuden
den aktuelle reservation: `X-Job-Lease`. Browsercookies giver ikke adgang til
worker-endpoints. Tokenoprettelse/tilbagekaldelse og indstillinger kræver normalt
administrator-login og CSRF-token.

| Kald | Formål |
|---|---|
| `POST /api/conversion/worker/heartbeat` | Meld GPU-test klar; forny eventuelt job |
| `POST /api/conversion/worker/claim` | Hent/reservér et job eller `null` |
| `GET …/jobs/<id>/files/<index>?offset=<bytes>` | Hent næste kildeblok |
| `PUT …/jobs/<id>/files/<index>?offset=<bytes>` | Upload næste resultatblok |
| `POST …/jobs/<id>/verify` | Kontrollér returneret fil på serveren |
| `POST …/jobs/<id>/complete` | Godkend hele jobbet til normal publicering |
| `POST …/jobs/<id>/fail` | Markér en fejlet konvertering; bevar originalen |

## Verifikation og tilbageførsel

En flytning mellem filsystemer kan ændre originalernes tidsstempler. Hvis det
sker, kontrollerer FjordSeed alle v1-torrentens stykker mod de originale
kontrolsummer, før resultatet publiceres. Samme størrelse alene godkendes ikke.
Kontrollen kræver en komplet, uomdøbt filliste og understøttede kontrolsummer;
ellers bevares filerne med en tydelig fejl. Et allerede konverteret job kan
fortsætte fra flytningen efter opdatering uden at kode filmen igen.
Indholdskontrollen afslutter ét kort stykke arbejde ad gangen og gemmer et
kontrolpunkt ved en verificeret stykkegrænse. Mellem bidderne opdateres status,
og VPN-forbindelsen kontrolleres. En genstart genoptager kontrollen fra seneste
kontrolpunkt, så længe originalernes fingeraftryk er uændrede.
Seedede torrenten før flytningen, genoptages den automatisk efter godkendt
publicering, hvis qBittorrent har efterladt den stoppet. Et fejlet startkald kan
gentages efter genstart uden ny konvertering. En bevidst pause før flytningen
eller et senere manuelt stop ophæves ikke af efterfølgende oprydning.

Pc-programmet og weboversigten viser særskilt metadataarbejde, resultatkontrol,
flytning og indholdskontrol. Billeder/s og resterende kodetid vises kun under
selve kodningen. En serverfejl under flytning vises som fejl, også når jobbets
seneste fase fortsat hedder `moving`.

For nye downloads/RSS med konvertering valgt kontrolleres hver videos samlede
bitrate. Kun værdier over den valgte videobitrate plus 5 % konverteres;
ved 30 Mbps er grænsen 31,5 Mbps. Filer under grænsen bevares uændret.
Reglen aktiverer ikke konvertering og scanner ikke det eksisterende bibliotek.
Manuelt valgte biblioteksjobs beholder deres udtrykkelige konverteringsvalg.

Regressionstests ligger i `tests/test_remote_*.py`, desktop-tests i
`desktop-converter/test_*.py`, og browserforløbet i `tests/browser_conversion.py`.
Et isoleret server/RTX 4090-forløb er testet med en 4K Dolby Vision-prøve,
2 lydspor og 54 undertekstspor, inklusive gentaget uploadblok og normal
bibliotekspublicering med uændret original.

Ved rollback: slå nye konverteringer fra, og lad accepterede pc-jobs blive
færdige først. Tag backup af app-data og buffer. En gammel serverversion forstår
ikke pc-reservationer og må ikke bruges til at behandle disse jobs.
