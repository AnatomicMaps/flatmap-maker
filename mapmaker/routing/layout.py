"""
Find an orderly 2D separation of paths which share edges of an acyclic branching network.

The problem is described in terms of drawing a flat (2D) diagram of interconnecting wires
between circuit nodes in a way that minimises wire crossovers, where a wire corresponds to
a path and a bundle of wires is a cable, corresponding to an edge of the network graph.


Problem description
-------------------

A **Network** consists of a set of **Nodes** that are connected by **Cables**.

A Cable connects to a Node at a **Port**. A Port contains a number of **Pins**.

Visually, a node is considered to be a circle, with each port a non-overlapping segment of the
node's circumference, and the pins of each port as evenly spaced points within a port's segment.
Pins within a port are consecutively numbered, starting with 1, in an anti-clockwise direction
-- when looking into a port, pin 1 is the leftmost pin.

Each Cable contains one or more **Wires**. Each end of a wire connects to a single pin in the respective ports
which terminate the cable, and all of a port's pins have a wire connected. i.e. The number of pins in a port
equals the number of wires in the cable attached to the port.

Nodes with one attached Cable are called **Terminal Nodes**, or simply Terminals.

Nodes with more than one connected Cable are called **Branch Nodes**, or simply Branches.

The ports of a branch are connected via one-to-one mappings between their pins. Every pin in a port
is only connected to a single pin in some other port (of the branch node) -- no pins of a port are
connected to pins within that port. These port connections define a partition of a port's set of pins.

The number of pins in a port is the sum of the sizes of the partitions induced by the port's mappings
to other ports, so defining the sizes of these partitions for all ports of a branch is sufficient to
specify the ports of a branch. (:math:`|\{P\ to\ Q\}| = |\{Q\ to\ P\}|`).


Constraints
-----------

1) All cables are ribbon cables, that is no wires in a cable crossover each other. In terms of a
   flat layout, if a cable contains :math:`N` wires then :math:`pin\ 1` of one of the cable's ports is
   connected to :math:`pin\ N` of the port at the other end of the cable.

2) Within a branch, no crossovers occur in the pin connections between any two ports (although
   crossovers may occur with connections to other ports). This means that if a mapping between
   port's :math:`P` and :math:`Q` is described as :math:`(p_1,\ p_2,\ ...\ p_N)` of :math:`P`
   connect to :math:`(q_1,\ q_2,\ ...\ q_N)` of :math:`Q`, then :math:`p_i\ <\ p_j \iff q_i\ >\ q_j`.

"""


import pyscipopt as scip



class Node(object):
    """
    Args:
        port_interconnects: a list of tuples of decreasing length

    Returns:
    --------
    G_prime : networkx.Graph object
        The subgraph of G fullfilling criteria 1) and 2).

    """
    def __init__(self, id, port_interconnects: list(tuple)):
        pass



class Layout(object):
    def __init__(self, path_network):
        self.__model = scip.Model()
        self.__vars = {}

    def add_node(self, Node):
        pass


class PathNetwork(object):
    def __init__(self, network):
        self.__network = network

    def add_connectivity_model(self, model):
        pass

    def add_path(self, path):
        pass

    def layout_paths(self):
        m = scip.Model()



    for m, branch in enumerate(branches):
        for n, configuration in enumerate(branch)
            x[m, n] = model.addVar(f'x[{m}, {n}', vtype='B')
        # Only one configuration from each branch
        model.addCons(quicksum(x[m, n] for n in range(len(branch))) == 1)
    model.setObjective(quicksum(x[m, n] for m in range(len(branches)) for n in range(len(branch))), 'minimize')

