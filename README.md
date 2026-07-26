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

```
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
