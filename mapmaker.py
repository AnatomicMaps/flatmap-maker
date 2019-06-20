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
import subprocess
import tempfile

#===============================================================================

from src.drawml import GeoJsonExtractor
from src.mbtiles import TileDatabase
from src.styling import Style

#===============================================================================

if __name__ == '__main__':
    import argparse
    import os, sys

    parser = argparse.ArgumentParser(description='Convert Powerpoint slides to a flatmap.')
    parser.add_argument('--debug-xml', action='store_true',
                        help="save a slide's DrawML for debugging")
    parser.add_argument('--slide', type=int, metavar='N',
                        help='only process this slide number (1-origin)')
    parser.add_argument('--version', action='version', version='0.2.1')


    base_url = 'http://localhost:8000'
    maps_dir = '/Users/dave/build/mapmaker/mvt'
    background_image = 'background.jpeg'

    parser.add_argument('map_id', metavar='MAP_ID',
                        help='a unique identifier for the map')
    parser.add_argument('powerpoint', metavar='POWERPOINT_FILE',
                        help='the name of a Powerpoint file')

    ## --background
    ##
    ## specify range of slides...
    # --force option

    args = parser.parse_args()

    map_dir = os.path.join(maps_dir, args.map_id)
    mbtiles_file = os.path.join(map_dir, 'index.mbtiles')


    if not os.path.exists(map_dir):
        os.makedirs(map_dir)

    print('Extracting layers...')
    filenames = []
    map_extractor = GeoJsonExtractor(args.powerpoint, args)

    # Process slides, saving layer information

    layers = {}
    tippe_inputs = []
    for slide_number in range(2, len(map_extractor)+1):  # First slide is background layer, so skip
        (fh, filename) = tempfile.mkstemp(suffix='.json')
        os.close(fh)
        filenames.append(filename)
        layer = map_extractor.slide_to_layer(slide_number, False)
        layer.save(filename)
        tippe_inputs.append({
            'file': filename,
            'layer': layer.layer_id,
            'description': layer.description
        })
        layers[layer.layer_id] = layer.annotations

    print(layers)

    if len(layers) == 0:
        sys.exit('No map layers in Powerpoint...')

    # Generate Mapbox vector tiles

    print('Running tippecanoe...')
    subprocess.run(['tippecanoe', '--projection=EPSG:4326', '--force',
                    # No compression results in a smaller `mbtiles` file
                    # and is also required to serve tile directories
                    '--no-tile-compression',
                    '--output={}'.format(mbtiles_file),
                    ]
                    + list(["-L{}".format(json.dumps(input)) for input in tippe_inputs])
                   )

    # Set our map's actual bounds and centre (`tippecanoe` uses bounding box
    # containing all features, which is not full map area)

    bounds = map_extractor.bounds()
    map_centre = [(bounds[0]+bounds[2])/2, (bounds[1]+bounds[3])/2]
    map_bounds = [bounds[0], bounds[3], bounds[2], bounds[1]]   # southwest and northeast ccorners

    tile_db = TileDatabase(mbtiles_file)
    tile_db.execute("UPDATE metadata SET value='{}' WHERE name = 'center'"
                    .format(','.join([str(x) for x in map_centre])))
    tile_db.execute("UPDATE metadata SET value='{}' WHERE name = 'bounds'"
                    .format(','.join([str(x) for x in map_bounds])))
    tile_db.execute("COMMIT")

    # Create style file

    print('Creating style file...')

## args.base_url
## args.background
    style_dict = Style.style('{}/{}'.format(base_url, args.map_id),
                             tile_db.metadata(),
                             background_image)   ## args.background


    with open(os.path.join(map_dir, 'index.json'), 'w') as output_file:
        json.dump(style_dict, output_file)

    # Tidy up

    print('Cleaning up...')
    for filename in filenames:
        os.remove(filename)

#===============================================================================
