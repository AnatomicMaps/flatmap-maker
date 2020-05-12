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


MAPMAKER_VERSION = '0.7.0b1'

#===============================================================================

FLATMAP_VERSION  = 1.1

#===============================================================================

import datetime
import io
import json
import subprocess
import tempfile

#===============================================================================

import requests

#===============================================================================

from drawml import GeoJsonExtractor
##from layermapping import LayerMapping
from mbtiles import MBTiles
##from ontologies import OntologyData
##from rdf import update_RDF
from styling import Style
from tilemaker import make_background_tiles
from tilejson import tile_json

#===============================================================================

def main():
    import argparse
    import os, sys

    parser = argparse.ArgumentParser(description='Convert Powerpoint slides to a flatmap.')

    parser.add_argument('-b', '--background-tiles', action='store_true',
                        help="generate image tiles of map's layers (may take a while...)")
    parser.add_argument('--anatomical-map',
                        help='Excel spreadsheet file for mapping shape classes to anatomical entities')

    parser.add_argument('-n', '--no-vector-tiles', action='store_true',
                        help="don't generate vector tiles database and style files")
    parser.add_argument('-t', '--tile', dest='tile_slide', metavar='N', type=int, default=0,
                        help='only generate image tiles for this slide (1-origin); implies --background-tiles and --no-vector-tiles')

    parser.add_argument('-z', '--initial-zoom', metavar='N', type=int, default=4,
                        help='initial zoom level (defaults to 4)')
    parser.add_argument('--max', dest='max_zoom', metavar='N', type=int, default=10,
                        help='maximum zoom level (defaults to 10)')
    parser.add_argument('--min', dest='min_zoom', metavar='N', type=int, default=2,
                        help='minimum zoom level (defaults to 2)')

    parser.add_argument('-x', '--line-extension', metavar='LINE_EXTENSION', type=int, default=200,
                        help='amount to extend ends of region dividing lines in PPT EMUs (defaults to 200)')

    parser.add_argument('-d', '--debug', dest='debug_xml', action='store_true',
                        help="save a slide's DrawML for debugging")
    parser.add_argument('-s', '--save-geojson', action='store_true',
                        help='Save GeoJSON files for each layer')
    parser.add_argument('-u', '--upload', metavar='USER@SERVER',
                        help='Upload generated map to server')

    parser.add_argument('-v', '--version', action='version', version='0.3.1')

    required = parser.add_argument_group('required arguments')

    required.add_argument('--map-dir', dest='map_base', metavar='MAP_DIR', required=True,
                        help='base directory for generated flatmaps')
    required.add_argument('--id', dest='map_id', metavar='MAP_ID', required=True,
                        help='a unique identifier for the map')
    required.add_argument('--slides', dest='powerpoint', metavar='POWERPOINT', required=True,
                        help='File or URL of Powerpoint slides')

    # --force option

    args = parser.parse_args()

    print('Mapmaker {}'.format(MAPMAKER_VERSION))

    if args.min_zoom < 0 or args.min_zoom > args.max_zoom:
        sys.exit('--min-zoom must be between 0 and {}'.format(args.max_zoom))
    if args.max_zoom < args.min_zoom or args.max_zoom > 15:
        sys.exit('--max-zoom must be between {} and 15'.format(args.min_zoom))
    if args.initial_zoom < args.min_zoom or args.initial_zoom > args.max_zoom:
        sys.exit('--initial-zoom must be between {} and {}'.format(args.min_zoom, args.max_zoom))

    map_zoom = (args.min_zoom, args.max_zoom, args.initial_zoom)

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
        map_source = pptx_source
    else:
        if not os.path.exists(args.powerpoint):
            sys.exit('Missing Powerpoint file')
        pptx_source = os.path.abspath(args.powerpoint)
        pptx_modified = os.path.getmtime(pptx_source)
        pptx_bytes = open(pptx_source, 'rb')
        map_source = 'file:/{}'.format(pptx_source)

    if args.background_tiles:
        pdf_source = '{}.pdf'.format(os.path.splitext(pptx_source)[0])
        if pdf_source.startswith('http:') or pdf_source.startswith('https:'):
            response = requests.get(pdf_source)
            if response.status_code != requests.codes.ok:
                pptx_bytes.close()
                sys.exit('Cannot retrieve PDF of Powerpoint (needed to generate background tiles)')
            pdf_bytes = io.BytesIO(response.content)
        else:
            if not os.path.exists(pdf_source):
                pptx_bytes.close()
                sys.exit('Missing PDF of Powerpoint (needed to generate background tiles)')
            if os.path.getmtime(pdf_source) < pptx_modified:
                pptx_bytes.close()
                sys.exit('PDF of Powerpoint is too old...')
            with open(pdf_source, 'rb') as f:
                pdf_bytes = f.read()

    map_dir = os.path.join(args.map_base, args.map_id)
    args.output_dir = map_dir

    args.label_database = os.path.join(args.map_base, 'labels.sqlite')

    map_models = ''

    if not os.path.exists(map_dir):
        os.makedirs(map_dir)

