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

import io
import json
import subprocess
import tempfile
import datetime

#===============================================================================

import requests

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
    parser.add_argument('--max-zoom', metavar='N', type=int, default=7,
                        help='maximum zoom level (defaults to 7)')
    parser.add_argument('--no-vector-tiles', action='store_true',
                        help="don't generate vector tiles database and style files")
    parser.add_argument('--tile-slide', metavar='N', type=int, default=0,
                        help='only generate image tiles for this slide (1-origin); implies --background-tiles and --no-vector-tiles')

    parser.add_argument('--debug-xml', action='store_true',
                        help="save a slide's DrawML for debugging")
    parser.add_argument('--version', action='version', version='0.3.1')

    parser.add_argument('map_base', metavar='MAPS_DIR',
                        help='base directory for generated flatmaps')

    parser.add_argument('map_id', metavar='MAP_ID',
                        help='a unique identifier for the map')
    parser.add_argument('powerpoint', metavar='POWERPOINT',
                        help='File or URL of Powerpoint slides')

    # --force option

    args = parser.parse_args()

    if args.max_zoom < 1 or args.max_zoom > 15:
        sys.exit('--max-zoom must be between 1 and 15')

    if args.tile_slide > 0:
        args.background_tiles = True
        args.no_vector_tiles = True

    if args.powerpoint.startswith('http:') or args.powerpoint.startswith('https:'):
        response = requests.get(args.powerpoint)
        if response.status_code != requests.codes.ok:
            sys.exit('Cannot retrieve remote Powerpoint file')
        pptx_source = args.powerpoint
        pptx_modified = 0   ## Can we get timestamp from PMR metadata?? Or even i
        pptx_bytes = io.BytesIO(response.content)
    else:
        if not os.path.exists(args.powerpoint):
            sys.exit('Missing Powerpoint file')
        pptx_source = os.path.abspath(args.powerpoint)
        pptx_modified = os.path.getmtime(pptx_source)
        pptx_bytes = open(pptx_source, 'rb')

    if args.background_tiles:
        pdf_source = '{}.pdf'.format(os.path.splitext(pptx_source)[0])
        if pdf_source.startswith('http:') or pdf_source.startswith('https:'):
            response = requests.get(pdf_source)
            if response.status_code != requests.codes.ok:
                sys.exit('Cannot retrieve PDF of Powerpoint (needed to generate background tiles)')
            pdf_bytes = io.BytesIO(response.content)
        else:
            if not os.path.exists(pdf_source):
                sys.exit('Missing PDF of Powerpoint (needed to generate background tiles)')
            if os.path.getmtime(pdf_source) < pptx_modified:
                sys.exit('PDF of Powerpoint is too old...')
            with open(pdf_source, 'rb') as f:
                pdf_bytes = f.read()

    map_dir = os.path.join(args.map_base, args.map_id)

    map_describes = ''

    if not os.path.exists(map_dir):
        os.makedirs(map_dir)

    print('Extracting layers...')
    filenames = []
    map_extractor = GeoJsonExtractor(pptx_bytes, args)

    # Process slides, saving layer information

    annotations = {}
    map_layers = []
    tippe_inputs = []
    for slide_number in range(1, len(map_extractor)+1):
        if args.tile_slide > 0 and args.tile_slide != slide_number:
            continue

        layer = map_extractor.slide_to_layer(slide_number, False)
        for error in layer.errors:
            print(error)

        map_layer = {
            'id': layer.layer_id,
            'description': layer.description,
            'selectable': layer.selectable,
            'selected': layer.selected
        }
        if layer.background_for:
            map_layer['background_for'] = layer.background_for
        map_layers.append(map_layer)

        if layer.describes:
            map_describes = layer.describes

        if layer.selectable:
            annotations.update(layer.annotations)
            (fh, filename) = tempfile.mkstemp(suffix='.json')
            os.close(fh)
            filenames.append(filename)
            layer.save(filename)
            tippe_inputs.append({
                'file': filename,
                'layer': layer.layer_id,
                'description': layer.description
            })

    if len(map_layers) == 0:
        sys.exit('No map layers in Powerpoint...')

    layer_ids = [layer['id'] for layer in map_layers]

    # Get our map's actual bounds and centre

    bounds = map_extractor.bounds()
    map_centre = [(bounds[0]+bounds[2])/2, (bounds[1]+bounds[3])/2]
    map_bounds = [bounds[0], bounds[3], bounds[2], bounds[1]]   # southwest and northeast ccorners

    # The vector tiles' database

    mbtiles_file = os.path.join(map_dir, 'index.mbtiles')


    if args.no_vector_tiles:
        if args.tile_slide == 0:
            tile_db = MBTiles(mbtiles_file)

    else:
        # Generate Mapbox vector tiles
        print('Running tippecanoe...')

        subprocess.run(['tippecanoe', '--projection=EPSG:4326', '--force',
                        # No compression results in a smaller `mbtiles` file
                        # and is also required to serve tile directories
                        '--no-tile-compression',
                        '--buffer=100',
                        '--maximum-zoom={}'.format(args.max_zoom),
                        '--output={}'.format(mbtiles_file),
                        ]
                        + list(["-L{}".format(json.dumps(input)) for input in tippe_inputs])
                       )

        # `tippecanoe` uses the bounding box containing all features as the
        # map bounds, which is not the same as the extracted bounds, so update
        # the map's metadata

        tile_db = MBTiles(mbtiles_file)

        tile_db.update_metadata(center=','.join([str(x) for x in map_centre]),
                                bounds=','.join([str(x) for x in map_bounds]))

        tile_db.execute("COMMIT")

    if args.tile_slide == 0:
        # Save path of the Powerpoint source
        tile_db.add_metadata(source=pptx_source)   ## We don't always want this updated...
                                                   ## e.g. if rerunning after tile generation
        # What the map describes
        if map_describes:
            tile_db.add_metadata(describes=map_describes)

        # Save annotations in metadata
        tile_db.add_metadata(annotations=json.dumps(annotations))

        # Save the maps creation time
        tile_db.add_metadata(creation=datetime.datetime.utcnow().isoformat())

        # Commit updates to the database
        tile_db.execute("COMMIT")

    if not args.no_vector_tiles:
        print('Creating style files...')

        map_index = {
            'id': args.map_id,
            'style': 'style.json',
            'layers': map_layers,
            'maxzoom': args.max_zoom
        }

        if map_describes:
            map_index['describes'] = map_describes

        # Create `index.json` for building a map in the viewer

        with open(os.path.join(map_dir, 'index.json'), 'w') as output_file:
            json.dump(map_index, output_file)

        # Create style file

        metadata = tile_db.metadata()

        style_dict = Style.style(args.map_id, layer_ids, metadata, args.max_zoom)
        with open(os.path.join(map_dir, 'style.json'), 'w') as output_file:
            json.dump(style_dict, output_file)

    if args.tile_slide == 0:
        # We are finished with the tile database, so close it
        tile_db.close();

    if args.background_tiles:
        print('Generating background tiles (may take a while...)')
        make_background_tiles(map_bounds, args.max_zoom, map_dir,
                              pdf_source, pdf_bytes, layer_ids, args.tile_slide)

    # Tidy up
    print('Cleaning up...')

    for filename in filenames:
        os.remove(filename)

#===============================================================================
