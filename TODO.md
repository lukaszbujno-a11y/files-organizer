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

2. [Zaimplementowane] Aplikacja uruchomiona w tle do wykrywania osób na zdjęciach
   (rozpoznawanie twarzy). Po wykryciu znanej osoby dodaje tag do zdjęcia (metadane
   IPTC/XMP Keywords, `Person:<Imię>`). Zobacz `files-organizer-faces` w README.md,
   moduły `face_recognizers/`, `metadata.py`, `face_watcher.py`, `face_cli.py`.

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
     biblioteki — reszta aplikacji zna tylko ten interfejs, nigdy insightface
     bezpośrednio (`FaceRecognizer` ← `InsightFaceRecognizer`, analogicznie do
     `CalendarSource` ← `IcsCalendarSource`).
   - Wewnątrz rozpoznawanie rozbite na wymienne niezależnie etapy:
     zdjęcie → detekcja twarzy (`FaceDetector`) → embedding (`FaceEmbedder`)
     → porównanie z bazą znanych osób (`KnownFacesIndex`) → wynik.
     Domyślna implementacja (`InsightFaceRecognizer`) realizuje wszystkie etapy
     przez `insightface` (pakiet modeli `buffalo_l`, tylko moduły `detection` +
     `recognition` — bez wieku/płci/landmarków, żeby było lżej i prościej niż
     pierwotnie rozważany `deepface`, bez kompilowania czegokolwiek jak przy
     `dlib`). Detekcja i embedding wychodzą z insightface w jednym wywołaniu
     (`FaceAnalysis.get()`), więc `InsightFaceEmbedder` tylko odczytuje
     embedding już policzony przez detektor — sam detektor da się później
     podmienić osobno, o ile nowy embedder też umie się z nim dogadać.
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
     którego nazwa sugeruje tylko odczyt. Zostawione osobno — `exif_reader.py`
     dalej odczytuje tylko datę/model aparatu, `metadata.py` czyta i dopisuje
     tagi osób.
   - Nazwa tagu z namespace'em: `Person:Anna` jako wartość pola Keywords
     (IPTC + XMP-dc:Subject) — bez własnej schemy XMP (wymagałaby pliku
     konfiguracyjnego exiftool), żeby nie kolidować z innymi słowami
     kluczowymi w pliku.

   Do doprecyzowania:
   - Lokalność a pobranie wag modelu: pierwsze uruchomienie `insightface`
     wymaga jednorazowego połączenia z internetem, żeby pobrać paczkę modelu
     `buffalo_l` do `~/.insightface/models/` (żadne dane użytkownika nie są
     wysyłane, tylko wagi ściągane). Do ustalenia: czy to akceptowalne, czy
     wymagane jest działanie w 100% offline od pierwszego uruchomienia (wtedy
     wagi trzeba dostarczyć razem z instalacją albo pobrać ręcznie wcześniej,
     wg osobnej instrukcji).
