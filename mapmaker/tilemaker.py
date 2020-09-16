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
import math
import multiprocessing
import os
import shutil
import subprocess
import tempfile

#===============================================================================

import cv2
import fitz
import mercantile
import numpy as np

from tqdm import tqdm

#===============================================================================

from mbtiles import MBTiles, ExtractionError

#===============================================================================

MIN_ZOOM  =  2
MAX_ZOOM  = 10

TILE_SIZE = (512, 512)
WHITE     = (255, 255, 255)

#===============================================================================

# Based on https://stackoverflow.com/a/54148416/2159023

def make_transparent(img, colour=WHITE):
    transparent = img.copy()
    if colour == WHITE:
        transparent[:, :, 3] = (255*((transparent[:, :, :3] != 255).any(axis=2) * (transparent[:, :, 3] != 0))).astype(np.uint8)
    else:
        transparent[:, :, 3] = (255*((transparent[:,:,0:3] != tuple(colour)[0:3]).any(axis=2) * (transparent[:, :, 3] != 0))).astype(np.uint8)
    return transparent

#===============================================================================

def not_transparent(img):
    return np.any(img[:,:,3])

#===============================================================================

def transparent_image(size=(1, 1)):
    image = np.full(size + (4,), 255, dtype=np.uint8)
    image[:,:,3] = 0
    return image

#===============================================================================

def get_image_size(img):
    return tuple(reversed(img.shape[:2]))

def paste_image(destination, source, offset):
    destination[offset[1]:offset[1]+source.shape[0],
                offset[0]:offset[0]+source.shape[1]] = source
    return destination

#===============================================================================

class Affine(object):
    def __init__(self, scale, translateA, translateB):
        self._matrix = np.array([[ scale[0], 0, -scale[0]*translateA[0] + translateB[0] ],
                                 [ 0, scale[1], -scale[1]*translateA[1] + translateB[1] ],
                                 [ 0,        0,                                       1 ]])

    def __str__(self):
        return 'Affine: {}'.format(self._matrix)

    def transform(self, x, y):
    #=========================
        return (self._matrix@[x, y, 1])[:2]

#===============================================================================

class Rect(object):
    def __init__(self, *args):
        if not args:
            raise ValueError('Missing arguments for Rect constructor')
        if len(args) == 4:
            self.x0 = float(args[0])
            self.y0 = float(args[1])
            self.x1 = float(args[2])
            self.y1 = float(args[3])
        elif len(args) == 2:                  # 2 Points provided
            self.x0 = float(args[0][0])
            self.y0 = float(args[0][1])
            self.x1 = float(args[1][0])
            self.y1 = float(args[1][1])
        else:
            raise ValueError('Invalid arguments for Rect constructor')

    def __str__(self):
        return 'Rect: ({} x {})'.format(self.width, self.height)

    @property
    def height(self):
        return abs(self.y1 - self.y0)

    @property
    def width(self):
        return abs(self.x1 - self.x0)

#===============================================================================

def check_image_size(dimension, max_dim, lower, upper, bounds, scale):
    if dimension < max_dim:
        if lower < bounds[0]:
            if upper < bounds[1]:
                return max_dim - dimension
            else:
                return int(math.floor(0.5 - lower*scale))
    elif dimension != max_dim:
        raise AssertionError('Image size mismatch: {} != {}'.format(dimension, max_dim))
    return 0

#===============================================================================

class TileSource(object):
    def __init__(self, tile_pixel_rect, image_rect):
        self._image_rect = image_rect
        sx = self._image_rect.width/tile_pixel_rect.width
        sy = self._image_rect.height/tile_pixel_rect.height
        self._tile_to_image = Affine((sx, sy), (tile_pixel_rect.x0, tile_pixel_rect.y0), (0, 0))

    def extract_tile_as_image(self, x0, y0, x1, y1, scaling):
    #========================================================
        # Overridden by subclass
        return transparent_image()

    def get_scaling(self, x0, y0, x1, y1):
    #=====================================
        return (TILE_SIZE[0]/(x1 - x0), TILE_SIZE[1]/(y1 - y0))

    def get_tile(self, tile_x, tile_y):
    #==================================
        (x0, y0) = self._tile_to_image.transform(TILE_SIZE[0]*tile_x,
                                                 TILE_SIZE[1]*tile_y)
        (x1, y1) = self._tile_to_image.transform(TILE_SIZE[0]*(tile_x + 1),
                                                 TILE_SIZE[1]*(tile_y + 1))
        scaling = self.get_scaling(x0, y0, x1, y1)
        image = self.extract_tile_as_image(x0, y0, x1, y1, scaling)
        image_size = get_image_size(image)
        if image_size == tuple(TILE_SIZE):
            return make_transparent(image)
        else:
            # Pad out partial tiles
            tile = transparent_image(TILE_SIZE)
            x_start = check_image_size(image_size[0], TILE_SIZE[0], x0, x1, (0, self._image_rect.x1), scaling[0])
            y_start = check_image_size(image_size[1], TILE_SIZE[1], y0, y1, (0, self._image_rect.y1), scaling[1])
            paste_image(tile, image, (x_start, y_start))
            return make_transparent(tile)

