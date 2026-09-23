"""
graph_builder.py
Budowanie grafu (lista sąsiedztwa) na podstawie tabeli Connections.
Obsługuje instrukcja_ab / instrukcja_ba oraz unikanie wind i schodów.
"""

class GraphBuilder:
    def __init__(self, conn, CONN_COLS):
        self.conn = conn
        self.CONN_COLS = CONN_COLS
        self.graph = {}
        self.edges = {}

    def build_graph(self, avoid_stairs=False, avoid_elevator=False):
        self.graph.clear()
        self.edges.clear()

        query = f"""
            SELECT
                c.{self.CONN_COLS["from_room"]} AS from_room,
                c.{self.CONN_COLS["to_room"]}   AS to_room,
                c.{self.CONN_COLS["dystans"]}   AS distance,
                c.{self.CONN_COLS["dodatkowy_czas"]} AS extra_time,
                c.instrukcja_ab,
                c.instrukcja_ba,
                c.{self.CONN_COLS["status"]} AS status
            FROM Connections c
            WHERE c.{self.CONN_COLS["status"]} = 'Aktywny'
        """

        rows = self.conn.execute(query).fetchall()

        for row in rows:
            from_room = str(row["from_room"]).strip()
            to_room = str(row["to_room"]).strip()

            distance = float(row["distance"] or 0)
            extra_time = float(row["extra_time"] or 0)

            instr_ab = (row["instrukcja_ab"] or "").lower()
            instr_ba = (row["instrukcja_ba"] or "").lower()

           
            if avoid_stairs and (self._has_stairs(instr_ab) or self._has_stairs(instr_ba)):
                continue
            if avoid_elevator and (self._has_elevator(instr_ab) or self._has_elevator(instr_ba)):
                continue

            cost = distance + extra_time

            
            self._add_edge(from_room, to_room, cost)
            self._add_edge(to_room, from_room, cost)

            
            self.edges[(from_room, to_room)] = {
                "from_room": from_room,
                "to_room": to_room,
                "distance": distance,
                "extra_time": extra_time,
                "instrukcja_ab": instr_ab,
                "instrukcja_ba": instr_ba
            }

            self.edges[(to_room, from_room)] = {
                "from_room": to_room,
                "to_room": from_room,
                "distance": distance,
                "extra_time": extra_time,
                
                "instrukcja_ab": instr_ba,
                "instrukcja_ba": instr_ab
            }

        return self.graph

    def _add_edge(self, from_node, to_node, cost):
        self.graph.setdefault(from_node, []).append((to_node, cost))

    def _has_stairs(self, text):
        return any(w in text for w in ["schod", "schody", "schodami"])

    def _has_elevator(self, text):
        return any(w in text for w in ["wind", "windą", "windy", "windę"])

    def has_node(self, node):
        return node in self.graph

    def get_edge_details(self, from_node, to_node):
        return self.edges.get((from_node, to_node))
