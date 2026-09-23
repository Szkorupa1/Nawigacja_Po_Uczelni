# Aplikacja Nawigacyjna

# Baza danych do pobrania

Baza danych nie jest w repozytorium, ponieważ jest zbyt duża.

**[Pobierz bazę danych](https://github.com/Szkorupa1/Nawigacja_Po_Uczelni/releases/download/v1.0/Baza.db)**

Po pobraniu umieść plik `database.db` w katalogu głównym projektu.

---

# Nawigacja wewnątrz budynku

Aplikacja internetowa wyznaczająca trasę dojścia do wybranego miejsca w budynku. Projekt inżynierski, Dawid Szkorupa, promotor: dr inż. Jarosław Flak, Wydział Automatyki, Elektroniki i Informatyki, Gliwice 2025/2026.

Budynek jest odwzorowany jako graf (węzły to pomieszczenia, korytarze, schody i windy, krawędzie to przejścia z wagą w postaci dystansu i dodatkowego czasu). Najkrótsza trasa jest wyznaczana algorytmem Dijkstry. System nie wymaga żadnej dodatkowej infrastruktury, np. beaconów BLE.

## Funkcje

Użytkownik:
- wybór punktu startowego i docelowego,
- start z kodu QR (punkt startowy uzupełnia się automatycznie),
- trasa standardowa, bez schodów lub bez wind,
- nawigacja krok po kroku z opcjonalnymi zdjęciami.

Administrator (panel chroniony hasłem):
- dodawanie i edycja pomieszczeń oraz połączeń,
- instrukcje osobno dla obu kierunków przejścia,
- aktywacja i dezaktywacja pomieszczeń i połączeń (np. remont),
- wizualizacja grafu z wyborem piętra.

## Technologie

Python 3, Flask, SQLite, HTML/CSS/JavaScript, vis-network.

## Uruchomienie

```bash
git clone https://github.com/<TWOJ-LOGIN>/<NAZWA-REPO>.git
cd <NAZWA-REPO>
pip install -r requirements.txt
```

Pobierz bazę danych (link na górze) i umieść ją w katalogu głównym projektu, a następnie uruchom:

```bash
python app.py
```

Aplikacja będzie dostępna pod adresem `http://127.0.0.1:5000`.

Wymagania: Python 3.x, min. 2 GB RAM, min. 1 GB wolnego miejsca na dysku.

## Model danych

- `Rooms`: Id, Name, Floor, Status, Type
- `Connections`: Id, From_room, To_room, Dystans, Dodatkowy_czas, Status, Instrukcja_ab, Instrukcja_ba, Img_ab, Img_ba

Graf jest budowany w pamięci przy każdym zapytaniu o trasę, na podstawie aktywnych rekordów z bazy.

## Autor

Dawid Szkorupa


