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
   - Konfiguracja backendu w `config.yaml`, sekcja `face_recognition` (wzorem
     sekcji `calendar`), z polem `type` wybierającym implementację.
   - Enrollment znanych osób: katalog referencyjny `known_faces/<Osoba>/*.jpg`,
     ścieżka konfigurowalna w `face_recognition`.

   Architektura (uszczegółowiona po przeglądzie):
   - Interfejs `FaceRecognizer` całkowicie niezależny od konkretnej
     biblioteki — reszta aplikacji zna tylko ten interfejs, nigdy DeepFace
     bezpośrednio (`FaceRecognizer` ← `DeepFaceRecognizer`, analogicznie do
     `CalendarSource` ← `IcsCalendarSource`).
   - Wewnątrz rozpoznawanie rozbite na wymienne niezależnie etapy:
     zdjęcie → detekcja twarzy (`FaceDetector`) → embedding (`FaceEmbedder`)
     → porównanie z bazą znanych osób (`KnownFacesIndex`) → wynik.
     Domyślna implementacja (`DeepFaceRecognizer`) realizuje wszystkie etapy
     przez `deepface`, ale sam detektor da się później podmienić osobno.
   - Wynik rozpoznania to `list[RecognizedPerson]` (dataclass: `name`,
     `confidence`, `bbox`), nie pojedynczy string — na zdjęciu może być
     kilka osób naraz.
   - Enrollment cache'owany: `known_faces/cache/embeddings.pkl` (lub
     `.index`). Przy starcie porównaj daty modyfikacji plików referencyjnych
     z cache — przebuduj indeks tylko gdy coś się zmieniło, żeby nie liczyć
     embeddingów od nowa przy każdym uruchomieniu.
   - Watcher nie rozpoznaje twarzy bezpośrednio w callbacku `watchdog`:
     `watchdog` → kolejka (`Queue`) → worker → `FaceRecognizer` →
     `MetadataWriter`. Zabezpiecza to przed zalaniem workera, gdy użytkownik
     kopiuje naraz setki zdjęć.
   - Odczyt/zapis tagów w osobnym module `metadata.py` (`read_tags`,
     `write_tags` przez `exiftool`) zamiast rozszerzania `exif_reader.py`,
     którego nazwa sugeruje tylko odczyt — czy scalić z `exif_reader.py`,
     czy zostawić osobno, do ustalenia przy implementacji.
   - Nazwa tagu z namespace'em, np. `Person:Anna` / `People:Anna` (osobne
     pole XMP), żeby nie kolidować z innymi słowami kluczowymi w pliku.

   Do doprecyzowania:
   - Lokalność a pobranie wag modelu: pierwsze uruchomienie `deepface`
     wymaga jednorazowego połączenia z internetem, żeby pobrać pliki modelu
     (żadne dane użytkownika nie są wysyłane, tylko wagi ściągane).
     Do ustalenia: czy to akceptowalne, czy wymagane jest działanie w 100%
     offline od pierwszego uruchomienia (wtedy wagi trzeba dostarczyć razem
     z instalacją albo pobrać ręcznie wcześniej, wg osobnej instrukcji).
