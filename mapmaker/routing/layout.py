#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2022  David Brooks
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

import itertools

#===============================================================================

import networkx as nx
from pyomo.environ import *

#===============================================================================

# Following is based on arXiv:17010.02226v1 [cs:CG] 5 Oct 2017
# "Efficient Generation of Geographically Accurate Transit Maps"
# Hannah Bast, Patrick Brosi, Sabine Storandt.

class TransitMap:
    def __init__(self, route, lines):
        self.__graph = nx.Graph()
        self.__lines = lines
        for id, edge in route.items():
            self.__graph.add_edge(*edge, id=id)

        self.__model = ConcreteModel()

        # e_l_le_p
        def e_l_le_p_set():
            for _, _, e in self.__graph.edges(data='id'):
                for l in self.__lines[e]:
                    for p in range(1, len(self.__lines[e])+1):
                        yield (e, l, p)
        self.__model.e_l_le_p = Var(e_l_le_p_set(), domain=Binary)

        def line_position_unique_constraint(model, e, l, p):
            if p == len(self.__lines[e]):
                return Constraint.Skip
            return model.e_l_le_p[e, l, p] <= model.e_l_le_p[e, l, p+1]
        self.__model.line_position_unique_constraint = Constraint(e_l_le_p_set(), rule=line_position_unique_constraint)

        def edge_position_set():
            for _, _, e in self.__graph.edges(data='id'):
                for p in range(1, len(self.__lines[e])+1):
                    yield (e, p)

        def edge_position_unique_constraint(model, e, p):
            return sum(model.e_l_le_p[e, l, p] for l in self.__lines[e]) == p
        self.__model.edge_position_unique_constraint = Constraint(edge_position_set(), rule=edge_position_unique_constraint)

        # e_A_lt_B
        def e_A_lt_B_set():
            for node, degree in self.__graph.degree:
                if degree >= 2:
                    for pair in itertools.permutations(self.__graph.edges(node, data='id'), 2):
                        e, e1 = (pair[0][2], pair[1][2])
                        for A, B in itertools.combinations(self.__lines[e], 2):
                            if A in self.__lines[e1] and B in self.__lines[e1]:
                                yield (node, e, A, B)
                                yield (node, e, B, A)
        self.__model.e_A_lt_B = Var(set(e_A_lt_B_set()), domain=Binary)

        def node_crossing_order_constraint(model, node, e, A, B):
            return (sum(model.e_l_le_p[e, A, p] for p in range(1, len(self.__lines[e])+1))
                  - sum(model.e_l_le_p[e, B, p] for p in range(1, len(self.__lines[e])+1))
                  + len(lines[e])*model.e_A_lt_B[node, e, B, A]) >= 0
        self.__model.node_crossing_order_constraint = Constraint(set(e_A_lt_B_set()), rule=node_crossing_order_constraint)

        def node_crossing_unique_constraint(model, node, e, A, B):
            return model.e_A_lt_B[node, e, A, B] + model.e_A_lt_B[node, e, B, A] == 1
        self.__model.node_crossing_unique_constraint = Constraint(set(e_A_lt_B_set()), rule=node_crossing_unique_constraint)

        # e_e1_A_B
        def e_e1_A_B_set():
            for node, degree in self.__graph.degree:
                if degree >= 2:
                    for pair in itertools.permutations(self.__graph.edges(node, data='id'), 2):
                        e, e1 = (pair[0][2], pair[1][2])
                        for A, B in itertools.permutations(self.__lines[e], 2):
                            yield (node, e, e1, A, B)
        self.__model.e_e1_A_B = Var(e_e1_A_B_set(), domain=Binary)

        def node_crossing_exists_constraint_1(model, node, e, e1, A, B):
            if (A not in self.__lines[e]  or B not in self.__lines[e]
             or A not in self.__lines[e1] or B not in self.__lines[e1]):
                return Constraint.Skip   ## Why needed ??
            return (model.e_A_lt_B[node, e,  A, B]
                  - model.e_A_lt_B[node, e1, A, B]
                  - model.e_e1_A_B[node, e, e1, A, B]) <= 0

        def node_crossing_exists_constraint_2(model, node, e, e1, A, B):
            if (A not in self.__lines[e]  or B not in self.__lines[e]
             or A not in self.__lines[e1] or B not in self.__lines[e1]):
                return Constraint.Skip
            return (model.e_A_lt_B[node, e1, A, B]
                  - model.e_A_lt_B[node, e,  A, B]
                  - model.e_e1_A_B[node, e, e1, A, B]) <= 0

        self.__model.node_crossing_exists_constraint_1 = Constraint(e_e1_A_B_set(), rule=node_crossing_exists_constraint_1)
        self.__model.node_crossing_exists_constraint_2 = Constraint(e_e1_A_B_set(), rule=node_crossing_exists_constraint_2)

        # We minimise total crossings-over of lines
        def total_crossings(model):
            return sum(model.e_e1_A_B[node, e1, e2, A, B]
                for (node, e1, e2, A, B) in e_e1_A_B_set())
        self.__model.total_crossings = Objective(rule=total_crossings)

    def solve(self):
        # Solve the model using CBC
        SolverFactory('cbc').solve(self.__model)

    def results(self):
        ordered = {}
        for _, _, e in self.__graph.edges(data='id'):
            order = []
            last_l = None
            for l in self.__lines[e]:
                for p in range(1, len(self.__lines[e])+1):
                    if self.__model.e_l_le_p[e, l, p].value == 1:
                        if l != last_l:
                            order.append((p, l))
                            last_l = l
            ordered[e] = [l for _, l in sorted(order)]
        return ordered

#===============================================================================

if __name__ == '__main__':
#=========================

    from pprint import pprint

    route_edges = {
        'L1_dorsal_root': ('L1_dorsal_root_end', 'L1-spinal'),
        'L1_spinal_n': ('L1-spinal', 'L1_L2_spinal_n-lumbar_splanchnic_n'),
        'L1_ventral_root_ramus': ('L1-spinal', 'L1_ventral_root_ramusd'),
        'L2_dorsal_root': ('L2-spinal', 'L2_dorsal_root_end'),
        'L2_spinal_n': ('L2-spinal', 'L1_L2_spinal_n-lumbar_splanchnic_n'),
        'L2_ventral_root_ramus': ('L2-spinal', 'L2_ventral_root_ramus_end'),
        'bladder_n': ('bladder_n-bladder', 'keast_3'),
        'hypogastric_n': ('keast_6', 'keast_3'),
        'lumbar_splanchnic_n': ('keast_6', 'L1_L2_spinal_n-lumbar_splanchnic_n'),
        'pelvic_splanchnic_n': ('keast_3', 'L6_S1_spinal_n-pelvic_splanchnic_n')
    }

    L = {
        'L1_dorsal_root': {4},
        'L1_spinal_n': {0, 2, 4},
        'L1_ventral_root_ramus': {0, 2},
        'L2_dorsal_root': {4},
        'L2_spinal_n': {0, 2, 4},
        'L2_ventral_root_ramus': {0, 2},
        'bladder_n': {0, 1, 2, 3, 4},
        'hypogastric_n': {0, 2, 4},
        'lumbar_splanchnic_n': {0, 2, 4},
        'pelvic_splanchnic_n': {1, 3}
    }

    tm = TransitMap(route_edges, L)

    tm.solve()

    pprint(tm.results())

#===============================================================================