#===============================================================================

class ImageTileSource(TileSource):
    def __init__(self, tile_pixel_rect, image):
        if image.shape[2] == 3:
            image = cv2.cvtColor(image, cv2.COLOR_RGB2RGBA)
        self.__source_image = image
        super().__init__(tile_pixel_rect, Rect((0, 0), get_image_size(image)))

    def extract_tile_as_image(self, x0, y0, x1, y1, scaling):
    #========================================================
        X0 = max(0, round(x0))
        X1 = min(round(x1), self.__source_image.shape[1])
        Y0 = max(0, round(y0))
        Y1 = min(round(y1), self.__source_image.shape[0])
        width = (TILE_SIZE[0] if x0 >= 0 and x1 < self.__source_image.shape[1]
            else round(scaling[0]*(X1 - X0)))
        height = (TILE_SIZE[1] if y0 >= 0 and y1 < self.__source_image.shape[0]
            else round(scaling[1]*(Y1 - Y0)))
        return cv2.resize(self.__source_image[Y0:Y1, X0:X1], (width, height), interpolation=cv2.INTER_CUBIC)

#===============================================================================

class PDFTileSource(TileSource):
    def __init__(self, tile_pixel_rect, pdf_page):
        super().__init__(tile_pixel_rect, pdf_page.rect)
        self._pdf_page = pdf_page

    def get_scaling(self, x0, y0, x1, y1):
    #=====================================
        return ((TILE_SIZE[0] - 1)/(x1 - x0),   # Fitz includes RH edge pixel
                (TILE_SIZE[1] - 1)/(y1 - y0))   # so scale to 1px smaller...

    def extract_tile_as_image(self, x0, y0, x1, y1, scaling):
    #========================================================

        # We now clip to avoid a black line if region outside of page...
        if x1 >= self._image_rect.width: x1 = self._image_rect.width - 1
        if y1 >= self._image_rect.height: y1 = self._image_rect.height - 1

        pixmap = self._pdf_page.getPixmap(clip=fitz.Rect(x0, y0, x1, y1),
                                          matrix=fitz.Matrix(*scaling),
                                          alpha=True)
        data = pixmap.getImageData('png')
        return cv2.imdecode(np.frombuffer(data, 'B'), cv2.IMREAD_UNCHANGED)

#===============================================================================

