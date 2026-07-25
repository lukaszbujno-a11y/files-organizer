# TODO

1. Weryfikacja zdjęć na podstawie metadanych lokalizacji (EXIF GPS). Jeśli
   zdjęcie zostało zrobione w lokalizacji poza krajem wskazanym w konfiguracji
   (np. `home_country: "Polska"`), utwórz katalog w uzgodnionej strukturze
   nazwany wg wzorca `data Kraj-Miasto`, np.:
   ```
   2026/
       07/
           2026-07-15 Chorwacja-Split
   ```
   Nazwę kraju/miasta ustalić na podstawie reverse geocodingu współrzędnych
   GPS z EXIF.

2. Aplikacja uruchomiona w tle do wykrywania osób na zdjęciach (rozpoznawanie
   twarzy). Po wykryciu znanej osoby dodać tag do zdjęcia (np. do metadanych
   EXIF/IPTC lub do słownika osoba → katalog, analogicznie do `phone_mapping`).

   Założenie: przetwarzanie zdjęć (rozpoznawanie twarzy) musi odbywać się
   wyłącznie lokalnie na komputerze użytkownika — zdjęcia ani dane z nich
   wyekstrahowane nie mogą być wysyłane poza lokalny komputer (bez chmury,
   bez zewnętrznych API).

   Ustalenia (omówione, do realizacji):
   - Osobny, długo działający proces w tle (watcher, np. przez bibliotekę
     `watchdog`), obserwujący `input_dir` i tagujący nowe pliki na bieżąco —
     niezależny od jednorazowego pipeline'u kalendarzowego (`run_pipeline`).
   - Rozpoznawanie twarzy schowane za interfejsem `FaceRecognizer`
     (analogicznie do `CalendarSource` w `calendar_sources/`), żeby bibliotekę
     rozpoznającą można było w przyszłości łatwo podmienić bez zmian w reszcie
     kodu. Domyślny backend: `deepface` (czysta biblioteka Python, instalacja
     bez kompilacji C/C++, wagi modeli pobierane raz przy pierwszym użyciu i
     trzymane lokalnie).
   - Konfiguracja backendu w `config.yaml`, sekcja `face_recognition` (wzorem
     sekcji `calendar`), z polem `type` wybierającym implementację.
   - Enrollment znanych osób: katalog referencyjny `known_faces/<Osoba>/*.jpg`,
     ścieżka konfigurowalna w `face_recognition`.
   - Wynik rozpoznania zapisywany jako tag w samym pliku (EXIF/IPTC Keywords /
     XMP Subject) przez `exiftool` — wymaga dopisania funkcji **zapisu**
     metadanych (dziś `exif_reader.py` tylko czyta).
