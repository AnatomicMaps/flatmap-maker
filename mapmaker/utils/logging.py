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
import logging.handlers
import multiprocessing
from typing import Any, Callable, Optional

#===============================================================================

import structlog
from structlog.typing import EventDict, WrappedLogger
import tqdm

#===============================================================================

from mapmaker.settings import settings

#===============================================================================

class QueueHandlerJSON(logging.handlers.QueueHandler):
    def prepare(self, record: logging.LogRecord) -> logging.LogRecord:
        record = super().prepare(record)
        record.msg = json.dumps(record.msg)
        return record

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

def configure_logging(log_json_file=None, verbose=False, silent=False, debug=False,
#==================================================================================
                      log_queue: Optional[multiprocessing.Queue]=None) -> Optional[logging.FileHandler]:

    log_level = logging.DEBUG if debug else logging.INFO

    # Configure standard logger with a null configuration
    logging.config.dictConfig({
        'version': 1,
        'handlers': {
            'null': {
                'class': 'logging.NullHandler',
                'level': log_level
            }
        },
        'formatters': {
        },
        'loggers': {
            '': {
                'handlers': ['null'],
                'level': log_level,
                'propagate': True
            },
        }
    })

    # Get our logger
    logger = logging.getLogger('mapmaker')

    # Log to the console if not sending logs to a queue
    if log_queue is None:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(logging.CRITICAL if silent else log_level)
        structured_formatter = structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(colors=True)
            ],
        )
        stream_handler.setFormatter(structured_formatter)
        logger.addHandler(stream_handler)

    json_formatter = structlog.stdlib.ProcessorFormatter(
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            RenameJSONRenderer('msg')
        ],
    )

    # Log as JSON to a file if requested
    json_handler = None
    if log_json_file is not None:
        json_handler = logging.FileHandler(log_json_file)
        json_handler.setLevel(log_level)
        json_handler.setFormatter(json_formatter)
        logger.addHandler(json_handler)

    # For when mapmaker is run as a process by a flatmap server.
    if log_queue is not None:
        queue_handler = logging.handlers.QueueHandler(log_queue)
        queue_handler.setFormatter(json_formatter)
        logger.addHandler(queue_handler)

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

    return json_handler

#===============================================================================

log: structlog.BoundLogger = structlog.get_logger('mapmaker')

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