class TileMaker(object):
    def __init__(self, extent, map_dir, map_zoom=(MIN_ZOOM, MAX_ZOOM)):
        self._map_dir = map_dir
        self._min_zoom = map_zoom[0]
        self._max_zoom = map_zoom[1]

        # We need a manager to share the list of database names between processes
        self._manager = multiprocessing.Manager()
        self._database_names = self._manager.list()

        # Get whole tiles that span the image's extent
        self._tiles = list(mercantile.tiles(*extent, self._max_zoom))
        tile_0 = self._tiles[0]
        tile_N = self._tiles[-1]
        self._tile_start_coords = (tile_0.x, tile_0.y)
        self._tile_end_coords = (tile_N.x, tile_N.y)

        # Tiled area in world coordinates (metres)
        bounds_0 = mercantile.xy_bounds(tile_0)
        bounds_N = mercantile.xy_bounds(tile_N)
        tile_world = Rect(bounds_0.left, bounds_0.top, bounds_N.right, bounds_N.bottom)

        # Tiled area in tile pixel coordinates
        tile_extent = Rect(0, 0, TILE_SIZE[0]*(tile_N.x-tile_0.x+1), TILE_SIZE[1]*(tile_N.y-tile_0.y+1))

        # Affine transform from world to tile pixel coordinates
        sx = tile_extent.width/tile_world.width
        sy = tile_extent.height/tile_world.height
        world_to_tile = Affine((sx, -sy), (tile_world.x0, tile_world.y0), (0, 0))

        # Extent in world coordinates (metres)
        sw = mercantile.xy(*extent[:2])
        ne = mercantile.xy(*extent[2:])

        # Converted to tile pixel coordinates
        self._tile_pixel_rect = Rect(world_to_tile.transform(sw[0], ne[1]),
                                     world_to_tile.transform(ne[0], sw[1]))

        self._processes = []

    @property
    def database_names(self):
        return self._database_names

    def make_tiles(self, source_id, tile_source, layer_id):
    #======================================================
        database_name = '{}.mbtiles'.format(layer_id)
        self._database_names.append(database_name)
        mbtiles = MBTiles(os.path.join(self._map_dir, database_name), True, True)
        mbtiles.add_metadata(id=layer_id, source=source_id)

        zoom = self._max_zoom
        print('Tiling zoom level {} for {}'.format(zoom, layer_id))
        progress_bar = tqdm(total=len(self._tiles),
            unit='tiles', ncols=40,
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')
        for tile in self._tiles:
            image = tile_source.get_tile(tile.x - self._tile_start_coords[0],
                                         tile.y - self._tile_start_coords[1])
            if not_transparent(image):
                mbtiles.save_tile_as_png(zoom, tile.x, tile.y, image)
            progress_bar.update(1)
        progress_bar.close()

        self.make_overview_tiles(mbtiles, layer_id, zoom, self._tile_start_coords, self._tile_end_coords)
        mbtiles.close() #True)

    def make_overview_tiles(self, mbtiles, layer_id, zoom, start_coords, end_coords):
    #================================================================================
        if zoom > self._min_zoom:
            zoom -= 1
            print('Tiling zoom level {} for {}'.format(zoom, layer_id))
            HALF_SIZE = (TILE_SIZE[0]//2, TILE_SIZE[1]//2)
            half_start = (start_coords[0]//2, start_coords[1]//2)
            half_end = (end_coords[0]//2, end_coords[1]//2)
            progress_bar = tqdm(total=(half_end[0]-half_start[0]+1)
                                     *(half_end[1]-half_start[1]+1),
                unit='tiles', ncols=40,
                bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')
            for x in range(half_start[0], half_end[0] + 1):
                for y in range(half_start[1], half_end[1] + 1):
                    overview_tile = transparent_image(TILE_SIZE)
                    for i in range(2):
                        for j in range(2):
                            try:
                                tile = mbtiles.get_tile(zoom+1, 2*x+i, 2*y+j)
                                half_tile = cv2.resize(tile, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
                                paste_image(overview_tile, half_tile, (i*HALF_SIZE[0], j*HALF_SIZE[1]))
                            except ExtractionError:
                                pass
                    if not_transparent(overview_tile):
                        mbtiles.save_tile_as_png(zoom, x, y, overview_tile)
                    progress_bar.update(1)
            progress_bar.close()
            self.make_overview_tiles(mbtiles, layer_id, zoom, half_start, half_end)

    def wait_for_processes(self):
    #============================
        for process in self._processes:
            process.join()

###

    def make_tiles_from_image(self, image, source_id, layer_id):
    #===========================================================
        self.make_tiles(source_id, ImageTileSource(self._tile_pixel_rect, image), layer_id)

    def start_make_tiles_from_image(self, image, source_id, layer_id):
    #=================================================================
        process = multiprocessing.Process(target=self.make_tiles_from_image, args=(image, source_id, layer_id))
        self._processes.append(process)
        process.start()

###

    def make_tiles_from_pdf(self, pdf_page, source_id, layer_id):
    #============================================================
        self.make_tiles(source_id, PDFTileSource(self._tile_pixel_rect, pdf_page), layer_id)

    def start_make_tiles_from_pdf(self, pdf_bytes, source_id, page_no, layer_id):
    #============================================================================
        print('Page {}: {}'.format(page_no, layer_id))
        pdf = fitz.Document(stream=pdf_bytes, filetype='application/pdf')
        process = multiprocessing.Process(target=self.make_tiles_from_pdf, args=(pdf[page_no - 1], source_id, layer_id))
        self._processes.append(process)
        process.start()

#===============================================================================

def make_background_tiles_from_image(map_bounds, map_zoom, map_dir, image, source_name, layer_id):
    tile_maker = TileMaker(map_bounds, map_dir, map_zoom)
    tile_maker.start_make_tiles_from_image(image, source_name, layer_id)
    tile_maker.wait_for_processes()
    return tile_maker.database_names

#===============================================================================

def make_background_tiles_from_pdf(map_bounds, map_zoom, map_dir, pdf_bytes, source_name, layer_ids, slide=0):
    tile_maker = TileMaker(map_bounds, map_dir, map_zoom)
    if slide > 0:   # There is just a single layer
        tile_maker.start_make_tiles_from_pdf(pdf_bytes, '{}#{}'.format(source_name, slide), slide, layer_ids[0])
    else:
        for n, layer_id in enumerate(layer_ids):
            tile_maker.start_make_tiles_from_pdf(pdf_bytes, '{}#{}'.format(source_name, n+1), n+1, layer_id)

    tile_maker.wait_for_processes()
    return tile_maker.database_names

#===============================================================================

if __name__ == '__main__':
    import sys

    map_extent = [-10, -20, 10, 20]
    max_zoom = 6

    mode = 'PDF' if len(sys.argv) < 2 else sys.argv[1].upper()

    if mode == 'PDF':
        pdf_file = '../map_sources/body_demo.pdf'
        with open(pdf_file, 'rb') as f:
            make_background_tiles_from_pdf(map_extent, [MIN_ZOOM, max_zoom],
                                           '../maps/demo', f.read(),
                                           pdf_file, ['base'], 1)
    elif mode == 'JPEG':
        jpeg_file = './mbf/pig/sub-10sam-1P10-1Slide2p3MT10x.jp2'
        make_background_tiles_from_image(map_extent, [MIN_ZOOM, max_zoom],
                                         '../maps/demo', Image.open(jpeg_file),
                                         jpeg_file, 'test')
    else:
        sys.exit('Unknown mode of test -- must be "JPEG" or "PDF"')

#===============================================================================
