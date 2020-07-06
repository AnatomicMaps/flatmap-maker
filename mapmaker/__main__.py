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





#===============================================================================

__version__ = '0.9.0-devel'

#===============================================================================

import io

import requests

#===============================================================================

from drawml import GeoJsonExtractor
from flatmap import Flatmap
from tilemaker import make_background_tiles_from_pdf

#===============================================================================

def main():
    import argparse
    import os, sys

    parser = argparse.ArgumentParser(description='Convert Powerpoint slides to a flatmap.')

    parser.add_argument('-b', '--background-tiles', action='store_true',
                        help="generate image tiles of map's layers (may take a while...)")
    parser.add_argument('--anatomical-map',
                        help='Excel spreadsheet file for mapping shape classes to anatomical entities')
    parser.add_argument('--properties',
                        help='JSON file specifying additional properties of shapes')

    parser.add_argument('-c', '--check-errors', action='store_true',
                        help="check for errors without generating a map")
    parser.add_argument('-t', '--tile', dest='tile_slide', metavar='N', type=int, default=0,
                        help='only generate image tiles for this slide (1-origin); implies --background-tiles and --no-vector-tiles')

    parser.add_argument('-z', '--initial-zoom', metavar='N', type=int, default=4,
                        help='initial zoom level (defaults to 4)')
    parser.add_argument('--max', dest='max_zoom', metavar='N', type=int, default=10,
                        help='maximum zoom level (defaults to 10)')
    parser.add_argument('--min', dest='min_zoom', metavar='N', type=int, default=2,
                        help='minimum zoom level (defaults to 2)')


    parser.add_argument('-d', '--debug', dest='debug_xml', action='store_true',
                        help="save a slide's DrawML for debugging")
    parser.add_argument('-s', '--save-geojson', action='store_true',
                        help='Save GeoJSON files for each layer')
    parser.add_argument('-u', '--upload', metavar='USER@SERVER',
                        help='Upload generated map to server')

    parser.add_argument('-v', '--version', action='version', version=__version__)

    required = parser.add_argument_group('required arguments')

    required.add_argument('--map-dir', dest='map_base', metavar='MAP_DIR', required=True,
                        help='base directory for generated flatmaps')
    required.add_argument('--id', dest='map_id', metavar='MAP_ID', required=True,
                        help='a unique identifier for the map')
    required.add_argument('--slides', dest='powerpoint', metavar='POWERPOINT', required=True,
                        help='File or URL of Powerpoint slides')

    # --force option

    args = parser.parse_args()

    print('Mapmaker {}'.format(__version__))

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

    if not os.path.exists(map_dir):
        os.makedirs(map_dir)

    map_extractor = GeoJsonExtractor(pptx_bytes, args)
    flatmap = Flatmap(args.map_id, map_source, ' '.join(sys.argv),
                      map_dir, map_zoom, map_extractor.latlng_bounds())

#*    # Labels and relationships between anatomical entities

#*    args.ontology_data = OntologyData()
#*    args.layer_mapping = LayerMapping('./layers.json', 'features')

    # Process slides, saving layer information
    print('Extracting layers...')
    for slide_number in range(1, len(map_extractor)+1):
        if args.tile_slide > 0 and args.tile_slide != slide_number:
            continue
        layer = map_extractor.slide_to_layer(slide_number,
                                             debug_xml=args.debug_xml)
        for error in layer.errors:
            print(error)
        flatmap.add_layer(layer)

    # We are finished with the Powerpoint
    pptx_bytes.close()

    if len(flatmap) == 0:
        sys.exit('No map layers in Powerpoint...')

    if args.check_errors:
        # Show what the map is about
        if flatmap.models:
            print('Checked map for {}'.format(flatmap.models))

    else:
        print('Running tippecanoe...')
        flatmap.make_vector_tiles()

        if args.tile_slide == 0:
            print('Creating index and style files...')
            flatmap.save_map_json(args.background_tiles
                               or os.path.isfile(os.path.join(map_dir, '{}.mbtiles'.format(flatmap.layer_ids[0]))))

        if args.background_tiles:
            print('Generating background tiles (may take a while...)')
            image_tile_files = make_background_tiles_from_pdf(flatmap.bounds, map_zoom, map_dir,
                                                              pdf_bytes, pdf_source,
                                                              flatmap.layer_ids, args.tile_slide)
            flatmap.add_upload_files(image_tile_files)

        # Show what the map is about
        if flatmap.models:
            print('Generated map for {}'.format(flatmap.models))

        if args.upload:
            flatmap.upload(args.upload)
            print('Uploaded map...', cmd_stream.read())

    # Tidy up
    print('Cleaning up...')
    flatmap.finalise(args.save_geojson)

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================
