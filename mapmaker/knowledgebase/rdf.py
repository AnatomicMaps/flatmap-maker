#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019  David Brooks
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

import os

#===============================================================================

import rdflib

#===============================================================================

from mapmaker.knowledgebase import KnowledgeBase

#===============================================================================

class UrlMaker(object):
    def __init__(self, base, layer):
        self._base = '{}/{}'.format(base, layer)

    def url(self, id):
        return rdflib.URIRef('{}/{}'.format(self._base, id))

#===============================================================================

def update_RDF(map_base, map_id, map_source, annotations, update_knowledgebase=False):

    map_dir = os.path.join(map_base, map_id)

    # RDF generation

    if update_knowledgebase:
        kb_path = os.path.join(map_base, 'KnowledgeBase.sqlite')
        print('Knowledge base: ', kb_path, (not os.path.exists(kb_path)))
        graph = KnowledgeBase(kb_path, create=(not os.path.exists(kb_path)))
    else:
        graph = rdflib.Graph()

#    graph.namespace_manager = NS.SCICRUNCH_NS
#    namespaces_dict = NS.namespaces_dict()
## Only really need rdf: obo: fma: FMA: RO: UBERON: ILX: flatmap:
## See https://github.com/RDFLib/rdflib/issues/794
#
    namespaces_dict = {
        'FMA': rdflib.namespace.Namespace('http://purl.org/sig/ont/fma/fma'),
        'ILX': rdflib.namespace.Namespace('http://uri.interlex.org/base/ilx_'),
        'NCBITaxon': rdflib.namespace.Namespace('http://purl.obolibrary.org/obo/NCBITaxon_'),
        'RO': rdflib.namespace.Namespace('http://purl.obolibrary.org/obo/RO_'),
        'UBERON': rdflib.namespace.Namespace('http://purl.obolibrary.org/obo/UBERON_'),
        'fma': rdflib.namespace.Namespace('http://purl.org/sig/ont/fma/'),
        'ilx': rdflib.namespace.Namespace('http://uri.interlex.org/'),
        'obo': rdflib.namespace.Namespace('http://purl.obolibrary.org/obo/'),
        }
    for pfx, ns in namespaces_dict.items():
        graph.bind(pfx, ns, override=True)

    FLATMAP_NS = rdflib.namespace.Namespace('http://celldl.org/ontologies/flatmap/')
    graph.bind('flatmap', FLATMAP_NS, override=True)

    map_uri = rdflib.URIRef(map_source)
    for object_id, metadata in annotations.items():
        if 'error' in metadata:
            print('Error in {} layer: {}: {}'.format(metadata['layer'],
                                                     metadata['error'],
                                                     metadata['annotation']))
            continue

        layer_urls = UrlMaker(map_source, metadata['layer'])
        annotation = metadata['annotation']
        properties = Parser.annotation(annotation)
        feature_id = properties.get('id')

        feature_uri = layer_urls.url(feature_id)
        graph.remove( (feature_uri, None, None) )
        feature_class = None

        route = { 'source': '', 'via': [], 'target': '' }

        for key, value in properties.items():
            if key == 'models':
                prop = namespaces_dict['RO']['0003301']
                (prefix, local) = value.split(':', 1)
                graph.add( (feature_uri, prop, namespaces_dict[prefix][local]) )
            elif key == 'node':
                feature_class = FLATMAP_NS['Node']
                graph.add( (feature_uri, FLATMAP_NS['nodeClass'], FLATMAP_NS[value[0]]) )
            elif key == 'edge':
                feature_class = FLATMAP_NS['Edge']
                if len(value) < 2:
                    raise ValueError('Edge must have a source and target: {}'.format(annotation))
                route['source'] = value[0]
                route['target'] = value[-1]
                route['via'] = value[1:-1]
            elif key in ['source', 'via', 'target']:
                if feature_class is None:
                    feature_class = FLATMAP_NS['Edge']
                elif feature_class != FLATMAP_NS['Edge']:
                    raise ValueError('Only edges can be routed: {}'.format(annotation))
                if key in ['source', 'target']:
                    route[key] = value[0]
                else:
                    route['via'].extend(value)
        if feature_class is None:
            feature_class = FLATMAP_NS['Node']  # Assume we have a Node
        elif feature_class == FLATMAP_NS['Edge']:
            if route['source']:
                graph.add( (feature_uri, FLATMAP_NS['source'], layer_urls.url(route['source'])) )
            if route['target']:
                graph.add( (feature_uri, FLATMAP_NS['target'], layer_urls.url(route['target'])) )
            for via in route['via']:
                graph.add( (feature_uri, FLATMAP_NS['via'], layer_urls.url(via)) )

        graph.add( (feature_uri, FLATMAP_NS['map'], map_uri) )
        graph.add( (feature_uri, rdflib.namespace.RDF['type'], feature_class) )

    with open(os.path.join(map_dir, 'annotations.ttl'), 'w') as turtle:
        # Don't set `base=map_uri` until RDFLib 5.0 and then use `explicit_base=True`
        # See https://github.com/RDFLib/rdflib/issues/559
        turtle.write(graph.serialize(format='turtle').decode('utf-8'))

    graph.close()

#===============================================================================
