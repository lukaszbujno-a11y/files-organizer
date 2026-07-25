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
│   ├── models.py            # Event, Photo
│   ├── exif_reader.py       # odczyt EXIF przez exiftool (data, model aparatu)
│   ├── calendar_sources/    # ICS / Google / Outlook
│   ├── matcher.py           # dopasowanie zdjęcia do wydarzenia
│   ├── organizer.py         # budowa struktury katalogów, kopiowanie/przenoszenie
│   ├── config.py            # wczytywanie config.yaml
│   ├── pipeline.py          # pętla dopasowanie->kopiowanie, współdzielona przez CLI i GUI
│   ├── gui.py               # okno graficzne (Tkinter): ścieżki, tryb, config, log
│   └── cli.py                # `files-organizer --config config.yaml [--dry-run] [--gui]`
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
