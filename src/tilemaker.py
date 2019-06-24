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

import os
import shutil
import subprocess
import tempfile

#===============================================================================

'''
import landez
import mercantile

TILE_SIZE = 512
MAX_ZOOM = 10

class TileMaker(object):
    def __init__(self, image, bounds, resolution):
        self._image = image
        self._image_size = (400, 400) ## pixels
        self._bounds = bounds
        # Switch to metres
        sw = mercantile.xy(*bounds[:2])
        ne = mercantile.xy(*bounds[2:])
        self._top_left = (sw[0], ne[1])
        self._bottom_right = (ne[0], sw[1])
        self._width = ne[0] - sw[0]
        self._height = ne[1] - sw[1]

    def make_tiles(self):
        pass

    def make_tiles_at_zoom(self, zoom):
        for tile in mercantile.tiles(*self._bounds, zoom):
            bds = mercantile.xy_bounds(tile)
            if (bds.left < self._top_left[0] or bds.right >= self._bottom_right[0]
             or bds.top < self._top_left[1] or bds.bottom >= self._bottom_right[1]):
                # part image
                pass
            else:
                # tile bds chunk out of image as tile z, x, y

                self._image_size[0]*(bds.left - self._top_left[0])/self._width

                  (bds.right - self._top_left[0])/self._width
'''

#===============================================================================

def make_image(pdf_file, image_file):
#====================================
    print('Generating {}...'.format(image_file))
    subprocess.run(['convert',
        '-density', '72',
        '-transparent', 'white',
        pdf_file, image_file])


def make_background_images(layer_ids, map_dir, pdf_file):
#========================================================
    map_image_dir = os.path.join(map_dir, 'images')
    if not os.path.exists(map_image_dir):
        os.makedirs(map_image_dir)

    work_dir = tempfile.mkdtemp()

    subprocess.run(['qpdf', '--split-pages', pdf_file, os.path.join(work_dir, 'slide%d.pdf')])

    make_image(os.path.join(work_dir, 'slide01.pdf'),
               os.path.join(map_image_dir, 'background.png'))
    for n, layer_id in enumerate(layer_ids):
        make_image(os.path.join(work_dir, 'slide{:02d}.pdf'.format(n+2)),
                   os.path.join(map_image_dir, '{}.png'.format(layer_id)))

    shutil.rmtree(work_dir)

#===============================================================================
