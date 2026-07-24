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
│   ├── exif_reader.py       # odczyt EXIF (data, model aparatu)
│   ├── calendar_sources/    # ICS / Google / Outlook
│   ├── matcher.py           # dopasowanie zdjęcia do wydarzenia
│   ├── organizer.py         # budowa struktury katalogów, kopiowanie/przenoszenie
│   ├── config.py            # wczytywanie config.yaml
│   └── cli.py                # `files-organizer --config config.yaml [--dry-run]`
├── tests/                    # testy pytest
├── examples/sample.ics       # przykładowy kalendarz do testów
└── data/{input,output}/      # domyślne katalogi wejścia/wyjścia (gitignored)
```

## Uruchomienie

```
pip install -e ".[dev]"
cp config.example.yaml config.yaml
files-organizer --config config.yaml --dry-run
pytest
```
