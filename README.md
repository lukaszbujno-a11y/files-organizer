# 

# files-organizer
Application to organise files

# Założenia

Wejście:

katalog ze zdjęciami i filmami,
dostęp do kalendarza (Google Calendar, Outlook lub plik ICS),
lista telefonów/aparatów (rozpoznawana z EXIF).

# Dane wykorzystywane:

data i godzina wykonania zdjęcia (EXIF DateTimeOriginal),
model telefonu/aparatu (EXIF Model),
wydarzenia z kalendarza:
nazwa,
początek,
koniec,
lokalizacja (opcjonalnie),
tag

# Logika działania
Odczytaj wszystkie wydarzenia z kalendarza.
Odczytaj metadane każdego zdjęcia.
Znajdź wydarzenie, którego zakres czasu obejmuje godzinę wykonania zdjęcia.
można dodać margines ±2 godziny.
Jeśli wydarzenie zostało znalezione:
utwórz katalog w strukturze np:
2026/
    07/
        2026-07-15 Wakacje Chorwacja

Skopiuj lub przenieś zdjęcie do katalogu w zaleznosci od ustawienia.
Jeżeli zdjęcie nie pasuje do żadnego wydarzenia:
Nieprzypisane/
    2026-07

Uwzględnienie telefonu (opcja opcjonalna)
Model telefonu można wykorzystać np. do rozdzielenia zdjęć na postawie tagu informacji w kalendarzu o osobie która jest na dydarzeniu. Doposowanie na postawie słownika TAG - TELEFON (marka model) - KATALOG NADRZEDNY

Dodatkowe dopasowanie
Jeżeli wydarzenia nachodzą na siebie:
utwórz katalog w strukturze np:
2026/
    07/
        2026-07-15 Niedopasowane

## Reguły przypisywania (kalendarz → lokalizacja → data)

Oprócz kalendarza zdjęcie można przypisać na podstawie lokalizacji lub samej daty.
Reguły ustawia się w `config.yaml` (`rules`) — są sprawdzane po kolei i wygrywa
pierwsza pasująca. Domyślnie włączony jest tylko kalendarz:

| Reguła     | Kiedy pasuje                                                                 | Katalog                               |
|------------|------------------------------------------------------------------------------|---------------------------------------|
| `calendar` | zdjęcie mieści się w wydarzeniu (± `margin_hours`)                           | `2026/07/2026-07-15 Wakacje Chorwacja` |
| `location` | GPS z EXIF wskazuje kraj inny niż `home_country`                             | `2026/07/2026-07-15 Chorwacja-Split`  |
| `date`     | z danego dnia do tej reguły dotarło **więcej niż** `date_group_threshold` (domyślnie 5) zdjęć | `2026/07/2026-07-15`                  |

Zdjęcia przypisane przez wcześniejszą regułę nie liczą się do progu reguły `date`.
Kolejność można zmienić (np. `rules: ["calendar", "date", "location"]`), a w GUI
(sekcja „Reguły”) i w CLI (`--rules calendar,location,date`, `--date-group-threshold 10`)
można reguły włączać/wyłączać i zmieniać próg na jedno uruchomienie.
Nazwy są domyślnie po polsku (`location_recognition.language: "pl"`, więc
`home_country: "Polska"`). Backend lokalizacji wybiera `location_recognition.type`:

- `nominatim` — online (OpenStreetMap): miasta i kraje po polsku, z polskimi znakami
  (`2026-07-15 Austria-Wiedeń`, `Kraków`, `Lwów`). Do serwera wysyłane są **tylko
  współrzędne GPS** zdjęcia (nie samo zdjęcie). Serwer pozwala na 1 zapytanie/s, więc
  wyniki są cache'owane w `~/.cache/files-organizer/nominatim.json` (w komórkach ok. 2×2 km,
  `cache_cell_km: 2`). Zdjęcia z jednego miejsca i ponowne uruchomienia
  korzystają z cache. **Bez internetu** nazwy są brane z cache, a gdy którejś tam nie ma,
  cały proces jest przerywany z błędem — w `files-organizer` jeszcze przed kopiowaniem/
  przenoszeniem (żaden plik nie zostaje ruszony), w `files-organizer-locations` przed
  zapisem kolejnych tagów.
- `reverse_geocoder` (domyślny) — w pełni offline, wymaga
  `pip install -e ".[location_recognition]"`. Kraje są po polsku, ale miasta pochodzą z bazy
  GeoNames i są angielskie, bez polskich znaków (`Krakow`, `Vienna`).

# Technologia

Jezyk programowania Python.
Pozostale do ustalenia

# Struktura projektu

