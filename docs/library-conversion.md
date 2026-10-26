# Konverter eksisterende film i Behold

Åbn **Indstillinger → Konvertering → Behold · Eksisterende film**. Listen læser
videofiler fra den aktuelle Behold/downloadplacering. Søg efter filmen, vælg
20/30/40 Mbps, og tryk **Send til pc**. Det er et eksplicit job til en tilsluttet
Windows-pc; indstillingen for automatisk konvertering af nye downloads og RSS
ændres ikke. En offline pc kan hente jobbet senere.

Forløbet er:

1. FjordSeed kontrollerer, at filmen tilhører én færdig qBittorrent-torrent.
   Delte/cross-seedede filer afvises, så en anden torrent ikke mister sine filer.
2. Der oprettes en arbejdskopi i den skjulte buffer. Hardlinks sparer plads;
   på tværs af underliggende diske bruges en kopi med kontrol af ledig plads.
   Kun den valgte video sendes til pc'en. Andre torrentfiler, undertekster og
   artwork bevares, men sendes ikke unødigt gennem pc'en.
3. Pc'en bruger jobbets bitrate og returnerer filmen. Den eksisterende broker
   kontrollerer spor, opløsning, HDR, kapitler og øvrige bevaringskrav.
4. Først efter godkendelsen kaldes qBittorrents `setLocation`. Hele torrentens
   originalmateriale flyttes til `/downloads/Seeder/<navn>-<job-id>`. FjordSeed
   opretter selv `Seeder` i sin faste downloadrod ved opstart og kontrollerer
   løbende, at mappen er skrivbar. Den ligger uden for det valgte FjordFlix-bibliotek.
   På Medier-netværksdrevet deles den som `M:\Seeder` ved siden af `Bibliotek`.
   Eksisterende jobs beholder deres journalførte placering.
5. FjordSeed afventer qBittorrents bekræftede placering og kontrollerer filerne
   igen. Derefter publiceres den komplette konverterede video på bibliotekets
   gamle plads; uændrede ledsagefiler bevares. MP4/AVI osv. får MKV-filendelse.

**Behold forbliver Behold.** Ingen ny automatisk sletning tilføjes. Originalen
bevares i seedingmappen med de eksisterende ratio-, tids- og sletteregler.
Seedingafslutning udsættes, mens konvertering/flytning er under behandling.
En automatisk torrentplacering skiftes til manuel placering ved flytningen,
så en kategori ikke efterfølgende flytter originalen tilbage til biblioteket.

Den færdige film får mærket **Konverteret**, bitrate og tidspunkt i listen.
En lille `<film>.mkv.fjordseed.json` gemmer oplysningerne ved filmen, så de
overlever genstart. Eksisterende `.fjordseed-converted.json`-kvitteringer fra
konvertering af nye downloads genkendes også. Verificerede rapportfiler fra
Windows-programmets lokale konvertering genkendes, hvis de følger med filmen. Videofilens titel ændres ikke.

Filnavnskollisioner, ændrede originaler og uventede torrentplaceringer stopper
publiceringen. Ingen eksisterende biblioteksfil overskrives. Forløbet er
journalført og kan fortsætte efter genstart. Før qBittorrent begynder at flytte,
kan et job annulleres; kun arbejdsfiler fjernes, og originalen bliver i Behold.
Fejlede pc-jobs kan genstartes med **Prøv igen**.

Filer uden en entydig torrent vises med forklaring og kan ikke sendes gennem
dette forløb, fordi deres original ikke kan flyttes via qBittorrent. Biblioteket
skal understøtte hardlinks til den eksklusive publicering. Højst 5.000 videofiler
vises i én liste; brugerfladen viser 100 ad gangen med søgning.

Verifikation: `tests/test_library_conversion.py` dækker journal, kollisioner,
bevaring, genstart, flere diske, annullering og metadata. Den særskilte native
test køres kun i en disponibel, netværksisoleret testcontainer med
`FJORDSEED_TEST_QBIT_BINARY=1`; den flytter en syntetisk torrent med en rigtig
qBittorrent og rechecker originalen på den nye placering. Den udfører ingen
GPU-konvertering af rigtige film.
