#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2022  David Brooks
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

# Radius of circular region used to join centrelines
MIN_EDGE_JOIN_RADIUS = 6000     ## needs to be some fraction of map size...

# Path separation gap
PATH_SEPARATION = 0.5*MIN_EDGE_JOIN_RADIUS

# Tolerance used when simplifying Shapely objects
SMOOTHING_TOLERANCE = 10

# Length of an arrow head
ARROW_LENGTH = 4500

#===============================================================================