```
files-organizer/
├── pyproject.toml          # zależności, konfiguracja pytest
├── config.example.yaml     # przykładowa konfiguracja (skopiuj do config.yaml)
├── src/files_organizer/
│   ├── models.py            # Event, Photo, RecognizedPerson
│   ├── exif_reader.py       # odczyt EXIF przez exiftool (data, model aparatu)
│   ├── calendar_sources/    # ICS / Google / Outlook
│   ├── matcher.py           # dopasowanie zdjęcia do wydarzenia
│   ├── organizer.py         # budowa struktury katalogów, kopiowanie/przenoszenie
│   ├── config.py            # wczytywanie config.yaml
│   ├── pipeline.py          # pętla dopasowanie->kopiowanie, współdzielona przez CLI i GUI
│   ├── gui.py               # okno graficzne (Tkinter): ścieżki, tryb, config, log
│   ├── cli.py               # `files-organizer --config config.yaml [--dry-run] [--gui]`
│   ├── face_recognizers/    # FaceRecognizer ← InsightFaceRecognizer (detektor/embedder/known faces)
│   ├── metadata.py          # odczyt/zapis tagów osób w zdjęciu przez exiftool
│   ├── face_watcher.py      # watcher (watchdog) + kolejka + worker tagujący twarze na bieżąco
│   └── face_cli.py          # `files-organizer-faces --config config.yaml`
├── tests/                    # testy pytest
├── examples/sample.ics       # przykładowy kalendarz do testów
├── data/{input,output}/      # domyślne katalogi wejścia/wyjścia (gitignored)
└── scripts/setup-git.sh      # konfiguracja tożsamości git (patrz niżej)
```

## Uruchomienie

