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
import pyomo.environ as pyomo

#===============================================================================

# Following is based on arXiv:17010.02226v1 [cs:CG] 5 Oct 2017
# "Efficient Generation of Geographically Accurate Transit Maps"
# Hannah Bast, Patrick Brosi, Sabine Storandt.

class TransitMap:
    def __init__(self, edges, edge_lines, node_edge_order):
        self.__graph = nx.Graph(edges)
        for edge in self.__graph.edges:
            self.__graph.edges[edge]['lines'] = set()
        for edge, lines in edge_lines.items():
            self.__graph.edges[edge]['lines'].update(lines)
        self.__model = pyomo.ConcreteModel()
        node_ordering = { key: tuple(node for node in ordered_nodes if node in self.__graph)
                            for key, ordered_nodes in node_edge_order.items() }

        #======================================================================

        # n_n1_l_le_p   or   e_l<=p

        def n_n1_l_le_p_set():
            for n, n1, lines in self.__graph.edges(data='lines'):
                for l in lines:
                    for p in range(1, len(lines)+1):
                        yield (n, n1, l, p)
                        yield (n1, n, l, p)

        def n_n1_l_le_p_constraint(model, n, n1, l, p):
            if p == len(self.__graph.edges[n, n1]['lines']):
                return pyomo.Constraint.Skip
            return model.n_n1_l_le_p[n, n1, l, p] <= model.n_n1_l_le_p[n, n1, l, p+1]

        def edge_position_set():
            for n, n1, lines in self.__graph.edges(data='lines'):
                for p in range(1, len(lines)+1):
                    yield (n, n1, p)
                    yield (n1, n, p)

        def edge_position_unique_constraint(model, n, n1, p):
            return sum(model.n_n1_l_le_p[n, n1, l, p] for l in self.__graph.edges[n, n1]['lines']) == p

        def edge_line_set():
            for n, n1, lines in self.__graph.edges(data='lines'):
                for l in lines:
                    yield (n, n1, l)

        def edge_line_mirror_constraint(model, n, n1, l):
            lines = self.__graph.edges[n, n1]['lines']
            return (sum(model.n_n1_l_le_p[n, n1, l, p]
                      + model.n_n1_l_le_p[n1, n, l, p] for p in range(1, len(lines)+1))) == (len(lines) + 1)

        self.__model.n_n1_l_le_p = pyomo.Var(n_n1_l_le_p_set(), domain=pyomo.Binary)                                    # pyright: ignore[reportAttributeAccessIssue]
        self.__model.n_n1_l_p_constraint = pyomo.Constraint(n_n1_l_le_p_set(), rule=n_n1_l_le_p_constraint)             # pyright: ignore[reportAttributeAccessIssue]
        self.__model.edge_position_unique_constraint = pyomo.Constraint(edge_position_set(), rule=edge_position_unique_constraint)  # pyright: ignore[reportAttributeAccessIssue]
        self.__model.edge_line_mirror_constraint = pyomo.Constraint(edge_line_set(), rule=edge_line_mirror_constraint)  # pyright: ignore[reportAttributeAccessIssue]

        #======================================================================

        # n_n1_A_lt_B   or  e_A<B
        # A before B in (n, n1) <===> B before A in (n1, n)

        def n_n1_A_lt_B_set():
            for n, n1, lines in self.__graph.edges(data='lines'):
                for A, B in itertools.combinations(lines, 2):
                    yield (n, n1, A, B)
                    yield (n, n1, B, A)
                    yield (n1, n, A, B)
                    yield (n1, n, B, A)

        def n_n1_A_lt_B_constraint_1(model, n, n1, A, B):
            lines = self.__graph.edges[n, n1]['lines']
            return (sum(model.n_n1_l_le_p[n, n1, A, p] for p in range(1, len(lines)+1))
                  - sum(model.n_n1_l_le_p[n, n1, B, p] for p in range(1, len(lines)+1))
                  + len(lines)*model.n_n1_A_lt_B[n, n1, B, A]) >= 0

        def n_n1_A_lt_B_constraint_2(model, n, n1, A, B):
            return model.n_n1_A_lt_B[n, n1, A, B] + model.n_n1_A_lt_B[n, n1, B, A] == 1

        def n_n1_A_lt_B_constraint_3(model, n, n1, A, B):
            return model.n_n1_A_lt_B[n, n1, A, B] + model.n_n1_A_lt_B[n1, n, A, B] == 1

        self.__model.n_n1_A_lt_B = pyomo.Var(set(n_n1_A_lt_B_set()), domain=pyomo.Binary)                               # pyright: ignore[reportAttributeAccessIssue]
        self.__model.n_n1_A_lt_B_constraint_1 = pyomo.Constraint(set(n_n1_A_lt_B_set()), rule=n_n1_A_lt_B_constraint_1) # pyright: ignore[reportAttributeAccessIssue]
        self.__model.n_n1_A_lt_B_constraint_2 = pyomo.Constraint(set(n_n1_A_lt_B_set()), rule=n_n1_A_lt_B_constraint_2) # pyright: ignore[reportAttributeAccessIssue]
        self.__model.n_n1_A_lt_B_constraint_3 = pyomo.Constraint(set(n_n1_A_lt_B_set()), rule=n_n1_A_lt_B_constraint_3) # pyright: ignore[reportAttributeAccessIssue]

        #======================================================================

        # n_n1_n2_A_B   #   n_e_e1_A&B
        # A, B in both (n, n1) and (n, n2) (and also (n1, n) and (n2, n))
        # 0 if A, B don't cross, 1 if they cross

        def n_n1_n2_A_B_set():
            for node, degree in self.__graph.degree:
                if degree >= 2:
                    for e1, e2 in itertools.combinations(self.__graph.edges(node, data='lines'), 2):
                        for A, B in itertools.combinations(e1[2], 2):
                            if A in e2[2] and B in e2[2]:
                                yield (node, e1[1], e2[1], A, B)

        def n_n1_n2_A_B_constraint_1(model, node, n1, n2, A, B):
            return (model.n_n1_A_lt_B[node, n1, A, B]
                  - model.n_n1_A_lt_B[node, n2, B, A]
                  - model.n_n1_n2_A_B[node, n1, n2, A, B]) <= 0

        def n_n1_n2_A_B_constraint_2(model, node, n1, n2, A, B):
            return (model.n_n1_A_lt_B[node, n2, B, A]
                  - model.n_n1_A_lt_B[node, n1, A, B]
                  - model.n_n1_n2_A_B[node, n1, n2, A, B]) <= 0

        self.__model.n_n1_n2_A_B = pyomo.Var(n_n1_n2_A_B_set(), domain=pyomo.Binary)                                # pyright: ignore[reportAttributeAccessIssue]
        self.__model.n_n1_n2_A_B_constraint_1 = pyomo.Constraint(n_n1_n2_A_B_set(), rule=n_n1_n2_A_B_constraint_1)  # pyright: ignore[reportAttributeAccessIssue]
        self.__model.n_n1_n2_A_B_constraint_2 = pyomo.Constraint(n_n1_n2_A_B_set(), rule=n_n1_n2_A_B_constraint_2)  # pyright: ignore[reportAttributeAccessIssue]

        #======================================================================

        # This makes sure that lines radiating from a node preserve the geomteric order of
        # the drawn centrelines.

        # n_n1_n2_n3_A_B
        # (n, n1), (n, n2), (n, n3) are in counter-clockwise order
        # A, B both in L((n, n1)) s.th. neither A nor B in both L((n, n2)), L((n, n3))
        # A in L((n, n2)) <==> B in L((n, n3)) ==> value = 1 if eA<B, 0 if eB<A
        # A in L((n, n2)) <==> B in L((n, n2)) ==> value = 0 if eA<B, 1 if eB<A

        def n_n1_n2_n3_A_B_set():
            for node, degree in self.__graph.degree:
                if degree > 2 and node in node_ordering:
                    ordered_nodes = [n for n in node_ordering[node] if [node, n] in self.__graph.edges] # pyright: ignore[reportOperatorIssue]
                    for i, n1 in enumerate(ordered_nodes):
                        nodes = ordered_nodes[i+1:] + ordered_nodes[:i]
                        e1_lines = self.__graph.edges[node, n1]['lines']
                        for (n2, n3) in itertools.combinations(nodes, 2):
                            e2_lines = self.__graph.edges[node, n2]['lines']
                            e3_lines = self.__graph.edges[node, n3]['lines']
                            for A, B in itertools.combinations(e1_lines, 2):
                                if ((not (A in e2_lines and B in e2_lines)
                                 and not (A in e3_lines and B in e3_lines))
                                 and (A in e2_lines and B in e3_lines
                                   or A in e3_lines and B in e2_lines)):
                                    yield (node, n1, n2, n3, A, B)

        def n_n1_n2_n3_A_B_constraint(model, node, n1, n2, n3, A, B):
            if A in self.__graph.edges[node, n3]['lines']:
                return 1 - model.n_n1_A_lt_B[node, n1, A, B] - model.n_n1_n2_n3_A_B[node, n1, n2, n3, A, B] <= 0
            else:
                return 1 - model.n_n1_A_lt_B[node, n1, B, A] - model.n_n1_n2_n3_A_B[node, n1, n2, n3, A, B] <= 0

        self.__model.n_n1_n2_n3_A_B = pyomo.Var(n_n1_n2_n3_A_B_set(), domain=pyomo.Binary)                              # pyright: ignore[reportAttributeAccessIssue]
        self.__model.n_n1_n2_n3_A_B_constraint = pyomo.Constraint(n_n1_n2_n3_A_B_set(), rule=n_n1_n2_n3_A_B_constraint) # pyright: ignore[reportAttributeAccessIssue]

        #======================================================================

        # We minimise total crossings-over of lines
        def total_crossings(model):
            return (sum(model.n_n1_n2_A_B[node, n1, n2, A, B]
                            for (node, n1, n2, A, B) in model.n_n1_n2_A_B)
                  + sum(model.n_n1_n2_n3_A_B[node, n1, n2, n3, A, B]
                            for (node, n1, n2, n3, A, B) in model.n_n1_n2_n3_A_B))

        self.__model.total_crossings = pyomo.Objective(rule=total_crossings)    # pyright: ignore[reportAttributeAccessIssue]

    #======================================================================


    #======================================================================

    def solve(self, tee=False):
    #==========================
        # Solve the model using CBC
        options = {'sec': 600, 'threads': 10, 'ratio': 0.02}
        pyomo.SolverFactory('cbc').solve(self.__model, options = options, tee=tee)

    def results(self):
    #=================
        ordering = {}
        for n, n1, lines in self.__graph.edges(data='lines'):
            order = []
            last_l = None
            for l in lines:
                for p in range(1, len(lines)+1):
                    if self.__model.n_n1_l_le_p[n, n1, l, p].value == 1:
                        if l != last_l:
                            order.append((p, l))
                            last_l = l
            ordering[(n, n1)] = [l for _, l in sorted(order)]
        return ordering

