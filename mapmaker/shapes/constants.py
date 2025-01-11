#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2018 - 2025  David Brooks
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

EPSILON = 1e-6
MAX_PARALLEL_SKEW = 0.001

#===============================================================================

# SVG pixel space -- these values are based on the CVS bondgraph diagram

MAX_LINE_WIDTH = 20             # Close together parallel edges a polygons are converted to lines
MIN_LINE_ASPECT_RATIO = 1.5     #

MAX_TEXT_VERTICAL_OFFSET = 5    # Between cluster baseline and baselines of text in the cluster
TEXT_BASELINE_OFFSET = -14.5    # From vertical centre of a component

#===============================================================================