Odczyt EXIF/metadanych korzysta z narzędzia [exiftool](https://exiftool.org/)
(obsługuje też pliki wideo, w przeciwieństwie do samego Pillow):

```
brew install exiftool
```

```
pip install -e ".[dev]"
cp config.example.yaml config.yaml
files-organizer --config config.yaml --dry-run
pytest
```

Ścieżki wejścia/wyjścia można też wskazać bez configu:

```
# bez config.yaml: input_dir = katalog bieżący, output_dir = ./output
cd /sciezka/ze/zdjeciami
files-organizer --dry-run

# jawne wskazanie katalogów (nadpisuje config.yaml, jeśli istnieje)
files-organizer --input-dir /sciezka/ze/zdjeciami --output-dir /sciezka/wynikowa --dry-run
```

## Tryb graficzny (GUI)

```
files-organizer --gui
```

Otwiera okno, w którym można:
- wskazać/edytować katalog źródłowy i docelowy (pola tekstowe + przyciski „Wybierz…”),
- wybrać plik `config.yaml` i wczytać go do formularza,
- przełączyć tryb **kopiuj / przenieś** oraz margines dopasowania i podgląd (dry-run),
- uruchomić akcję przyciskiem „Uruchom” i obserwować log kopiowania/przenoszenia na żywo,
- bezpiecznie przerwać akcję przyciskiem „Zatrzymaj” — bieżący plik jest zawsze dokańczany,
  zatrzymanie następuje dopiero przed kolejnym plikiem, więc nic nie zostaje w połowie skopiowane.

W trybie terminalowym (bez `--gui`) działa to samo zabezpieczenie pod Ctrl+C: pierwsze
Ctrl+C kończy bieżący plik i zatrzymuje się, drugie przerywa natychmiast.

GUI wymaga Tkinter. Na macOS z Pythonem z Homebrew doinstaluj obsługę Tk (dopasuj wersję
do swojego Pythona):

```
brew install python-tk@3.12
```

Bez `config.yaml` (lub bez sekcji `calendar` w configu) zdjęcia nie są
dopasowywane do wydarzeń kalendarza — trafiają do katalogu `Nieprzypisane`.

## Konfiguracja Google Calendar

Tokena nie pozyskuje się ręcznie — potrzebny jest tylko plik `credentials.json`
(klient OAuth typu „Desktop app”), a `token.json` aplikacja tworzy sama po pierwszym
zalogowaniu w przeglądarce.

1. **Projekt i API** — wybierz/utwórz projekt w [Google Cloud Console](https://console.cloud.google.com/)
   i [włącz Google Calendar API](https://console.cloud.google.com/apis/library/calendar-json.googleapis.com).
2. **Ekran zgody** — w [Google Auth Platform → Branding](https://console.cloud.google.com/auth/branding)
   podaj nazwę aplikacji (np. `files-organizer`) i swój e-mail, typ odbiorców **External**.
   W [Audience](https://console.cloud.google.com/auth/audience) dodaj swój adres Gmail jako
   **Test user** (albo od razu „Publish app” — patrz uwaga niżej).
   Dokumentacja: https://developers.google.com/workspace/guides/configure-oauth-consent
3. **Klient OAuth** — w [Clients](https://console.cloud.google.com/auth/clients) kliknij
   „Create client”, typ **Desktop app**, nazwa dowolna → „Create”.
   W oknie, które się pojawi, kliknij **Download JSON** — sekret klienta jest widoczny/do
   pobrania tylko w tym momencie; jeśli go przegapisz, dodaj nowy sekret w szczegółach klienta
   albo utwórz nowego klienta.
   Dokumentacja: https://developers.google.com/workspace/guides/create-credentials#desktop-app
4. Zapisz pobrany plik jako `~/.config/files-organizer/credentials.json`
   (poza repozytorium — to sekret) i usuń stary `token.json`, jeśli istnieje.
   Pełny przykład dla Pythona (te same kroki): https://developers.google.com/workspace/calendar/api/quickstart/python
5. Zainstaluj zależności i ustaw sekcję `calendar` w `config.yaml`:

   ```
   pip install -e ".[google]"
   ```

   ```yaml
   calendar:
     type: "google"
     credentials_file: "~/.config/files-organizer/credentials.json"
     token_file: "~/.config/files-organizer/token.json"
     # calendar_id: "primary"   # domyślnie główny kalendarz
   ```

6. Przy pierwszym uruchomieniu otworzy się przeglądarka z prośbą o zgodę (dostęp tylko do
   odczytu wydarzeń). Po zatwierdzeniu `token.json` zapisze się pod `token_file` i kolejne
   uruchomienia nie będą już wymagały logowania. Aby wymusić ponowne logowanie, usuń ten plik.

Jeśli aplikacja OAuth ma w Google Cloud status **Testing**, refresh token wygasa po 7 dniach —
wtedy przy następnym uruchomieniu okno logowania otworzy się ponownie. Żeby tego uniknąć,
zmień status na **In production** (Google Auth Platform → Audience → „Publish app”);
do prywatnego użytku weryfikacja przez Google nie jest wymagana.

## Rozpoznawanie twarzy (proces w tle)

Osobny, długo działający proces (niezależny od `files-organizer`/`run_pipeline`) obserwuje
`input_dir` i taguje zdjęcia znanymi osobami na bieżąco, w miarę jak trafiają do katalogu.
Przy starcie taguje też wszystkie pliki, które już tam są (obserwacja obejmuje tylko zdarzenia
zachodzące od momentu uruchomienia, więc bez tego jednorazowego skanu plik dodany przed startem
zostałby zignorowany). Całe przetwarzanie (detekcja i rozpoznawanie twarzy) odbywa się wyłącznie
lokalnie — zdjęcia ani dane z nich wyekstrahowane nie są nigdzie wysyłane.

```
pip install -e ".[face_recognition]"
```

Skonfiguruj sekcję `face_recognition` w `config.yaml` (patrz `config.example.yaml`) i przygotuj
katalog referencyjny ze zdjęciami znanych osób:

```
known_faces/
    Anna/
        1.jpg
        2.jpg
    Bartek/
        1.jpg
```

Uruchomienie:

```
files-organizer-faces --config config.yaml
```

Domyślnie każdy rozpoznany tag trzeba zatwierdzić w terminalu (`y`/`n`), zanim zostanie zapisany
do zdjęcia. Żeby zamiast tego tagować w pełni automatycznie (bez pytania), użyj `--auto`:

```
files-organizer-faces --config config.yaml --auto
```

Podgląd bez zapisu (`--dry-run`) rozpoznaje twarze i pokazuje w logu, jaki tag zostałby dodany
do każdego pliku, ale nic nie zapisuje do zdjęć (potwierdzenia są wtedy pomijane, bo i tak nic
by się nie zapisało):

``` script
files-organizer-faces --config config.yaml --dry-run
```

Potwierdzanie w samym terminalu bywa niewygodne, bo nie widać zdjęcia — `--gui` otwiera zamiast
tego okno z podglądem każdego rozpoznanego zdjęcia i przyciskami Zatwierdź/Odrzuć:

```
files-organizer-faces --config config.yaml --gui
```

`--gui` można łączyć z `--auto` (wtedy okno tylko pokazuje log, bez pytania o potwierdzenie) i
z `--dry-run`.

Rozpoznane osoby są zapisywane jako słowa kluczowe `Person:<Imię>` (IPTC/XMP Keywords) w pliku
zdjęcia — dopisywane, nigdy nadpisywane, więc ponowne wykrycie tej samej osoby jest bezpieczne.
Embeddingi zdjęć referencyjnych są cache'owane (`known_faces_dir/cache/embeddings.pkl`) i
przeliczane tylko wtedy, gdy dany plik referencyjny się zmienił.

Pierwsze uruchomienie modelu `insightface` (`buffalo_l`) wymaga jednorazowego połączenia
z internetem, żeby pobrać wagi modelu do `~/.insightface/models/` (same wagi, żadne dane
użytkownika).

## Przygotowanie do pracy z git

GitHub blokuje push, jeśli commity zawierają prywatny e-mail (błąd `GH007`).
Przed pierwszym commitem w tym repo uruchom:

```
./scripts/setup-git.sh                 # auto-wykrycie przez `gh` CLI
./scripts/setup-git.sh <github-login>  # albo podaj login ręcznie
```

Ustawi to `git config user.email/user.name` (lokalnie, tylko dla tego repo)
na Twój adres `users.noreply.github.com`. Skrypt jest generyczny — bez zmian
można go skopiować do innych projektów.
