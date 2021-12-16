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

import math

#===============================================================================

def image_offset(dimension, max_dim, limit, bounds, scale):
#==========================================================
    if dimension < max_dim:
        if limit[0] < bounds[0]:
            if limit[1] < bounds[1]:
                return max_dim - dimension
            else:
                return int(math.floor(0.5 - limit[0]*scale))
    elif dimension != max_dim:
        raise AssertionError('Image size mismatch: {} != {}'.format(dimension, max_dim))
    return 0

def image_size(img):
#===================
    return tuple(reversed(img.shape[:2]))

def paste_image(destination, source, offset):
#============================================
    destination[offset[1]:offset[1]+source.shape[0],
                offset[0]:offset[0]+source.shape[1]] = source
    return destination

#===============================================================================
