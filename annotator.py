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

from src.drawml import GeometryExtractor, AnnotationWriter
from src.mbtiles import MBTiles
from src.rdf import update_RDF

#===============================================================================

if __name__ == '__main__':
    import argparse
    import os, sys

    parser = argparse.ArgumentParser(description='Convert Powerpoint slides to a flatmap.')

    parser.add_argument('--debug-xml', action='store_true',
                        help="save a slide's DrawML for debugging")
    parser.add_argument('--load-json', action='store_true',
                        help='load annotations from JSON')
    parser.add_argument('--powerpoint', metavar='POWERPOINT',
                        help='File or URL of Powerpoint slides')
    parser.add_argument('--save-json', action='store_true',
                        help='also save annotations as JSON')
    parser.add_argument('--update-powerpoint', metavar='OUTPUT',
                        help='update annotation data in POWERPOINT and save as OUTPUT')
    parser.add_argument('--version', action='version', version='0.4.0')

    parser.add_argument('map_base', metavar='MAPS_DIR',
                        help='base directory for generated flatmaps')
    parser.add_argument('map_id', metavar='MAP_ID',
                        help='a unique identifier for the map')
    # Need to be able to process a remote (PMR) source...

    args = parser.parse_args()

    if args.load_json and args.save_json:
        sys.exit('Cannot load and save JSON at the same time')

    if args.update_powerpoint:
        if not args.powerpoint:
            sys.exit('use --powerpoint option to specify slides to update')
        elif args.powerpoint.startswith('http:') or args.powerpoint.startswith('https:'):
            sys.exit('can only update local Powerpoint files')

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
            map_source = pptx_source
        else:
            if not os.path.exists(args.powerpoint):
                sys.exit('Missing Powerpoint file')
            pptx_source = os.path.abspath(args.powerpoint)
            pptx_bytes = open(pptx_source, 'rb')
            map_source = 'file:/{}'.format(pptx_source)

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

        # We are finished with the Powerpoint

        pptx_bytes.close()

    elif args.load_json:
        map_source = tile_db.metadata('source')
        with open(os.path.join(map_dir, 'annotations.json'), 'r') as input:
            annotations = json.load(input)
        tile_db.update_metadata(annotations=json.dumps(annotations))

    else:
        map_source = tile_db.metadata('source')
        annotations = json.loads(tile_db.metadata('annotations'))

    tile_db.close();

    # Save annotations as JSON

    if args.save_json:
        with open(os.path.join(map_dir, 'annotations.json'), 'w') as output:
            json.dump(annotations, output)

    if args.update_powerpoint:
        annotation_writer = AnnotationWriter(pptx_source)
        for id, metadata in annotations.items():
            annotation_writer.update_annotation(id, metadata['annotation'])
        annotation_writer.remove_unseen();
        annotation_writer.save(args.update_powerpoint)

    update_RDF(args.map_base, args.map_id, map_source, annotations)

#===============================================================================
