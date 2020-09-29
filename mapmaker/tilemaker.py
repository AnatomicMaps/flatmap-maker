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

class Transform(object):
    def __init__(self, scale, translateA=None, translateB=None):
        if translateA is None: translateA = (0, 0)
        if translateB is None: translateB = (0, 0)
        self._matrix = np.array([[ scale[0], 0, -scale[0]*translateA[0] + translateB[0] ],
                                 [ 0, scale[1], -scale[1]*translateA[1] + translateB[1] ],
                                 [ 0,        0,                                       1 ]])

    def __str__(self):
        return 'Transform: {}'.format(self._matrix)

    def transform_point(self, x, y):
    #===============================
        return (self._matrix@[x, y, 1])[:2]

#===============================================================================

class Point(object):
    def __init__(self, x, y):
        self.x = x
        self.y = y

    def __str__(self):
        return 'Point: ({}, {})'.format(self.x, self.y)

    def transform(self, matrix):
    #===========================
        return Point(*matrix.transform_point(self.x, self.y))

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
        return 'Rect: ({}, {}, {}, {}) {} x {})'.format(self.x0, self.y0,
                                                        self.x1, self.y1,
                                                        self.width, self.height)

    @property
    def height(self):
        return abs(self.y1 - self.y0)

    @property
    def width(self):
        return abs(self.x1 - self.x0)

    def to_fitz(self):
    #=================
        return fitz.Rect(self.x0, self.y0, self.x1, self.y1)

    def transform(self, matrix):
    #===========================
        return Rect(matrix.transform_point(self.x0, self.y0), matrix.transform_point(self.x1, self.y1))

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

class ScaledImageSource(object):
    """
    A class to tile an image that has been scaled to tile pixel coordinates

    :param image: An OpenCV image. The image has to have been scaled to
                  tile pixel coordinates
    :type image: class:`numpy.ndarray`
    :param image_offset: The offset of the image in tile pixels,
                       origin is top-left of tiles
    :type image_offset: tuple(int, int)
    """
    def __init__(self, image, image_offset):
        """Constructor"""
        print('Image:', get_image_size(image), ' offset:', image_offset)
        if image.shape[2] == 3:
            image = cv2.cvtColor(image, cv2.COLOR_RGB2RGBA)
        self.__image = image
        image_size = get_image_size(image)
        self.__image_width = image_size[0]
        self.__image_height = image_size[1]
        self.__image_offset = image_offset

    def get_tile(self, tile_x, tile_y):
    #==================================
        """
        Extract a tile from the source image

        :param tile_x: tile X-coordinate number, relative to left of tiled area
        :type tile_x: int
        :param tile_y: tile Y-coordinate number, relative to top of tiled area
        :type tile_y: int
        :returns: A ``TILE_SIZE`` image
        :rtype: class:`numpy.ndarray`
        """

        # Get tile sides relative to image

        x0 = TILE_SIZE[0]*tile_x - self.__image_offset[0]
        x1 = x0 + TILE_SIZE[0]
        y0 = TILE_SIZE[1]*tile_y - self.__image_offset[1]
        y1 = y0 + TILE_SIZE[1]

        # Extract image subset that is covered by the tile

        X0 = max(0, x0)
        X1 = min(x1, self.__image_width)
        Y0 = max(0, y0)
        Y1 = min(y1, self.__image_height)


        image = self.__image[Y0:Y1, X0:X1]

        # Check for image partially covering tile and pad if necessary,
        # returning a transparent image
        #
        image_size = get_image_size(image)
        if image_size == TILE_SIZE:
            return make_transparent(image)
        else:
            x_start = -x0 if x0 < 0 else 0
            y_start = -y0 if y0 < 0 else 0
            tile = transparent_image(TILE_SIZE)
            paste_image(tile, image, (x_start, y_start))
            return make_transparent(tile)

#===============================================================================

