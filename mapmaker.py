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
import multiprocessing
import multiprocessing.connection
import subprocess
import tempfile

#===============================================================================

from src.drawml import GeoJsonExtractor
from src.styling import Style

#===============================================================================

def process_slide(extractor, slide_number, output_file, result_queue):
    slide = extractor.slide_to_geometry(slide_number, False)
    slide.save(output_file)
    result_queue.put((output_file, slide.layer_id, slide.description))

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

    if not os.path.exists(map_dir):
        os.makedirs(map_dir)

    print('Extracting layers...')
    filenames = []
    processes = []
    map_extractor = GeoJsonExtractor(args.powerpoint, args)
    result_queue = multiprocessing.Queue()
    for s in range(2, len(map_extractor)+1):  # First slide is background layer
        (fh, filename) = tempfile.mkstemp(suffix='.json')
        os.close(fh)
        filenames.append(filename)

        # We extract slides in parallel...

        process = multiprocessing.Process(target=process_slide, args=(map_extractor, s, filename, result_queue))
        processes.append(process)
        process.start()

    # Get layer details from each process

    num_processes = len(processes)
    if num_processes == 0:
        sys.exit('No map layers in Powerpoint...')

    tippe_inputs = []
    while num_processes:
        (filename, layer_id, description) = result_queue.get()
        print('Processed layer {}: {}'.format(layer_id, description))
        tippe_inputs.append({
            'file': filename,
            'layer': layer_id,
            'description': description
            })
        num_processes -= 1

    # Wait for all processes to complete

    for process in processes:
        process.join()

    # Generate Mapbox vector tiles

    print('Running tippecanoe...')
    tile_dir = os.path.join(map_dir, 'mvtiles')
    if not os.path.exists(tile_dir):
        os.makedirs(tile_dir)

    subprocess.run(['tippecanoe',
                    '--projection=EPSG:4326',
                    '--no-tile-compression',
                    '--force',  ## Set layer names...
                    '--output-to-directory={}'.format(tile_dir)]
                    + list(["-L{}".format(json.dumps(input)) for input in tippe_inputs])
                   )

    # Create style file

    print('Creating style file...')

    metadata_file = os.path.join(tile_dir, 'metadata.json')

## args.base_url
## args.background
    style_dict = Style.style('{}/{}'.format(base_url, args.map_id),
                             metadata_file,
                             map_extractor.bounds(),
                             background_image)

    with open(os.path.join(map_dir, 'style.json'), 'w') as output_file:
        json.dump(style_dict, output_file)

    # Tidy up

    print('Cleaning up...')
    for filename in filenames:
        os.remove(filename)

#===============================================================================
