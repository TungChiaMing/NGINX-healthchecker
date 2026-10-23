import logging
import coloredlogs
from typing import Optional

class Logger:
    _loggers = {}

    def __new__(cls, name: str, log_file: Optional[str] = "test.txt",
                log_level: int = logging.DEBUG, file_level: int = logging.DEBUG):
        if name in cls._loggers:
            return cls._loggers[name]
        fmt = '%(levelname)s %(asctime)s [%(method)s %(route)s] %(message)s'

        logger = logging.getLogger(name)
        logger.setLevel(log_level)

        if log_file and not any(isinstance(h, logging.FileHandler) and h.baseFilename == log_file for h in logger.handlers):
            fh = logging.FileHandler(log_file)
            fh.setLevel(file_level)
            
            datefmt = '%Y-%m-%d %H:%M:%S'
            fh.setFormatter(logging.Formatter(fmt=fmt, datefmt=datefmt))
            logger.addHandler(fh)

        if not any(isinstance(h, coloredlogs.ColoredFormatter) for h in logger.handlers):
            coloredlogs.install(level=log_level, logger=logger,
                                fmt=fmt,
                                datefmt='%Y-%m-%d %H:%M:%S')

        cls._loggers[name] = logger
        return logger