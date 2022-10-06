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

from collections import defaultdict, OrderedDict
from typing import Hashable, Union

#===============================================================================

import networkx as nx

#===============================================================================

def smooth_edges(G: nx.Graph, end_nodes: Union[list, set]=None, edge_nodes_attribute: str='edge-nodes') -> nx.MultiDiGraph:
    """
    Return a networkx.MultiGraph copy of G with all degree 2 nodes removed.

    Each edge of the resulting graph has an OrderedDict attribute, whose name is given by
    ``edge_nodes_attribute``, containing nodes and their attributes for all nodes removed
    from the original edge.
    """
    def follow_edge_path(start_node, path_node) -> OrderedDict:
        edge_nodes = OrderedDict({start_node: G.nodes[start_node],
                                  path_node: G.nodes[path_node]})
        prev_node = start_node
        while G.degree(path_node) == 2 and path_node not in end_nodes:    # type: ignore
            for node in G[path_node]:
                # This will loop a maximum of two times (since degree == 2) and
                # find the next node going forward on the path
                if node != prev_node:
                    prev_node = path_node
                    path_node = node
                    break
            edge_nodes[path_node] = G.nodes[path_node]
        return edge_nodes

    # Directed to match removed node order in the resulting path attribute
    # Multi- because there may be more than one smoothed edge between nodes
    R = nx.MultiDiGraph()
    if end_nodes is None:
        end_nodes = set()
    for (node, degree) in G.degree:
        if degree != 2 or node in end_nodes:
            R.add_node(node, **G.nodes[node])
    seen_paths: dict[Hashable, set] = defaultdict(set)
    for node in R:
        for path_node in G[node]:
            if path_node not in seen_paths[node]:
                edge_nodes = follow_edge_path(node, path_node)
                node_ids = list(edge_nodes)
                seen_paths[node_ids[0]].add(node_ids[1])
                seen_paths[node_ids[-1]].add(node_ids[-2])
                (node_0, _) = edge_nodes.popitem(last=False)
                (node_1, _) = edge_nodes.popitem(last=True)
                key = R.add_edge(node_0, node_1)
                R.edges[node_0, node_1, key][edge_nodes_attribute] = edge_nodes
    return R

#===============================================================================
