#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019-21  David Brooks
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

import networkx as nx

#===============================================================================

import nifstd_tools.simplify as nif

#===============================================================================

# ApiNATOMY predicates

ApiNATOMY_annotates = 'apinatomy:annotates'
ApiNATOMY_internalIn = 'apinatomy:internalIn'
ApiNATOMY_lyphs = 'apinatomy:lyphs'
ApiNATOMY_next = 'apinatomy:next'
ApiNATOMY_nexts = 'apinatomy:next*'
ApiNATOMY_publications = 'apinatomy:publications'

#===============================================================================

def isLayer(s, blob):
    return nif.ematch(blob, (lambda e, m: nif.sub(e, m) and nif.pred(e, nif.layerIn)), s)

def layer_regions(start, blob):
    direct = [nif.obj(t) for t in
              nif.ematch(blob, (lambda e, m: nif.sub(e, m)
                                and (nif.pred(e, ApiNATOMY_internalIn) or
                                     nif.pred(e, nif.endIn) or
                                     nif.pred(e, nif.fasIn))),
                         start)]
    layers = [nif.obj(t) for d in direct for t in
              nif.ematch(blob, (lambda e, m: nif.sub(e, m)
                                and isLayer(m, blob)
                                and (nif.pred(e, nif.ie) or
                                     nif.pred(e, nif.ext))),
                         d)]
    lregs = []
    if layers:
        ldir = [nif.obj(t) for d in direct for t in
                nif.ematch(blob, (lambda e, m: nif.sub(e, m)
                                  and nif.pred(e, nif.layerIn)),
                           d)]
        lregs = [nif.obj(t) for d in ldir for t in
                 nif.ematch(blob, (lambda e, m: nif.sub(e, m)
                                   and not isLayer(m, blob)
                                   and (nif.pred(e, nif.ie) or
                                        nif.pred(e, nif.ext))),
                            d)]
    regions = [nif.obj(t) for d in direct for t in
               nif.ematch(blob, (lambda e, m: nif.sub(e, m)
                                 and not isLayer(m, blob)
                                 and (nif.pred(e, nif.ie) or
                                      nif.pred(e, nif.ext))),
                          d)]
    assert not (lregs and regions), (lregs, regions)  # not both
    regions = lregs if lregs else regions
    return start, layers[0] if layers else None, regions[0] if regions else None

#===============================================================================

def connectivity(data):
    blob, *_ = nif.apinat_deblob(data)
    starts = [nif.obj(e) for e in blob['edges'] if nif.pred(e, ApiNATOMY_lyphs)]
    nexts = [(nif.sub(t), nif.obj(t)) for start in starts for t in
              nif.ematch(blob, (lambda e, m: nif.pred(e, ApiNATOMY_next)
                                          or nif.pred(e, ApiNATOMY_nexts)), None)]
    connected_pairs = sorted(set([tuple([layer_regions(e, blob) for e in p]) for p in nexts]))
    G = nx.DiGraph()
    for pair in connected_pairs:
        if pair[0][1:] != pair[1][1:]:
            G.add_edge(pair[0][1:], pair[1][1:], directed=True)
    return G

#===============================================================================

def knowledge(entity, data):
    knowledge = {}
    for node in data['nodes']:
        if node.get('id') == entity:
            knowledge['label'] = node['meta'].get('synonym', [entity])[0]
            break
    apinatomy_neuron = None
    for edge in data['edges']:
        if nif.sub(edge) == entity and nif.pred(edge, ApiNATOMY_annotates):
            apinatomy_neuron = nif.obj(edge)
            break
    if apinatomy_neuron is not None:
        publications = []
        for edge in data['edges']:
            if nif.sub(edge) == apinatomy_neuron and nif.pred(edge, ApiNATOMY_publications):
                publications.append(nif.obj(edge))
        knowledge['publications'] = publications
    knowledge['connectivity'] = connectivity(data)
    return knowledge

#===============================================================================
