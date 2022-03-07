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
    def __init__(self, route, lines, node_edge_order):
        self.__graph = nx.Graph()
        self.__lines = lines
        for id, edge in route.items():
            self.__graph.add_edge(*edge, id=id)

        self.__model = ConcreteModel()

        #======================================================================

        self.__edge_set = { e for _, _, e in self.__graph.edges(data='id') }

        #======================================================================

        # e_l_le_p
        def e_l_le_p_set():
            for e in self.__edge_set:
                for l in self.__lines[e]:
                    for p in range(1, len(self.__lines[e])+1):
                        yield (e, l, p)

        def e_l_le_p_constraint(model, e, l, p):
            if p == len(self.__lines[e]):
                return Constraint.Skip
            return model.e_l_le_p[e, l, p] <= model.e_l_le_p[e, l, p+1]

        def edge_position_set():
            for e in self.__edge_set:
                for p in range(1, len(self.__lines[e])+1):
                    yield (e, p)

        def edge_position_unique_constraint(model, e, p):
            return sum(model.e_l_le_p[e, l, p] for l in self.__lines[e]) == p

        self.__model.e_l_le_p = Var(e_l_le_p_set(), domain=Binary)
        self.__model.e_l_le_p_constraint = Constraint(e_l_le_p_set(), rule=e_l_le_p_constraint)
        self.__model.edge_position_unique_constraint = Constraint(edge_position_set(), rule=edge_position_unique_constraint)

        #======================================================================

        # e_A_lt_B
        def e_A_lt_B_set():
            for e in self.__edge_set:
                for A, B in itertools.combinations(self.__lines[e], 2):
                    yield (e, A, B)
                    yield (e, B, A)

        def e_A_lt_B_constraint_1(model, e, A, B):
            return (sum(model.e_l_le_p[e, A, p] for p in range(1, len(self.__lines[e])+1))
                  - sum(model.e_l_le_p[e, B, p] for p in range(1, len(self.__lines[e])+1))
                  + len(lines[e])*model.e_A_lt_B[e, B, A]) >= 0

        def e_A_lt_B_constraint_2(model, e, A, B):
            return model.e_A_lt_B[e, A, B] + model.e_A_lt_B[e, B, A] == 1

        self.__model.e_A_lt_B = Var(set(e_A_lt_B_set()), domain=Binary)
        self.__model.e_A_lt_B_constraint_1 = Constraint(set(e_A_lt_B_set()), rule=e_A_lt_B_constraint_1)
        self.__model.e_A_lt_B_constraint_2 = Constraint(set(e_A_lt_B_set()), rule=e_A_lt_B_constraint_2)

        #======================================================================

        # e_e1_A_B
        def e_e1_A_B_node_set():
            for node, degree in self.__graph.degree:
                if degree >= 2:
                    for e, e1 in itertools.permutations(self.edges(node), 2):
                        for A, B in itertools.permutations(self.__lines[e], 2):
                            if A in self.__lines[e1] and B in self.__lines[e1]:
                                yield (node, e, e1, A, B)

        def e_e1_A_B_constraint_1(model, node, e, e1, A, B):
            return (model.e_A_lt_B[e,  A, B]
                  - model.e_A_lt_B[e1, A, B]
                  - model.e_e1_A_B[node, e, e1, A, B]) <= 0

        def e_e1_A_B_constraint_2(model, node, e, e1, A, B):
            return (model.e_A_lt_B[e1, A, B]
                  - model.e_A_lt_B[e,  A, B]
                  - model.e_e1_A_B[node, e, e1, A, B]) <= 0

        self.__model.e_e1_A_B = Var(e_e1_A_B_node_set(), domain=Binary)
        self.__model.e_e1_A_B_constraint_1 = Constraint(e_e1_A_B_node_set(), rule=e_e1_A_B_constraint_1)
        self.__model.e_e1_A_B_constraint_2 = Constraint(e_e1_A_B_node_set(), rule=e_e1_A_B_constraint_2)

        #======================================================================

        # e_e1_e2_A_B
        # e, e1, e2 are in counter-clockwise order
        # A, B both in L(e) s.th. neither A nor B in both L(e1), L(e2)
        # A in L(e1) <==> B in L(e2) ==> value = 1 if eA<B, 0 if eB<A
        # A in L(e2) <==> B in L(e1) ==> value = 0 if eA<B, 1 if eB<A

        def e_e1_e2_A_B_node_set():
            for node, degree in self.__graph.degree:
                if degree > 2 and node in node_edge_order:
                    ordered_edges = node_edge_order[node]
                    for n, e in enumerate(ordered_edges):
                        edges = ordered_edges[n+1:] + ordered_edges[:n]
                        for (e1, e2) in itertools.combinations(edges, 2):
                            for A, B in itertools.combinations(self.__lines[e], 2):
                                if ((not (A in self.__lines[e1] and B in self.__lines[e1])
                                 and not (A in self.__lines[e2] and B in self.__lines[e2]))
                                 and (A in self.__lines[e1] and B in self.__lines[e2]
                                   or A in self.__lines[e2] and B in self.__lines[e1])):
                                    yield (node, e, e1, e2, A, B)

        def e_e1_e2_A_B_constraint(model, node, e, e1, e2, A, B):
            if A in self.__lines[e2]:
                return 1 - model.e_A_lt_B[e, A, B] - model.e_e1_e2_A_B[node, e, e1, e2, A, B] <= 0
            else:
                return 1 - model.e_A_lt_B[e, B, A] - model.e_e1_e2_A_B[node, e, e1, e2, A, B] <= 0


        self.__model.e_e1_e2_A_B = Var(e_e1_e2_A_B_node_set(), domain=Binary)
        self.__model.e_e1_e2_A_B_constraint = Constraint(e_e1_e2_A_B_node_set(), rule=e_e1_e2_A_B_constraint)

            return (sum(model.e_l_le_p[e, A, p] for p in range(1, len(self.__lines[e])+1))
                  - sum(model.e_l_le_p[e, B, p] for p in range(1, len(self.__lines[e])+1))


                if degree >= 2:
                    for pair in itertools.permutations(self.__graph.edges(node, data='id'), 2):
                        e, e1 = (pair[0][2], pair[1][2])
                            yield (node, e, e1, A, B)

            if (A not in self.__lines[e]  or B not in self.__lines[e]
             or A not in self.__lines[e1] or B not in self.__lines[e1]):

            if (A not in self.__lines[e]  or B not in self.__lines[e]
             or A not in self.__lines[e1] or B not in self.__lines[e1]):
                return Constraint.Skip


        # We minimise total crossings-over of lines
        def total_crossings(model):
            return (sum(model.e_e1_A_B[node, e1, e2, A, B]
                            for (node, e1, e2, A, B) in self.__model.e_e1_A_B)
                  + sum(model.e_e1_e2_A_B[node, e, e1, e2, A, B]
                            for (node, e, e1, e2, A, B) in self.__model.e_e1_e2_A_B))

        self.__model.total_crossings = Objective(rule=total_crossings)

    def solve(self):
    def edges(self, node):
    #=====================
        for _, _, e in self.__graph.edges(node, data='id'):
            yield e

        # Solve the model using CBC
        SolverFactory('cbc').solve(self.__model)

    def results(self):
    #=================
        ordered = {}
        for e in self.__edge_set:
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
        'L1_ventral_root_ramus': ('L1-spinal', 'L1_ventral_root_ramus_end'),
        'L2_dorsal_root': ('L2-spinal', 'L2_dorsal_root_end'),
        'L2_spinal_n': ('L2-spinal', 'L1_L2_spinal_n-lumbar_splanchnic_n'),
        'L2_ventral_root_ramus': ('L2-spinal', 'L2_ventral_root_ramus_end'),
        'bladder_n': ('bladder_n-bladder', 'keast_3'),
        'hypogastric_n': ('keast_6', 'keast_3'),
        'lumbar_splanchnic_n': ('keast_6', 'L1_L2_spinal_n-lumbar_splanchnic_n'),
        'pelvic_splanchnic_n': ('keast_3', 'L6_S1_spinal_n-pelvic_splanchnic_n')
    }

    node_order = {   # Order 3 and above nodes where lines differ between edges, anticlockwise order
        'keast_3': ['bladder_n', 'pelvic_splanchnic_n', 'hypogastric_n'],
        'L1-spinal': ['lumbar_splanchnic_n', 'L1_ventral_root_ramus', 'L1_dorsal_root'],
        'L2-spinal': ['lumbar_splanchnic_n', 'L2_ventral_root_ramus', 'L2_dorsal_root'],
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


    tm.solve()
    tm = TransitMap(route_edges, L, node_order)

    pprint(tm.results())

#===============================================================================
