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

import logging

#===============================================================================

import tqdm

#===============================================================================

from mapmaker.settings import settings

#===============================================================================

logger = logging.getLogger(__name__)

def configure_logging(log_file, verbose=False, silent=False):
    log_format = '%(asctime)s %(levelname)s: %(message)s'
    if silent:
        logging.lastResort = None
        if log_file is not None:
            logger.setLevel(logging.INFO)
    else:
        logger.setLevel(logging.INFO)
        if verbose:
            logging.basicConfig(format='%(message)s')
        else:
            logging.basicConfig(format=log_format)
    if log_file is not None:
        file_handler = logging.FileHandler(log_file)
        formatter = logging.Formatter(log_format)
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.INFO)
        logger.addHandler(file_handler)

#===============================================================================

class log(object):
    def __init__(self, *args):
        logger.info(''.join(args))

    @staticmethod
    def debug(*args):
        logger.debug(''.join(args))

    @staticmethod
    def error(*args):
        logger.error(''.join(args))

    @staticmethod
    def exception(*args):
        logger.exception(''.join(args))

    @staticmethod
    def info(*args):
        logger.info(''.join(args))

    @staticmethod
    def warn(*args):
        logger.warn(''.join(args))

#===============================================================================

class ProgressBar(object):
    def __init__(self, *args, show=True, **kwargs):
        if show and settings.get('verbose', False):
            self.__progress_bar = tqdm.tqdm(*args, **kwargs)
        else:
            self.__progress_bar = None

    def update(self, *args):
    #=======================
        if self.__progress_bar is not None:
            self.__progress_bar.update(*args)

    def close(self):
    #===============
        if self.__progress_bar is not None:
            self.__progress_bar.close()

#===============================================================================