class ImageTileSource(ScaledImageSource):
    """
    Scale and map an image to tiles

    :param map_rect: The map's extent in tile pixels. This region is covered
                     by a set of whole tiles which may extend beyond the map
    :type map_rect: class:`Rect`
    :param image: An OpenCV image. The image is scaled to fit the
                  map's tile pixel extent
    :type image: class:`numpy.ndarray`
    :param image_rect: The region of the image to tile (in tile pixels,
                       after scaling, origin is top-left of page)
    :type image_rect: class:`Rect`, optional
    """
    def __init__(self, map_rect, image, image_rect=None):
        """Constructor"""
        if image.shape[2] == 3:
            image = cv2.cvtColor(image, cv2.COLOR_RGB2RGBA)
        self.__source_image = image
        image_size = get_image_size(image)
        self.__tile_to_image = Transform((image_size[0]/map_rect.width, image_size[1]/map_rect.height),
                                         (map_rect.x0, map_rect.y0), (0, 0))
        self.__image_rect = map_rect if image_rect is None else image_rect

#===============================================================================

class PDFTileSource(ScaledImageSource):
    """
    Scale and map a PDF page to tiles

    :param map_rect: The map's extent in tile pixels. This region is covered
                     by a set of whole tiles which may extend beyond the map
    :type map_rect: class:`Rect`
    :param pdf_page: A page of a PDF document. The page is converted to an image
                     scaled to fit the map's tile pixel extent
    :type pdf_page: class:`fitz.Page`
    :param image_bbox: The region of the page to tile (in tile pixels,
                       after scaling, origin is top-left of page). By default
                       the entire page is tiled
    :type image_bbox: class:`Rect`, optional
    :param image_transform: If not ``None`` the extracted image is transformed
                            using ``cv2.perspectiveTransform`` before being used
                            as the source for tiles
    :type image_transform: class:`numpy.ndarray`, optional
    """
    def __init__(self, map_rect, pdf_page, image_bbox=None, image_transform=None):
        """Constructor"""
        page_to_tile = fitz.Matrix(map_rect.width/pdf_page.rect.width,
                                   map_rect.height/pdf_page.rect.height)


        if image_bbox is None:
            clip_region = None
            image_offset = (round(map_rect.x0), round(map_rect.y0))
        else:
            clip_region = image_bbox.transform(Transform((pdf_page.rect.width/map_rect.width,
                                                          pdf_page.rect.height/map_rect.height))
                                              ).to_fitz()
            image_offset = (round(image_bbox.x0), round(image_bbox.y0))

        data = pdf_page.getPixmap(matrix=page_to_tile, alpha=True, clip=clip_region).getImageData('png')
        pdf_image = cv2.imdecode(np.frombuffer(data, 'B'), cv2.IMREAD_UNCHANGED)

        if image_transform is not None:
            print('XFRM:', image_transform)
            #pdf_image = cv2.perspectiveTransform(pdf_image, image_transform)

        super().__init__(pdf_image, image_offset)


class PDFDetailsSource(ScaledImageSource):
    def __init__(self, map_rect, pdf_page, image_rect=None):
        pass


#===============================================================================