#===============================================================================

if __name__ == '__main__':
#=========================

    from pprint import pprint

    edges = {
        ('L1_L2_spinal_n-lumbar_splanchnic_n', 'L1-spinal'),
        ('L1_L2_spinal_n-lumbar_splanchnic_n', 'L2-spinal'),
        ('L1_L2_spinal_n-lumbar_splanchnic_n', 'keast_6'),
        ('L1_dorsal_root_end', 'L1-spinal'),
        ('L1_ventral_root_ramus_end', 'L1-spinal'),
        ('L2-spinal', 'L2_ventral_root_ramus_end'),
        ('L2_dorsal_root_end', 'L2-spinal'),
        ('L6-spinal', 'L6_dorsal_root_end'),
        ('L6_S1_spinal_n-pelvic_splanchnic_n', 'L6-spinal'),
        ('L6_ventral_root_end', 'L6-spinal'),
        ('S1-spinal', 'L6_S1_spinal_n-pelvic_splanchnic_n'),
        ('S1_dorsal_root_end', 'S1-spinal'),
        ('S1_ventral_root_end', 'S1-spinal'),
        ('bladder_n-bladder', 'keast_3'),
        ('keast_3', 'L6_S1_spinal_n-pelvic_splanchnic_n'),
        ('keast_3', 'bladder_n-bladder'),
        ('keast_3', 'keast_6'),
        ('keast_6', 'keast_3')
    }

    edge_lines = {
        ('L1-spinal', 'L1_L2_spinal_n-lumbar_splanchnic_n'): {1, 2, 4},
        ('L1-spinal', 'L1_dorsal_root_end'): {4},
        ('L1_ventral_root_ramus_end', 'L1-spinal'): {1, 2},
        ('L2-spinal', 'L1_L2_spinal_n-lumbar_splanchnic_n'): {1, 2, 4},
        ('L2-spinal', 'L2_dorsal_root_end'): {4},
        ('L2-spinal', 'L2_ventral_root_ramus_end'): {1, 2},
        ('L6-spinal', 'L6_S1_spinal_n-pelvic_splanchnic_n'): {0, 3},
        ('L6_dorsal_root_end', 'L6-spinal'): {3},
        ('L6_ventral_root_end', 'L6-spinal'): {0},
        ('S1-spinal', 'L6_S1_spinal_n-pelvic_splanchnic_n'): {0, 3},
        ('S1-spinal', 'S1_dorsal_root_end'): {3},
        ('S1-spinal', 'S1_ventral_root_end'): {0},
        ('bladder_n-bladder', 'keast_3'): {2},           ### NB. Node order difference
        ('keast_3', 'L6_S1_spinal_n-pelvic_splanchnic_n'): {0, 3},
        ('keast_3', 'bladder_n-bladder'): {0, 1, 3, 4},  ### NB. Node order difference
        ('keast_6', 'L1_L2_spinal_n-lumbar_splanchnic_n'): {1, 2, 4},
        ('keast_6', 'keast_3'): {1, 2, 4}
    }

    node_edge_order = {   # Order 3 and above nodes where lines differ between edges, anticlockwise order
        'L1_L2_spinal_n-lumbar_splanchnic_n': ('keast_6', 'L2-spinal', 'L1-spinal'),
        'L6_S1_spinal_n-pelvic_splanchnic_n': ('keast_3', 'S1-spinal', 'L6-spinal'),
        'L1-spinal': ('L1_L2_spinal_n-lumbar_splanchnic_n',
                      'L1_ventral_root_ramus_end',
                      'L1_ventral_root_end',
                      'L1_dorsal_root_end'),
        'L2-spinal': ('L1_L2_spinal_n-lumbar_splanchnic_n',
                      'L2_ventral_root_ramus_end',
                      'L2_dorsal_root_end'),
        'L6-spinal': ('L6_S1_spinal_n-pelvic_splanchnic_n',
                      'L6_ventral_root_end',
                      'L6_dorsal_root_end'),
        'S1-spinal': ('L6_S1_spinal_n-pelvic_splanchnic_n',
                      'S1_ventral_root_end',
                      'S1_dorsal_root_end'),
        'keast_3': ('bladder_n-bladder',
                    'L6_S1_spinal_n-pelvic_splanchnic_n',
                    'keast_6')
    }


    tee = False
    tm = TransitMap(edges, edge_lines, node_edge_order)

    pprint(edge_lines)
    print()

    tm.solve(tee=tee)
    results = tm.results()
    pprint(results)

#===============================================================================
