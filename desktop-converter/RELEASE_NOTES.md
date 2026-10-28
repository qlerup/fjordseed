Windows-installationspakke til Fjord-konvertering.

- Når FjordSeed sender en konvertering til pc'en, glider en popup op nederst til højre med filnavn, bitrate, status, fremdrift og forventet tid. Den vises også, når programmet kører i baggrunden, uden at tage tastaturfokus.

- HEVC bruger NVDEC-afkodning, når GPU'ens afkodningsfunktioner er verificeret. Det undgår den FFmpeg-softwareafkodningssti, hvor NVEncC crashede i `avcodec-63.dll` på den undersøgte 4K-fil.
- NVEncC's exitkode gemmes i loggen og vises ved fejl. En stoppet konvertering viser ikke længere et aktivt estimat på resterende tid.

- **Send til pc** starter GPU-konverteringen direkte fra netværksmappen med 20/30/40 Mbps. Ingen første download til pc-cache eller upload af resultatfilen.
- Efter kontrol flytter qBittorrent hele originaltorrentens mapper og filer til Seeder. Den konverterede udgave publiceres i Bibliotek med uafhængige kopier af undertekster.
- Fremdrift, forventet tid og afbrydelse vises i programmet. Seriepakker bevares intakte; senere afsnit kan konverteres uden at flytte originalpakken igen.

- Mappevalget deles automatisk med FjordSeed via den eksisterende pc-forbindelse og vises under den tilsluttede pc.
- Videofiler vises med søgning og mappegruppering i FjordSeed. Uden mappevalg afventes valget i programmet.

- Installation for den aktuelle Windows-bruger med startmenugenvej og valgfri skrivebordsgenvej.
- Afinstallation via Windows. Brugerens forbindelsesoplysninger og præferencer bevares.
- Program, NVEncC, FFmpeg og MKVToolNix er inkluderet; Python er ikke nødvendigt på mål-pc'en.
- Én FjordSeed-visning med Windows-mappevælger. Forbindelseskoden gemmes krypteret til Windows-brugeren.

Konverteringen starter fra filoversigten under den tilsluttede pc i FjordSeed. Det tidligere HTTP-downloadflow starter ikke.

Krav: Windows 10/11 64-bit, en kompatibel NVIDIA-GPU og driver samt adgang til bibliotekets netværksmappe.
