#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020-2021  David Brooks
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

from collections.abc import Iterable
from collections import Counter, defaultdict
from dataclasses import dataclass
from itertools import permutations, product
from typing import List

from pprint import pprint

import networkx as nx
import numpy as np

#===============================================================================

class PortError(ValueError):
    pass

#===============================================================================

@dataclass
class Port:
    offset: int     #! Starting pin number
    pins: int       #! Number of pins

#===============================================================================

@dataclass
class Configuration:
    pin_connections: tuple
    crossings: int

#===============================================================================

class PortHub(object):
    def __init__(self, id: str, port_connections: dict):
        self.__id = id
        self.__port_connections = port_connections
        port_sizes = defaultdict(int)
        for port_pair, count in port_connections.items():
            (start_port, end) = port_pair if len(port_pair) == 2 else (port_pair[0], None)
            port_sizes[start_port] += count
            if isinstance(end, Iterable):
                for end_port in end:
                    if start_port == end_port:
                        raise PortError("Start and end ports must be different")
                    port_sizes[end_port] += count
            elif end is not None:
                if start_port == end:
                    raise PortError("Start and end ports must be different")
                port_sizes[end] += count
        ports = sorted(port_sizes)
        if ports[0] != 0 or ports[-1] != (len(ports) - 1):
            raise PortError("Port numbers must be consecutive, starting from 0")

        self.__ports = []
        port_offset = 0
        for port in range(len(ports)):
            size = port_sizes[port]
            cable_port = Port(port_offset, size)
            self.__ports.append(cable_port)
            port_offset += size
        self.__pin_count = port_offset

        if len(self.__ports) > 1:
            self.__configurations = [ Configuration(configuration, PortHub.__crossings(configuration))
                                        for configuration in self.__configuration_set()]
        else:
            self.__configurations = []   # How to represent terminal nodes??

    @property
    def configurations(self):
        return self.__configurations

    @property
    def id(self):
        return self.__id

    @property
    def pin_count(self):
        return self.__pin_count

    @property
    def ports(self):
        return self.__ports

    def __configuration_set(self):
    #=============================
        configuration_set = set()
        for pin_combination in product(*[permutations(range(port.pins))
                                             for port in self.__ports]):

            available = [list(c) for c in pin_combination]
            
            def next_available(port):
                if available[port]:
                    return available[port].pop(0) + self.__ports[port].offset
            
            def end_pin(port):
                pin = next_available(port)
                if pin is None:
                    raise ValueError(f'Port circuit ({start_port}, {port}) has no available pins for {self.__id}/{self.__port_connections}')
                return pin
            
            configuration = []
            for (start_port, end), count in self.__port_connections.items():
                for connection in range(count):
                    start_pin = next_available(start_port)
                    if start_pin is not None:
                        if isinstance(end, Iterable):
                            for end_port in end:
                                configuration.append((start_pin, end_pin(end_port)))
                        else:
                            configuration.append((start_pin, end_pin(end)))
            configuration_set.add(tuple(sorted(configuration)))
        return configuration_set

    @staticmethod
    def __crossed(c1, c2):
    #=====================
        ordered = sorted(set(c1 + c2))
        if len(ordered) < 4:
            return False
        delta = abs(ordered.index(c1[0]) - ordered.index(c1[1]))
        return delta == 2

    @staticmethod
    def __crossings(configuration):
    #==============================
        crossings = 0
        for n, c1 in enumerate(configuration):
            for c2 in configuration[n+1:]:
                if PortHub.__crossed(c1, c2):
                    crossings += 1
        return crossings

#===============================================================================

class ConnectedNodes(object):
    def __init__(self, cabling, node_centroids, wire_equivalences=None):
        self.__wire_equivalences = wire_equivalences if wire_equivalences is not None else None
        self.__node_cables = defaultdict(list)  #! List if cables connected to a node
        for cable in cabling:
            for node_id in cable.node_ids:
                self.__node_cables[node_id].append(cable)

        self.__node_wires = defaultdict(set)    #! Set of wires connected to a node
        for node_id, cables in self.__node_cables.items():
            self.__node_wires[node_id] = set([wire for cable in cables
                                                for wire in self.__equivalent_wires(cable.wires)])

        self.__hub_graph = nx.Graph()
        for node_id, cables in self.__node_cables.items():
            node_centroid = node_centroids[node_id]
            cable_angles = []
            for cable_number, cable in enumerate(cables):
                self.__hub_graph.add_edge(*cable.node_ids, cable=cable)
                if node_id == cable.node_ids[0]:
                    remote_node = cable.node_ids[1]
                elif node_id == cable.node_ids[1]:
                    remote_node = cable.node_ids[0]
                # Get angle to remote node from this node
                cable_angles.append((np.arctan2(*(node_centroid - node_centroids[remote_node])[::-1]), cable))
            # This ensures ports physical order matches the geometry of the node's cables
            ordered_cables = [pair[1] for pair in sorted(cable_angles)]
            cable_count = len(ordered_cables)

            port_wires = defaultdict(set)
            for port in range(cable_count):
                for wire in self.__equivalent_wires(ordered_cables[port].wires):
                    port_wires[port].add(wire)

            # Find number of wires in common between pairs of cables
            connections = []
            unconnected = self.__node_wires[node_id].copy()
            for port_0 in range(cable_count):
                for wire in port_wires[port_0]:
                    if wire in unconnected:
                        to_ports = []
                        for port_1 in range(port_0 + 1, cable_count):
                            if wire in port_wires[port_1]:
                                to_ports.append(port_1)
                        if len(to_ports) == 1:
                            connections.append((port_0, to_ports[0]))
                        elif len(to_ports) > 1:
                            connections.append((port_0, tuple(sorted(to_ports))))
                        unconnected.remove(wire)
            if len(connections) == 0:
                port_connections = { (0,): len(port_wires[0]) }
            else:
                port_connections = dict(Counter(connections))

            self.__hub_graph.add_node(node_id, hub=PortHub(node_id, port_connections))


