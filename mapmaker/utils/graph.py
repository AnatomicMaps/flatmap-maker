#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020 - 2022  David Brooks
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
#===============================================================================

from collections import defaultdict

#===============================================================================

import networkx as nx

#===============================================================================

def smooth_edges(G, end_nodes=None, path_attribute='path-nodes'):
    """
    Return a networkx.MultiDiGraph copy of G with all degree 2 nodes removed.

    Each edge of the resulting graph has a list attribute, whose name is given by
    ``path_attribute``, containing any nodes removed along the original edge.
    """
    def follow_path(start_node, path_node):
        path = [start_node, path_node]
        prev_node = start_node
        while G.degree(path_node) == 2 and path_node not in end_nodes:
            for node in G[path_node]:
                # This will loop a maximum of two times (since degree == 2) and
                # find the next node going forward on the path
                if node != prev_node:
                    prev_node = path_node
                    path_node = node
                    break
            path.append(path_node)
        return path

    # Directed to match removed node order in the resulting path attribute
    # Multi- because there may be more than one smoothed edge between nodes
    R = nx.MultiDiGraph()
    if end_nodes is None:
        end_nodes = set()
    for (node, degree) in G.degree:
        if degree != 2 or node in end_nodes:
            R.add_node(node, **G.nodes[node])
            R.nodes[node]['degree'] = degree
    seen_paths = defaultdict(set)
    for node in R:
        for path_node in G[node]:
            if path_node not in seen_paths[node]:
                path = follow_path(node, path_node)
                key = R.add_edge(path[0], path[-1])
                R.edges[path[0], path[-1], key][path_attribute] = path[1:-1]
                key = R.add_edge(path[-1], path[0])
                R.edges[path[-1], path[0], key][path_attribute] = reversed(path[1:-1])
                seen_paths[path[0]].add(path[1])
                seen_paths[path[-1]].add(path[-2])
    return R

#===============================================================================
