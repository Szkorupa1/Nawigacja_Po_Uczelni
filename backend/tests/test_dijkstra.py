import unittest
import sqlite3
from pathfinding import find_shortest_path
from graph_builder import GraphBuilder

CONN_COLS = {
    "from_room": "from_room",
    "to_room": "to_room",
    "dystans": "dystans",
    "dodatkowy_czas": "dodatkowy_czas",
    "status": "status"
}

class TestDijkstraAlgorithm(unittest.TestCase):

    def setUp(self):
        """Tworzy testową bazę danych w pamięci"""
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row

        self.conn.execute("""
            CREATE TABLE Connections (
                from_room TEXT,
                to_room TEXT,
                dystans INTEGER,
                dodatkowy_czas INTEGER,
                status TEXT,
                instrukcja_ab TEXT,
                instrukcja_ba TEXT
            )
        """)

        # Prosty graf: A -> B -> C
        self.conn.execute("""
            INSERT INTO Connections VALUES
            ('A', 'B', 5, 0, 'Aktywny', 'idź prosto', 'idź prosto'),
            ('B', 'C', 3, 0, 'Aktywny', 'skręć w lewo', 'skręć w prawo')
        """)

        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_find_simple_path(self):
        """Poprawne znalezienie trasy"""
        result, error = find_shortest_path(
            self.conn, CONN_COLS, "A", "C"
        )

        self.assertIsNone(error)
        self.assertEqual(result["steps"], 2)
        self.assertEqual(result["total_distance"], 8)

    def test_no_path(self):
        """Brak trasy pomiędzy węzłami"""
        result, error = find_shortest_path(
            self.conn, CONN_COLS, "A", "D"
        )

        self.assertIsNone(result)
        self.assertIsNotNone(error)

    def test_same_start_and_end(self):
        """Start i koniec w tym samym punkcie"""
        result, error = find_shortest_path(
            self.conn, CONN_COLS, "A", "A"
        )

        self.assertIsNone(error)
        self.assertEqual(result["steps"], 0)
        self.assertEqual(result["total_distance"], 0)

    def test_instruction_direction(self):
        """Poprawny dobór instrukcji AB"""
        result, error = find_shortest_path(
            self.conn, CONN_COLS, "A", "C"
        )

        instructions = [step["instruction"] for step in result["path"]]
        self.assertIn("skręć w lewo", instructions)


if __name__ == "__main__":
    unittest.main()
