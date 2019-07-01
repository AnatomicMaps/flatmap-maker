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
from src.mbtiles import MBTiles
from src.styling import Style
from src.tilemaker import make_background_tiles

#===============================================================================

if __name__ == '__main__':
    import argparse
    import os, sys

    parser = argparse.ArgumentParser(description='Convert Powerpoint slides to a flatmap.')
    parser.add_argument('--background-tiles', action='store_true',
                        help="generate image tiles of map's layers")
    parser.add_argument('--debug-xml', action='store_true',
                        help="save a slide's DrawML for debugging")
    parser.add_argument('--version', action='version', version='0.3.1')

    parser.add_argument('map_base', metavar='MAPS_DIR',
                        help='base directory for generated flatmaps')

    parser.add_argument('map_id', metavar='MAP_ID',
                        help='a unique identifier for the map')
    parser.add_argument('powerpoint', metavar='POWERPOINT_FILE',
                        help='Powerpoint file of flatmap')

    # --force option

    args = parser.parse_args()

    # Determining maximum zoom level...

    max_zoom = 7   ## set from command line, default to 7 ??


    if not os.path.exists(args.powerpoint):
        sys.exit('Missing Powerpoint file')

    if args.background_tiles:
        pdf_file = '{}.pdf'.format(os.path.splitext(args.powerpoint)[0])
        if not os.path.exists(pdf_file):
            sys.exit('PDF of Powerpoint required to generate background tiles')

    map_dir = os.path.join(args.map_base, args.map_id)

    if not os.path.exists(map_dir):
        os.makedirs(map_dir)

    print('Extracting layers...')
    filenames = []
    map_extractor = GeoJsonExtractor(args.powerpoint, args)

    # Process slides, saving layer information

    annotations = {}
    layers = []
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
        layers.append({
            'id': layer.layer_id,
            'description': layer.description
            })
        annotations.update(layer.annotations)

    if len(layers) == 0:
        sys.exit('No map layers in Powerpoint...')



    # Generate Mapbox vector tiles

    print('Running tippecanoe...')

    mbtiles_file = os.path.join(map_dir, 'index.mbtiles')

    subprocess.run(['tippecanoe', '--projection=EPSG:4326', '--force',
                    # No compression results in a smaller `mbtiles` file
                    # and is also required to serve tile directories
                    '--no-tile-compression',
                    '--buffer=100',
                    '--maximum-zoom={}'.format(max_zoom),
                    '--output={}'.format(mbtiles_file),
                    ]
                    + list(["-L{}".format(json.dumps(input)) for input in tippe_inputs])
                   )

    # Set our map's actual bounds and centre (`tippecanoe` uses bounding box
    # containing all features, which is not full map area)

    bounds = map_extractor.bounds()
    map_centre = [(bounds[0]+bounds[2])/2, (bounds[1]+bounds[3])/2]
    map_bounds = [bounds[0], bounds[3], bounds[2], bounds[1]]   # southwest and northeast ccorners

    tile_db = MBTiles(mbtiles_file)

    tile_db.update_metadata(center=','.join([str(x) for x in map_centre]),
                            bounds=','.join([str(x) for x in map_bounds]))
    # Save path of the Powerpoint source
    tile_db.add_metadata(source=os.path.abspath(args.powerpoint))

    # Save annotations in metadata
    tile_db.add_metadata(annotations=json.dumps(annotations))

    # Commit updates to the database
    tile_db.execute("COMMIT")


    print('Creating style files...')

    # Create `index.json` for building a map in the viewer
    with open(os.path.join(map_dir, 'index.json'), 'w') as output_file:
        json.dump({
            'id': args.map_id,
            'style': 'style.json',
            'layers': layers,
            'maxzoom': max_zoom
        }, output_file)

    # Create style file

    layer_ids = [layer['id'] for layer in layers]
    metadata = tile_db.metadata()

    style_dict = Style.style(args.map_id, layer_ids, metadata, max_zoom)
    with open(os.path.join(map_dir, 'style.json'), 'w') as output_file:
        json.dump(style_dict, output_file)

    if args.background_tiles:
        print('Generating background tiles (may take a while...)')
        make_background_tiles(map_bounds, max_zoom, map_dir, pdf_file, layer_ids)

    # Tidy up

    print('Cleaning up...')
    for filename in filenames:
        os.remove(filename)

#===============================================================================
