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

def configure_logging(log_file, quiet=False, silent=False):
    log_format = '%(asctime)s %(levelname)s: %(message)s'
    if not silent:
        if quiet:
            logging.basicConfig(format=log_format)
        else:
            logging.basicConfig(format='%(message)s')
        logging.getLogger().setLevel(logging.INFO)
        if log_file is not None:
            logger = logging.FileHandler(log_file)
            formatter = logging.Formatter(log_format)
            logger.setFormatter(formatter)
            logging.getLogger().addHandler(logger)
    elif log_file is not None:
        logging.basicConfig(
            format=log_format,
            filename=log_file,
            level=logging.INFO
        )

#===============================================================================

class log(object):
    def __init__(self, *args):
        logging.info(''.join(args))

    @staticmethod
    def debug(*args):
        logging.debug(''.join(args))

    @staticmethod
    def error(*args):
        logging.error(''.join(args))

    @staticmethod
    def exception(*args):
        logging.exception(''.join(args))

    @staticmethod
    def info(*args):
        logging.info(''.join(args))

    @staticmethod
    def warn(*args):
        logging.warn(''.join(args))

#===============================================================================

class ProgressBar(object):
    def __init__(self, *args, show=True, **kwargs):
        if show and not settings.get('quiet', False):
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
