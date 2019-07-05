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

import json
import os

#===============================================================================

import rdflib

#===============================================================================

from src.drawml import GeometryExtractor
from src.parser import Parser
from src.mbtiles import MBTiles

from src.knowledgebase import KnowledgeBase
import src.namespaces as NS

#===============================================================================

if __name__ == '__main__':
    import argparse
    import os, sys

    parser = argparse.ArgumentParser(description='Convert Powerpoint slides to a flatmap.')

    parser.add_argument('--debug-xml', action='store_true',
                        help="save a slide's DrawML for debugging")
    parser.add_argument('--powerpoint', metavar='POWERPOINT',
                        help='File or URL of Powerpoint slides')
    parser.add_argument('--update-knowledgebase', action='store_true',
                        help="directly update the SPARC knowledge base")
    parser.add_argument('--version', action='version', version='0.3.2')

    parser.add_argument('map_base', metavar='MAPS_DIR',
                        help='base directory for generated flatmaps')
    parser.add_argument('map_id', metavar='MAP_ID',
                        help='a unique identifier for the map')
    # Need to be able to process a remote (PMR) source...

    args = parser.parse_args()

    map_dir = os.path.join(args.map_base, args.map_id)

    # MBTILES --> PPT

    # MBTILES --> RDF

    mbtiles_file = os.path.join(map_dir, 'index.mbtiles')
    tile_db = MBTiles(mbtiles_file)

    if args.powerpoint:
        if args.powerpoint.startswith('http:') or args.powerpoint.startswith('https:'):
            response = requests.get(args.powerpoint)
            if response.status_code != requests.codes.ok:
                sys.exit('Cannot retrieve remote Powerpoint file')
            pptx_source = args.powerpoint
            pptx_bytes = io.BytesIO(response.content)
        else:
            if not os.path.exists(args.powerpoint):
                sys.exit('Missing Powerpoint file')
            pptx_source = os.path.abspath(args.powerpoint)
            pptx_bytes = open(pptx_source, 'rb')

        map_source = pptx_source

        ## Don't run if dir exists and not --force
        ## rmdir if exists and --force
        ##

        if not os.path.exists(map_dir):
            os.makedirs(map_dir)

        print('Extracting layers...')
        map_extractor = GeometryExtractor(pptx_bytes, args)

        # Process slides, saving layer information

        annotations = {}
        layers = []
        for slide_number in range(2, len(map_extractor)+1):  # First slide is background layer, so skip
            layer = map_extractor.slide_to_layer(slide_number, False)
            layers.append({
                'id': layer.layer_id,
                'description': layer.description
                })
            annotations.update(layer.annotations)

        if len(layers) == 0:
            sys.exit('No map layers in Powerpoint...')

        # Save path of the Powerpoint source
        tile_db.add_metadata(source=pptx_source)
        # Save annotations in metadata
        tile_db.add_metadata(annotations=json.dumps(annotations))
        # Commit updates to the database
        tile_db.execute("COMMIT")

    else:
        map_source = tile_db.metadata('source')
        annotations = json.loads(tile_db.metadata('annotations'))

    tile_db.close();

    # RDF generation

    if args.update_knowledgebase:
        kb_path = os.path.join(args.map_base, 'KnowledgeBase.sqlite')
        print(kb_path, (not os.path.exists(kb_path)))
        graph = KnowledgeBase(kb_path, create=(not os.path.exists(kb_path)))
    else:
        graph = rdflib.Graph()

#    graph.namespace_manager = NS.SCICRUNCH_NS
#    namespaces_dict = NS.namespaces_dict()
    ## Only really need rdf: obo: fma: FMA: RO: UBERON: ILX: flatmap:
    namespaces_dict = {
        'FMA': rdflib.namespace.Namespace('http://purl.org/sig/ont/fma/fma'),
        'ILX': rdflib.namespace.Namespace('http://uri.interlex.org/base/ilx_'),
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
    for object_id, properties in annotations.items():
        if 'error' in properties:
            print('Error in {} layer: {}: {}'.format(properties['layer'],
                                                     properties['error'],
                                                     properties['annotation']))
            continue

        annotation = Parser.annotation(properties['annotation'])
        feature_id = annotation[0]
        feature_class = None
        feature_uri = rdflib.URIRef('{}/{}'.format(map_source, feature_id))
        graph.remove( (feature_uri, None, None) )

        route = { 'source': '', 'via': [], 'target': '' }

        for p in annotation[1:]:
            if p[0] == 'models':
                prop = namespaces_dict['RO']['0003301']
                for o in p[1]:
                    (prefix, local) = o.split(':', 1)
                    graph.add( (feature_uri, prop, namespaces_dict[prefix][local]) )
            elif p[0] == 'node':
                feature_class = FLATMAP_NS['Node']
                graph.add( (feature_uri, FLATMAP_NS['nodeClass'], FLATMAP_NS[p[1]]) )
            elif p[0] == 'edge':
                feature_class = FLATMAP_NS['Edge']
                if len(p[1]) < 2:
                    raise ValueError('Edge must have a source and target: {}'.format(annotation))
                route['source'] = p[1][0]
                route['target'] = p[1][-1]
                route['via'] = p[1][1:-1]
            elif p[0] in ['source', 'via', 'target']:
                if feature_class is None:
                    feature_class = FLATMAP_NS['Edge']
                elif feature_class != FLATMAP_NS['Edge']:
                    raise ValueError('Only edges can be routed: {}'.format(annotation))
                if p[0] == 'source':
                    route['source'] = p[1][1:]
                elif p[0] == 'target':
                    route['target'] = p[1][1:]
                else:
                    route['via'].append(p[1][1:])
        if feature_class is None:
            feature_class = FLATMAP_NS['Node']  # Assume we have a Node
        elif feature_class == FLATMAP_NS['Edge']:
            if route['source']:
                graph.add( (feature_uri, FLATMAP_NS['source'],
                            rdflib.URIRef('{}/{}'.format(map_source, route['source']))) )
            if route['target']:
                graph.add( (feature_uri, FLATMAP_NS['target'],
                            rdflib.URIRef('{}/{}'.format(map_source, route['target']))) )
            for via in route['via']:
                graph.add( (feature_uri, FLATMAP_NS['via'],
                            rdflib.URIRef('{}/{}'.format(map_source, via))) )

        graph.add( (feature_uri, FLATMAP_NS['map'], map_uri) )
        graph.add( (feature_uri, rdflib.namespace.RDF['type'], feature_class) )

    with open(os.path.join(map_dir, 'annotations.ttl'), 'w') as turtle:
        # Don't set `base=map_uri` until RDFLib 5.0 and then use `explicit_base=True`
        # See https://github.com/RDFLib/rdflib/issues/559
        turtle.write(graph.serialize(format='turtle').decode('utf-8'))

    graph.close()

#===============================================================================
