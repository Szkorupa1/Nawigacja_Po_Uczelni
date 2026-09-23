import unittest
import sqlite3
from graph_builder import GraphBuilder

CONN_COLS = {
    "from_room": "from_room",
    "to_room": "to_room",
    "dystans": "dystans",
    "dodatkowy_czas": "dodatkowy_czas",
    "status": "status"
}

class TestGraphBuilder(unittest.TestCase):

    def setUp(self):
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

        self.conn.execute("""
            INSERT INTO Connections VALUES
            ('A', 'B', 5, 0, 'Aktywny', 'idź prosto', 'idź prosto'),
            ('B', 'C', 3, 0, 'Nieaktywny', 'idź prosto', 'idź prosto'),
            ('C', 'D', 2, 0, 'Aktywny', 'wejdź po schodach', 'zejdź po schodach'),
            ('D', 'E', 4, 0, 'Aktywny', 'wjedź windą', 'zjedź windą')
        """)

        self.conn.commit()

    def tearDown(self):
        self.conn.close()

    def test_build_basic_graph(self):
        """Poprawne utworzenie listy sąsiedztwa"""
        builder = GraphBuilder(self.conn, CONN_COLS)
        graph = builder.build_graph()

        self.assertIn("A", graph)
        self.assertIn(("B", 5), graph["A"])

    def test_ignore_inactive_connections(self):
        """Ignorowanie nieaktywnych połączeń"""
        builder = GraphBuilder(self.conn, CONN_COLS)
        graph = builder.build_graph()

        self.assertNotIn("C", graph.get("B", []))

    def test_avoid_stairs(self):
        """Pomijanie schodów"""
        builder = GraphBuilder(self.conn, CONN_COLS)
        graph = builder.build_graph(avoid_stairs=True)

        for edges in graph.values():
            for node, _ in edges:
                self.assertNotEqual(node, "D")

    def test_avoid_elevator(self):
        """Pomijanie wind"""
        builder = GraphBuilder(self.conn, CONN_COLS)
        graph = builder.build_graph(avoid_elevator=True)

        for edges in graph.values():
            for node, _ in edges:
                self.assertNotEqual(node, "E")

    def test_edge_details(self):
        """Dostęp do szczegółów krawędzi"""
        builder = GraphBuilder(self.conn, CONN_COLS)
        builder.build_graph()

        edge = builder.get_edge_details("A", "B")
        self.assertIsNotNone(edge)
        self.assertEqual(edge["distance"], 5)


if __name__ == "__main__":
    unittest.main()
