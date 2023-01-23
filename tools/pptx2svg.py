#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019 - 2022 David Brooks
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

from mapmaker.settings import settings
from mapmaker.sources.powerpoint.pptx2svg import Pptx2Svg

#===============================================================================

__version__ = '2.0.0-a.1'

#===============================================================================


## Add --crop option (and --margins) ???

def main():
    import argparse
    from pathlib import Path
    import sys

    parser = argparse.ArgumentParser(description='Convert flatmap Powerpoint slides to SVG.')

    parser.add_argument('-v', '--version', action='version', version=__version__)
    parser.add_argument('-d', '--debug', action='store_true', help='output debugging information')

    #parser.add_argument('-q', '--quiet', action='store_true', help='do not show progress bar')
    #parser.add_argument('-x', '--export-shapes', action='store_true', help='export closed shapes as JSON')
    #parser.add_argument('--exclude-shapes', metavar='FILENAME', help='previously exported shapes to exclude from SVG')
    #
    # --celldl option?? Pass to Pptx2Svg

    parser.add_argument('manifest', metavar='MANIFEST',
                        help='a flatmap manifest specifying Powerpoint sources')

    args = parser.parse_args()
    settings['debug'] = args.debug

    manifest_path = Path(args.manifest)
    map_dir = manifest_path.parent
    with open(manifest_path, 'rb') as fp:
        manifest = json.loads(fp.read())

    slide_kinds = ['base', 'layer'] if manifest.get('kind') == 'functional' else ['slides']
    powerpoints = []
    for source in manifest['sources']:
        if source['kind'] in slide_kinds:
            powerpoints.append(str(map_dir / source['href']))
    if len(powerpoints) == 0:
        sys.exit('No Powerpoint files specified in manifest')

    for powerpoint in powerpoints:
        print(f'Processing {powerpoint}...')
        extractor = Pptx2Svg(powerpoint)
        extractor.slides_to_svg()
        print(f'{powerpoint} slides saved as:')
        for layer_id, svg_file in extractor.save_layers(map_dir).items():
            print(f'    {layer_id}: {svg_file}')

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================
