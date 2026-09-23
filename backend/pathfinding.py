"""
pathfinding.py
Algorytm Dijkstry – znajdowanie najkrótszej ścieżki między pokojami
z poprawnym doborem instrukcji kierunkowych.
"""

import heapq
from graph_builder import GraphBuilder


def find_shortest_path(conn, CONN_COLS, start_room, end_room,
                       avoid_stairs=False, avoid_elevator=False):

    builder = GraphBuilder(conn, CONN_COLS)
    graph = builder.build_graph(
        avoid_stairs=avoid_stairs,
        avoid_elevator=avoid_elevator
    )

    start_room = str(start_room).strip()
    end_room = str(end_room).strip()

    if not builder.has_node(start_room):
        return None, f"Pokój startowy '{start_room}' nie istnieje lub nie ma aktywnych połączeń"
    if not builder.has_node(end_room):
        return None, f"Pokój docelowy '{end_room}' nie istnieje lub nie ma aktywnych połączeń"

    # --- Dijkstra ---
    distances = {node: float("inf") for node in graph}
    previous = {node: None for node in graph}

    distances[start_room] = 0
    pq = [(0, start_room)]

    while pq:
        current_dist, current = heapq.heappop(pq)

        if current == end_room:
            break
        if current_dist > distances[current]:
            continue

        for neighbor, weight in graph[current]:
            new_dist = current_dist + weight
            if new_dist < distances[neighbor]:
                distances[neighbor] = new_dist
                previous[neighbor] = current
                heapq.heappush(pq, (new_dist, neighbor))

    if distances[end_room] == float("inf"):
        return None, f"Nie znaleziono ścieżki z '{start_room}' do '{end_room}'"

    # --- Odtwarzanie ścieżki z poprawną instrukcją ---
    path = []
    node = end_room

    while previous[node] is not None:
        prev = previous[node]
        edge = builder.get_edge_details(prev, node)

        if edge:
            
            if edge["from_room"] == prev and edge["to_room"] == node:
                instruction = edge.get("instrukcja_ab", "idź prosto")
            else:
                instruction = edge.get("instrukcja_ba", "idź prosto")

            distance = edge.get("distance", 0)
            extra_time = edge.get("extra_time", 0)
        else:
            instruction = "idź prosto"
            distance = 0
            extra_time = 0

        path.append({
            "from": prev,
            "to": node,
            "instruction": instruction,
            "distance": distance,
            "extra_time": extra_time
        })

        node = prev

    path.reverse()

    

    return {
        "path": path,
        "total_distance": distances[end_room],
        "steps": len(path)
    }, None



