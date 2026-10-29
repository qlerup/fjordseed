# Dolby Vision-opbevaring

Nye DV-konverteringer bruger samme `prepare_output` på Windows og server:
NVEncC → mediekontrol → reversibel HDR10-udgave + `.mkv.fjord-dv.zip` →
kontrol af HDR10 og arkiv → publicering af begge filer. Ældre pc-klienters DV-
resultater får samme efterbehandling på serveren. Legacy HTTP-job sender DV-filen
og laver arkivet på serveren, da transporten kun overfører mediefiler.

Under **Indstillinger → Konvertering → Gemte Dolby Vision-konverteringer** vises
film og episoder med arkiver i tilsluttede biblioteker. Søgefeltet filtrerer på
filsti. Gendannelse køres asynkront i qBittorrent-containerens afgrænsede lager,
og bruger ingen GPU. Status gemmes i `/config/dolby-vision.json`; proces- og
ledgerlåse forhindrer samtidige gendannelser. Køen genoptages, når listen åbnes
efter en container-genstart. Arkivet beholdes efter gendannelse.

Dolby Vision RPU-NAL-enheder erstattes med HEVC filler, og MKV-konfigurationen
med Void. Billeddata, lyd, tidsstempler og filstørrelse ændres ikke. Originale
bytes inklusive berørte CRC-felter opbevares komprimeret. Et gendannet resultat
skal have præcis samme SHA-256 som den kontrollerede DV-fil før arkivering.
En ændret HDR-fil, beskadiget backup eller utilstrækkelig plads afvises.
Udskiftningen sker først efter kontrol af hele arbejdskopien. Ingen seedende
original eller andre hardlinks ændres ved udskiftningen.

Kun HDR10-kompatibel profil 8.1 arkiveres. Profil 7 konverteres som hidtil til
8.1 uden enhancement layer; den oprindelige profil 7 kan ikke genskabes fra
arkivet. Ikke-understøttede MKV-layouts afvises og originalen beholdes.

Behold arkivet ved siden af filmen, også ved manuel flytning. Ældre konverteringer
uden arkiv vises ikke automatisk. En rollback af app-koden skal bevare begge
filer; gamle app-versioner viser ikke gendannelseslisten. Gendannelse aktiverer
Dolby Vision igen, så den berørte Plex-app kan igen få afspilningsproblemer,
indtil dens fejl er rettet. Plex kan have behov for at analysere den ændrede fil.