#*    # Labels and relationships between anatomical entities

#*    args.ontology_data = OntologyData()
#*    args.layer_mapping = LayerMapping('./layers.json', 'features')

    filenames = []
    upload_files = ['index.mbtiles']

    print('Extracting layers...')
    map_extractor = GeoJsonExtractor(pptx_bytes, args)

    # Process slides, saving layer information

    annotations = {}
    map_layers = []
    tippe_inputs = []
    for slide_number in range(1, len(map_extractor)+1):
        if args.tile_slide > 0 and args.tile_slide != slide_number:
            continue

        layer = map_extractor.slide_to_layer(slide_number,
                                                save_output=False,
                                                debug_xml=args.debug_xml)
        for error in layer.errors:
            print(error)

        if layer.zoom is not None:
            map_zoom = layer.zoom

        map_layer = {
            'id': layer.layer_id,
            'slide-id': layer.slide_id,
            'description': layer.description,
            'selectable': layer.selectable,
            'selected': layer.selected,
            'queryable-nodes': layer.queryable_nodes,
            'features': layer.map_features
        }
        if layer.background_for:
            map_layer['background_for'] = layer.background_for
        map_layers.append(map_layer)

        if layer.models:
            map_models = layer.models

        if layer.selectable:
            annotations.update(layer.annotations)
            filename = os.path.join(map_dir, '{}.json'.format(layer.layer_id))
            filenames.append(filename)
            layer.save(filename)
            tippe_inputs.append({
                'file': filename,
                'layer': 'features',   ## Have `feature-layer(NAME)` as slide annotation??
                'description': layer.description
            })

    # We are finished with the Powerpoint

    pptx_bytes.close()

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
        if len(tippe_inputs) == 0:
            sys.exit('No selectable layers in Powerpoint...')

        # Generate Mapbox vector tiles
        print('Running tippecanoe...')

        subprocess.run(['tippecanoe', '--projection=EPSG:4326', '--force',
                        # No compression results in a smaller `mbtiles` file
                        # and is also required to serve tile directories
                        '--no-tile-compression',
                        '--buffer=100',
                        '--minimum-zoom={}'.format(map_zoom[0]),
                        '--maximum-zoom={}'.format(map_zoom[1]),
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
        tile_db.add_metadata(source=map_source)    ## We don't always want this updated...
                                                   ## e.g. if re-running after tile generation
        # What the map models
        if map_models:
            tile_db.add_metadata(describes=map_models)

        # Save layer details in metadata
        tile_db.add_metadata(layers=json.dumps(map_layers))

        # Save annotations in metadata
        tile_db.add_metadata(annotations=json.dumps(annotations))

        # Save command used to run mapmaker
        tile_db.add_metadata(created_by=' '.join(sys.argv))

        # Save the maps creation time
        tile_db.add_metadata(created=datetime.datetime.utcnow().isoformat())

        # Commit updates to the database
        tile_db.execute("COMMIT")


#*        ## TODO: set ``layer.properties`` for annotations...
#*        ##update_RDF(args.map_base, args.map_id, map_source, annotations)

    if not args.no_vector_tiles:
        print('Creating style files...')

        map_index = {
            'id': args.map_id,
            'min-zoom': map_zoom[0],
            'max-zoom': map_zoom[1],
            'bounds': map_bounds,
            'version': FLATMAP_VERSION,
        }

        if map_models:
            map_index['describes'] = map_models

        # Create `index.json` for building a map in the viewer

        with open(os.path.join(map_dir, 'index.json'), 'w') as output_file:
            json.dump(map_index, output_file)

        # Create style file

        metadata = tile_db.metadata()

        style_dict = Style.style(layer_ids, metadata, map_zoom)
        with open(os.path.join(map_dir, 'style.json'), 'w') as output_file:
            json.dump(style_dict, output_file)

        # Create TileJSON file

        json_source = tile_json(args.map_id, map_zoom, map_bounds)
        with open(os.path.join(map_dir, 'tilejson.json'), 'w') as output_file:
            json.dump(json_source, output_file)

    upload_files.extend(['index.json', 'style.json', 'tilejson.json'])

    if args.tile_slide == 0:
        # We are finished with the tile database, so close it
        tile_db.close();

    if args.background_tiles:
        print('Generating background tiles (may take a while...)')
        upload_files.extend(make_background_tiles(map_bounds, map_zoom, map_dir,
                              pdf_source, pdf_bytes, layer_ids, args.tile_slide))

    # Show what the map is about
    if map_models:
        print('Generated map for {}'.format(map_models))

    if args.upload:
        upload = ' '.join([ '{}/{}'.format(args.map_id, f) for f in upload_files ])
        cmd_stream = os.popen('tar -C {} -c -z {} | ssh {} "tar -C /flatmaps -x -z"'
                             .format(args.map_base, upload, args.upload))
        print('Uploaded map...', cmd_stream.read())

    # Tidy up
    print('Cleaning up...')

    for filename in filenames:
        if args.save_geojson:
            print(filename)
        else:
            os.remove(filename)

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================
