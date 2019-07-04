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

#===============================================================================

from src.drawml import GeometryExtractor

#===============================================================================

if __name__ == '__main__':
    import argparse
    import os, sys

    parser = argparse.ArgumentParser(description='Convert Powerpoint slides to a flatmap.')

    parser.add_argument('--debug-xml', action='store_true',
                        help="save a slide's DrawML for debugging")
    parser.add_argument('--version', action='version', version='0.3.2')

    parser.add_argument('map_base', metavar='MAPS_DIR',
                        help='base directory for generated flatmaps')

    parser.add_argument('map_id', metavar='MAP_ID',
                        help='a unique identifier for the map')
    parser.add_argument('powerpoint', metavar='POWERPOINT_FILE',
                        help='Powerpoint file of flatmap')

    # Need to be able to process a remote (PMR) source...

    args = parser.parse_args()

    if not os.path.exists(args.powerpoint):
        sys.exit('Missing Powerpoint file')

    map_dir = os.path.join(args.map_base, args.map_id)

    ## Don't run if dir exists and not --force
    ## rmdir if exists and --force
    ##

    if not os.path.exists(map_dir):
        os.makedirs(map_dir)

    print('Extracting layers...')
    map_extractor = GeometryExtractor(args.powerpoint, args)

    # Process slides, saving layer information

    annotations = {}
    layers = []
    for slide_number in range(len(map_extractor)+1):  # First slide is background layer, so skip ???
        layer = map_extractor.slide_to_layer(slide_number, False)
        layers.append({
            'id': layer.layer_id,
            'description': layer.description
            })
        annotations.update(layer.annotations)

    if len(layers) == 0:
        sys.exit('No map layers in Powerpoint...')

    # The vector tiles' database

    if False:
        mbtiles_file = os.path.join(map_dir, 'index.mbtiles')

        tile_db = MBTiles(mbtiles_file)

        # Update annotations in metadata
        tile_db.update_metadata(annotations=json.dumps(annotations))

        # Commit updates to the database
        tile_db.execute("COMMIT")

        # We are finished with the tile database, so close it
        tile_db.close();


    print(json.dumps(annotations))

#===============================================================================