# g.edges(0, data=True)  # edges from 0 with data attributes
# g[0]  # neighbours of 0


    def layout(self):
        # Divide hub nodes into:
        #   Single cable nodes
        #       Single wire cable
        #
        #   Head nodes -- one multi-wire cable, others all single wire cables
        #       Geometric order of single wire cables with minimum node crossing
        #       determines wire order in multi-wire cable.
        #
        #   Until all nodes seen:
        #       Find unseen neighbours of each head node
        #           Know wiring of connecting cables
        #
        # Node neighbours
        #
        # Node/cables as a networkx graph.
        #
        pass

    def __equivalent_wires(self, wires):
        return map(lambda wire: self.__wire_equivalences.get(wire, wire), wires)

#===============================================================================

@dataclass
class Cable:
    id: str         #! The cable's ID
    wires: list     #! Identifiers for the wires in the cable
    node_ids: list  #! Identifiers of the two PortHubs connected by the cable

#===============================================================================

def layout(path_network):
    cable_paths = defaultdict(set)
    cable_ends = defaultdict(set)
    centroids = {}
    for path_id, route_graph in path_network.items():
        for node0, node1, properties in route_graph.edges.data():
            if properties.get('type') != 'terminal':
                id = properties.get('id')
                assert(id is not None)
                cable_paths[id].add(path_id)
                if id not in cable_ends:
                    centroids[node0] = np.array(route_graph.nodes[node0]['geometry'].centroid.coords[0])
                    centroids[node1] = np.array(route_graph.nodes[node1]['geometry'].centroid.coords[0])
                    cable_ends[id] = set([node0, node1])
                else:
                    assert(cable_ends[id] == set([node0, node1]))

    cables = [ Cable(id, paths, list(cable_ends[id]))
                    for id, paths in cable_paths.items() ]

    connectivity = ConnectedNodes(cables, centroids, {})

#===============================================================================

if __name__ == '__main__':

    keast_cables = [
        Cable('bladder nerve', ['keast 3', 'keast 11'], ['bladder terminal', 'pelvic ganglion']),
        Cable('hypogastric nerve', ['keast 3', 'keast 11'], ['inferior mesentric ganglion', 'pelvic ganglion']),
        Cable('lumbar splanchnic nerve', ['keast 7', 'keast 11'], ['inferior mesentric ganglion', 'L1-L2 branch']),
        Cable('L1 spinal', ['keast 7', 'keast 11'], ['L1-L2 branch', 'L1 base']),
        Cable('L1 dorsal root', ['keast 11'], ['L1 base', 'L1 dorsal root terminal']),
        Cable('L1 ventral root', ['keast 7'], ['L1 base', 'L1 ventral root terminal']),
        Cable('L2 spinal', ['keast 7', 'keast 11'], ['L1-L2 branch', 'L2 base']),
        Cable('L2 dorsal root', ['keast 11'], ['L2 base', 'L2 dorsal root terminal']),
        Cable('L2 ventral root', ['keast 7'], ['L2 base', 'L2 ventral root terminal']),
    ]

    node_positions = {
        'L1 dorsal root terminal': np.array([1, 1]),
        'L1 ventral root terminal': np.array([3, 1]),
        'L1 base': np.array([2, 5]),
        'L2 dorsal root terminal': np.array([5, 1]),
        'L2 ventral root terminal': np.array([7, 1]),
        'L2 base': np.array([6, 5]),
        'L1-L2 branch': np.array([8, 8]),
        'inferior mesentric ganglion': np.array([12, 12]),
        'pelvic ganglion': np.array([16, 16]),
        'bladder terminal': np.array([12, 24]),
    }

    #wire_equivalences = [('keast_3', 'keast_7')]  ## or as dict map??
    # define as a list of tuples and construct dict for map??
    keast_equivalences = {
        'keast 3': 'keast 3_7',
        'keast 7': 'keast 3_7',
    }

    keast_connectivity = ConnectedNodes(
                            keast_cables,
                            node_positions,
                            keast_equivalences)

#===============================================================================
