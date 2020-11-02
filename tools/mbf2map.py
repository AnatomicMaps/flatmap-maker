#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020  David Brooks
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

from mapmaker.flatmap import Flatmap
from mapmaker.mbfbioscience import MBFLayer

#===============================================================================

if __name__ == '__main__':
    import argparse
    import os, sys

    parser = argparse.ArgumentParser(description='Convert a segmented MBF image to a flatmap.')

    parser.add_argument('-z', '--initial-zoom', metavar='N', type=int, default=4,
                        help='initial zoom level (defaults to 4)')
    parser.add_argument('--max-zoom', dest='max_zoom', metavar='N', type=int, default=10,
                        help='maximum zoom level (defaults to 10)')
    parser.add_argument('--min-zoom', dest='min_zoom', metavar='N', type=int, default=2,
                        help='minimum zoom level (defaults to 2)')
    parser.add_argument('-u', '--upload', metavar='USER@SERVER',
                        help='Upload generated map to server')

    required = parser.add_argument_group('required arguments')
    required.add_argument('--map-dir', dest='map_base', metavar='MAP_DIR', required=True,
                        help='base directory for generated flatmaps')
    required.add_argument('--id', dest='map_id', metavar='MAP_ID', required=True,
                        help='a unique identifier for the map')
    required.add_argument('--mbf', dest='mbf_file', metavar='MBF_XML', required=True,
                        help='File or URL of MBF XML file of segmented image')

    args = parser.parse_args()

    if args.min_zoom < 0 or args.min_zoom > args.max_zoom:
        sys.exit('--min-zoom must be between 0 and {}'.format(args.max_zoom))
    if args.max_zoom < args.min_zoom or args.max_zoom > 15:
        sys.exit('--max-zoom must be between {} and 15'.format(args.min_zoom))
    if args.initial_zoom < args.min_zoom or args.initial_zoom > args.max_zoom:
        sys.exit('--initial-zoom must be between {} and {}'.format(args.min_zoom, args.max_zoom))

    map_zoom = (args.min_zoom, args.max_zoom, args.initial_zoom)

    map_dir = os.path.join(args.map_base, args.map_id)
    if not os.path.exists(map_dir):
        os.makedirs(map_dir)

    if not os.path.exists(args.mbf_file):
        sys.exit('Missing MBF XML file')

    mbf_layer = MBFLayer(os.path.abspath(args.mbf_file), 'vagus')
    flatmap = Flatmap(args.map_id, args.mbf_file, ' '.join(sys.argv),
                      map_dir, map_zoom, mbf_layer)
    flatmap.add_layer(mbf_layer)
    flatmap.output_layers()

    print('Running tippecanoe...')
    flatmap.make_vector_tiles()

    print('Creating index and style files...')
    flatmap.save_map_json(True)

    """
    Only if no os.path.isfile(os.path.join(map_dir, '{}.mbtiles'.format(args.map_id)))) ??
    force with --background-tiles option ??

    """
    print('Generating background tiles (may take a while...)')
    image_tile_files = make_background_tiles_from_image(flatmap.bounds, map_zoom, map_dir,
                                                        mbf_layer.image, args.mbf_file, args.map_id)
    flatmap.add_upload_files(image_tile_files)

    if args.upload:
        print('Uploaded map...', flatmap.upload(args.map_base, args.upload))

    # Tidy up
    print('Cleaning up...')
    flatmap.finalise(True)

#===============================================================================