class TileMaker(object):
    """
    A class for generating image tiles for a map

    Image tiles are stored as ``mbtiles``, in a SQLite3 database.

    The map's extent together with the maximum zoom level is used to determine
    the set of tiles that covers the map, along with a transform from map
    coordinates to tile pixel coordinates and the the location of the map in
    terms of tile pixels.

    :param source_name: The file name or URL for the source image data
    :type source_name: str
    :param extent: The map's extent as in latitude and longitude
    :type extent: tuple(south, west, north, east)
    :param output_dir: The directory in which to store image tiles
    :type output_dir: str
    :param map_zoom: The range of zoom levels to generate tiles
    :type map_zoom: tuple, optional, defaults to (`MIN_ZOOM`, `MAX_ZOOM`)
    """
    def __init__(self, source_name, extent, output_dir, map_zoom=(MIN_ZOOM, MAX_ZOOM)):
        self.__source_name = source_name
        self.__output_dir = output_dir
        self.__min_zoom = map_zoom[0]
        self.__max_zoom = map_zoom[1]

        # We need a manager to share the list of database names between processes

        self.__manager = multiprocessing.Manager()
        self.__database_names = self.__manager.list()
        self.__processes = []

        # Get the set oof tiles that span the map

        self.__tiles = list(mercantile.tiles(*extent, self.__max_zoom))
        tile_0 = self.__tiles[0]
        tile_N = self.__tiles[-1]
        self.__tile_start_coords = (tile_0.x, tile_0.y)
        self.__tile_end_coords = (tile_N.x, tile_N.y)

        # Tiled area in world coordinates (metres)

        bounds_0 = mercantile.xy_bounds(tile_0)
        bounds_N = mercantile.xy_bounds(tile_N)
        tile_world = Rect(bounds_0.left, bounds_0.top, bounds_N.right, bounds_N.bottom)

        # Tiled area in tile pixel coordinates

        tile_extent = Rect(0, 0, TILE_SIZE[0]*(tile_N.x-tile_0.x+1), TILE_SIZE[1]*(tile_N.y-tile_0.y+1))

        # Transform between world and tile pixel coordinates

        sx = tile_extent.width/tile_world.width
        sy = tile_extent.height/tile_world.height
        self.__world_to_tile = Transform((sx, -sy), (tile_world.x0, tile_world.y0), (0, 0))
        self.__tile_to_world = Transform((1.0/sx, -1.0/sy), (0, 0), (tile_world.x0, tile_world.y0))

        # Extent in world coordinates (metres)

        sw = mercantile.xy(*extent[:2])
        ne = mercantile.xy(*extent[2:])

        # Map extent in tile pixel coordinates

        self.__map_rect = Rect(sw[0], ne[1], ne[0], sw[1]).transform(self.__world_to_tile)


    @property
    def database_names(self):
        return self.__database_names

    def make_tiles(self, tile_source, layer_id):
    #===========================================
        database_name = '{}.mbtiles'.format(layer_id)
        self.__database_names.append(database_name)
        mbtiles = MBTiles(os.path.join(self.__output_dir, database_name), True, True)
        mbtiles.add_metadata(id='{}#{}'.format(self.__source_name, layer_id),
                             source=self.__source_name)

        zoom = self.__max_zoom
        print('Tiling zoom level {} for {}'.format(zoom, layer_id))
        progress_bar = tqdm(total=len(self.__tiles),
            unit='tiles', ncols=40,
            bar_format='{l_bar}{bar}| {n_fmt}/{total_fmt}')
        for tile in self.__tiles:
            image = tile_source.get_tile(tile.x - self.__tile_start_coords[0],
                                         tile.y - self.__tile_start_coords[1])
            if not_transparent(image):
                mbtiles.save_tile_as_png(zoom, tile.x, tile.y, image)
            progress_bar.update(1)
        progress_bar.close()

        self.make_overview_tiles(mbtiles, layer_id, zoom, self.__tile_start_coords, self.__tile_end_coords)
        mbtiles.close() #True)

    def make_overview_tiles(self, mbtiles, layer_id, zoom, start_coords, end_coords):
    #================================================================================
        if zoom > self.__min_zoom:
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
        for process in self.__processes:
            process.join()

###

    def make_tiles_from_image(self, image, layer_id):
    #================================================
        tile_source = ImageTileSource(self.__map_rect, image)
        self.make_tiles(tile_source, layer_id)

    def start_make_tiles_from_image(self, image, layer_id):
    #======================================================
        process = multiprocessing.Process(target=self.make_tiles_from_image, args=(image, layer_id))
        self.__processes.append(process)
        process.start()

###

    def make_tiles_from_pdf_(self, pdf_page, image_layer):
    #=====================================================
        bounds = image_layer.bounding_box
        tile_source = PDFTileSource(self.__map_rect, pdf_page,
                                    Rect(*bounds) if bounds is not None else bounds,
                                    image_layer.image_transform)
        self.make_tiles(tile_source, image_layer.id)

    def start_tiles_from_pdf_process(self, pdf_bytes, image_layer):
    #==============================================================
        page_no = image_layer.slide_number
        print('Page {}: {}'.format(page_no, image_layer.id))

        pdf = fitz.Document(stream=pdf_bytes, filetype='application/pdf')

        process = multiprocessing.Process(target=self.make_tiles_from_pdf_, args=(pdf[page_no - 1], image_layer))

        self.__processes.append(process)
        process.start()

#===============================================================================

def make_background_tiles_from_image(map_bounds, map_zoom, output_dir, image, source_name, layer_id):
    tile_maker = TileMaker(map_bounds, output_dir, map_zoom)
    tile_maker.start_make_tiles_from_image(image, source_name, layer_id)
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
