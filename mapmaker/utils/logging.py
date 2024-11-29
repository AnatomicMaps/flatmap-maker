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

import json
import logging
import logging.config
import typing
from typing import Any, Callable, Optional

#===============================================================================

import structlog
from structlog.typing import EventDict, WrappedLogger
import tqdm

#===============================================================================

from mapmaker.settings import settings

#===============================================================================

class RenameJSONRenderer:
    def __init__(self,
      to: str, replace_by: str | None = None,
      serializer: Callable[..., str | bytes] = json.dumps, **dumps_kw: Any):
        self.__renamer = structlog.processors.EventRenamer(to, replace_by)
        self.__json_renderer = structlog.processors.JSONRenderer(serializer, **dumps_kw)

    def __call__(self, logger: WrappedLogger, name: str, event_dict: EventDict) -> str | bytes:
        return self.__json_renderer(logger, name, self.__renamer(logger, name, event_dict))

#===============================================================================

def configure_logging(log_file=None, verbose=False, silent=False, debug=False) -> Optional[logging.FileHandler]:

    log_level = logging.DEBUG if debug else logging.INFO

    logging_config = {
        'version': 1,
        'handlers': {
            'stream': {
                'class': 'logging.StreamHandler',
                'level': log_level,
                'formatter': 'structured'
            }
        },
        'formatters': {
            'json': {
                '()': structlog.stdlib.ProcessorFormatter,
                "processor": RenameJSONRenderer('msg'),
            },
            'structured': {
                '()': structlog.stdlib.ProcessorFormatter,
                'processor': structlog.dev.ConsoleRenderer(colors=True),
            },
        },
        'loggers': {
            '': {
                'handlers': ['stream'],
                'level': log_level,
                'propagate': True
            },
        }
    }

    if silent:
        logging_config['handlers']['stream']['level'] = logging.CRITICAL

    if log_file is not None:
        logging_config['handlers']['jsonfile'] = {
            'class': 'logging.FileHandler',
            'level': log_level,
            'formatter': 'json',
            'filename': log_file
        }
        logging_config['loggers']['']['handlers'].append('jsonfile')

    # Configure standard logger
    logging.config.dictConfig(logging_config)

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.TimeStamper(fmt='iso'),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    if log_file is not None:
        return typing.cast(logging.FileHandler, logging.getLogger().handlers[1])

#===============================================================================

log: structlog.BoundLogger = structlog.get_logger()

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
