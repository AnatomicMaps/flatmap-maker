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

__version__ = '1.0.0b1'

#===============================================================================

FLATMAP_VERSION  = 1.2

#===============================================================================

# Default zoom range of generated flatmap

MIN_ZOOM  =  2   #: Default minimum zoom level for generated flatmaps
MAX_ZOOM  = 10   #: Default maximum zoom level for generated flatmaps

#===============================================================================

from .maker import Flatmap

#===============================================================================
